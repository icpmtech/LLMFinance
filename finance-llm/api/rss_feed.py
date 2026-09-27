"""Leitura de feeds RSS/Atom e OPML (sem estado).

Este módulo é a «antena» do leitor: vai à rede buscar o XML do feed (com
`ETag`/`Last-Modified` para não voltar a descarregar o que não mudou), converte-o
em artigos normalizados com o `feedparser`, descobre o feed de uma página HTML
quando o utilizador cola o endereço do site, e importa/exporta listas OPML.

Não guarda nada: quem persiste é o `api/rss_store.py`.
"""
from __future__ import annotations

import html as html_module
import logging
import re
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Sequence
from urllib.parse import urljoin, urlparse
from xml.etree import ElementTree

import feedparser
import requests

logger = logging.getLogger(__name__)

USER_AGENT = "Mozilla/5.0 (compatible; IQOS-RSS/1.0; +https://iqos.local/leitor)"
ACCEPT = (
    "application/rss+xml, application/atom+xml, application/xml;q=0.9, "
    "text/xml;q=0.8, text/html;q=0.7, */*;q=0.5"
)
MAX_ENTRIES = 200
MAX_CANDIDATES = 8

# Caminhos onde vive o feed em grande parte dos sites.
COMMON_PATHS = ("/feed", "/feed/", "/rss", "/rss.xml", "/feed.xml", "/atom.xml", "/index.xml", "/rss/", "/feed/atom")

CONNECT_TIMEOUT = 10
READ_TIMEOUT = 25
TIMEOUT = (CONNECT_TIMEOUT, READ_TIMEOUT)


