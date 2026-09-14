"""Coletor RSS/Atom financeiro.

Obtém feeds de múltiplas fontes, normaliza itens para o formato usado pelo
pipeline de NLP/Elasticsearch e permite indexação via api.elasticsearch_ingest.

Dependências:
    pip install feedparser requests

Exemplo de uso:
    from collectors.rss import collect_finance_rss, DEFAULT_FEEDS
    items = collect_finance_rss(ticker="AAPL", max_items=30)
"""
import hashlib
import logging
import re
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List, Optional
from urllib.parse import urlparse

import feedparser
import requests

logger = logging.getLogger(__name__)

# Feeds genéricos de finanças/negócios. Podem ser sobrepostos via RSS_FEEDS_URLS env.
# A lista contém feeds que atualmente respondem com XML RSS/Atom válido.
DEFAULT_FEEDS: List[str] = [
    # Yahoo Finance latest news
    "https://finance.yahoo.com/news/rssindex",
    # MarketWatch top stories
    "https://www.marketwatch.com/rss/topstories",
    # Investing.com global
    "https://www.investing.com/rss/news.rss",
    # Seeking Alpha market news
    "https://seekingalpha.com/market_currents.xml",
    # FT latest
    "https://www.ft.com/?format=rss",
    # Wall Street Journal markets
    "https://feeds.a.dj.com/rss/RSSMarketsMain.xml",
    # CNBC top news (mirror RSS feed)
    "https://search.cnbc.com/rs/search/combinedcms/view.xml?partnerId=wrss01&id=100003114",
]


def _get_feed_urls() -> List[str]:
    """Devolve a lista de URLs de feed a utilizar."""
    import os
    raw = os.getenv("RSS_FEEDS_URLS")
    if raw:
        return [u.strip() for u in raw.split(",") if u.strip()]
    return DEFAULT_FEEDS


def _parse_published(entry: Dict[str, Any]) -> Optional[datetime]:
    """Extrai a data de publicação de uma entrada feedparser."""
    for field in ("published_parsed", "updated_parsed", "created_parsed"):
        parsed = entry.get(field)
        if parsed:
            try:
                dt = datetime(*parsed[:6], tzinfo=timezone.utc)
                return dt
            except Exception:
                pass
    for field in ("published", "updated", "created"):
        value = entry.get(field)
        if value:
            try:
                return _parse_date_string(str(value))
            except Exception:
                pass
    return None


def _parse_date_string(value: str) -> datetime:
    """Parse tolerante de datas RSS (RFC 822 e ISO)."""
    value = value.strip()
    # RFC 822: "Mon, 02 Jan 2023 15:04:05 GMT"
    for fmt in (
        "%a, %d %b %Y %H:%M:%S %Z",
        "%a, %d %b %Y %H:%M:%S %z",
        "%d %b %Y %H:%M:%S %Z",
        "%Y-%m-%dT%H:%M:%S%z",
        "%Y-%m-%dT%H:%M:%SZ",
        "%Y-%m-%dT%H:%M:%S",
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%d",
    ):
        try:
            return datetime.strptime(value, fmt).replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    raise ValueError(f"Formato de data não reconhecido: {value}")


def _article_text_from_url(url: str, timeout: int = 10) -> str:
    """Tenta extrair texto limpo da página HTML (fallback para sumário)."""
    try:
        resp = requests.get(url, timeout=timeout, headers={"User-Agent": "Mozilla/5.0"})
        resp.raise_for_status()
        text = resp.text
        # strip tags simples
        text = re.sub(r"<script[^>]*>.*?</script>", "", text, flags=re.S | re.I)
        text = re.sub(r"<style[^>]*>.*?</style>", "", text, flags=re.S | re.I)
        text = re.sub(r"<[^>]+>", " ", text)
        text = re.sub(r"\s+", " ", text).strip()
        # Limita a 2k chars
        return text[:2000]
    except Exception as e:
        logger.debug("Não foi possível obter artigo %s: %s", url, e)
        return ""


def _normalize_item(entry: Dict[str, Any], source: str, fetch_full_text: bool = False) -> Optional[Dict[str, Any]]:
    """Converte uma entrada do feedparser num dict normalizado."""
    title = (entry.get("title") or "").strip()
    link = (entry.get("link") or "").strip()
    summary = (entry.get("summary") or entry.get("description") or "").strip()
    if not title:
        return None

    if fetch_full_text and link and len(summary) < 80:
        fetched = _article_text_from_url(link)
        if fetched:
            summary = fetched

    published_dt = _parse_published(entry)
    published_iso = published_dt.isoformat() if published_dt else datetime.now(timezone.utc).isoformat()

    # Gera id estável a partir de título+link+data
    id_seed = f"{title}|{link}|{published_iso[:10]}"
    item_id = hashlib.sha256(id_seed.encode()).hexdigest()[:24]

    return {
        "id": item_id,
        "title": title,
        "summary": summary,
        "url": link,
        "publisher": _extract_publisher(entry, link, source),
        "published": published_iso,
        "source": source,
        "tags": [t.get("term") for t in entry.get("tags", []) if t.get("term")],
    }


