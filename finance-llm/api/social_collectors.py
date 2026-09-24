"""Coletores das redes sociais (LinkedIn, TikTok, Reddit e Facebook).

Este módulo sabe **como falar com cada plataforma** e devolve sempre a mesma
forma normalizada — é o equivalente, para as redes sociais, do que um *parser*
de site é para a recolha web (`scraper_service`).

O que funciona sem credenciais (verificado nesta máquina)
---------------------------------------------------------
- **LinkedIn** — a página pública de uma empresa (`/company/<slug>/`) traz um
  bloco `JSON-LD` com a publicação mais recente: autor, data, texto, ligação e
  número de reações. Não precisa de sessão.
- **Reddit** — o JSON público (`/r/<sub>/hot.json`) responde a HTTP simples com
  impressão digital de Chrome; quando o IP está bloqueado, a página
  `shreddit-post` do mesmo endereço continua a servir de alternativa.
- **TikTok** — o `oembed` (por URL de vídeo) e o `api/challenge/detail` (por
  hashtag) respondem sem chave; a página `/embed/tag/<tag>` dá as ligações dos
  vídeos em destaque, que depois se enriquecem pelo `oembed`.

O que exige credenciais
-----------------------
- **Reddit · pesquisa por palavra-chave** — a página de pesquisa é bloqueada a
  IPs de servidor; usa-se a API OAuth (`client_id`/`client_secret`).
- **Facebook** — a Graph API exige um `access_token` (token de página). Sem
  token não há recolha; o canal fica marcado como «precisa de credenciais», com
  a indicação de onde obter o token.

Tudo degrada com elegância: uma plataforma em baixo devolve um erro explicativo
por canal, sem derrubar a API nem os outros canais.
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

DEFAULT_TIMEOUT = 30.0
DEFAULT_LIMIT = 25
MAX_LIMIT = 200

#: Agente de browser usado nas páginas públicas (as APIs JSON não o precisam).
BROWSER_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)

#: Catálogo das plataformas suportadas: rótulos, variantes e o que cada uma pede.
PLATFORMS: Dict[str, Dict[str, Any]] = {
    "linkedin": {
        "label": "LinkedIn",
        "kinds": {
            "company": {
                "label": "Empresa (página pública)",
                "target": "identificador da empresa (ex.: microsoft)",
                "credentials": False,
                "notes": "Página pública: traz a publicação mais recente em JSON-LD (texto, data, reações).",
            },
        },
        "credential_hint": "",
        "color": "#0a66c2",
    },
    "reddit": {
        "label": "Reddit",
        "kinds": {
            "subreddit": {
                "label": "Comunidade (subreddit)",
                "target": "nome do subreddit (ex.: investimentos)",
                "credentials": False,
                "notes": "JSON público da listagem; alternativa HTML (`shreddit-post`) se o IP estiver bloqueado.",
            },
            "search": {
                "label": "Pesquisa por palavra-chave",
                "target": "termo a pesquisar",
                "credentials": True,
                "notes": "A página de pesquisa bloqueia IPs de servidor; usa a API OAuth do Reddit.",
            },
        },
        "credential_hint": (
            "Crie uma aplicação em https://www.reddit.com/prefs/apps (tipo «script») e "
            "preencha `client_id` e `client_secret` nas opções do canal."
        ),
        "color": "#ff4500",
    },
    "tiktok": {
        "label": "TikTok",
        "kinds": {
            "hashtag": {
                "label": "Hashtag",
                "target": "hashtag sem # (ex.: edp)",
                "credentials": False,
                "notes": "Métricas da hashtag pela API pública + vídeos em destaque da página de incorporação.",
            },
            "video": {
                "label": "Vídeo (URL)",
                "target": "ligação completa do vídeo",
                "credentials": False,
                "notes": "Metadados do vídeo pelo oembed oficial (título, autor, miniatura).",
            },
        },
        "credential_hint": "",
        "color": "#000000",
    },
    "facebook": {
        "label": "Facebook",
        "kinds": {
            "page": {
                "label": "Página",
                "target": "identificador ou nome da página",
                "credentials": True,
                "notes": "Graph API: publicações com mensagem, data, reações, comentários e partilhas.",
            },
        },
        "credential_hint": (
            "Crie uma aplicação em https://developers.facebook.com/apps e use um token de "
            "página em `access_token` (variável FACEBOOK_ACCESS_TOKEN)."
        ),
        "color": "#1877f2",
    },
}

PLATFORM_IDS = tuple(PLATFORMS.keys())


class CollectorError(RuntimeError):
    """Falha de recolha já explicada para o utilizador.

    `status` distingue o que o canal precisa: `credentials` (falta uma chave),
    `blocked` (a plataforma recusou o pedido) ou `error` (qualquer outra falha).
    """

    def __init__(self, message: str, *, status: str = "error", hint: str = "") -> None:
        super().__init__(message)
        self.status = status
        self.hint = hint


# ------------------------------------------------------------------ utilidades
def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _iso_from_epoch(value: Any) -> Optional[str]:
    """Converte segundos Unix (Reddit) numa data ISO."""
    try:
        stamp = float(value)
    except (TypeError, ValueError):
        return None
    if stamp <= 0:
        return None
    return datetime.fromtimestamp(stamp, tz=timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _int(value: Any) -> int:
    """Inteiro tolerante (o Reddit devolve `score` por vezes como string/None)."""
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return 0


def _clean(value: Any, limit: int = 20000) -> str:
    text = re.sub(r"\s+", " ", str(value or "")).strip()
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


def _post_id_from_url(url: str) -> str:
    """Identificador estável a partir de uma ligação de publicação."""
    match = re.search(r"(?:activity|status|posts|video)[-_/](\d{6,})", url or "")
    if match:
        return match.group(1)
    match = re.search(r"/comments/([a-z0-9]+)", url or "", re.I)
    if match:
        return match.group(1)
    return hashlib.sha1((url or "").encode("utf-8")).hexdigest()[:16]


def _item_id(platform: str, kind: str, target: str, post_id: str) -> str:
    """Identidade global de uma publicação (`_id` no Elasticsearch)."""
    raw = f"{platform}|{kind}|{target}|{post_id}".lower()
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()


def _post(
    *,
    platform: str,
    kind: str,
    target: str,
    post_id: str,
    url: str = "",
    title: str = "",
    text: str = "",
    author: str = "",
    community: str = "",
    published_at: Optional[str] = None,
    metrics: Optional[Dict[str, Any]] = None,
    image: str = "",
    tags: Optional[List[str]] = None,
    data: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Publicação normalizada (a mesma forma para todas as plataformas)."""
    metrics = {k: _int(v) for k, v in (metrics or {}).items() if v is not None}
    return {
        "platform": platform,
        "kind": kind,
        "target": target,
        "post_id": str(post_id),
        "item_id": _item_id(platform, kind, target, str(post_id)),
        "url": url,
        "title": _clean(title, 1024),
        "text": _clean(text, 20000),
        "author": _clean(author, 256),
        "community": _clean(community, 256),
        "published_at": published_at,
        "metrics": metrics,
        "media": {"image": image} if image else {},
        "tags": [str(t) for t in (tags or []) if t][:32],
        "lang": "",
        "collected_at": _now(),
        "data": data or {},
    }


