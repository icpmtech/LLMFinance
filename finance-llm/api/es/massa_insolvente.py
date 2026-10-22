"""Publicidade da Composição da Massa Insolvente (art.º 152.º do CIRE).

Módulo do pacote :mod:`api.es` — ver `api/elasticsearch_client.py`, que
continua a expor a API pública (os coletores/serviços importam de lá).
"""
from __future__ import annotations

import logging
from datetime import datetime
from typing import Any, Dict, List, Optional

from elasticsearch import Elasticsearch

from api.es.core import get_es_client
from api.es.entidades import _bulk_index_docs
from api.es.indices import MASSA_INSOLVENTE_INDEX
from api.es.mappings import ensure_indices

logger = logging.getLogger(__name__)


# --- Massa Insolvente: anúncios do art.º 152.º do CIRE ------------------

def massa_insolvente_existing_ids(
    pub_ids: List[str],
    es: Optional[Elasticsearch] = None,
) -> Dict[str, Any]:
    """Devolve quais dos ``pub_ids`` já existem no índice da massa insolvente."""
    client = es or get_es_client()
    if not client or not pub_ids:
        return {"found": [], "known": 0, "checked": 0, "index": MASSA_INSOLVENTE_INDEX}

    unique = list(dict.fromkeys(str(item) for item in pub_ids if item))
    found: List[str] = []
    chunk_size = 5000
    try:
        ensure_indices(client)
        for start in range(0, len(unique), chunk_size):
            chunk = unique[start: start + chunk_size]
            resp = client.search(
                index=MASSA_INSOLVENTE_INDEX,
                body={
                    "size": len(chunk),
                    "track_total_hits": False,
                    "_source": ["pub_id"],
                    "query": {"terms": {"pub_id": chunk}},
                },
            )
            for hit in resp.get("hits", {}).get("hits", []):
                valor = (hit.get("_source") or {}).get("pub_id")
                if not valor:
                    valor = str(hit.get("_id", "")).split(":", 1)[-1]
                found.append(str(valor))
    except Exception as exc:
        return {"error": str(exc), "found": [], "known": 0, "checked": len(unique), "index": MASSA_INSOLVENTE_INDEX}

    return {"found": found, "known": len(found), "checked": len(unique), "index": MASSA_INSOLVENTE_INDEX}


def index_massa_insolvente_items(
    items: List[Dict[str, Any]],
    run_id: Optional[str] = None,
    skip_existing: bool = True,
    es: Optional[Elasticsearch] = None,
) -> Dict[str, Any]:
    """Indexa anúncios da massa insolvente no ``MASSA_INSOLVENTE_INDEX``.

    O ``_id`` é o ``pub_id`` (sha1 do processo + data + tribunal). Com
    ``skip_existing`` (por omissão) os documentos que já existem são ignorados,
    pelo que reimportar o mesmo período só acrescenta o que é novo.
    """
    client = es or get_es_client()
    if not client:
        return {"error": "Elasticsearch indisponível", "indexed_count": 0, "total": 0}

    preparados: List[Dict[str, Any]] = []
    for item in items:
        doc = {k: v for k, v in item.items() if not k.startswith("_") and v is not None}
        if not doc.get("pub_id"):
            continue
        doc["source"] = doc.get("source") or "citius_massa_insolvente"
        if run_id:
            doc["run_id"] = run_id
        preparados.append(doc)

    ignorados: List[str] = []
    if skip_existing and preparados:
        existentes = massa_insolvente_existing_ids([str(d["pub_id"]) for d in preparados], es=client)
        ja_no_indice = set(existentes.get("found") or [])
        ignorados = [str(d["pub_id"]) for d in preparados if str(d["pub_id"]) in ja_no_indice]
        preparados = [d for d in preparados if str(d["pub_id"]) not in ja_no_indice]
        if existentes.get("error"):
            logger.warning("Não foi possível verificar duplicados da massa insolvente: %s", existentes["error"])

    now = datetime.utcnow().isoformat()
    docs = [{**doc, "ingested_at": now} for doc in preparados]
    result = _bulk_index_docs(MASSA_INSOLVENTE_INDEX, docs, id_field="pub_id", es=client)
    result["received"] = len(items)
    result["indexed_count"] = result.get("indexed_count", 0)
    result["skipped_existing"] = len(ignorados)
    result["candidates"] = len(preparados)
    return result