def _extract_publisher(entry: Dict[str, Any], link: str, fallback: str) -> str:
    """Tenta extrair nome do publisher a partir do feed, link ou fallback."""
    publisher = entry.get("author") or entry.get("author_detail", {}).get("name")
    if publisher:
        return publisher
    if link:
        try:
            netloc = urlparse(link).netloc
            if netloc:
                return netloc.replace("www.", "").split(":")[0]
        except Exception:
            pass
    return fallback


def _fetch_feed(url: str, timeout: int = 20) -> Optional[feedparser.FeedParserDict]:
    """Faz parse de um feed RSS/Atom com timeout e logging."""
    try:
        # feedparser >=6 não aceita timeout diretamente; usamos requests para fetch.
        resp = requests.get(url, timeout=timeout, headers={"User-Agent": "Mozilla/5.0"})
        resp.raise_for_status()
        parsed = feedparser.parse(resp.content)
        if parsed.get("bozo_exception"):
            logger.warning("Feed %s parse warning: %s", url, parsed.get("bozo_exception"))
        return parsed
    except Exception as e:
        logger.error("Erro ao obter feed %s: %s", url, e)
        return None


def _matches_ticker(item: Dict[str, Any], ticker: str) -> bool:
    """Verifica se o item menciona o ticker ou nome da empresa."""
    ticker = ticker.upper()
    names = _known_company_names.get(ticker, [])
    text = f"{item.get('title', '')} {item.get('summary', '')} {item.get('tags', [])}".lower()
    if re.search(rf"\b{re.escape(ticker)}\b", text, re.I):
        return True
    for name in names:
        if name.lower() in text:
            return True
    return False


def collect_finance_rss(
    ticker: Optional[str] = None,
    max_items: int = 200,
    max_per_feed: int = 50,
    fetch_full_text: bool = False,
    feed_urls: Optional[Iterable[str]] = None,
    since_days: int = 30,
) -> List[Dict[str, Any]]:
    """Coleta itens RSS financeiros normalizados.

    Args:
        ticker: se indicado, filtra itens que mencionam o ticker/nome da empresa.
        max_items: limite global de itens devolvidos.
        max_per_feed: limite de itens por feed.
        fetch_full_text: tenta fazer fetch do artigo completo quando o sumário é curto.
        feed_urls: URLs de feeds a usar (omissão usa default/env).
        since_days: ignora itens mais antigos que N dias.

    Returns:
        Lista de dicts normalizados com id, title, summary, url, publisher,
        published, source, tags.
    """
    urls = list(feed_urls or _get_feed_urls())
    if not urls:
        logger.warning("Nenhum URL de RSS configurado.")
        return []

    cutoff = datetime.now(timezone.utc).timestamp() - since_days * 24 * 3600
    results: List[Dict[str, Any]] = []
    seen_ids: set = set()

    for url in urls:
        parsed = _fetch_feed(url)
        if not parsed or not parsed.entries:
            continue
        feed_title = parsed.feed.get("title") or urlparse(url).netloc or "rss"
        count = 0
        for entry in parsed.entries:
            if count >= max_per_feed:
                break
            item = _normalize_item(entry, source=feed_title, fetch_full_text=fetch_full_text)
            if not item:
                continue
            if item["id"] in seen_ids:
                continue
            published_dt = _parse_published(entry)
            if published_dt and published_dt.timestamp() < cutoff:
                continue
            if ticker and not _matches_ticker(item, ticker):
                continue
            seen_ids.add(item["id"])
            results.append(item)
            count += 1
            if len(results) >= max_items:
                break
        if len(results) >= max_items:
            break

    # Ordena por data descendente
    results.sort(key=lambda x: x.get("published") or "", reverse=True)
    logger.info("RSS collect: %d items from %d feeds (ticker=%s)", len(results), len(urls), ticker or "any")
    return results


_known_company_names: Dict[str, List[str]] = {
    "AAPL": ["apple", "iphone", "ipad", "mac"],
    "TSLA": ["tesla", "cybertruck"],
    "GOOGL": ["google", "alphabet", "youtube"],
    "MSFT": ["microsoft", "windows", "xbox"],
    "AMZN": ["amazon", "aws"],
    "NVDA": ["nvidia", "geforce", "rtx"],
    "META": ["meta", "facebook", "instagram"],
    "NFLX": ["netflix"],
    "AMD": ["amd"],
    "INTC": ["intel"],
}


def _update_known_names(ticker: str, names: List[str]) -> None:
    """Permite registar nomes adicionais de empresas para matching RSS."""
    _known_company_names[ticker.upper()] = list(dict.fromkeys(names + _known_company_names.get(ticker.upper(), [])))


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    for it in collect_finance_rss(ticker="AAPL", max_items=10, since_days=7):
        print(it["published"], it["publisher"], it["title"][:80])