def _json_after(text: str, marker: str) -> Optional[Any]:
    """Extrai o objeto JSON que começa no primeiro `{` a seguir a `marker`."""
    index = text.find(marker)
    if index < 0:
        return None
    begin = text.find("{", index)
    if begin < 0:
        return None
    depth = 0
    in_string = False
    escape = False
    for pos in range(begin, len(text)):
        char = text[pos]
        if in_string:
            if escape:
                escape = False
            elif char == "\\":
                escape = True
            elif char == '"':
                in_string = False
            continue
        if char == '"':
            in_string = True
        elif char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                try:
                    return json.loads(text[begin : pos + 1])
                except json.JSONDecodeError:
                    return None
    return None


# ------------------------------------------------------------- clientes HTTP
def _proxy_for(options: Dict[str, Any]) -> str:
    """Proxy do canal (opções do canal ou variáveis de ambiente)."""
    return str(
        (options or {}).get("proxy")
        or os.environ.get("SOCIAL_PROXY")
        or os.environ.get("TWOCAPTCHA_PROXY")
        or ""
    ).strip()


def _credential(options: Dict[str, Any], *names: str) -> str:
    """Primeiro valor não vazio entre as opções do canal e as variáveis de ambiente."""
    options = options or {}
    for name in names:
        value = options.get(name)
        if value:
            return str(value).strip()
    for name in names:
        value = os.environ.get(name.upper())
        if value:
            return str(value).strip()
    return ""


