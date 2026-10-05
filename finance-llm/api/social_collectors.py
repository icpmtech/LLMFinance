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
import importlib
import importlib.util
import json
import logging
import os
import re
import time
import warnings
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import quote_plus, urljoin, urlparse
from xml.etree import ElementTree

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
                "notes": (
                    "Tenta a API OAuth (se configurada), o JSON público, o feed Atom (`/.rss`) e, em "
                    "último recurso, o HTML (`shreddit-post`) — os IPs de servidor são recusados em "
                    "alguns destes endereços."
                ),
            },
            "search": {
                "label": "Pesquisa por palavra-chave",
                "target": "termo a pesquisar",
                "credentials": True,
                "notes": (
                    "Usa a API OAuth do Reddit quando há credenciais; sem elas tenta o feed de "
                    "pesquisa público (`/search.rss`)."
                ),
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
    "internet": {
        "label": "Internet",
        "kinds": {
            "page": {
                "label": "Página (URL)",
                "target": "ligação completa da página",
                "credentials": False,
                "notes": "Lê a página pública e traz título, texto, imagem e vídeo (Open Graph).",
            },
        },
        "credential_hint": "",
        "color": "#0ea5e9",
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
    video: str = "",
    images: Optional[List[str]] = None,
    videos: Optional[List[str]] = None,
    tags: Optional[List[str]] = None,
    data: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Publicação normalizada (a mesma forma para todas as plataformas)."""
    metrics = {k: _int(v) for k, v in (metrics or {}).items() if v is not None}
    gallery = [url for url in (images or []) if url]
    clips = [url for url in (videos or []) if url]
    media: Dict[str, Any] = {}
    if image or gallery:
        media["image"] = image or gallery[0]
        media["images"] = list(dict.fromkeys([media["image"], *gallery]))[:24]
    if video or clips:
        media["video"] = video or clips[0]
        media["videos"] = list(dict.fromkeys([media["video"], *clips]))[:12]
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
        "media": media,
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
    if status in (401, 429, 999):
        # 999 é o código com que o LinkedIn (e outros) recusam robôs.
        raise CollectorError(
            f"A plataforma bloqueou a leitura de {url} (estado {status}).",
            status="blocked",
            hint="Esta plataforma só serve conteúdos a sessões autenticadas; o que a pesquisa devolve fica registado como ligação.",
        )
    return page


def _page_html(page: Any) -> str:
    """HTML de uma página do Scrapling (`html_content` é o corpo já descodificado)."""
    for name in ("html_content", "body"):
        try:
            value = getattr(page, name, None)
        except Exception as exc:
            # Algumas páginas trazem bytes mal formados e o descodificador interno falha.
            logger.debug("Leitura de %s falhou numa página: %s", name, exc)
            continue
        if value is None:
            continue
        if isinstance(value, (bytes, bytearray)):
            for encoding in ("utf-8", "cp1252", "latin-1"):
                try:
                    return bytes(value).decode(encoding, "replace")
                except Exception:
                    continue
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


def _xml_local(tag: Any) -> str:
    """Nome local de uma etiqueta XML (sem o espaço de nomes)."""
    return str(tag or "").split("}")[-1].lower()


def _reddit_atom_entries(text: str) -> List[Dict[str, Any]]:
    """Entradas de um feed Atom (`/r/<sub>/.rss`) ou RSS do Reddit.

    O feed público é servido a IPs a que o JSON responde 403 (bloqueio a
    datacenter), por isso é a alternativa sem credenciais mais fiável.
    """
    try:
        root = ElementTree.fromstring((text or "").strip())
    except Exception:
        return []

    entries: List[Dict[str, Any]] = []
    for node in root.iter():
        if _xml_local(node.tag) not in ("entry", "item"):
            continue
        item: Dict[str, Any] = {"tags": []}
        for child in node:
            name = _xml_local(child.tag)
            if name == "title":
                item["title"] = child.text or ""
            elif name == "link":
                item["link"] = child.get("href") or (child.text or "")
            elif name in ("id", "guid"):
                item.setdefault("id", child.text or "")
            elif name in ("updated", "published", "pubdate"):
                item.setdefault("published", (child.text or "").strip())
            elif name in ("content", "description", "summary"):
                if not item.get("content"):
                    item["content"] = child.text or ""
            elif name == "author":
                inner = next((sub.text or "" for sub in child if _xml_local(sub.tag) == "name"), "")
                item["author"] = inner or (child.text or "")
            elif name == "creator":  # dc:creator (RSS)
                item["author"] = child.text or ""
            elif name == "category":
                # Atom do Reddit: `term="investimentos" label="r/investimentos"`.
                # Guardam-se os dois (distintos) para se distinguir a comunidade do flair.
                for value in (child.get("term"), child.get("label"), child.text):
                    value = str(value or "").strip()
                    if value and value not in item["tags"]:
                        item["tags"].append(value)
        entries.append(item)
    return entries


def _reddit_rss_posts(text: str, target: str, kind: str) -> List[Dict[str, Any]]:
    """Publicações a partir do feed Atom público do Reddit."""
    posts: List[Dict[str, Any]] = []
    for entry in _reddit_atom_entries(text):
        url = _clean(entry.get("link") or "", 1024)
        raw_id = str(entry.get("id") or "")
        post_id = raw_id.split("_")[-1] if raw_id.startswith("t") and "_" in raw_id else ""
        labels = [str(t) for t in (entry.get("tags") or []) if t]
        community = next((t for t in labels if t.startswith("r/")), "") or f"r/{target}"
        flair = next((t for t in labels if not t.startswith("r/") and t.lower() != str(target).lower()), "")
        posts.append(
            _post(
                platform="reddit",
                kind=kind,
                target=target,
                post_id=post_id or _post_id_from_url(url),
                url=url,
                title=entry.get("title") or "",
                text=_strip_tags(entry.get("content") or ""),
                author=str(entry.get("author") or "").replace("/u/", ""),
                community=community,
                published_at=_clean(entry.get("published") or "", 40) or None,
                tags=[t for t in ["reddit", target, flair] if t],
                data={"source": "rss", "flair": flair},
            )
        )
    return posts


def _reddit_feed(
    endpoints: Tuple[str, ...],
    target: str,
    kind: str,
    notes: List[str],
    options: Dict[str, Any],
    *,
    params: Optional[Dict[str, Any]] = None,
) -> List[Dict[str, Any]]:
    """Percorre os feeds públicos do Reddit até um devolver entradas."""
    headers = {
        "User-Agent": _credential(options, "user_agent") or "IQOS/1.0 (pesquisa social)",
        "Accept": "application/atom+xml,application/rss+xml,application/xml;q=0.9,*/*;q=0.8",
    }
    for endpoint in endpoints:
        try:
            feed = _http_get(
                endpoint,
                params=params,
                headers=headers,
                options=options,
                expect_json=False,
            )
        except CollectorError as exc:
            notes.append(f"{endpoint} → {exc}")
            continue
        posts = _reddit_rss_posts(feed, target, kind)
        if posts:
            notes.append(f"Recolha pelo feed público de {endpoint}.")
            return posts
        notes.append(f"{endpoint} não trouxe entradas.")
    return []


def _reddit_failure_detail(notes: List[str]) -> str:
    """Resumo legível das tentativas falhadas (para a mensagem de erro)."""
    reasons: List[str] = []
    for note in notes:
        if "→" not in note:
            continue
        endpoint, _, reason = note.partition("→")
        endpoint = endpoint.strip().removeprefix("https://").rstrip("/")
        reason = _clean(reason, 90)
        if reason and reason not in reasons:
            reasons.append(f"{endpoint}: {reason}")
    if not reasons:
        return ""
    return "\n" + "\n".join(f"• {r}" for r in reasons[-4:])


def collect_reddit(channel: Dict[str, Any], *, limit: int = DEFAULT_LIMIT) -> Dict[str, Any]:
    """Publicações de um subreddit ou resultados de uma pesquisa no Reddit."""
    target = str(channel.get("target") or "").strip().lstrip("/")
    kind = str(channel.get("kind") or "subreddit")
    if not target:
        raise CollectorError("O canal do Reddit precisa de um `target` (subreddit ou termo de pesquisa).")
    options = channel.get("options") or {}
    notes: List[str] = []
    limit = max(1, min(int(limit), MAX_LIMIT))

    token = ""
    try:
        token = _reddit_token(options)
    except CollectorError as exc:
        notes.append(f"Credenciais do Reddit ignoradas: {exc}")

    if kind == "search":
        if token:
            try:
                payload = _http_get(
                    "https://oauth.reddit.com/search",
                    params={"q": target, "limit": limit, "sort": "relevance", "t": "month", "raw_json": 1},
                    headers={"Authorization": f"Bearer {token}"},
                    options=options,
                )
            except CollectorError as exc:
                notes.append(f"Pesquisa OAuth → {exc}")
            else:
                posts = _reddit_json_posts(payload, target, kind)
                if posts:
                    notes.append("Recolha pela API OAuth do Reddit.")
                    return {"items": posts[:limit], "notes": notes}
                notes.append("A pesquisa OAuth não devolveu publicações.")
        else:
            notes.append("Sem credenciais OAuth; a tentar o feed de pesquisa público.")

        posts = _reddit_feed(
            ("https://www.reddit.com/search.rss", "https://old.reddit.com/search.rss"),
            target,
            kind,
            notes,
            options,
            params={"q": target, "sort": "relevance", "t": "month", "limit": limit},
        )
        if posts:
            return {"items": posts[:limit], "notes": notes}

        raise CollectorError(
            f"A pesquisa no Reddit por «{target}» não devolveu publicações.",
            status="credentials" if not token else "blocked",
            hint=PLATFORMS["reddit"]["credential_hint"],
        )

    # Subreddit: OAuth (se configurado), variantes públicas JSON, feed Atom e,
    # por fim, HTML — o Reddit bloqueia umas e serve outras conforme o IP e a
    # altura.
    subreddit = target.split("/")[-1]

    if token:
        for path in (f"r/{subreddit}/hot", f"r/{subreddit}/new"):
            try:
                payload = _http_get(
                    f"https://oauth.reddit.com/{path}",
                    params={"limit": limit, "raw_json": 1},
                    headers={"Authorization": f"Bearer {token}"},
                    options=options,
                )
            except CollectorError as exc:
                notes.append(f"oauth.reddit.com/{path} → {exc}")
                continue
            posts = _reddit_json_posts(payload, subreddit, kind)
            if posts:
                notes.append(f"Recolha pela API OAuth do Reddit ({path}).")
                return {"items": posts[:limit], "notes": notes}
            notes.append(f"oauth.reddit.com/{path} devolveu uma lista vazia.")

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

    # Feed Atom público: é o endereço que continua a responder quando o JSON
    # devolve 403 a IPs de datacenter (traz título, autor, data e o corpo).
    posts = _reddit_feed(
        (
            f"https://www.reddit.com/r/{subreddit}/.rss",
            f"https://old.reddit.com/r/{subreddit}/.rss",
        ),
        subreddit,
        kind,
        notes,
        options,
        params={"limit": limit},
    )
    if posts:
        return {"items": posts[:limit], "notes": notes}

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
        f"O Reddit não devolveu publicações de r/{subreddit} em nenhum dos endereços públicos."
        + _reddit_failure_detail(notes),
        status="blocked",
        hint=(
            "O Reddit bloqueia IPs de servidor (JSON, feed Atom e HTML). Configure um proxy "
            "residencial nas opções do canal (`proxy`) ou credenciais OAuth "
            "(`client_id`/`client_secret`, app do tipo «script»)."
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


# ------------------------------------------------------------------ internet
#: Meta-informação (Open Graph/Twitter) usada para tirar texto, imagem e vídeo de uma página.
_META_AFTER_RE = re.compile(
    r"<meta[^>]+(?:property|name|itemprop)\s*=\s*[\"'](?P<key>[^\"']+)[\"'][^>]*?content\s*=\s*[\"'](?P<value>[^\"']*)[\"']",
    re.I,
)
_META_BEFORE_RE = re.compile(
    r"<meta[^>]+content\s*=\s*[\"'](?P<value>[^\"']*)[\"'][^>]*?(?:property|name|itemprop)\s*=\s*[\"'](?P<key>[^\"']+)[\"']",
    re.I,
)
_TITLE_RE = re.compile(r"<title[^>]*>(?P<title>.*?)</title>", re.I | re.S)
_IMG_RE = re.compile(r"<img[^>]+src\s*=\s*[\"'](?P<src>[^\"']+)[\"']", re.I)
_VIDEO_RE = re.compile(r"<(?:video|source)[^>]+src\s*=\s*[\"'](?P<src>[^\"']+\.(?:mp4|webm|m3u8)[^\"']*)[\"']", re.I)
_IFRAME_RE = re.compile(r"<iframe[^>]+src\s*=\s*[\"'](?P<src>https?://[^\"']+)[\"']", re.I)
_SCRIPT_VIDEO_RE = re.compile(r"https?://[^\"'\s]+(?:youtube\.com/embed/[^\"'\s]+|player\.vimeo\.com/video/\d+)", re.I)

#: Resultados do DuckDuckGo Lite (usado quando os pacotes de pesquisa falham).
_LITE_LINK_RE = re.compile(
    r"<a[^>]+class=[\"']result-link[\"'][^>]*href=[\"'](?P<url>[^\"']+)[\"'][^>]*>(?P<title>.*?)</a>",
    re.I | re.S,
)
_LITE_SNIPPET_RE = re.compile(
    r"<td[^>]*class=[\"']result-snippet[\"'][^>]*>(?P<snippet>.*?)</td>", re.I | re.S
)

#: Cache de pesquisas na web (`(query, limite)` -> (momento, resultado)).
_search_cache: Dict[Tuple[str, int], Tuple[float, Dict[str, Any]]] = {}
#: Cache das pesquisas de imagens/vídeos (`("images"|"videos", query, limite)`).
_media_cache: Dict[Tuple[str, str, int], Tuple[float, Dict[str, Any]]] = {}
_SEARCH_TTL_SECONDS = 900.0


def _strip_tags(value: str) -> str:
    """Texto limpo a partir de HTML (sem marcação)."""
    return _clean(re.sub(r"<[^>]+>", " ", value or ""), 4000)


def _absolutize(url: str, base: str) -> str:
    """Ligação absoluta (as páginas usam muitas vezes caminhos relativos)."""
    url = _clean(url, 1024)
    if not url or url.startswith("data:"):
        return ""
    if url.lower().startswith(("http://", "https://")):
        return url
    try:
        return urljoin(base, url)
    except Exception:
        return url


def _visible_text(html: str, limit: int = 1200) -> str:
    """Texto visível de uma página (sem scripts, estilos e marcação)."""
    text = re.sub(r"<(script|style|noscript|svg)[^>]*>.*?</\1>", " ", html or "", flags=re.I | re.S)
    text = re.sub(r"<!--.*?-->", " ", text, flags=re.S)
    return _strip_tags(text)[:limit]


def _page_metas(html: str) -> Dict[str, str]:
    """Meta-informação da página: `og:*`, `twitter:*` e afins (primeira ocorrência ganha)."""
    metas: Dict[str, str] = {}
    for regex in (_META_AFTER_RE, _META_BEFORE_RE):
        for match in regex.finditer(html or ""):
            key = str(match.group("key") or "").strip().lower()
            value = _clean(match.group("value") or "", 2000)
            if key and value and key not in metas:
                metas[key] = value
    return metas


def _first_match(regex: "re.Pattern[str]", html: str) -> str:
    match = regex.search(html or "")
    return _clean(match.group(1), 1024) if match else ""


#: Atributos onde as imagens aparecem (inclui as preguiçosas e o `srcset`).
_IMG_ATTR_RE = re.compile(
    r"(?:src|data-src|data-original|data-lazy-src|data-image|srcset)\s*=\s*[\"'](?P<value>[^\"']+)[\"']",
    re.I,
)
_IMG_TAG_RE = re.compile(r"<img[^>]+>", re.I)
_IMAGE_EXT_RE = re.compile(r"\.(jpe?g|png|webp|gif|avif)", re.I)
_YT_ID_RE = re.compile(r"(?:youtube\.com/(?:watch\?v=|embed/|shorts/)|youtu\.be/)([A-Za-z0-9_-]{6,})", re.I)
_YT_VIDEOID_RE = re.compile(r"[\"']videoId[\"']\s*:\s*[\"']([A-Za-z0-9_-]{6,})[\"']", re.I)
#: Ligações de **vídeo** (e não de canais/perfis) usadas na alternativa da pesquisa web.
_VIDEO_URL_RE = re.compile(
    r"(youtube\.com/watch\?v=|youtu\.be/|youtube\.com/shorts/|vimeo\.com/\d+|dailymotion\.com/video/"
    r"|tiktok\.com/@[^/]+/video/\d+|facebook\.com/[^/]+/videos/)",
    re.I,
)


def _page_images(html: str, metas: Dict[str, str], base: str, limit: int = 12) -> List[str]:
    """Imagens de uma página: primeiro as anunciadas (`og:image`), depois os `<img>`."""
    announced = [
        metas.get(key) or ""
        for key in ("og:image", "og:image:secure_url", "og:image:url", "twitter:image", "twitter:image:src")
    ]
    found: List[str] = []
    for raw in announced:
        absolute = _absolutize(raw, base)
        if absolute and absolute not in found:
            found.append(absolute)

    for tag in _IMG_TAG_RE.finditer(html or ""):
        for attr in _IMG_ATTR_RE.finditer(tag.group(0)):
            for candidate in str(attr.group("value")).split(","):
                raw = candidate.strip().split(" ")[0]
                if not raw:
                    continue
                absolute = _absolutize(raw, base)
                if not absolute or absolute in found:
                    continue
                # Sem extensão de imagem conhecida não se arrisca (pixels, tracking);
                # `.svg` são ícones de interface, não fotografias.
                if not _IMAGE_EXT_RE.search(absolute) or _IMAGE_SKIP_RE.search(absolute) or ".svg" in absolute.lower():
                    continue
                found.append(absolute)
                if len(found) >= limit:
                    return found
    return found[:limit]


def _page_videos(html: str, metas: Dict[str, str], base: str, limit: int = 8) -> List[str]:
    """Vídeos de uma página: `og:video`, `<video>/<source>` e incorporações conhecidas."""
    found: List[str] = []

    def add(value: str) -> bool:
        absolute = _absolutize(value, base)
        if absolute and absolute not in found and absolute.lower().startswith("http"):
            found.append(absolute)
        return len(found) >= limit

    for raw in (
        metas.get("og:video"),
        metas.get("og:video:url"),
        metas.get("og:video:secure_url"),
        metas.get("twitter:player:stream"),
        metas.get("twitter:player"),
    ):
        if raw and add(raw):
            return found

    for match in _VIDEO_RE.finditer(html or ""):
        if add(match.group("src")):
            return found
    for match in _IFRAME_RE.finditer(html or ""):
        candidate = match.group("src")
        if _VIDEO_HOSTS_RE.search(candidate) and add(candidate):
            return found
    for match in _YT_VIDEOID_RE.finditer(html or ""):
        if add(f"https://www.youtube.com/watch?v={match.group(1)}"):
            return found
    return found[:limit]


def search_web(query: str, *, limit: int = 10) -> Dict[str, Any]:
    """Pesquisa na internet (Brave/SerpAPI se houver chave; senão DuckDuckGo).

    Devolve `{query, items: [{title, url, snippet, engine}], engine, error}`.
    Os motores são tentados por ordem e a falha de um não impede os seguintes:
    `ddgs` (pacote atual), `duckduckgo_search` (antigo) e, por fim, o HTML do
    DuckDuckGo Lite (sem dependências). Os resultados ficam em cache durante
    `_SEARCH_TTL_SECONDS` — repetir a mesma pesquisa (a UI fá-lo) não volta a
    bater no motor, evitando o bloqueio por ritmo.
    """
    query = _clean(query, 300)
    if not query:
        return {"query": query, "items": [], "engine": "", "error": "Pesquisa vazia."}

    cached = _search_cache.get((query, int(limit or 10)))
    if cached and (time.time() - cached[0]) < _SEARCH_TTL_SECONDS:
        return {**cached[1], "cached": True}

    def _normalize(rows: Any, engine: str) -> List[Dict[str, Any]]:
        items: List[Dict[str, Any]] = []
        for row in rows or []:
            if not isinstance(row, dict) or row.get("error"):
                continue
            url = str(row.get("href") or row.get("url") or row.get("link") or "").strip()
            if not url:
                continue
            items.append(
                {
                    "title": _strip_tags(str(row.get("title") or ""))[:400],
                    "url": url[:1024],
                    "snippet": _strip_tags(str(row.get("body") or row.get("snippet") or row.get("description") or ""))[:1200],
                    "engine": engine,
                }
            )
        return items

    def _remember(outcome: Dict[str, Any]) -> Dict[str, Any]:
        if outcome.get("items"):
            _search_cache[(query, int(limit or 10))] = (time.time(), outcome)
            if len(_search_cache) > 400:
                oldest = sorted(_search_cache.items(), key=lambda kv: kv[1][0])[:100]
                for key, _ in oldest:
                    _search_cache.pop(key, None)
        return outcome

    # 1. Chaves de API (Brave/SerpAPI) têm prioridade.
    if os.getenv("BRAVE_API_KEY") or os.getenv("SERPAPI_KEY"):
        try:
            from api import tools as tools_module  # noqa: PLC0415

            items = _normalize(tools_module.web_search(query, limit, "auto"), "api")
            if items:
                return _remember({"query": query, "items": items, "engine": items[0].get("engine") or "api"})
        except Exception as exc:  # pragma: no cover - depende do ambiente
            logger.info("Pesquisa web por API falhou: %s", exc)

    # 2. Pacotes do DuckDuckGo (`ddgs` é o nome atual; o `duckduckgo_search`
    #    antigo só é usado se aquele não estiver instalado).
    module_name = next(
        (name for name in ("ddgs", "duckduckgo_search") if importlib.util.find_spec(name) is not None),
        "",
    )
    if module_name:
        try:
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                module = importlib.import_module(module_name)
                with module.DDGS() as ddgs:
                    rows = list(ddgs.text(query, max_results=limit))
            items = _normalize(rows, "duckduckgo")
            if items:
                return _remember({"query": query, "items": items, "engine": "duckduckgo"})
        except Exception as exc:
            logger.info("Pesquisa web com %s falhou: %s", module_name, exc)

    # 3. HTML do DuckDuckGo Lite (sem dependências). Em época de muito uso o
    #    motor responde 202 (pedido aceite mas sem resultados): vale a pena
    #    esperar e tentar de novo uma vez.
    for attempt in (1, 2):
        try:
            html = _fetch_text(f"https://lite.duckduckgo.com/lite/?q={quote_plus(query)}", {"timeout": DEFAULT_TIMEOUT})
            links = list(_LITE_LINK_RE.finditer(html or ""))
            snippets = [_strip_tags(m.group("snippet")) for m in _LITE_SNIPPET_RE.finditer(html or "")]
            items = [
                {
                    "title": _strip_tags(m.group("title"))[:400],
                    "url": _clean(m.group("url"), 1024),
                    "snippet": (snippets[index] if index < len(snippets) else "")[:1200],
                    "engine": "duckduckgo-lite",
                }
                for index, m in enumerate(links[:limit])
            ]
            if items:
                return _remember({"query": query, "items": items, "engine": "duckduckgo-lite"})
        except Exception as exc:
            logger.info("DuckDuckGo Lite falhou: %s", exc)
        if attempt == 1:
            time.sleep(2.5)

    return {
        "query": query,
        "items": [],
        "engine": "",
        "error": "Sem motor de pesquisa disponível (instale `ddgs` ou configure BRAVE_API_KEY/SERPAPI_KEY).",
    }


def collect_web_page(
    url: str,
    *,
    options: Optional[Dict[str, Any]] = None,
    target: str = "",
    tags: Optional[List[str]] = None,
    kind: str = "page",
) -> Dict[str, Any]:
    """Lê uma página da internet e devolve uma publicação normalizada.

    Extrai o que a página expõe de forma pública: título, descrição, **imagens**
    (`og:image` e todos os `<img>`/`srcset`) e **vídeos** (`og:video`,
    `<video>`/`<source>` e incorporações do YouTube/Vimeo/TikTok), além da data de
    publicação. Páginas que bloqueiem a leitura (LinkedIn, por exemplo) levantam
    `CollectorError` com `status`.
    """
    url = str(url or "").strip()
    if not url.lower().startswith(("http://", "https://")):
        raise CollectorError(f"Ligação inválida: {url!r}.", status="definition")
    html = _fetch_text(url, options)
    if not html:
        raise CollectorError(f"A página {url} não devolveu conteúdo.", status="empty")

    metas = _page_metas(html)
    title = metas.get("og:title") or metas.get("twitter:title") or _strip_tags(_first_match(_TITLE_RE, html))
    description = (
        metas.get("og:description")
        or metas.get("twitter:description")
        or metas.get("description")
        or ""
    )
    images = _page_images(html, metas, url)
    videos = _page_videos(html, metas, url)
    published = (
        metas.get("article:published_time")
        or metas.get("og:updated_time")
        or metas.get("date")
        or metas.get("pubdate")
        or None
    )
    site = metas.get("og:site_name") or urlparse(url).netloc
    post_id = _post_id_from_url(url) or hashlib.sha1(url.encode("utf-8")).hexdigest()[:16]
    # Sem descrição na meta-informação, vale o texto visível da página.
    if not description:
        description = _visible_text(html)

    return _post(
        platform="internet",
        kind=kind,
        target=target or site or url,
        post_id=post_id,
        url=url,
        title=title,
        text=description,
        author=site,
        community=site,
        published_at=_iso_from_epoch(published) if str(published or "").isdigit() else published,
        image=images[0] if images else "",
        video=videos[0] if videos else "",
        images=images,
        videos=videos,
        tags=[*(tags or []), "internet", site],
        data={
            "site": site,
            "og_type": metas.get("og:type") or "",
            "has_image": bool(images),
            "has_video": bool(videos),
            "images_found": len(images),
            "videos_found": len(videos),
        },
    )


# ------------------------------------------------- imagens e vídeos (pesquisa)
#: Campos de imagem/vídeo que interessam (e que não são ícones nem pixels).
_IMAGE_SKIP_RE = re.compile(
    r"(sprite|logo|icon|favicon|avatar|pixel|blank|spacer|placeholder|loading|1x1|badge|button|/ads?/"
    r"|preview|notificat|wrapper|share|banner|social|thumb-|_thumb|watermark|flag|arrow|bullet)",
    re.I,
)
_VIDEO_HOSTS_RE = re.compile(r"(youtube\.com|youtu\.be|vimeo\.com|dailymotion\.com|tiktok\.com|facebook\.com/.*video)", re.I)


def _ddgs_module() -> str:
    """Nome do pacote de pesquisa instalado (`ddgs` é o atual)."""
    return next(
        (name for name in ("ddgs", "duckduckgo_search") if importlib.util.find_spec(name) is not None),
        "",
    )


def _media_cache_get(key: Tuple[str, str, int]) -> Optional[Dict[str, Any]]:
    cached = _media_cache.get(key)
    if cached and (time.time() - cached[0]) < _SEARCH_TTL_SECONDS:
        return {**cached[1], "cached": True}
    return None


def _media_cache_put(key: Tuple[str, str, int], outcome: Dict[str, Any]) -> Dict[str, Any]:
    if outcome.get("items"):
        _media_cache[key] = (time.time(), outcome)
        if len(_media_cache) > 300:
            for old_key, _ in sorted(_media_cache.items(), key=lambda kv: kv[1][0])[:80]:
                _media_cache.pop(old_key, None)
    return outcome


def _run_ddgs(method: str, query: str, limit: int) -> List[Dict[str, Any]]:
    """Corre um método do pacote de pesquisa (`images`, `videos`) e devolve as linhas cruas."""
    module_name = _ddgs_module()
    if not module_name:
        return []
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        module = importlib.import_module(module_name)
        with module.DDGS() as ddgs:
            fn = getattr(ddgs, method, None)
            if fn is None:
                return []
            return list(fn(query, max_results=limit))


def search_images(query: str, *, limit: int = 12) -> Dict[str, Any]:
    """Pesquisa **imagens** na internet (DuckDuckGo/Bing por trás do `ddgs`).

    Devolve `{query, items: [{title, image, thumbnail, page_url, host, engine}], error}`.
    Sem o pacote `ddgs` (ou bloqueado por ritmo) devolve a lista vazia com o motivo.
    """
    query = _clean(query, 300)
    if not query:
        return {"query": query, "items": [], "engine": "", "error": "Pesquisa vazia."}
    key = ("images", query, int(limit or 12))
    cached = _media_cache_get(key)
    if cached:
        return cached
    try:
        rows = _run_ddgs("images", query, max(1, min(int(limit or 12), 50)))
    except Exception as exc:
        return {"query": query, "items": [], "engine": "", "error": f"Pesquisa de imagens falhou: {exc}"}

    items: List[Dict[str, Any]] = []
    seen: set = set()
    for row in rows or []:
        if not isinstance(row, dict):
            continue
        image = str(row.get("image") or "").strip()
        if not image or image in seen or not image.lower().startswith("http"):
            continue
        seen.add(image)
        page_url = str(row.get("url") or row.get("source") or "").strip()
        items.append({
            "title": _strip_tags(str(row.get("title") or ""))[:300],
            "image": image[:1024],
            "thumbnail": str(row.get("thumbnail") or "")[:1024],
            "page_url": page_url[:1024],
            "host": urlparse(page_url or image).netloc.lower().removeprefix("www."),
            "width": row.get("width"),
            "height": row.get("height"),
            "engine": "duckduckgo-images",
        })
    outcome = {"query": query, "items": items, "engine": "duckduckgo-images", "error": None if items else "Sem imagens."}
    return _media_cache_put(key, outcome)


def search_videos(query: str, *, limit: int = 8) -> Dict[str, Any]:
    """Pesquisa **vídeos** na internet. Devolve `{query, items: [...], error}`.

    Cada item traz a ligação do vídeo, a miniatura, o autor e a duração — dá para
    mostrar a miniatura na ficha e abrir o vídeo no browser. Quando o motor de
    vídeos não devolve nada (acontece com frequência), cai numa pesquisa web por
    `site:youtube.com`, `site:vimeo.com` e `site:tiktok.com`, e a miniatura do
    YouTube é derivada do identificador do vídeo (sem chave de API).
    """
    query = _clean(query, 300)
    if not query:
        return {"query": query, "items": [], "engine": "", "error": "Pesquisa vazia."}
    key = ("videos", query, int(limit or 8))
    cached = _media_cache_get(key)
    if cached:
        return cached

    items: List[Dict[str, Any]] = []
    seen: set = set()
    engine = "duckduckgo-videos"
    try:
        rows = _run_ddgs("videos", query, max(1, min(int(limit or 8), 30)))
    except Exception as exc:
        rows = []
        logger.info("Pesquisa de vídeos falhou (%s); a cair na pesquisa web.", exc)

    for row in rows or []:
        if not isinstance(row, dict):
            continue
        url = str(row.get("content") or row.get("url") or "").strip()
        if not url or url in seen or not url.lower().startswith("http"):
            continue
        seen.add(url)
        thumbs = row.get("images") if isinstance(row.get("images"), dict) else {}
        thumb = str(thumbs.get("large") or thumbs.get("medium") or thumbs.get("small") or row.get("thumbnail") or "")
        items.append({
            "title": _strip_tags(str(row.get("title") or ""))[:300],
            "url": url[:1024],
            "thumbnail": thumb[:1024],
            "description": _strip_tags(str(row.get("description") or ""))[:400],
            "publisher": _strip_tags(str(row.get("publisher") or row.get("uploader") or ""))[:200],
            "duration": str(row.get("duration") or "")[:32],
            "published_at": row.get("published") or row.get("published_at"),
            "host": urlparse(url).netloc.lower().removeprefix("www."),
            "engine": engine,
        })

    if not items:
        # Alternativa: procurar as ligações de vídeo na pesquisa web (que tem
        # DuckDuckGo Lite como rede de segurança).
        engine = "web-videos"
        for site in ("youtube.com", "vimeo.com", "tiktok.com"):
            outcome = search_web(f"{query} site:{site}", limit=max(3, min(int(limit or 6), 10)))
            for row in outcome.get("items") or []:
                url = str(row.get("url") or "").strip()
                if not url or url in seen or not _VIDEO_URL_RE.search(url):
                    # Só vídeos: a pesquisa devolve também canais e perfis.
                    continue
                seen.add(url)
                host = urlparse(url).netloc.lower().removeprefix("www.")
                yt_id = _YT_ID_RE.search(url)
                thumbnail = f"https://img.youtube.com/vi/{yt_id.group(1)}/hqdefault.jpg" if yt_id else ""
                items.append({
                    "title": _strip_tags(str(row.get("title") or ""))[:300],
                    "url": url[:1024],
                    "thumbnail": thumbnail,
                    "description": _strip_tags(str(row.get("snippet") or ""))[:400],
                    "publisher": host,
                    "duration": "",
                    "published_at": None,
                    "host": host,
                    "engine": engine,
                })
            if len(items) >= (limit or 8):
                break

    outcome = {
        "query": query,
        "items": items[: max(1, int(limit or 8))],
        "engine": engine,
        "error": None if items else "Sem vídeos encontrados.",
    }
    return _media_cache_put(key, outcome)



# -------------------------------------------------------------------- despacho
_COLLECTORS = {
    "linkedin": collect_linkedin,
    "reddit": collect_reddit,
    "tiktok": collect_tiktok,
    "facebook": collect_facebook,
    "internet": lambda channel, limit=DEFAULT_LIMIT: {
        "items": [collect_web_page(str(channel.get("target") or ""), options=channel.get("options") or {}, tags=channel.get("tags") or [])],
        "notes": [],
    },
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
