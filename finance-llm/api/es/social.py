"""Publicações de redes sociais por canal.

Módulo do pacote :mod:`api.es` — ver `api/elasticsearch_client.py`,
que continua a expor a API pública (os coletores/serviços importam de lá).
"""
import logging
from typing import Any, Dict, List, Optional

from elasticsearch import Elasticsearch
from elasticsearch.helpers import bulk
from api.es.core import _clean_flattened, _today, get_es_client
from api.es.indices import SOCIAL_INDEX
from api.es.mappings import ensure_indices
from api.es.scraping import _sentiment_summary

logger = logging.getLogger(__name__)




# ---------------------------------------------------------------------------
# Pesquisa social (LinkedIn, TikTok, Reddit, Facebook) — índice `finance_social`
# ---------------------------------------------------------------------------

#: Métricas de interação guardadas como campos próprios (para ordenar/agregar).
SOCIAL_METRIC_FIELDS = ("likes", "comments", "shares", "views")




def index_social_items(
    channel: Dict[str, Any],
    items: List[Dict[str, Any]],
    trigger: str = "manual",
    es: Optional[Elasticsearch] = None,
) -> Dict[str, Any]:
    """Indexa publicações sociais em `finance_social`.

    O `_id` do documento é o `item_id` calculado pelo `social_service`
    (`sha1(plataforma|tipo|alvo|id-da-publicação)`), pelo que repetir uma recolha
    **atualiza** as publicações já conhecidas (métricas mais recentes) em vez de
    as duplicar.
    """
    client = es or get_es_client()
    if not client:
        return {"error": "Elasticsearch indisponível", "indexed_count": 0, "error_count": 0}

    ensure_indices(client)
    now = _today()
    channel = channel or {}
    actions: List[Dict[str, Any]] = []
    for item in items or []:
        item_id = str(item.get("item_id") or "").strip()
        if not item_id:
            continue
        metrics = item.get("metrics") if isinstance(item.get("metrics"), dict) else {}
        tags = item.get("tags")
        if isinstance(tags, str):
            tags = [tags]
        sentimento = item.get("sentiment") if isinstance(item.get("sentiment"), dict) else {}
        doc: Dict[str, Any] = {
            "platform": str(item.get("platform") or channel.get("platform") or "")[:32],
            "channel_id": str(item.get("channel_id") or channel.get("id") or "")[:128],
            "channel_name": str(item.get("channel_name") or channel.get("name") or "")[:256],
            "kind": str(item.get("kind") or channel.get("kind") or "")[:32],
            "run_id": str(item.get("run_id") or "")[:64],
            "item_id": item_id,
            "post_id": str(item.get("post_id") or "")[:256],
            "url": str(item.get("url") or "")[:1024],
            "title": str(item.get("title") or "")[:1024],
            "text": str(item.get("text") or "")[:100000],
            "author": str(item.get("author") or "")[:256],
            "community": str(item.get("community") or "")[:256],
            "lang": str(item.get("lang") or "")[:16],
            "image": str((item.get("media") or {}).get("image") or item.get("image") or "")[:1024],
            "video": str((item.get("media") or {}).get("video") or item.get("video") or "")[:1024],
            "images": [str(url)[:1024] for url in ((item.get("media") or {}).get("images") or item.get("images") or []) if url][:24],
            "videos": [str(url)[:1024] for url in ((item.get("media") or {}).get("videos") or item.get("videos") or []) if url][:12],
            "person_nif": str(item.get("person_nif") or channel.get("person_nif") or "")[:32],
            "person_name": str(item.get("person_name") or channel.get("person_name") or "")[:512],
            "tags": [str(t) for t in (tags or []) if t not in (None, "")][:64],
            "collected_at": str(item.get("collected_at") or now),
            "trigger": trigger or "manual",
            "data": _clean_flattened(item.get("data") or {}) or {},
        }
        for metric in SOCIAL_METRIC_FIELDS:
            try:
                doc[metric] = int(metrics.get(metric) or 0)
            except (TypeError, ValueError):
                doc[metric] = 0
        published = item.get("published_at")
        if published:
            doc["published_at"] = str(published)
        label = str(sentimento.get("label") or "").strip().lower()
        if label:
            doc["sentiment"] = label
            doc["sentiment_engine"] = str(sentimento.get("engine") or "")[:32]
            try:
                doc["sentiment_score"] = float(sentimento.get("polarity") or 0.0)
            except (TypeError, ValueError):
                doc["sentiment_score"] = 0.0
        actions.append({"_index": SOCIAL_INDEX, "_id": item_id, "_source": doc})

    if not actions:
        return {"indexed_count": 0, "error_count": 0}

    try:
        success, errors = bulk(client, actions, raise_on_error=False, stats_only=False, refresh=True)
        error_list = errors if isinstance(errors, list) else []
        if error_list:
            logger.warning("Pesquisa social: %s de %s itens falharam na indexação", len(error_list), len(actions))
        return {
            "indexed_count": int(success),
            "error_count": len(error_list),
            "errors": [str(e.get("index", {}).get("error", e))[:300] for e in error_list[:5]],
        }
    except Exception as exc:
        return {"error": str(exc), "indexed_count": 0, "error_count": len(actions)}