def _http_get(
    url: str,
    *,
    params: Optional[Dict[str, Any]] = None,
    headers: Optional[Dict[str, str]] = None,
    options: Optional[Dict[str, Any]] = None,
    timeout: float = DEFAULT_TIMEOUT,
    expect_json: bool = True,
) -> Any:
    """Pedido HTTP simples, com proxy opcional e erros já traduzidos.

    Um 429 (limite de pedidos) é repetido uma vez depois de uma pausa curta: as
    plataformas sociais limitam rajadas e a repetição resolve a maior parte dos
    casos sem intervenção.
    """
    try:
        import httpx
    except Exception as exc:  # pragma: no cover - httpx é dependência base
        raise CollectorError("O `httpx` não está instalado no interpretador da API.") from exc

    options = options or {}
    proxy = _proxy_for(options)
    kwargs: Dict[str, Any] = {"timeout": timeout, "follow_redirects": True}
    if proxy:
        kwargs["proxy"] = proxy
    request_headers = {"User-Agent": BROWSER_UA, "Accept-Language": "pt-PT,pt;q=0.9,en;q=0.8"}
    request_headers.update(headers or {})

    response: Any = None
    for attempt in range(2):
        try:
            with httpx.Client(**kwargs) as client:
                response = client.get(url, params=params, headers=request_headers)
        except Exception as exc:
            raise CollectorError(f"Falha de rede ao contactar {url}: {exc}", status="error") from exc
        if response.status_code != 429 or attempt == 1:
            break
        pause = _retry_after_seconds(response) or 3.0
        logger.info("Pesquisa social: %s limitou os pedidos (429); nova tentativa em %.0f s.", url, pause)
        time.sleep(min(pause, 30.0))

    if response.status_code == 403:
        raise CollectorError(
            f"A plataforma recusou o pedido (403) a {url}.",
            status="blocked",
            hint="Tente um proxy residencial nas opções do canal (`proxy`).",
        )
    if response.status_code == 429:
        raise CollectorError(
            "A plataforma limitou os pedidos (429) mesmo depois de uma repetição. Tente mais tarde.",
            status="blocked",
        )
    if response.status_code >= 400:
        detail = _clean(response.text, 300) or f"HTTP {response.status_code}"
        raise CollectorError(
            f"Resposta {response.status_code} de {url}: {detail}",
            status="blocked" if response.status_code in (401, 403, 451) else "error",
        )

    if not expect_json:
        return response.text
    try:
        return response.json()
    except Exception as exc:
        raise CollectorError(
            f"A resposta de {url} não é JSON (provável página de bloqueio).",
            status="blocked",
            hint="Tente um proxy residencial ou outro tipo de recolha.",
        ) from exc


def _retry_after_seconds(response: Any) -> Optional[float]:
    """Segundos pedidos pelo servidor no cabeçalho `Retry-After`."""
    raw = ""
    try:
        raw = str(response.headers.get("retry-after") or "").strip()
    except Exception:
        return None
    if not raw:
        return None
    try:
        return float(raw)
    except ValueError:
        return None


def _fetch_html(url: str, options: Optional[Dict[str, Any]] = None) -> Any:
    """Página HTML com a impressão digital de Chrome (Scrapling `http`)."""
    try:
        from scrapling.fetchers import FetcherSession  # type: ignore
    except Exception as exc:
        raise CollectorError(
            "O Scrapling não está instalado no interpretador que corre a API.",
            hint="Instale com `pip install \"scrapling[fetchers]\"`.",
        ) from exc

    options = options or {}
    proxy = _proxy_for(options)
    kwargs: Dict[str, Any] = {"impersonate": "chrome"}
    if proxy:
        kwargs["proxy"] = proxy
    try:
        with FetcherSession(**kwargs) as session:
            try:
                page = session.get(url, stealthy_headers=True, timeout=int(options.get("timeout") or DEFAULT_TIMEOUT))
            except TypeError:
                page = session.get(url, timeout=int(options.get("timeout") or DEFAULT_TIMEOUT))
    except Exception as exc:
        raise CollectorError(f"Falha ao abrir {url}: {exc}") from exc

    status = getattr(page, "status", None)
    if status == 403:
        raise CollectorError(f"A plataforma recusou o pedido (403) a {url}.", status="blocked")
    return page


def _page_html(page: Any) -> str:
    """HTML de uma página do Scrapling (`html_content` é o corpo já descodificado)."""
    for name in ("html_content", "body"):
        value = getattr(page, name, None)
        if value is None:
            continue
        if isinstance(value, (bytes, bytearray)):
            try:
                return value.decode("utf-8", "replace")
            except Exception:
                continue
        text = str(value)
        if text:
            return text
    return ""


def _fetch_text(url: str, options: Optional[Dict[str, Any]] = None) -> str:
    """HTML de uma página pública.

    Usa o Scrapling (impressão digital TLS de Chrome, que o LinkedIn exige) e cai
    no httpx quando o Scrapling não está instalado ou não devolve corpo.
    """
    try:
        page = _fetch_html(url, options)
    except CollectorError as exc:
        logger.debug("Scrapling falhou em %s (%s); a usar httpx.", url, exc)
        return _http_get(url, options=options, expect_json=False)
    html = _page_html(page)
    if html:
        return html
    return _http_get(url, options=options, expect_json=False)


def _node_attr(node: Any, *names: str) -> str:
    """Atributo de um nó do Scrapling (tolerante a nomes ausentes)."""
    attrib = getattr(node, "attrib", None)
    if not isinstance(attrib, dict):
        return ""
    for name in names:
        value = attrib.get(name)
        if value:
            return str(value)
        lowered = {str(k).lower(): v for k, v in attrib.items()}
        if name.lower() in lowered and lowered[name.lower()]:
            return str(lowered[name.lower()])
    return ""


