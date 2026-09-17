"""
Proxy de leitura de páginas para o Browser do IQ OS (`/proxy`).

Motivo: a maioria dos sites envia `X-Frame-Options`/`Content-Security-Policy:
frame-ancestors` e recusa ser mostrada dentro de um `iframe` (base.gov.pt,
euronext.com, finance.yahoo.com, Google, …). O servidor, ao contrário do
browser, consegue ler essas páginas: aqui buscamo-las, **removemos os
cabeçalhos que impedem a incorporação**, injetamos um `<base>` para que os
recursos (CSS/JS/imagens) continuem a ser pedidos ao site original e injetamos
um pequeno script que:

- redireciona `fetch`/`XMLHttpRequest` para o site original através do próprio
  proxy (contorna o CORS, já que a página passa a ter a nossa origem);
- intercepta cliques em ligações e submissões de formulários e pede ao Browser
  do IQ OS (a janela que a incorpora) para navegar — assim a barra de endereço,
  os separadores e o histórico continuam a funcionar;
- faz o POST de formulários dentro do próprio quadro (postbacks ASP.NET, por
  exemplo) e reescreve o documento com a resposta.

Limitações assumidas (v1, sem estado):

- **Sem sessões**: cookies não são reenviados nem guardados, pelo que sites com
  login (banca, e-mail, redes sociais) não funcionam por aqui — esses continuam
  a abrir numa aba do sistema.
- Páginas que dependem de muito JavaScript de terceiros (Google, SPAs pesadas)
  podem aparecer incompletas.
- Não segue pedidos que o browser faria fora da navegação (Service Workers,
  WebSockets) do site original.

Segurança: só http/https, sem destinos privados/loopback (SSRF), limite de
tamanho, tempo limite e sem repassar cookies ou credenciais.
"""
from __future__ import annotations

import asyncio
import ipaddress
import logging
import re
import socket
from typing import Any, Dict, Optional, Tuple
from urllib.parse import urlparse

import httpx
import websockets
from fastapi import (
    APIRouter,
    HTTPException,
    Query,
    Request,
    Response,
    WebSocket,
    WebSocketDisconnect,
)
from starlette.concurrency import run_in_threadpool

from api import events_service as events

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/proxy", tags=["proxy"])

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)

REQUEST_HEADERS = {
    "User-Agent": USER_AGENT,
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
    "Accept-Language": "pt-PT,pt;q=0.9,en;q=0.8",
    "Upgrade-Insecure-Requests": "1",
}

#: Cabeçalhos de resposta que impedem (ou atrapalham) a incorporação.
STRIP_RESPONSE_HEADERS = {
    "x-frame-options",
    "content-security-policy",
    "content-security-policy-report-only",
    "cross-origin-opener-policy",
    "cross-origin-embedder-policy",
    "cross-origin-resource-policy",
    "strict-transport-security",
    "report-to",
    "nel",
    "set-cookie",
    "set-cookie2",
    "content-encoding",
    "content-length",
    "transfer-encoding",
    "connection",
    "keep-alive",
}

#: Cabeçalhos do pedido original que não devem ser reenviados.
STRIP_REQUEST_HEADERS = {
    "host",
    "content-length",
    "connection",
    "cookie",
    "authorization",
    "origin",
    "referer",
    "accept-encoding",
    "sec-fetch-dest",
    "sec-fetch-mode",
    "sec-fetch-site",
    "sec-fetch-user",
}

MAX_BYTES = 12 * 1024 * 1024
TIMEOUT = httpx.Timeout(25.0, connect=10.0)

_PRIVATE_HOSTS = {"localhost", "localhost.localdomain", "ip6-localhost", "metadata.google.internal"}


def _is_public_target(host: str) -> bool:
    """Recusa destinos privados/loopback (proteção contra SSRF)."""
    if not host:
        return False
    lowered = host.lower().strip("[]")
    if lowered in _PRIVATE_HOSTS or lowered.endswith(".local") or lowered.endswith(".internal"):
        return False
    try:
        infos = socket.getaddrinfo(lowered, None)
    except socket.gaierror:
        return False
    for info in infos:
        address = info[4][0]
        try:
            ip = ipaddress.ip_address(address)
        except ValueError:
            continue
        if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved or ip.is_multicast:
            return False
    return True


def _validated_target(url: str) -> str:
    parsed = urlparse(url.strip())
    if parsed.scheme not in ("http", "https"):
        raise HTTPException(status_code=400, detail="Só são aceites endereços http:// ou https://.")
    if not parsed.hostname:
        raise HTTPException(status_code=400, detail="Endereço sem domínio.")
    if not _is_public_target(parsed.hostname):
        raise HTTPException(status_code=400, detail="Este endereço não é público e não pode ser lido pelo proxy.")
    return parsed.geturl()


