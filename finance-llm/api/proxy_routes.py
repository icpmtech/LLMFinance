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

import ipaddress
import logging
import re
import socket
from typing import Any, Dict, Optional, Tuple
from urllib.parse import urlparse

import httpx
from fastapi import APIRouter, HTTPException, Query, Request, Response
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
    """Script injetado na página lida: ligações, formulários e pedidos em JS."""
    return (
        "<script>(function(){"
        'var BASE="' + base_url.replace('"', "%22") + '";'
        "var origin=new URL(BASE).origin;"
        'function absolute(u){try{return new URL(u,BASE).href;}catch(e){return null;}}'
        'function proxied(u){return "/proxy?url="+encodeURIComponent(u);}'
        'function shouldProxy(u){return !!u&&u.indexOf(origin)===0&&/^https?:/.test(u);}'
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
        "note": "Leitura sem sessão: sites com login continuam a abrir numa aba do sistema.",
    }