def _node_text(node: Any) -> str:
    """Texto de um nó do Scrapling (HTML pode trazer marcação pelo meio)."""
    try:
        return _clean(getattr(node, "text", "") or "")
    except Exception:
        return ""


def _css(page: Any, selector: str) -> List[Any]:
    try:
        return list(page.css(selector) or [])
    except Exception:
        return []


# ------------------------------------------------------------------- LinkedIn
#: Campos do bloco `Organization` do JSON-LD que interessam à ficha da empresa.

def _linkedin_from_html(text: str) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    """Extrai as publicações e a ficha da empresa do JSON-LD da página pública."""
    blocks = re.findall(r'<script type="application/ld\+json">(.*?)</script>', text, re.S)
    posts: List[Dict[str, Any]] = []
    organization: Dict[str, Any] = {}
    for block in blocks:
        try:
            payload = json.loads(block)
        except json.JSONDecodeError:
            continue
        graph = payload.get("@graph") if isinstance(payload, dict) else None
        nodes = graph if isinstance(graph, list) else ([payload] if isinstance(payload, dict) else [])
        for node in nodes:
            if not isinstance(node, dict):
                continue
            if node.get("@type") == "SocialMediaPosting":
                link = str(node.get("mainEntityOfPage") or "")
                stats = node.get("interactionStatistic") or {}
                likes = 0
                if isinstance(stats, list):
                    for entry in stats:
                        likes = max(likes, _int((entry or {}).get("userInteractionCount")))
                    stats = stats[0] if stats else {}
                if isinstance(stats, dict):
                    likes = likes or _int(stats.get("userInteractionCount"))
                author = node.get("author") or {}
                posts.append(
                    _post(
                        platform="linkedin",
                        kind="company",
                        target="",
                        post_id=_post_id_from_url(link),
                        url=link,
                        title=_clean(node.get("text"), 200),
                        text=node.get("text"),
                        author=_clean((author or {}).get("name") if isinstance(author, dict) else author, 256),
                        published_at=node.get("datePublished"),
                        metrics={"likes": likes},
                        data={"headline": node.get("headline") or ""},
                    )
                )
            elif node.get("@type") == "Organization":
                stats = node.get("interactionStatistic")
                organization = {
                    "name": node.get("name") or "",
                    "description": node.get("description") or "",
                    "url": node.get("url") or "",
                    "logo": node.get("logo") or "",
                    "followers": _int(stats.get("userInteractionCount")) if isinstance(stats, dict) else 0,
                }
    return posts, organization


def collect_linkedin(channel: Dict[str, Any], *, limit: int = DEFAULT_LIMIT) -> Dict[str, Any]:
    """Publicações públicas de uma empresa (a página «guest» traz JSON-LD)."""
    target = str(channel.get("target") or "").strip().strip("/")
    if not target:
        raise CollectorError("O canal do LinkedIn precisa do identificador da empresa (`target`).")
    url = f"https://www.linkedin.com/company/{target}/"

    # O LinkedIn varia o HTML (e às vezes serve uma versão sem JSON-LD): repete-se
    # uma vez antes de dar a página por vazia.
    posts: List[Dict[str, Any]] = []
    organization: Dict[str, Any] = {}
    attempts = max(1, int(channel.get("options", {}).get("attempts") or 2))
    for attempt in range(attempts):
        text = _fetch_text(url, channel.get("options"))
        posts, organization = _linkedin_from_html(text)
        if posts:
            break
        if attempt + 1 < attempts:
            time.sleep(1.5)

    #: O `target` entra no `item_id` (identidade global da publicação).
    for item in posts:
        item["target"] = target
        item["community"] = f"linkedin.com/company/{target}"
        item["tags"] = ["linkedin", target]
        item["item_id"] = _item_id(item["platform"], item["kind"], target, item["post_id"])
    posts = posts[: max(1, limit)]
    organization = {**organization, "url": organization.get("url") or url}
    notes: List[str] = []
    if not posts:
        notes.append(
            "A página pública não trouxe publicações em JSON-LD (o LinkedIn varia o HTML por região/sessão)."
        )
    if organization:
        notes.append(
            f"Empresa: {organization.get('name') or target}"
            + (f" · {organization['followers']} seguidores" if organization.get("followers") else "")
        )
    return {"items": posts, "notes": notes, "organization": organization}