def _bootstrap(base_url: str) -> str:
    """Script injetado na página lida: ligações, formulários e pedidos em JS.

    Todo o tráfego do quadro passa pelo proxy: as chamadas de dados dos widgets
    (por exemplo `symbol-search.tradingview.com`) são para outros domínios, onde
    o browser as bloquearia por CORS. Como a página passa a ter a nossa origem, o
    pedido reencaminhado é same-origin. O que já é nosso (`/proxy`, a API do
    IQ OS) e os esquemas não-HTTP ficam como estão, para não haver ciclos.
    """
    return (
        "<script>(function(){"
        'var BASE="' + base_url.replace('"', "%22") + '";'
        "var SELF=location.origin;"
        'function absolute(u){try{return new URL(u,BASE).href;}catch(e){return null;}}'
        # Os pedidos reencaminhados têm de ser absolutos para nós: a página tem
        # `<base>` apontado ao site original, e um caminho relativo resolveria
        # para lá (o browser recusava por CORS).
        'function proxied(u){return SELF+"/proxy?url="+encodeURIComponent(u);}'
        "function shouldProxy(u){if(!u||!/^https?:/.test(u))return false;"
        "if(u.indexOf(SELF)===0)return false;if(u.indexOf(\"/proxy?url=\")===0)return false;"
        "return true;}"
        "function post(kind,payload){var message={source:\"iq-os-browser\",kind:kind};"
        "for(var key in (payload||{})){message[key]=payload[key];}"
        'try{if(window.parent&&window.parent!==window){window.parent.postMessage(message,"*");}}catch(e){}}'
        "var nativeFetch=window.fetch;"
        "if(nativeFetch){window.fetch=function(input,init){try{"
        'var url=typeof input==="string"?input:((input&&input.url)||"");var abs=absolute(url);'
        "if(shouldProxy(abs)){input=proxied(abs);}}catch(e){}return nativeFetch.call(this,input,init);};}"
        "var nativeOpen=XMLHttpRequest.prototype.open;"
        "XMLHttpRequest.prototype.open=function(){var args=[].slice.call(arguments);try{"
        "var abs=absolute(args[1]);if(shouldProxy(abs)){args[1]=proxied(abs);}}catch(e){}"
        "return nativeOpen.apply(this,args);};"
        "if(navigator.sendBeacon){var nativeBeacon=navigator.sendBeacon.bind(navigator);"
        "navigator.sendBeacon=function(url,data){try{var abs=absolute(url);"
        "if(shouldProxy(abs)){return nativeBeacon(proxied(abs),data);}}catch(e){}"
        "return nativeBeacon(url,data);};}"
        # WebSocket: os servidores de tempo real validam o `Origin` do handshake e
        # recusam o nosso (403). Passa-se por `/proxy/ws`, que abre a ligação do
        # servidor com o `Origin` do próprio site.
        "var NativeWS=window.WebSocket;"
        "if(NativeWS){var ProxiedWS=function(url,protocols){var target=url;"
        "try{var abs=absolute(url);"
        "if(abs&&/^wss?:/.test(abs)){var scheme=location.protocol===\"https:\"?\"wss://\":\"ws://\";"
        "target=scheme+location.host+\"/proxy/ws?url=\"+encodeURIComponent(abs)"
        "+\"&origin=\"+encodeURIComponent(new URL(BASE).origin);}}catch(e){}"
        "return protocols===undefined?new NativeWS(target):new NativeWS(target,protocols);};"
        "ProxiedWS.prototype=NativeWS.prototype;"
        "ProxiedWS.CONNECTING=NativeWS.CONNECTING;ProxiedWS.OPEN=NativeWS.OPEN;"
        "ProxiedWS.CLOSING=NativeWS.CLOSING;ProxiedWS.CLOSED=NativeWS.CLOSED;"
        "window.WebSocket=ProxiedWS;}"
        # Além do encaminhamento, a página diz à aplicação se o conteúdo chegou a
        # desenhar. Alguns widgets (TradingView) carregam a interface toda mas
        # ficam sem gráfico quando o servidor deles recusa os dados, e sem erro
        # de JavaScript — a aplicação só veria um quadro vazio e nunca saberia.
        "var chartTries=0;"
        "function watchChart(){chartTries+=1;var nodes=document.querySelectorAll(\"canvas\");"
        "var width=0;if(nodes.length){width=nodes[0].width;}"
        'post("chart",{canvases:nodes.length,width:width,tries:chartTries});'
        "if(nodes.length||chartTries>=20)return;setTimeout(watchChart,1000);}"
        "setTimeout(watchChart,1200);"
        'document.addEventListener("click",function(event){'
        'var node=event.target;while(node&&node.tagName!=="A"){node=node.parentElement;}'
        'if(!node||event.defaultPrevented)return;var href=node.getAttribute("href")||"";'
        'if(!href||href.charAt(0)==="#")return;var abs=absolute(href);'
        'if(!abs||!/^https?:/.test(abs))return;event.preventDefault();'
        'post(node.target==="_blank"?"open":"navigate",{url:abs});},true);'
        'document.addEventListener("submit",function(event){'
        'var form=event.target;if(!form||form.tagName!=="FORM")return;'
        'var action=absolute(form.getAttribute("action")||BASE);'
        'var method=(form.getAttribute("method")||"GET").toUpperCase();'
        'event.preventDefault();'
        'if(method==="GET"){post("navigate",{url:action,method:"GET"});return;}'
        "var body;try{body=new URLSearchParams(new FormData(form)).toString();}catch(e){body=\"\";}"
        'post("status",{text:"A enviar formulário…"});'
        'fetch(proxied(action),{method:"POST",body:body,'
        'headers:{"content-type":"application/x-www-form-urlencoded"}})'
        ".then(function(r){return r.text();}).then(function(html){"
        'var doc=document;doc.open();doc.write(html);doc.close();'
        'post("status",{text:"Formulário enviado."});})'
        '.catch(function(){post("status",{text:"Falha ao enviar o formulário."});});},true);'
        'post("ready",{url:BASE});'
        "})();</script>"
    )