# --------------------------------------------------------------------------
# Catálogo de sugestões (economia, mercados, reguladores e Portugal)
# --------------------------------------------------------------------------
SUGGESTIONS: List[Dict[str, Any]] = [
    {"id": "eco", "title": "ECO — Economia Online", "url": "https://eco.sapo.pt/feed/", "site_url": "https://eco.sapo.pt", "category": "Portugal", "language": "pt", "hint": "Economia e empresas em Portugal", "tags": ["economia", "portugal"]},
    {"id": "negocios", "title": "Jornal de Negócios", "url": "https://www.jornaldenegocios.pt/rss", "site_url": "https://www.jornaldenegocios.pt", "category": "Portugal", "language": "pt", "hint": "Diário de economia e finanças", "tags": ["economia", "portugal"]},
    {"id": "jornaleconomico", "title": "Jornal Económico", "url": "https://jornaleconomico.pt/feed/", "site_url": "https://jornaleconomico.pt", "category": "Portugal", "language": "pt", "hint": "Atualidade económica", "tags": ["economia", "portugal"]},
    {"id": "observador", "title": "Observador", "url": "https://observador.pt/feed/", "site_url": "https://observador.pt", "category": "Portugal", "language": "pt", "hint": "Últimas notícias", "tags": ["noticias", "portugal"]},
    {"id": "publico", "title": "Público — Últimas", "url": "https://feeds.feedburner.com/publico-ultimas", "site_url": "https://www.publico.pt", "category": "Portugal", "language": "pt", "hint": "Jornal diário", "tags": ["noticias", "portugal"]},
    {"id": "dn", "title": "Diário de Notícias", "url": "https://www.dn.pt/rss", "site_url": "https://www.dn.pt", "category": "Portugal", "language": "pt", "hint": "Jornal diário", "tags": ["noticias", "portugal"]},
    {"id": "bportugal", "title": "Banco de Portugal", "url": "https://www.bportugal.pt/rss", "site_url": "https://www.bportugal.pt", "category": "Reguladores", "language": "pt", "hint": "Comunicados e estatísticas do banco central", "tags": ["regulador", "portugal"]},
    {"id": "cmvm", "title": "CMVM — Comunicados", "url": "https://www.cmvm.pt/pt/RSS/Paginas/rss.aspx", "site_url": "https://www.cmvm.pt", "category": "Reguladores", "language": "pt", "hint": "Regulador do mercado de valores mobiliários", "tags": ["regulador", "mercados"]},
    {"id": "ecb", "title": "Banco Central Europeu — Imprensa", "url": "https://www.ecb.europa.eu/rss/press.html", "site_url": "https://www.ecb.europa.eu", "category": "Reguladores", "language": "en", "hint": "Comunicados do BCE", "tags": ["regulador", "europa"]},
    {"id": "yahoo-finance", "title": "Yahoo Finance", "url": "https://finance.yahoo.com/news/rssindex", "site_url": "https://finance.yahoo.com", "category": "Mercados", "language": "en", "hint": "Notícias de mercados", "tags": ["mercados"]},
    {"id": "cnbc-markets", "title": "CNBC — Markets", "url": "https://search.cnbc.com/rs/search/combinedcms/view.xml?partnerId=wrss01&id=20910258", "site_url": "https://www.cnbc.com", "category": "Mercados", "language": "en", "hint": "Mercados norte-americanos", "tags": ["mercados"]},
    {"id": "investing", "title": "Investing.com — Notícias", "url": "https://www.investing.com/rss/news.rss", "site_url": "https://www.investing.com", "category": "Mercados", "language": "en", "hint": "Notícias e análise de mercados", "tags": ["mercados"]},
    {"id": "ft-home", "title": "Financial Times", "url": "https://www.ft.com/rss/home", "site_url": "https://www.ft.com", "category": "Finanças", "language": "en", "hint": "Imprensa financeira internacional", "tags": ["financas"]},
    {"id": "economist-finance", "title": "The Economist — Finance & economics", "url": "https://www.economist.com/finance-and-economics/rss.xml", "site_url": "https://www.economist.com", "category": "Economia", "language": "en", "hint": "Análise económica", "tags": ["economia"]},
    {"id": "bloomberg-markets", "title": "Bloomberg — Markets", "url": "https://feeds.bloomberg.com/markets/news.rss", "site_url": "https://www.bloomberg.com", "category": "Mercados", "language": "en", "hint": "Mercados internacionais", "tags": ["mercados"]},
    {"id": "reuters-business", "title": "Reuters — Business", "url": "https://www.reutersagency.com/feed/?best-topics=business-finance", "site_url": "https://www.reuters.com", "category": "Finanças", "language": "en", "hint": "Agência noticiosa internacional", "tags": ["financas"]},
    {"id": "imf-blog", "title": "IMF Blog", "url": "https://www.imf.org/en/Blogs/rss", "site_url": "https://www.imf.org", "category": "Internacional", "language": "en", "hint": "Fundo Monetário Internacional", "tags": ["internacional", "economia"]},
    {"id": "oecd-news", "title": "OCDE — Notícias", "url": "https://www.oecd.org/newsroom/rss.xml", "site_url": "https://www.oecd.org", "category": "Internacional", "language": "en", "hint": "Organização para a Cooperação e Desenvolvimento", "tags": ["internacional", "economia"]},
    {"id": "eurostat", "title": "Eurostat — Comunicados", "url": "https://ec.europa.eu/eurostat/api/dissemination/statistics/1.0/rss", "site_url": "https://ec.europa.eu/eurostat", "category": "Internacional", "language": "en", "hint": "Estatísticas europeias", "tags": ["internacional", "estatisticas"]},
    {"id": "arxiv-qfin", "title": "arXiv — Finanças quantitativas", "url": "https://export.arxiv.org/rss/q-fin", "site_url": "https://arxiv.org/list/q-fin/recent", "category": "Investigação", "language": "en", "hint": "Artigos científicos de finanças quantitativas", "tags": ["investigacao", "quant"]},
    {"id": "hackernews", "title": "Hacker News", "url": "https://news.ycombinator.com/rss", "site_url": "https://news.ycombinator.com", "category": "Tecnologia", "language": "en", "hint": "Tecnologia e startups", "tags": ["tecnologia"]},
    {"id": "coindesk", "title": "CoinDesk", "url": "https://www.coindesk.com/arc/outboundfeeds/rss/", "site_url": "https://www.coindesk.com", "category": "Tecnologia", "language": "en", "hint": "Ativos digitais", "tags": ["cripto", "tecnologia"]},
]

SUGGESTION_CATEGORIES: Tuple[str, ...] = (
    "Portugal",
    "Reguladores",
    "Mercados",
    "Finanças",
    "Economia",
    "Internacional",
    "Investigação",
    "Tecnologia",
)


def suggestions() -> List[Dict[str, Any]]:
    return [dict(item) for item in SUGGESTIONS]


def suggestions_meta() -> Dict[str, Any]:
    return {"categories": list(SUGGESTION_CATEGORIES), "total": len(SUGGESTIONS)}