# --------------------------------------------------------------------- Reddit
def _reddit_token(options: Dict[str, Any]) -> str:
    """Token de acesso à API do Reddit (credenciais do canal ou ambiente)."""
    token = _credential(options, "token", "access_token", "reddit_token")
    if token:
        return token
    client_id = _credential(options, "client_id", "reddit_client_id")
    client_secret = _credential(options, "client_secret", "reddit_client_secret")
    if not (client_id and client_secret):
        return ""
    try:
        import httpx
    except Exception as exc:  # pragma: no cover
        raise CollectorError("O `httpx` não está instalado no interpretador da API.") from exc
    kwargs: Dict[str, Any] = {"timeout": DEFAULT_TIMEOUT}
    proxy = _proxy_for(options)
    if proxy:
        kwargs["proxy"] = proxy
    username = _credential(options, "username", "reddit_username") or client_id
    try:
        with httpx.Client(**kwargs) as client:
            response = client.post(
                "https://www.reddit.com/api/v1/access_token",
                data={"grant_type": "client_credentials"},
                auth=(client_id, client_secret),
                headers={"User-Agent": _credential(options, "user_agent") or "IQOS/1.0 (pesquisa social)"},
            )
    except Exception as exc:
        raise CollectorError(f"Falha ao pedir token ao Reddit: {exc}") from exc
    if response.status_code >= 400:
        raise CollectorError(
            f"O Reddit recusou as credenciais ({response.status_code}).",
            status="credentials",
            hint=PLATFORMS["reddit"]["credential_hint"],
        )
    payload = response.json() if response.headers.get("content-type", "").startswith("application/json") else {}
    del username
    return str(payload.get("access_token") or "")


def _reddit_json_posts(payload: Any, target: str, kind: str) -> List[Dict[str, Any]]:
    """Normaliza a lista `data.children` do Reddit (JSON público ou OAuth)."""
    children = ((payload or {}).get("data") or {}).get("children") or []
    posts: List[Dict[str, Any]] = []
    for child in children:
        row = (child or {}).get("data") or {}
        post_id = str(row.get("id") or "")
        permalink = row.get("permalink") or ""
        url = f"https://www.reddit.com{permalink}" if permalink.startswith("/") else (permalink or row.get("url") or "")
        body = row.get("selftext") or ""
        flair = row.get("link_flair_text") or ""
        posts.append(
            _post(
                platform="reddit",
                kind=kind,
                target=target,
                post_id=post_id or _post_id_from_url(url),
                url=url,
                title=row.get("title") or "",
                text=body,
                author=str(row.get("author") or ""),
                community=str(row.get("subreddit_name_prefixed") or f"r/{row.get('subreddit') or target}"),
                published_at=_iso_from_epoch(row.get("created_utc")),
                metrics={
                    "likes": row.get("score"),
                    "comments": row.get("num_comments"),
                    "views": row.get("view_count"),
                },
                image=str(row.get("thumbnail") or "") if str(row.get("thumbnail") or "").startswith("http") else "",
                tags=[t for t in ["reddit", target, flair] if t],
                data={
                    "upvote_ratio": row.get("upvote_ratio"),
                    "over_18": row.get("over_18"),
                    "is_video": row.get("is_video"),
                    "external_url": row.get("url") if row.get("url") != url else "",
                    "flair": flair,
                },
            )
        )
    return posts


def _reddit_html_posts(page: Any, target: str, kind: str) -> List[Dict[str, Any]]:
    """Alternativa sem JSON: os cartões `shreddit-post` da listagem pública.

    É o caminho que funciona quando o JSON responde 403 (bloqueio a IPs de
    datacenter): a página HTML continua a ser servida com os atributos do cartão.
    """
    posts: List[Dict[str, Any]] = []
    for node in _css(page, "shreddit-post"):
        permalink = _node_attr(node, "permalink")
        url = f"https://www.reddit.com{permalink}" if permalink.startswith("/") else permalink
        raw_id = _node_attr(node, "id") or ""
        post_id = raw_id.split("_")[-1] if raw_id else _post_id_from_url(url)
        title = _node_attr(node, "post-title") or _node_text(node)
        community = _node_attr(node, "subreddit-prefixed-name") or f"r/{target}"
        flair = _node_attr(node, "flair-text", "link-flair-text")
        images = _css(node, "img")
        image = ""
        for media in images:
            candidate = _node_attr(media, "src")
            if candidate.startswith("http"):
                image = candidate
                break
        posts.append(
            _post(
                platform="reddit",
                kind=kind,
                target=target,
                post_id=post_id,
                url=url,
                title=title,
                author=_node_attr(node, "author"),
                community=community,
                published_at=_node_attr(node, "created-timestamp") or None,
                metrics={
                    "likes": _node_attr(node, "score"),
                    "comments": _node_attr(node, "comment-count"),
                },
                image=image,
                tags=[t for t in ["reddit", target, flair] if t],
                data={
                    "post_type": _node_attr(node, "post-type"),
                    "domain": _node_attr(node, "domain"),
                    "content_href": _node_attr(node, "content-href"),
                },
            )
        )
    return posts