_META_CSP = re.compile(
    r"<meta[^>]+http-equiv\s*=\s*[\"']?content-security-policy[\"']?[^>]*>",
    re.IGNORECASE,
)
_HEAD_OPEN = re.compile(r"<head[^>]*>", re.IGNORECASE)


def _rewrite_html(html: str, final_url: str) -> str:
    """Remove políticas em `<meta>` e injeta `<base>` + o script de apoio."""
    cleaned = _META_CSP.sub("", html)
    injection = '<base href="' + final_url.replace('"', "%22") + '">' + _bootstrap(final_url)
    match = _HEAD_OPEN.search(cleaned)
    if match:
        position = match.end()
        return cleaned[:position] + injection + cleaned[position:]
    return injection + cleaned


def _forward_headers(request: Request) -> Dict[str, str]:
    headers = dict(REQUEST_HEADERS)
    for name, value in request.headers.items():
        lowered = name.lower()
        if lowered in STRIP_REQUEST_HEADERS or lowered.startswith("sec-") or lowered.startswith("proxy-"):
            continue
        if lowered in ("accept", "accept-language", "content-type", "user-agent"):
            continue
        headers[name] = value
    return headers


def _fetch(method: str, url: str, request: Request, body: Optional[bytes]) -> Tuple[bytes, str, int, Dict[str, str]]:
    headers = _forward_headers(request)
    content_type = request.headers.get("content-type")
    if body and content_type:
        headers["Content-Type"] = content_type

    with httpx.Client(follow_redirects=True, timeout=TIMEOUT) as client:
        with client.stream(method, url, headers=headers, content=body) as response:
            chunks: list[bytes] = []
            total = 0
            for chunk in response.iter_bytes():
                total += len(chunk)
                if total > MAX_BYTES:
                    raise HTTPException(status_code=413, detail="A página é demasiado grande para ser lida pelo proxy.")
                chunks.append(chunk)
            payload = b"".join(chunks)
            result_headers = {
                name: value
                for name, value in response.headers.items()
                if name.lower() not in STRIP_RESPONSE_HEADERS
            }
            return payload, response.headers.get("content-type", ""), response.status_code, result_headers


@router.get("")
def proxy_get(request: Request, url: str = Query(..., description="Endereço http(s) a ler")) -> Response:
    """Lê uma página e devolve-a pronta a ser incorporada num `iframe`."""
    return _handle("GET", request, url, None)


@router.post("")
async def proxy_post(request: Request, url: str = Query(..., description="Endereço http(s) a ler")) -> Response:
    """Como `GET`, mas reenvia o corpo (formulários/postbacks)."""
    body = await request.body()
    return await run_in_threadpool(_handle, "POST", request, url, body)