# --------------------------------------------------------------------------
# HTTP
# --------------------------------------------------------------------------
def http_get(url: str, *, etag: Optional[str] = None, last_modified: Optional[str] = None) -> Dict[str, Any]:
    """Vai buscar o recurso. `status` é `ok`, `not_modified` (304) ou `error`."""
    headers = {"User-Agent": USER_AGENT, "Accept": ACCEPT, "Accept-Language": "pt-PT,pt;q=0.9,en;q=0.8"}
    if etag:
        headers["If-None-Match"] = etag
    if last_modified:
        headers["If-Modified-Since"] = last_modified
    try:
        response = requests.get(url, headers=headers, timeout=TIMEOUT, allow_redirects=True)
    except requests.RequestException as exc:
        return {"status": "error", "error": f"{type(exc).__name__}: {exc}", "url": url}
    if response.status_code == 304:
        return {"status": "not_modified", "url": response.url or url, "etag": etag, "last_modified": last_modified}
    if response.status_code >= 400:
        return {"status": "error", "error": f"HTTP {response.status_code}", "url": response.url or url}
    return {
        "status": "ok",
        "url": response.url or url,
        "content": response.content,
        "etag": response.headers.get("ETag") or "",
        "last_modified": response.headers.get("Last-Modified") or "",
        "content_type": (response.headers.get("Content-Type") or "").lower(),
    }