def collect_reddit(channel: Dict[str, Any], *, limit: int = DEFAULT_LIMIT) -> Dict[str, Any]:
    """Publicações de um subreddit ou resultados de uma pesquisa no Reddit."""
    target = str(channel.get("target") or "").strip().lstrip("/")
    kind = str(channel.get("kind") or "subreddit")
    if not target:
        raise CollectorError("O canal do Reddit precisa de um `target` (subreddit ou termo de pesquisa).")
    options = channel.get("options") or {}
    notes: List[str] = []
    limit = max(1, min(int(limit), MAX_LIMIT))

    if kind == "search":
        token = _reddit_token(options)
        if not token:
            raise CollectorError(
                "A pesquisa por palavra-chave no Reddit exige credenciais OAuth.",
                status="credentials",
                hint=PLATFORMS["reddit"]["credential_hint"],
            )
        payload = _http_get(
            "https://oauth.reddit.com/search",
            params={"q": target, "limit": limit, "sort": "relevance", "t": "month", "raw_json": 1},
            headers={"Authorization": f"Bearer {token}"},
            options=options,
        )
        return {"items": _reddit_json_posts(payload, target, kind)[:limit], "notes": notes}

    # Subreddit: percorre as variantes públicas (JSON e HTML, domínio novo e
    # antigo) — o Reddit bloqueia umas e serve outras conforme o IP e a altura.
    subreddit = target.split("/")[-1]
    json_endpoints = (
        f"https://www.reddit.com/r/{subreddit}/hot.json",
        f"https://old.reddit.com/r/{subreddit}/hot.json",
        f"https://api.reddit.com/r/{subreddit}/hot",
    )
    for endpoint in json_endpoints:
        try:
            payload = _http_get(
                endpoint,
                params={"limit": limit, "raw_json": 1},
                headers={"User-Agent": _credential(options, "user_agent") or "IQOS/1.0 (pesquisa social)"},
                options=options,
            )
        except CollectorError as exc:
            notes.append(f"{endpoint} → {exc}")
            continue
        posts = _reddit_json_posts(payload, subreddit, kind)
        if posts:
            return {"items": posts[:limit], "notes": notes}
        notes.append(f"{endpoint} devolveu uma lista vazia.")

    html_endpoints = (
        f"https://www.reddit.com/r/{subreddit}/hot/",
        f"https://old.reddit.com/r/{subreddit}/hot/",
    )
    for endpoint in html_endpoints:
        try:
            page = _fetch_html(endpoint, options)
        except CollectorError as exc:
            notes.append(f"{endpoint} → {exc}")
            continue
        posts = _reddit_html_posts(page, subreddit, kind)
        if posts:
            notes.append(f"Recolha pela listagem HTML de {endpoint}.")
            return {"items": posts[:limit], "notes": notes}
        notes.append(f"{endpoint} não trouxe cartões (`shreddit-post`).")

    raise CollectorError(
        f"O Reddit não devolveu publicações de r/{subreddit} em nenhum dos endereços públicos.",
        status="blocked",
        hint=(
            "O Reddit bloqueia IPs de servidor. Configure um proxy residencial nas opções do canal "
            "(`proxy`) ou use credenciais OAuth (`client_id`/`client_secret`) com a variante «pesquisa»."
        ),
    )


# --------------------------------------------------------------------- TikTok
def _tiktok_hashtag_stats(tag: str, options: Dict[str, Any]) -> Dict[str, Any]:
    """Métricas da hashtag (API pública de desafios)."""
    payload = _http_get(
        "https://www.tiktok.com/api/challenge/detail/",
        params={"challengeName": tag, "aid": "1988"},
        options=options,
    )
    info = (payload or {}).get("challengeInfo") or {}
    challenge = info.get("challenge") or {}
    stats = challenge.get("stats") or {}
    return {
        "challenge_id": str(challenge.get("id") or ""),
        "title": challenge.get("title") or tag,
        "desc": challenge.get("desc") or "",
        "videos": _int(stats.get("videoCount")),
        "views": _int(stats.get("viewCount")),
    }


def _tiktok_oembed(url: str, options: Dict[str, Any]) -> Dict[str, Any]:
    """Metadados oficiais de um vídeo (não exige chave)."""
    payload = _http_get("https://www.tiktok.com/oembed", params={"url": url}, options=options)
    return payload if isinstance(payload, dict) else {}


def _tiktok_embed_video_urls(tag: str, options: Dict[str, Any]) -> List[str]:
    """Ligações de vídeos em destaque na página de incorporação da hashtag."""
    page = _fetch_html(f"https://www.tiktok.com/embed/tag/{tag}", options)
    urls: List[str] = []
    for node in _css(page, "a[href*='/video/']"):
        href = _node_attr(node, "href")
        if not href:
            continue
        if href.startswith("/"):
            href = f"https://www.tiktok.com{href}"
        if re.search(r"/video/\d+", href) and href not in urls:
            urls.append(href)
    return urls


