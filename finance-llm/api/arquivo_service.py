"""Serviço do módulo Arquivo.pt.

Recolhe e pesquisa capturas da web preservadas pelo Arquivo.pt (FCT).
Fontes:
- API pública de pesquisa de texto: `https://arquivo.pt/textsearch`
- API CDX: `https://arquivo.pt/wayback/cdx`

O serviço expõe metadados, pesquisa no índice local, recolha assistida e
indexação em `finance_arquivo_pt`.
"""
from __future__ import annotations

import logging
from datetime import datetime
from typing import Any, Dict, List, Optional

from collectors import arquivo as collector

logger = logging.getLogger(__name__)

INDEX = "finance_arquivo_pt"
SOURCE_LABEL = "Arquivo.pt — Pesquise páginas do passado"
SOURCE_ID = "arquivo-pt"

SEARCH_FIELDS = (
    "title^3",
    "url^2",
    "domain^2",
    "snippet",
    "text",
)

SORT_OPTIONS = ("relevance", "date_desc", "date_asc", "domain")


def meta() -> Dict[str, Any]:
    """Metadados do módulo para a UI."""
    return {
        "module": "arquivo",
        "source": "arquivo.pt",
        "source_label": SOURCE_LABEL,
        "index": INDEX,
        "search_page": "https://arquivo.pt",
        "api_docs": "https://github.com/arquivo/pwa-technologies/wiki/APIs",
        "max_items_per_request": 200,
        "default_max_items": collector.DEFAULT_MAX_ITEMS,
        "default_max_pages": collector.DEFAULT_MAX_PAGES,
        "notes": (
            "O Arquivo.pt é um serviço público da FCT que preserva páginas da web "
            "desde 1996. A API pública permite pesquisar texto completo e listar "
            "capturas (CDX) sem autenticação."
        ),
    }


def _doc_id(doc: Dict[str, Any]) -> str:
    """Gera `_id` estável para o Elasticsearch: domínio + timestamp + digest."""
    from urllib.parse import quote

    domain = doc.get("domain") or "unknown"
    tstamp = doc.get("tstamp") or ""
    digest = doc.get("digest") or ""
    return f"{domain}-{tstamp}-{digest}"[:512] or f"{domain}-{datetime.utcnow().isoformat()}"


def index_items(items: List[Dict[str, Any]], *, kind: str = "search") -> Dict[str, Any]:
    """Indexa itens normalizados no Elasticsearch."""
    from elasticsearch.helpers import bulk

    from api.elasticsearch_client import get_es_client

    client = get_es_client()
    if not client:
        return {"error": "Elasticsearch indisponível", "indexed_count": 0}

    now = datetime.utcnow().isoformat()
    actions = []
    for item in items:
        doc = dict(item)
        doc["kind"] = kind
        doc.setdefault("collected_at", now)
        actions.append({"_index": INDEX, "_id": _doc_id(doc), "_source": doc})

    if not actions:
        return {"indexed_count": 0, "total": 0}

    try:
        indexed, errors = bulk(client, actions, raise_on_error=False)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Falha ao indexar itens do Arquivo.pt: %s", exc)
        return {"error": str(exc), "indexed_count": 0, "total": len(actions)}

    return {"indexed_count": indexed, "errors": len(errors) if isinstance(errors, list) else errors, "total": len(actions)}


def collect(
    q: str,
    *,
    max_pages: int = collector.DEFAULT_MAX_PAGES,
    max_items: int = collector.DEFAULT_MAX_ITEMS,
    site: Optional[str] = None,
    type: Optional[str] = None,
    from_ts: Optional[str] = None,
    to_ts: Optional[str] = None,
    ingest: bool = True,
    min_interval: float = collector.DEFAULT_MIN_INTERVAL,
) -> Dict[str, Any]:
    """Recolhe resultados do Arquivo.pt e (opcionalmente) indexa-os."""
    result = collector.collect_search(
        q=q,
        max_pages=max_pages,
        max_items=max_items,
        site=site,
        type=type,
        from_ts=from_ts,
        to_ts=to_ts,
        min_interval=min_interval,
    )
    if ingest and result.get("items"):
        ingest_result = index_items(result["items"], kind="search")
        result["ingest"] = ingest_result
    return result