# --------------------------------------------------------------------------
# Análise do XML
# --------------------------------------------------------------------------
def _clean(value: Any, limit: int = 4000) -> str:
    text = html_module.unescape(str(value or ""))
    text = re.sub(r"(?is)<(script|style)[^>]*>.*?</\1>", " ", text)
    text = re.sub(r"(?s)<[^>]+>", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text[:limit]


def _first_image(*candidates: Any) -> str:
    for value in candidates:
        text = str(value or "")
        if not text:
            continue
        found = re.search(r'(?i)<img[^>]+src=["\']([^"\']+)["\']', text)
        if found:
            return found.group(1)
        if re.match(r"^https?://\S+\.(png|jpe?g|gif|webp|avif|svg)(\?\S*)?$", text.strip(), re.I):
            return text.strip()
    return ""


def _entry_image(entry: Any, html: str) -> str:
    for key in ("media_content", "media_thumbnail"):
        for item in entry.get(key) or []:
            url = str((item or {}).get("url") or "").strip()
            if url:
                return url
    for enclosure in entry.get("enclosures") or []:
        url = str((enclosure or {}).get("href") or (enclosure or {}).get("url") or "").strip()
        mime = str((enclosure or {}).get("type") or "")
        if url and (mime.startswith("image/") or re.search(r"\.(png|jpe?g|gif|webp|avif|svg)$", url, re.I)):
            return url
    return _first_image(html)


def _entry_date(entry: Any) -> Optional[str]:
    for key in ("published_parsed", "updated_parsed", "created_parsed"):
        value = entry.get(key)
        if value:
            try:
                return datetime(*value[:6], tzinfo=timezone.utc).isoformat()
            except (TypeError, ValueError):
                continue
    for key in ("published", "updated", "created"):
        raw = str(entry.get(key) or "").strip()
        if not raw:
            continue
        try:
            parsed = datetime.strptime(raw[:25], "%a, %d %b %Y %H:%M:%S")
            return parsed.replace(tzinfo=timezone.utc).isoformat()
        except ValueError:
            continue
    return None


def _reading_minutes(text: str) -> int:
    words = len([word for word in re.split(r"\s+", _clean(text, 100_000)) if word])
    return max(1, round(words / 200))


def parse_feed(content: Any) -> Dict[str, Any]:
    """Converte o XML/HTML do feed num dicionário normalizado."""
    raw = content.encode("utf-8", "ignore") if isinstance(content, str) else bytes(content or b"")
    parsed = feedparser.parse(raw)
    meta = parsed.get("feed") or {}
    feed_title = _clean(meta.get("title"), 300)
    site_url = str(meta.get("link") or "").strip()
    language = str(meta.get("language") or "").strip().lower()[:12]
    image = meta.get("image")
    icon = str(image.get("href") or "").strip() if isinstance(image, dict) else ""
    description = _clean(meta.get("subtitle") or meta.get("description"), 600)
    entries: List[Dict[str, Any]] = []
    for entry in (parsed.get("entries") or [])[:MAX_ENTRIES]:
        summary_html = ""
        content_value = ""
        contents = entry.get("content") or []
        if contents:
            content_value = str((contents[0] or {}).get("value") or "")
        summary_html = str(entry.get("summary") or entry.get("description") or "")
        if not content_value:
            content_value = summary_html
        summary = _clean(summary_html or content_value, 1200)
        url = str(entry.get("link") or "").strip()
        guid = str(entry.get("id") or entry.get("guid") or url).strip()
        entries.append(
            {
                "guid": guid,
                "title": _clean(entry.get("title"), 500),
                "url": url,
                "author": _clean(entry.get("author") or entry.get("dc_creator"), 200),
                "summary": summary,
                "content": content_value,
                "published_at": _entry_date(entry),
                "image_url": _entry_image(entry, content_value or summary_html),
                "categories": [
                    _clean((tag or {}).get("term"), 80)
                    for tag in (entry.get("tags") or [])
                    if _clean((tag or {}).get("term"), 80)
                ],
                "reading_minutes": _reading_minutes(content_value or summary),
            }
        )
    return {
        "title": feed_title,
        "site_url": site_url,
        "description": description,
        "language": language,
        "icon_url": icon,
        "entries": entries,
        "bozo": bool(parsed.get("bozo")),
        "bozo_exception": str(parsed.get("bozo_exception") or "")[:200],
    }


def _looks_like_feed(content: bytes, content_type: str) -> bool:
    if any(token in content_type for token in ("rss", "atom", "xml")):
        return True
    head = content[:400].lstrip().lower()
    return head.startswith(b"<?xml") or head.startswith(b"<rss") or head.startswith(b"<feed") or b"<rdf:rdf" in head


# --------------------------------------------------------------------------
# Descoberta do feed a partir de um endereço
# --------------------------------------------------------------------------
def _link_candidates(page: str, base_url: str) -> List[str]:
    found: List[str] = []
    pattern = re.compile(r"<link[^>]+>", re.I)
    for tag in pattern.findall(page):
        if not re.search(r'rel=["\']?alternate', tag, re.I):
            continue
        if not re.search(r'type=["\']?(application/(rss|atom)\+xml|application/xml|text/xml)', tag, re.I):
            continue
        href = re.search(r'href=["\']([^"\']+)["\']', tag, re.I)
        if href:
            candidate = urljoin(base_url, href.group(1).strip())
            if candidate not in found:
                found.append(candidate)
    return found


def discover(url: str) -> Dict[str, Any]:
    """Dado o endereço de um feed **ou** de uma página, devolve os feeds possíveis.

    Devolve `{"feed_url", "candidates", "error"}` — o primeiro candidato que
    analisa corretamente é o `feed_url`.
    """
    target = (url or "").strip()
    if not re.match(r"^https?://", target, re.I):
        return {"feed_url": None, "candidates": [], "error": "O endereço tem de começar por http:// ou https://."}
    first = http_get(target)
    if first.get("status") == "error":
        return {"feed_url": None, "candidates": [], "error": str(first.get("error") or "Falha de rede.")}
    content = first.get("content") or b""
    content_type = str(first.get("content_type") or "")
    base = str(first.get("url") or target)
    candidates: List[str] = []
    if _looks_like_feed(content, content_type):
        candidates.append(base)
    else:
        page = content.decode("utf-8", "ignore")
        candidates.extend(_link_candidates(page, base))
        for path in COMMON_PATHS:
            candidate = urljoin(base, path)
            if candidate not in candidates:
                candidates.append(candidate)
    for candidate in candidates[:MAX_CANDIDATES]:
        try:
            check = http_get(candidate)
        except Exception as exc:  # pragma: no cover - rede
            logger.debug("Candidato %s falhou: %s", candidate, exc)
            continue
        if check.get("status") != "ok":
            continue
        if not _looks_like_feed(check.get("content") or b"", str(check.get("content_type") or "")):
            continue
        return {"feed_url": str(check.get("url") or candidate), "candidates": candidates, "error": None}
    return {
        "feed_url": None,
        "candidates": candidates[:MAX_CANDIDATES],
        "error": "Não foi encontrado nenhum feed RSS/Atom nesse endereço.",
    }


def fetch_and_parse(url: str, *, etag: Optional[str] = None, last_modified: Optional[str] = None) -> Dict[str, Any]:
    """Recolha completa de um feed: HTTP + análise. Devolve `{status, feed, error, etag, last_modified, url}`."""
    response = http_get(url, etag=etag, last_modified=last_modified)
    if response.get("status") == "not_modified":
        return {"status": "not_modified", "feed": None, "error": None, "etag": etag or "", "last_modified": last_modified or "", "url": response.get("url") or url}
    if response.get("status") == "error":
        return {"status": "error", "feed": None, "error": str(response.get("error") or "Falha de rede."), "url": url}
    feed = parse_feed(response.get("content") or b"")
    if not feed["entries"] and feed.get("bozo") and not feed.get("title"):
        return {"status": "error", "feed": None, "error": f"O conteúdo não parece um feed válido ({feed.get('bozo_exception') or 'XML inválido'}).", "url": url}
    return {
        "status": "ok",
        "feed": feed,
        "error": None,
        "etag": str(response.get("etag") or ""),
        "last_modified": str(response.get("last_modified") or ""),
        "url": str(response.get("url") or url),
    }


# --------------------------------------------------------------------------
# OPML
# --------------------------------------------------------------------------
def parse_opml(text: str) -> Dict[str, Any]:
    """Lê uma lista OPML. Devolve `{"folders": [...], "feeds": [...], "error"}`."""
    try:
        root = ElementTree.fromstring(text)
    except ElementTree.ParseError as exc:
        return {"folders": [], "feeds": [], "error": f"OPML inválido: {exc}"}
    folders: List[str] = []
    feeds: List[Dict[str, Any]] = []

    def walk(node: Any, folder: Optional[str]) -> None:
        for outline in list(node):
            if str(outline.tag).lower() != "outline":
                # Contentores que não são `outline` (`<body>`, por exemplo).
                walk(outline, folder)
                continue
            xml_url = str(outline.get("xmlUrl") or outline.get("xmlurl") or "").strip()
            title = str(outline.get("title") or outline.get("text") or "").strip()
            if xml_url:
                feeds.append({"title": title or xml_url, "url": xml_url, "folder": folder, "site_url": str(outline.get("htmlUrl") or "").strip()})
                continue
            name = title or "Sem nome"
            if name not in folders:
                folders.append(name)
            walk(outline, name)

    walk(root, None)
    return {"folders": folders, "feeds": feeds, "error": None}


def build_opml(feeds: Sequence[Dict[str, Any]], folders: Sequence[Dict[str, Any]] = ()) -> str:
    """Exporta as fontes em OPML (agrupadas pelas pastas)."""
    def escape(value: Any) -> str:
        return (
            str(value or "")
            .replace("&", "&amp;")
            .replace("<", "&lt;")
            .replace(">", "&gt;")
            .replace('"', "&quot;")
        )

    by_folder: Dict[str, List[Dict[str, Any]]] = {}
    for feed in feeds:
        by_folder.setdefault(str(feed.get("folder_id") or ""), []).append(feed)
    lines = ['<?xml version="1.0" encoding="UTF-8"?>', '<opml version="2.0">', "  <head>", "    <title>IQ OS — Leitor RSS</title>", f"    <dateCreated>{datetime.now(timezone.utc).isoformat()}</dateCreated>", "  </head>", "  <body>"]
    for folder in folders:
        folder_id = str(folder.get("id") or "")
        inside = by_folder.get(folder_id) or []
        if not inside:
            continue
        lines.append(f'    <outline text="{escape(folder.get("name"))}" title="{escape(folder.get("name"))}">')
        for feed in inside:
            lines.append(
                f'      <outline type="rss" text="{escape(feed.get("title"))}" title="{escape(feed.get("title"))}" '
                f'xmlUrl="{escape(feed.get("url"))}" htmlUrl="{escape(feed.get("site_url"))}"/>'
            )
        lines.append("    </outline>")
    for feed in by_folder.get("") or []:
        lines.append(
            f'    <outline type="rss" text="{escape(feed.get("title"))}" title="{escape(feed.get("title"))}" '
            f'xmlUrl="{escape(feed.get("url"))}" htmlUrl="{escape(feed.get("site_url"))}"/>'
        )
    lines.extend(["  </body>", "</opml>", ""])
    return "\n".join(lines)


def host_of(url: str) -> str:
    try:
        return urlparse(url).netloc.lower()
    except ValueError:
        return ""


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def sleep(seconds: float) -> None:  # pragma: no cover - cortesia entre pedidos
    time.sleep(seconds)