def collect_tiktok(channel: Dict[str, Any], *, limit: int = DEFAULT_LIMIT) -> Dict[str, Any]:
    """Hashtag (métricas + vídeos em destaque) ou um vídeo concreto do TikTok."""
    target = str(channel.get("target") or "").strip().lstrip("#").strip()
    kind = str(channel.get("kind") or "hashtag")
    options = channel.get("options") or {}
    notes: List[str] = []
    if not target:
        raise CollectorError("O canal do TikTok precisa de um `target` (hashtag ou ligação do vídeo).")

    if kind == "video":
        url = target if target.startswith("http") else f"https://www.tiktok.com/{target.lstrip('/')}"
        payload = _tiktok_oembed(url, options)
        if not payload:
            raise CollectorError(f"O TikTok não devolveu metadados para {url}.")
        author_url = str(payload.get("author_url") or "")
        posts = [
            _post(
                platform="tiktok",
                kind="video",
                target=url,
                post_id=_post_id_from_url(url),
                url=url,
                title=payload.get("title") or "",
                text=payload.get("title") or "",
                author=payload.get("author_name") or "",
                community=author_url.replace("https://www.tiktok.com/", ""),
                image=str(payload.get("thumbnail_url") or ""),
                tags=["tiktok", "video"],
                data={"author_url": author_url, "type": payload.get("type") or ""},
            )
        ]
        return {"items": posts, "notes": notes}

    # Hashtag: métricas + vídeos em destaque (enriquecidos por oembed).
    stats = _tiktok_hashtag_stats(target, options)
    tag_post = _post(
        platform="tiktok",
        kind="hashtag",
        target=target,
        post_id=stats.get("challenge_id") or f"tag-{target}",
        url=f"https://www.tiktok.com/tag/{target}",
        title=f"#{stats.get('title') or target}",
        text=stats.get("desc") or "",
        author="TikTok",
        community=f"#{(stats.get('title') or target)}",
        published_at=None,
        metrics={"views": stats.get("views"), "videos": stats.get("videos")},
        tags=["tiktok", "hashtag", target],
        data={"video_count": stats.get("videos"), "view_count": stats.get("views")},
    )
    items: List[Dict[str, Any]] = [tag_post]
    notes.append(
        f"Hashtag #{target}: {stats.get('videos', 0)} vídeos · {stats.get('views', 0)} visualizações."
    )

    video_urls = _tiktok_embed_video_urls(target, options)
    if not video_urls:
        notes.append(
            "A página de incorporação não expôs vídeos (o TikTok serve a lista por JavaScript); "
            "adicione canais `video` com as ligações concretas."
        )
    for url in video_urls[: max(0, limit - 1)]:
        try:
            payload = _tiktok_oembed(url, options)
        except CollectorError as exc:
            notes.append(f"oembed falhou para {url}: {exc}")
            continue
        if not payload:
            continue
        items.append(
            _post(
                platform="tiktok",
                kind="hashtag",
                target=target,
                post_id=_post_id_from_url(url),
                url=url,
                title=payload.get("title") or "",
                text=payload.get("title") or "",
                author=payload.get("author_name") or "",
                community=f"#{(stats.get('title') or target)}",
                image=str(payload.get("thumbnail_url") or ""),
                tags=["tiktok", "hashtag", target],
                data={"author_url": payload.get("author_url") or "", "source": "embed"},
            )
        )
    return {"items": items[:limit], "notes": notes}