def _massa_query(
    *,
    q: Optional[str] = None,
    processo: Optional[str] = None,
    tipo: Optional[str] = None,
    especie: Optional[str] = None,
    tribunal: Optional[str] = None,
    tribunal_comarca: Optional[str] = None,
    insolvente: Optional[str] = None,
    ativo_tipo: Optional[str] = None,
    localizacao: Optional[str] = None,
    area_negocio: Optional[str] = None,
    data_from: Optional[str] = None,
    data_to: Optional[str] = None,
    valor_min: Optional[float] = None,
    valor_max: Optional[float] = None,
) -> Dict[str, Any]:
    """Query ``bool`` para pesquisa e analítica da massa insolvente."""
    must: List[Dict[str, Any]] = []
    filters: List[Dict[str, Any]] = []
    if q:
        must.append(
            {
                "multi_match": {
                    "query": q,
                    "fields": [
                        "insolvente^3",
                        "insolventes^3",
                        "processo^2",
                        "processo_numero^2",
                        "tribunal^2",
                        "especie",
                        "descricao",
                        "ativos.descricao",
                        "texto",
                    ],
                    "operator": "and",
                }
            }
        )
    if processo:
        filters.append({"match_phrase": {"processo": processo}})
    if tipo:
        filters.append({"term": {"tipo": tipo}})
    if especie:
        filters.append({"match_phrase": {"especie": especie}})
    if tribunal:
        filters.append({"match_phrase": {"tribunal": tribunal}})
    if tribunal_comarca:
        filters.append({"term": {"tribunal_comarca": tribunal_comarca}})
    if insolvente:
        filters.append({"match_phrase": {"insolvente": insolvente}})
    if ativo_tipo:
        filters.append({"term": {"ativo_tipos": ativo_tipo}})
    if localizacao:
        filters.append(
            {
                "bool": {
                    "should": [
                        {"term": {"localizacoes": localizacao}},
                        {"nested": {"path": "ativos", "query": {"term": {"ativos.localizacao": localizacao}}}},
                    ]
                }
            }
        )
    if area_negocio:
        filters.append({"match_phrase": {"area_negocio": area_negocio}})
    if data_from or data_to:
        interval: Dict[str, str] = {}
        if data_from:
            interval["gte"] = data_from
        if data_to:
            interval["lte"] = data_to
        filters.append({"range": {"data_atualizacao": interval}})
    if valor_min is not None or valor_max is not None:
        range_q: Dict[str, Any] = {}
        if valor_min is not None:
            range_q["gte"] = valor_min
        if valor_max is not None:
            range_q["lte"] = valor_max
        filters.append({"range": {"valor_avaliacao": range_q}})

    if must or filters:
        query: Dict[str, Any] = {"bool": {}}
        if must:
            query["bool"]["must"] = must
        if filters:
            query["bool"]["filter"] = filters
        return query
    return {"match_all": {}}


def search_massa_insolvente(
    *,
    q: Optional[str] = None,
    processo: Optional[str] = None,
    tipo: Optional[str] = None,
    especie: Optional[str] = None,
    tribunal: Optional[str] = None,
    tribunal_comarca: Optional[str] = None,
    insolvente: Optional[str] = None,
    ativo_tipo: Optional[str] = None,
    localizacao: Optional[str] = None,
    area_negocio: Optional[str] = None,
    data_from: Optional[str] = None,
    data_to: Optional[str] = None,
    valor_min: Optional[float] = None,
    valor_max: Optional[float] = None,
    size: int = 20,
    from_: int = 0,
    es: Optional[Elasticsearch] = None,
) -> Dict[str, Any]:
    """Pesquisa anúncios da composição da massa insolvente."""
    client = es or get_es_client()
    if not client:
        return {"error": "Elasticsearch indisponível", "items": [], "total": 0}

    ensure_indices(client)
    query = _massa_query(
        q=q,
        processo=processo,
        tipo=tipo,
        especie=especie,
        tribunal=tribunal,
        tribunal_comarca=tribunal_comarca,
        insolvente=insolvente,
        ativo_tipo=ativo_tipo,
        localizacao=localizacao,
        area_negocio=area_negocio,
        data_from=data_from,
        data_to=data_to,
        valor_min=valor_min,
        valor_max=valor_max,
    )

    body: Dict[str, Any] = {
        "query": query,
        "from": max(0, from_),
        "size": max(1, min(size, 200)),
        "track_total_hits": True,
        "sort": [{"data_atualizacao": {"order": "desc", "missing": "_last"}}, "_score"],
        "aggs": {
            "by_tipo": {"terms": {"field": "tipo", "size": 10}},
            "by_ativo_tipo": {"terms": {"field": "ativo_tipos", "size": 15}},
            "by_comarca": {"terms": {"field": "tribunal_comarca", "size": 25}},
            "by_tribunal": {"terms": {"field": "tribunal.keyword", "size": 25}},
            "by_especie": {"terms": {"field": "especie.keyword", "size": 15}},
            "by_localizacao": {"terms": {"field": "localizacoes", "size": 20}},
            "by_area_negocio": {"terms": {"field": "area_negocio.keyword", "size": 15}},
            "by_ano": {
                "date_histogram": {"field": "data_atualizacao", "calendar_interval": "year", "format": "yyyy"}
            },
            "by_mes": {
                "date_histogram": {"field": "data_atualizacao", "calendar_interval": "month", "format": "yyyy-MM"}
            },
            "valores": {"stats": {"field": "valor_avaliacao"}},
        },
    }

    try:
        resp = client.search(index=MASSA_INSOLVENTE_INDEX, body=body)
        aggs = resp.get("aggregations", {})
        return {
            "query": q,
            "total": resp["hits"]["total"]["value"],
            "items": [{**hit["_source"], "doc_id": hit["_id"]} for hit in resp["hits"]["hits"]],
            "from": from_,
            "size": size,
            "facets": {
                "tipo": [{"key": b["key"], "count": b["doc_count"]} for b in aggs.get("by_tipo", {}).get("buckets", [])],
                "ativo_tipo": [{"key": b["key"], "count": b["doc_count"]} for b in aggs.get("by_ativo_tipo", {}).get("buckets", [])],
                "tribunal_comarca": [{"key": b["key"], "count": b["doc_count"]} for b in aggs.get("by_comarca", {}).get("buckets", [])],
                "tribunal": [{"key": b["key"], "count": b["doc_count"]} for b in aggs.get("by_tribunal", {}).get("buckets", [])],
                "especie": [{"key": b["key"], "count": b["doc_count"]} for b in aggs.get("by_especie", {}).get("buckets", [])],
                "localizacao": [{"key": b["key"], "count": b["doc_count"]} for b in aggs.get("by_localizacao", {}).get("buckets", [])],
                "area_negocio": [{"key": b["key"], "count": b["doc_count"]} for b in aggs.get("by_area_negocio", {}).get("buckets", [])],
                "ano": [{"key": b.get("key_as_string"), "count": b["doc_count"]} for b in aggs.get("by_ano", {}).get("buckets", [])],
                "mes": [{"key": b.get("key_as_string"), "count": b["doc_count"]} for b in aggs.get("by_mes", {}).get("buckets", [])],
                "valor": aggs.get("valores", {}),
            },
        }
    except Exception as exc:
        return {"error": str(exc), "items": [], "total": 0}


