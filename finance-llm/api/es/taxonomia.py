"""Taxonomia europeia (EU taxonomy): indexação e pesquisa.

Módulo do pacote :mod:`api.es` — ver `api/elasticsearch_client.py`,
que continua a expor a API pública (os coletores/serviços importam de lá).
"""
import logging
from typing import Any, Dict, List, Optional

from elasticsearch import Elasticsearch
from elasticsearch.helpers import bulk
from api.es.core import get_es_client
from api.es.indices import EU_TAXONOMY_INDEX
from api.es.mappings import ensure_indices
from api.es.scraping import _accent_fold_terms

logger = logging.getLogger(__name__)



def index_eu_taxonomy(
    items: List[Dict[str, Any]],
    *,
    es: Optional[Elasticsearch] = None,
) -> Dict[str, Any]:
    """Indexa documentos do EU Taxonomy Navigator em `finance_eu_taxonomy`.

    Cada documento e identificado por `kind` + identificador (`activity_id`,
    `objective_id` ou `sector_id`). A indexacao atualiza documentos ja
    existentes (refresh imediato para leitura consistente).
    """
    client = es or get_es_client()
    if not client:
        return {"error": "Elasticsearch indisponivel", "indexed_count": 0, "error_count": 0}

    ensure_indices(client)

    actions: List[Dict[str, Any]] = []
    for item in items or []:
        kind = str(item.get("kind") or "").strip()
        doc_id = None
        if kind == "activity":
            doc_id = f"activity-{item.get('activity_id')}"
        elif kind == "objective":
            doc_id = f"objective-{item.get('objective_id')}"
        elif kind == "sector":
            doc_id = f"sector-{item.get('sector_id')}"
        if not doc_id or not kind:
            continue
        doc = {k: v for k, v in item.items() if k != "_id"}
        actions.append({"_index": EU_TAXONOMY_INDEX, "_id": doc_id, "_source": doc})

    if not actions:
        return {"indexed_count": 0, "error_count": 0}

    try:
        success, errors = bulk(client, actions, raise_on_error=False, stats_only=False, refresh=True)
        error_list = errors if isinstance(errors, list) else []
        if error_list:
            logger.warning("EU Taxonomy: %s de %s itens falharam na indexacao", len(error_list), len(actions))
        return {
            "indexed_count": int(success),
            "error_count": len(error_list),
            "errors": [str(e.get("index", {}).get("error", e))[:300] for e in error_list[:5]],
        }
    except Exception as exc:
        return {"error": str(exc), "indexed_count": 0, "error_count": len(actions)}




def search_eu_taxonomy(
    q: Optional[str] = None,
    kind: Optional[str] = None,
    sector: Optional[str] = None,
    objective_id: Optional[int] = None,
    nace: Optional[str] = None,
    size: int = 20,
    from_: int = 0,
    sort: str = "relevance",
    es: Optional[Elasticsearch] = None,
) -> Dict[str, Any]:
    """Pesquisa documentos do EU Taxonomy Navigator.

    A pesquisa cobre nome e descricao em ingles e portugues. Devolve facetas
    por tipo (`kind`), setor (`sector_pt`/`sector_en`) e objetivo ambiental.
    """
    client = es or get_es_client()
    if not client:
        return {"error": "Elasticsearch indisponivel", "total": 0, "items": [], "facets": {}}

    ensure_indices(client)

    filters: List[Dict[str, Any]] = []
    if kind:
        filters.append({"term": {"kind": str(kind).lower()}})
    if sector:
        filters.append({
            "bool": {
                "should": [
                    {"term": {"sector_en": str(sector)}},
                    {"term": {"sector_pt": str(sector)}},
                    {"wildcard": {"sector_en": {"value": f"*{sector}*", "case_insensitive": True}}},
                    {"wildcard": {"sector_pt": {"value": f"*{sector}*", "case_insensitive": True}}},
                ],
                "minimum_should_match": 1,
            }
        })
    if objective_id is not None:
        filters.append({"nested": {"path": "objectives", "query": {"term": {"objectives.objective_id": int(objective_id)}}}})
    if nace:
        prefix = str(nace).upper().replace(".", "").replace("-", "")
        filters.append({"prefix": {"nace_codes": prefix}})

    must: List[Dict[str, Any]] = []
    if q:
        folded = _accent_fold_terms(q)
        terms = [q, folded] if folded and folded != q else [q]
        should: List[Dict[str, Any]] = []
        for term in terms:
            should.extend([
                {"match_phrase": {"name_en": {"query": term, "boost": 6}}},
                {"match_phrase": {"name_pt": {"query": term, "boost": 6}}},
                {"match": {"name_en": {"query": term, "operator": "and", "boost": 3}}},
                {"match": {"name_pt": {"query": term, "operator": "and", "boost": 3}}},
                {"match": {"description_en": {"query": term, "boost": 1}}},
                {"match": {"description_pt": {"query": term, "boost": 1}}},
            ])
        must.append({"bool": {"should": should, "minimum_should_match": 1}})

    bool_query: Dict[str, Any] = {}
    if must:
        bool_query["must"] = must
    if filters:
        bool_query["filter"] = filters
    query = {"bool": bool_query} if bool_query else {"match_all": {}}

    sort_spec: List[Dict[str, Any]]
    if sort == "name":
        sort_spec = [{"name_en.keyword": {"order": "asc"}}]
    elif sort == "sector":
        sort_spec = [{"sector_en.keyword": {"order": "asc"}}, {"name_en.keyword": {"order": "asc"}}]
    else:
        sort_spec = ["_score", {"name_en.keyword": {"order": "asc"}}]

    body: Dict[str, Any] = {
        "size": max(0, min(int(size), 200)),
        "from": max(0, int(from_)),
        "query": query,
        "sort": sort_spec,
        "track_total_hits": True,
        "aggs": {
            "kinds": {"terms": {"field": "kind", "size": 10}},
            "sectors": {"terms": {"field": "sector_pt", "size": 50}},
            "objectives": {
                "nested": {"path": "objectives"},
                "aggs": {
                    "ids": {"terms": {"field": "objectives.objective_id", "size": 10}},
                    "names": {"terms": {"field": "objectives.objective_name_pt", "size": 10}},
                },
            },
        },
    }

    try:
        resp = client.search(index=EU_TAXONOMY_INDEX, body=body)
    except Exception as exc:
        return {"error": str(exc), "total": 0, "items": [], "facets": {}}

    aggs = resp.get("aggregations", {}) or {}
    total = resp.get("hits", {}).get("total", 0)
    total_value = total.get("value", 0) if isinstance(total, dict) else total

    obj_aggs = aggs.get("objectives", {}) or {}
    return {
        "total": int(total_value or 0),
        "items": [hit.get("_source") or {} for hit in resp.get("hits", {}).get("hits", [])],
        "facets": {
            "kinds": [{"key": b.get("key"), "count": b.get("doc_count")} for b in (aggs.get("kinds") or {}).get("buckets", []) if b.get("key")],
            "sectors": [{"key": b.get("key"), "count": b.get("doc_count")} for b in (aggs.get("sectors") or {}).get("buckets", []) if b.get("key")],
            "objectives": [
                {
                    "id": b.get("key"),
                    "count": b.get("doc_count"),
                }
                for b in (obj_aggs.get("ids") or {}).get("buckets", [])
                if b.get("key") is not None
            ],
        },
    }