def _handle(method: str, request: Request, url: str, body: Optional[bytes]) -> Response:
    target = _validated_target(url)
    try:
        payload, content_type, status, headers = _fetch(method, target, request, body)
    except HTTPException:
        raise
    except Exception as error:  # noqa: BLE001
        events.log_event(
            "warning",
            "proxy",
            f"Falha ao ler {target}: {type(error).__name__}",
            data={"url": target},
        )
        raise HTTPException(status_code=502, detail=f"Não foi possível ler a página ({type(error).__name__}).") from error

    is_html = "text/html" in content_type.lower() or "application/xhtml" in content_type.lower()
    if is_html:
        # O httpx já descodificou o conteúdo; aqui só tratamos do texto.
        charset = _charset_of(content_type) if "charset" in content_type.lower() else "utf-8"
        try:
            text = payload.decode(charset, errors="replace")
        except LookupError:
            text = payload.decode("utf-8", errors="replace")
        rewritten = _rewrite_html(text, target)
        headers["content-type"] = "text/html; charset=utf-8"
        headers["cache-control"] = "no-store"
        return Response(content=rewritten.encode("utf-8"), status_code=status, headers=headers)

    headers["x-iqos-proxy"] = "1"
    return Response(content=payload, status_code=status, headers=headers)


def _charset_of(content_type: str) -> str:
    for part in content_type.split(";"):
        name, _, value = part.partition("=")
        if name.strip().lower() == "charset":
            return value.strip().strip('"') or "utf-8"
    return "utf-8"


@router.get("/status")
def proxy_status() -> Dict[str, Any]:
    """Informação para a interface (limites e estado)."""
    return {
        "enabled": True,
        "max_bytes": MAX_BYTES,
        "timeout_seconds": 25,
        "websockets": True,
        "note": "Leitura sem sessão: sites com login continuam a abrir numa aba do sistema.",
    }


# --------------------------------------------------------------- WebSocket

WS_OPEN_TIMEOUT = 15


def _validated_ws_target(url: str) -> str:
    """Valida um destino `ws`/`wss` com as mesmas regras do proxy HTTP."""
    parsed = urlparse(url.strip())
    if parsed.scheme not in ("ws", "wss"):
        raise HTTPException(status_code=400, detail="Só são aceites endereços ws:// ou wss://.")
    if not parsed.hostname:
        raise HTTPException(status_code=400, detail="Endereço sem domínio.")
    if not _is_public_target(parsed.hostname):
        raise HTTPException(status_code=400, detail="Este endereço não é público e não pode ser lido pelo proxy.")
    return parsed.geturl()


@router.websocket("/ws")
async def proxy_websocket(
    websocket: WebSocket,
    url: str = Query(..., description="Endereço ws(s) a ligar"),
    origin: Optional[str] = Query(None, description="Origin a apresentar ao servidor de destino"),
) -> None:
    """Liga o browser a um WebSocket externo, apresentando o `Origin` do site.

    Motivo: os servidores de tempo real (por exemplo o stream da TradingView)
    recusam o handshake quando o `Origin` é o da nossa aplicação (HTTP 403).
    Aqui a ligação parte do servidor, com o `Origin` do próprio site.
    """
    try:
        target = _validated_ws_target(url)
    except HTTPException as error:
        await websocket.close(code=1008, reason=str(error.detail)[:120])
        return

    requested = websocket.headers.get("sec-websocket-protocol") or ""
    subprotocols = [item.strip() for item in requested.split(",") if item.strip()] or None
    upstream_origin = (origin or "").strip()
    if not upstream_origin.startswith(("http://", "https://")):
        parsed = urlparse(target)
        upstream_origin = f"{'https' if parsed.scheme == 'wss' else 'http'}://{parsed.netloc}"

    await websocket.accept(subprotocol=subprotocols[0] if subprotocols else None)
    headers = {"Origin": upstream_origin, "User-Agent": USER_AGENT}

    try:
        async with websockets.connect(
            target,
            additional_headers=headers,
            subprotocols=subprotocols,
            open_timeout=WS_OPEN_TIMEOUT,
            max_size=None,
            ping_interval=None,
        ) as upstream:

            async def client_to_upstream() -> None:
                while True:
                    message = await websocket.receive()
                    kind = message.get("type")
                    if kind == "websocket.disconnect":
                        return
                    if message.get("text") is not None:
                        await upstream.send(message["text"])
                    elif message.get("bytes") is not None:
                        await upstream.send(message["bytes"])

            async def upstream_to_client() -> None:
                async for message in upstream:
                    if isinstance(message, bytes):
                        await websocket.send_bytes(message)
                    else:
                        await websocket.send_text(message)

            tasks = [asyncio.create_task(client_to_upstream()), asyncio.create_task(upstream_to_client())]
            done, pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
            for task in pending:
                task.cancel()
            for task in done:
                task.exception()  # consome exceções esperadas (fecho do socket)
    except WebSocketDisconnect:
        pass
    except Exception as error:  # noqa: BLE001
        events.log_event(
            "warning",
            "proxy",
            f"WebSocket falhou para {target}: {type(error).__name__}",
            data={"url": target},
        )
    finally:
        try:
            await websocket.close()
        except Exception:  # noqa: BLE001
            pass