def search(
    q: Optional[str] = None,
    *,
    domain: Optional[str] = None,
    url: Optional[str] = None,
    mime_type: Optional[str] = None,
    type: Optional[str] = None,
    from_date: Optional[str] = None,
    to_date: Optional[str] = None,
    kind: Optional[str] = None,
    sort: str = "relevance",
    size: int = 20,
    offset: int = 0,
) -> Dict[str, Any]:
    """Pesquisa capturas indexadas do Arquivo.pt."""
    from api.elasticsearch_client import _text_search, get_es_client

    client = get_es_client()
    if not client:
        return {"error": "Elasticsearch indisponível", "total": 0, "items": []}

    if sort not in SORT_OPTIONS:
        sort = "relevance"

    must: List[Dict[str, Any]] = []
    filters: List[Dict[str, Any]] = []

    if q:
        must.append(
            {
                "multi_match": {
                    "query": q,
                    "fields": list(SEARCH_FIELDS),
                    "type": "best_fields",
                }
            }
        )
    if domain:
        filters.append({"term": {"domain": domain.lower()}})
    if url:
        filters.append({"term": {"url": url}})
    if mime_type:
        filters.append({"term": {"mime_type": mime_type}})
    if type:
        filters.append({"term": {"type": type}})
    if kind:
        filters.append({"term": {"kind": kind}})
    if from_date or to_date:
        range_filter: Dict[str, Any] = {"range": {"capture_date": {}}}
        if from_date:
            range_filter["range"]["capture_date"]["gte"] = from_date
        if to_date:
            range_filter["range"]["capture_date"]["lte"] = to_date
        filters.append(range_filter)

    query: Dict[str, Any] = {"bool": {}}
    if must:
        query["bool"]["must"] = must
    if filters:
        query["bool"]["filter"] = filters
    if not must and not filters:
        query = {"match_all": {}}

    sort_clause: List[Any] = ["_score"]
    if sort == "date_desc":
        sort_clause = [{"capture_date": {"order": "desc"}}, "_score"]
    elif sort == "date_asc":
        sort_clause = [{"capture_date": {"order": "asc"}}, "_score"]
    elif sort == "domain":
        sort_clause = [{"domain.keyword": {"order": "asc"}}, "_score"]

    body = {
        "query": query,
        "sort": sort_clause,
        "from": offset,
        "size": min(max(1, size), 200),
        "track_total_hits": True,
    }

    try:
        response = _text_search(client, index=INDEX, body=body, q=q)
        hits = response.get("hits", {})
        total = hits.get("total", {})
        total_value = total.get("value", 0) if isinstance(total, dict) else total
        items = [hit.get("_source", {}) for hit in hits.get("hits", [])]
        return {"total": total_value, "items": items, "offset": offset, "size": size, "query": q}
    except Exception as exc:  # noqa: BLE001
        logger.warning("Falha na pesquisa do Arquivo.pt: %s", exc)
        return {"error": str(exc), "total": 0, "items": []}


def status() -> Dict[str, Any]:
    """Volumetria do índice local do Arquivo.pt."""
    from api.elasticsearch_client import get_es_client

    client = get_es_client()
    if not client:
        return {"available": False, "total": 0, "error": "Elasticsearch indisponível"}
    try:
        if not client.indices.exists(index=INDEX):
            return {"available": False, "total": 0}
        count = client.count(index=INDEX).get("count", 0)
        return {"available": bool(count), "total": int(count), "index": INDEX}
    except Exception as exc:  # noqa: BLE001
        return {"available": False, "total": 0, "error": str(exc)}


def available() -> bool:
    """Indica se o índice local do Arquivo.pt existe."""
    return status().get("available", False)