# ------------------------------------------------------------------- Facebook
def collect_facebook(channel: Dict[str, Any], *, limit: int = DEFAULT_LIMIT) -> Dict[str, Any]:
    """Publicações de uma página do Facebook (Graph API, exige token)."""
    target = str(channel.get("target") or "").strip().strip("/")
    options = channel.get("options") or {}
    if not target:
        raise CollectorError("O canal do Facebook precisa do identificador da página (`target`).")
    token = _credential(options, "access_token", "token", "facebook_token")
    if not token:
        raise CollectorError(
            "A recolha do Facebook exige um token de acesso (Graph API).",
            status="credentials",
            hint=PLATFORMS["facebook"]["credential_hint"],
        )
    version = str(options.get("api_version") or "v21.0")
    payload = _http_get(
        f"https://graph.facebook.com/{version}/{target}/posts",
        params={
            "fields": (
                "id,message,story,created_time,permalink_url,full_picture,"
                "shares,reactions.summary(total_count),comments.summary(total_count)"
            ),
            "limit": max(1, min(int(limit), MAX_LIMIT)),
            "access_token": token,
        },
        options=options,
    )
    if isinstance(payload, dict) and payload.get("error"):
        error = payload["error"] or {}
        raise CollectorError(
            f"Graph API do Facebook: {error.get('message') or 'erro desconhecido'}",
            status="credentials" if error.get("code") in (190, 10, 200) else "error",
            hint=PLATFORMS["facebook"]["credential_hint"],
        )

    rows = (payload or {}).get("data") or []
    posts: List[Dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        reactions = ((row.get("reactions") or {}).get("summary") or {}).get("total_count")
        comments = ((row.get("comments") or {}).get("summary") or {}).get("total_count")
        shares = (row.get("shares") or {}).get("count")
        url = row.get("permalink_url") or f"https://www.facebook.com/{row.get('id') or ''}"
        posts.append(
            _post(
                platform="facebook",
                kind="page",
                target=target,
                post_id=str(row.get("id") or _post_id_from_url(url)),
                url=url,
                title=_clean(row.get("message") or row.get("story"), 200),
                text=row.get("message") or row.get("story") or "",
                author=target,
                community=f"facebook.com/{target}",
                published_at=row.get("created_time"),
                metrics={"likes": reactions, "comments": comments, "shares": shares},
                image=str(row.get("full_picture") or ""),
                tags=["facebook", target],
                data={"story": row.get("story") or ""},
            )
        )
    notes: List[str] = [] if posts else ["A página não devolveu publicações (pode não existir ou estar restrita)."]
    return {"items": posts, "notes": notes}


# -------------------------------------------------------------------- despacho
_COLLECTORS = {
    "linkedin": collect_linkedin,
    "reddit": collect_reddit,
    "tiktok": collect_tiktok,
    "facebook": collect_facebook,
}


def validate_channel_definition(platform: str, kind: str, target: str) -> None:
    """Confirma que a plataforma, a variante e o alvo existem no catálogo."""
    if platform not in PLATFORMS:
        raise CollectorError(
            f"Plataforma desconhecida: {platform!r}. Aceites: {', '.join(PLATFORM_IDS)}.",
            status="definition",
        )
    kinds = PLATFORMS[platform]["kinds"]
    if kind not in kinds:
        raise CollectorError(
            f"Variante desconhecida para {platform}: {kind!r}. Aceites: {', '.join(kinds)}.",
            status="definition",
        )
    if not str(target or "").strip():
        raise CollectorError(f"O canal de {platform} precisa de um `target`.", status="definition")


def collect(channel: Dict[str, Any], *, limit: int = DEFAULT_LIMIT) -> Dict[str, Any]:
    """Recolhe as publicações de um canal, seja qual for a plataforma.

    Devolve `{"items": [...], "notes": [...], "platform": ...}`. Lança
    `CollectorError` (com `status` e `hint`) quando a plataforma recusa ou faltam
    credenciais — o serviço transforma isso no estado do canal.
    """
    platform = str(channel.get("platform") or "").strip().lower()
    kind = str(channel.get("kind") or "").strip().lower()
    target = str(channel.get("target") or "").strip()
    validate_channel_definition(platform, kind, target)
    collector = _COLLECTORS[platform]
    result = collector(channel, limit=limit)
    items = result.get("items") or []
    for item in items:
        item["channel_id"] = channel.get("id") or ""
        item["channel_name"] = channel.get("name") or channel.get("id") or ""
        tags = list(item.get("tags") or [])
        for extra in channel.get("tags") or []:
            if extra not in tags:
                tags.append(extra)
        item["tags"] = tags
    return {
        "platform": platform,
        "kind": kind,
        "target": target,
        "items": items,
        "notes": list(result.get("notes") or []),
        "organization": result.get("organization") or {},
    }


def platform_catalog() -> List[Dict[str, Any]]:
    """Catálogo das plataformas para a UI (sem segredos)."""
    catalog: List[Dict[str, Any]] = []
    for platform_id, entry in PLATFORMS.items():
        catalog.append(
            {
                "id": platform_id,
                "label": entry["label"],
                "color": entry.get("color", ""),
                "credential_hint": entry.get("credential_hint", ""),
                "kinds": [
                    {
                        "id": kind_id,
                        "label": kind.get("label", kind_id),
                        "target": kind.get("target", ""),
                        "credentials": bool(kind.get("credentials")),
                        "notes": kind.get("notes", ""),
                    }
                    for kind_id, kind in (entry.get("kinds") or {}).items()
                ],
            }
        )
    return catalog


def credential_names(platform: str) -> Tuple[str, ...]:
    """Nomes de opção que contam como credencial de uma plataforma."""
    return {
        "reddit": ("token", "access_token", "client_id", "client_secret"),
        "facebook": ("access_token", "token"),
    }.get(platform, ())