def massa_insolvente_status(es: Optional[Elasticsearch] = None) -> Dict[str, Any]:
    """Volumetria do índice da massa insolvente."""
    client = es or get_es_client()
    if not client:
        return {"error": "Elasticsearch indisponível"}

    ensure_indices(client)
    try:
        count_resp = client.count(index=MASSA_INSOLVENTE_INDEX)
        total = count_resp.get("count", 0)
    except Exception as exc:
        return {"error": str(exc)}

    aggs_body = {
        "size": 0,
        "aggs": {
            "min_data": {"min": {"field": "data_atualizacao"}},
            "max_data": {"max": {"field": "data_atualizacao"}},
            "insolventes": {"cardinality": {"field": "insolvente.keyword", "precision_threshold": 40000}},
            "processos": {"cardinality": {"field": "processo.keyword", "precision_threshold": 40000}},
            "comarcas": {"cardinality": {"field": "tribunal_comarca"}},
            "by_tipo": {"terms": {"field": "tipo", "size": 10}},
            "by_ativo_tipo": {"terms": {"field": "ativo_tipos", "size": 15}},
            "by_comarca": {"terms": {"field": "tribunal_comarca", "size": 15}},
            "by_especie": {"terms": {"field": "especie.keyword", "size": 15}},
            "valores": {"stats": {"field": "valor_avaliacao"}},
        },
    }
    try:
        aggs_resp = client.search(index=MASSA_INSOLVENTE_INDEX, body=aggs_body)
        aggs = aggs_resp.get("aggregations", {})
        return {
            "index": MASSA_INSOLVENTE_INDEX,
            "documents": total,
            "insolventes": aggs.get("insolventes", {}).get("value", 0),
            "processos": aggs.get("processos", {}).get("value", 0),
            "comarcas": aggs.get("comarcas", {}).get("value", 0),
            "min_date": aggs.get("min_data", {}).get("value_as_string"),
            "max_date": aggs.get("max_data", {}).get("value_as_string"),
            "valor_stats": aggs.get("valores", {}),
            "by_tipo": [{"key": b["key"], "count": b["doc_count"]} for b in aggs.get("by_tipo", {}).get("buckets", [])],
            "by_ativo_tipo": [{"key": b["key"], "count": b["doc_count"]} for b in aggs.get("by_ativo_tipo", {}).get("buckets", [])],
            "by_comarca": [{"key": b["key"], "count": b["doc_count"]} for b in aggs.get("by_comarca", {}).get("buckets", [])],
            "by_especie": [{"key": b["key"], "count": b["doc_count"]} for b in aggs.get("by_especie", {}).get("buckets", [])],
        }
    except Exception as exc:
        return {"error": str(exc), "index": MASSA_INSOLVENTE_INDEX, "documents": total}


def massa_insolvente_runs_summary(run_ids: List[str], es: Optional[Elasticsearch] = None) -> Dict[str, int]:
    """Contagem de documentos por ``run_id`` no índice."""
    client = es or get_es_client()
    if not client or not run_ids:
        return {}
    try:
        resp = client.search(
            index=MASSA_INSOLVENTE_INDEX,
            body={
                "size": 0,
                "query": {"terms": {"run_id": run_ids}},
                "aggs": {"por_run": {"terms": {"field": "run_id", "size": len(run_ids)}}},
            },
        )
        return {b["key"]: b["doc_count"] for b in resp.get("aggregations", {}).get("por_run", {}).get("buckets", [])}
    except Exception:
        return {}