def _social_query(
    q: Optional[str] = None,
    platform: Optional[str] = None,
    channel_id: Optional[str] = None,
    tags: Optional[List[str]] = None,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    sentiments: Optional[List[str]] = None,
    person_nif: Optional[str] = None,
    kinds: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """Constrói a query de pesquisa de publicações sociais."""
    must: List[Dict[str, Any]] = []
    if q:
        must.append(
            {
                "query_string": {
                    "query": q,
                    "fields": ["title^3", "text^2", "author^2", "community", "url", "data.*"],
                    "default_operator": "and",
                    "lenient": True,
                    "analyze_wildcard": True,
                }
            }
        )
    filters: List[Dict[str, Any]] = []
    if platform:
        filters.append({"term": {"platform": platform}})
    if channel_id:
        filters.append({"term": {"channel_id": channel_id}})
    if person_nif:
        filters.append({"term": {"person_nif": str(person_nif)}})
    if tags:
        filters.append({"terms": {"tags": tags}})
    # Tipo de publicação (`post`, `video`, `comment`, `profile`…): é o que
    # permite filtrar as redes **por tipo**, não só por plataforma.
    tipos = [str(k).strip().lower() for k in (kinds or []) if str(k).strip()]
    if tipos:
        filters.append({"terms": {"kind": tipos}})
    etiquetas = [str(s).strip().lower() for s in (sentiments or []) if str(s).strip()]
    if etiquetas:
        filters.append({"terms": {"sentiment": etiquetas}})
    if date_from or date_to:
        rng: Dict[str, Any] = {}
        if date_from:
            rng["gte"] = date_from
        if date_to:
            rng["lte"] = date_to
        # Filtra pela data de publicação, mas cai na de recolha quando a
        # publicação não traz data (é o caso dos vídeos do TikTok e de páginas
        # do Facebook sem `created_time`).
        filters.append(
            {
                "bool": {
                    "should": [
                        {"range": {"published_at": rng}},
                        {
                            "bool": {
                                "must_not": {"exists": {"field": "published_at"}},
                                "must": [{"range": {"collected_at": rng}}],
                            }
                        },
                    ],
                    "minimum_should_match": 1,
                }
            }
        )

    bool_query: Dict[str, Any] = {"must": must or [{"match_all": {}}]}
    if filters:
        bool_query["filter"] = filters
    return {"bool": bool_query}




def search_social(
    q: Optional[str] = None,
    platform: Optional[str] = None,
    channel_id: Optional[str] = None,
    tags: Optional[List[str]] = None,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    sentiments: Optional[List[str]] = None,
    person_nif: Optional[str] = None,
    kinds: Optional[List[str]] = None,
    size: int = 20,
    from_: int = 0,
    sort: str = "recent",
    es: Optional[Elasticsearch] = None,
) -> Dict[str, Any]:
    """Pesquisa publicações sociais, com facetas por tipo, plataforma, canal e etiqueta."""
    client = es or get_es_client()
    if not client:
        return {"error": "Elasticsearch indisponível", "total": 0, "items": [], "facets": {}}

    ensure_indices(client)

    sort_spec: List[Any]
    if sort == "oldest":
        sort_spec = [{"collected_at": {"order": "asc"}}]
    elif sort == "engagement":
        sort_spec = [{"likes": {"order": "desc"}}, {"comments": {"order": "desc"}}]
    elif sort == "views":
        sort_spec = [{"views": {"order": "desc"}}, {"likes": {"order": "desc"}}]
    elif sort == "relevance" and q:
        sort_spec = [{"_score": {"order": "desc"}}, {"collected_at": {"order": "desc"}}]
    else:
        sort_spec = [{"collected_at": {"order": "desc"}}]

    body: Dict[str, Any] = {
        "size": max(0, min(int(size), 200)),
        "from": max(0, int(from_)),
        "query": _social_query(q, platform, channel_id, tags, date_from, date_to, sentiments, person_nif, kinds),
        "sort": sort_spec,
        "track_total_hits": True,
        "aggs": {
            "platforms": {"terms": {"field": "platform", "size": 20}},
            # Tipo de publicação: o painel de filtros das redes sociais é por aqui.
            "kinds": {"terms": {"field": "kind", "size": 20}},
            "channels": {"terms": {"field": "channel_id", "size": 50}},
            "tags": {"terms": {"field": "tags", "size": 50}},
            "days": {"date_histogram": {"field": "collected_at", "calendar_interval": "day", "min_doc_count": 0}},
            "sentiment": {"terms": {"field": "sentiment", "size": 10}},
            "sentiment_avg": {"avg": {"field": "sentiment_score"}},
        },
    }

    try:
        resp = client.search(index=SOCIAL_INDEX, body=body)
    except Exception as exc:
        logger.debug("Pesquisa social falhou (%s); a repetir sem `data.*`: %s", q, exc)
        if not q:
            return {"error": str(exc), "total": 0, "items": [], "facets": {}}
        fallback = dict(body)
        fallback["query"] = {
            "bool": {
                "must": [{"multi_match": {"query": q, "fields": ["title", "text", "author"], "lenient": True}}],
                "filter": _social_query(None, platform, channel_id, tags, date_from, date_to, sentiments, person_nif, kinds)["bool"].get("filter", []),
            }
        }
        try:
            resp = client.search(index=SOCIAL_INDEX, body=fallback)
        except Exception as inner:
            return {"error": str(inner), "total": 0, "items": [], "facets": {}}

    aggs = resp.get("aggregations", {}) or {}
    total = resp.get("hits", {}).get("total", 0)
    total_value = total.get("value", 0) if isinstance(total, dict) else total
    return {
        "total": int(total_value or 0),
        "items": [hit.get("_source") or {} for hit in resp.get("hits", {}).get("hits", [])],
        "facets": {
            "platforms": [
                {"key": b["key"], "count": b["doc_count"]} for b in aggs.get("platforms", {}).get("buckets", [])
            ],
            "kinds": [{"key": b["key"], "count": b["doc_count"]} for b in aggs.get("kinds", {}).get("buckets", [])],
            "channels": [
                {"key": b["key"], "count": b["doc_count"]} for b in aggs.get("channels", {}).get("buckets", [])
            ],
            "tags": [{"key": b["key"], "count": b["doc_count"]} for b in aggs.get("tags", {}).get("buckets", [])],
            "days": [
                {"key": b.get("key_as_string"), "count": b["doc_count"]}
                for b in aggs.get("days", {}).get("buckets", [])
                if b.get("doc_count")
            ],
            "sentiment": [
                {"key": b["key"], "count": b["doc_count"]} for b in aggs.get("sentiment", {}).get("buckets", [])
            ],
        },
        "sentiment": _sentiment_summary(aggs, int(total_value or 0)),
    }




def social_status(es: Optional[Elasticsearch] = None) -> Dict[str, Any]:
    """Volumetria do índice social (total e por plataforma)."""
    client = es or get_es_client()
    if not client:
        return {"available": False, "total": 0, "platforms": []}

    ensure_indices(client)
    try:
        resp = client.search(
            index=SOCIAL_INDEX,
            body={
                "size": 0,
                "track_total_hits": True,
                "aggs": {
                    "platforms": {"terms": {"field": "platform", "size": 20}},
                    "channels": {"terms": {"field": "channel_id", "size": 50}},
                },
            },
        )
        total = resp.get("hits", {}).get("total", 0)
        total_value = total.get("value", 0) if isinstance(total, dict) else total
        aggs = resp.get("aggregations", {}) or {}
        return {
            "available": True,
            "total": int(total_value or 0),
            "platforms": [
                {"key": b["key"], "count": b["doc_count"]} for b in aggs.get("platforms", {}).get("buckets", [])
            ],
            "channels": [
                {"key": b["key"], "count": b["doc_count"]} for b in aggs.get("channels", {}).get("buckets", [])
            ],
        }
    except Exception as exc:
        return {"available": False, "total": 0, "platforms": [], "error": str(exc)}




def delete_social_channel(channel_id: str, es: Optional[Elasticsearch] = None) -> Dict[str, Any]:
    """Remove do índice todas as publicações de um canal."""
    client = es or get_es_client()
    if not client:
        return {"error": "Elasticsearch indisponível"}
    ensure_indices(client)
    try:
        resp = client.delete_by_query(
            index=SOCIAL_INDEX,
            body={"query": {"term": {"channel_id": channel_id}}},
            refresh=True,
            conflicts="proceed",
        )
        return {"ok": True, "deleted": resp.get("deleted", 0)}
    except Exception as exc:
        return {"error": str(exc)}
