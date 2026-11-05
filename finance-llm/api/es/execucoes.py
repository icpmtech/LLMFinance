"""Lista Pública de Execuções (CITIUS).

Módulo do pacote :mod:`api.es` — ver `api/elasticsearch_client.py`,
que continua a expor a API pública (os serviços importam de lá).
"""
import logging
from datetime import datetime
from typing import Any, Dict, List, Optional

from elasticsearch import Elasticsearch

from api.es.core import get_es_client
from api.es.entidades import _bulk_index_docs
from api.es.indices import EXECUCOES_INDEX
from api.es.mappings import ensure_indices

logger = logging.getLogger(__name__)


# --- Lista Pública de Execuções ---------------------------------------------

def execucoes_existing_ids(
    pub_ids: List[str],
    es: Optional[Elasticsearch] = None,
) -> Dict[str, Any]:
    """Devolve quais dos ``pub_ids`` já existem no índice."""
    client = es or get_es_client()
    if not client or not pub_ids:
        return {"found": [], "known": 0, "checked": 0, "index": EXECUCOES_INDEX}

    unique = list(dict.fromkeys(str(item) for item in pub_ids if item))
    found: List[str] = []
    chunk_size = 5000
    try:
        ensure_indices(client)
        for start in range(0, len(unique), chunk_size):
            chunk = unique[start : start + chunk_size]
            resp = client.search(
                index=EXECUCOES_INDEX,
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
        return {
            "error": str(exc),
            "found": [],
            "known": 0,
            "checked": len(unique),
            "index": EXECUCOES_INDEX,
        }

    return {"found": found, "known": len(found), "checked": len(unique), "index": EXECUCOES_INDEX}


def index_execucoes_items(
    items: List[Dict[str, Any]],
    run_id: Optional[str] = None,
    skip_existing: bool = True,
    es: Optional[Elasticsearch] = None,
) -> Dict[str, Any]:
    """Indexa registos da Lista Pública de Execuções no índice ``EXECUCOES_INDEX``."""
    client = es or get_es_client()
    if not client:
        return {"error": "Elasticsearch indisponível", "indexed_count": 0, "total": 0}

    preparados: List[Dict[str, Any]] = []
    for item in items:
        doc = {k: v for k, v in item.items() if not k.startswith("_") and v is not None}
        if not doc.get("pub_id"):
            continue
        doc["source"] = doc.get("source") or "citius_execucoes"
        if run_id:
            doc["run_id"] = run_id
        preparados.append(doc)

    ignorados: List[str] = []
    if skip_existing and preparados:
        existentes = execucoes_existing_ids([str(d["pub_id"]) for d in preparados], es=client)
        ja_no_indice = set(existentes.get("found") or [])
        ignorados = [str(d["pub_id"]) for d in preparados if str(d["pub_id"]) in ja_no_indice]
        preparados = [d for d in preparados if str(d["pub_id"]) not in ja_no_indice]
        if existentes.get("error"):
            logger.warning("Não foi possível verificar duplicados das execuções: %s", existentes["error"])

    now = datetime.utcnow().isoformat()
    docs = [{**doc, "ingested_at": now} for doc in preparados]
    result = _bulk_index_docs(EXECUCOES_INDEX, docs, id_field="pub_id", es=client)
    result["received"] = len(items)
    result["indexed_count"] = result.get("indexed_count", 0)
    result["skipped_existing"] = len(ignorados)
    result["candidates"] = len(preparados)
    return result


def _execucoes_query(
    *,
    q: Optional[str] = None,
    nome_executado: Optional[str] = None,
    numero_processo: Optional[str] = None,
    tribunal: Optional[str] = None,
    comarca: Optional[str] = None,
    unidade_organica: Optional[str] = None,
    agente_execucao: Optional[str] = None,
    estado: Optional[str] = None,
    data_from: Optional[str] = None,
    data_to: Optional[str] = None,
    valor_min: Optional[float] = None,
    valor_max: Optional[float] = None,
) -> Dict[str, Any]:
    """Constrói a query de pesquisa do índice de execuções."""
    must: List[Dict[str, Any]] = []
    filters: List[Dict[str, Any]] = []

    if q:
        must.append(
            {
                "bool": {
                    "should": [
                        {"match": {"nome_executado": q}},
                        {"match": {"numero_processo": q}},
                        {"match": {"extra.tribunal": q}},
                        {"match": {"extra.comarca": q}},
                        {"match": {"extra.unidade_organica": q}},
                        {"match": {"extra.agente_execucao": q}},
                        {"match": {"extra.estado": q}},
                    ]
                }
            }
        )
    if nome_executado:
        must.append({"match": {"nome_executado": nome_executado}})
    if numero_processo:
        filters.append({"wildcard": {"numero_processo": f"*{numero_processo}*"}})
    if tribunal:
        filters.append({"match": {"extra.tribunal": tribunal}})
    if comarca:
        filters.append({"term": {"extra.comarca": comarca}})
    if unidade_organica:
        filters.append({"match": {"extra.unidade_organica": unidade_organica}})
    if agente_execucao:
        filters.append({"match": {"extra.agente_execucao": agente_execucao}})
    if estado:
        filters.append({"term": {"extra.estado": estado}})
    if data_from or data_to:
        date_filter: Dict[str, Any] = {}
        if data_from:
            date_filter["gte"] = data_from
        if data_to:
            date_filter["lte"] = data_to
        filters.append({"range": {"data_entrada": date_filter}})
    if valor_min is not None or valor_max is not None:
        valor_filter: Dict[str, Any] = {}
        if valor_min is not None:
            valor_filter["gte"] = valor_min
        if valor_max is not None:
            valor_filter["lte"] = valor_max
        filters.append({"range": {"extra.valor_execucao": valor_filter}})

    query: Dict[str, Any] = {"match_all": {}}
    if must or filters:
        query = {"bool": {}}
        if must:
            query["bool"]["must"] = must
        if filters:
            query["bool"]["filter"] = filters
    return query


def search_execucoes(
    q: Optional[str] = None,
    nome_executado: Optional[str] = None,
    numero_processo: Optional[str] = None,
    tribunal: Optional[str] = None,
    comarca: Optional[str] = None,
    unidade_organica: Optional[str] = None,
    agente_execucao: Optional[str] = None,
    estado: Optional[str] = None,
    data_from: Optional[str] = None,
    data_to: Optional[str] = None,
    valor_min: Optional[float] = None,
    valor_max: Optional[float] = None,
    size: int = 20,
    from_: int = 0,
    es: Optional[Elasticsearch] = None,
) -> Dict[str, Any]:
    """Pesquisa registos da Lista Pública de Execuções já indexados."""
    client = es or get_es_client()
    if not client:
        return {"error": "Elasticsearch indisponível", "items": [], "total": 0}

    ensure_indices(client)

    query = _execucoes_query(
        q=q,
        nome_executado=nome_executado,
        numero_processo=numero_processo,
        tribunal=tribunal,
        comarca=comarca,
        unidade_organica=unidade_organica,
        agente_execucao=agente_execucao,
        estado=estado,
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
        "sort": [{"data_entrada": {"order": "desc", "missing": "_last"}}, "_score"],
        "aggs": {
            "by_estado": {"terms": {"field": "extra.estado", "size": 15}},
            "by_comarca": {"terms": {"field": "extra.comarca", "size": 25}},
            "by_tribunal": {"terms": {"field": "extra.tribunal.keyword", "size": 25}},
            "by_agente": {"terms": {"field": "extra.agente_execucao.keyword", "size": 25}},
            "valor_total": {"sum": {"field": "extra.valor_execucao"}},
            "valor_medio": {"avg": {"field": "extra.valor_execucao"}},
            "valor_maximo": {"max": {"field": "extra.valor_execucao"}},
            "by_ano": {
                "date_histogram": {"field": "data_entrada", "calendar_interval": "year", "format": "yyyy"}
            },
            "by_mes": {
                "date_histogram": {"field": "data_entrada", "calendar_interval": "month", "format": "yyyy-MM"}
            },
        },
    }

    try:
        resp = client.search(index=EXECUCOES_INDEX, body=body)
        aggs = resp.get("aggregations", {})

        def _buckets(name: str) -> List[Dict[str, Any]]:
            return [
                {"key": b["key"], "count": b["doc_count"]}
                for b in aggs.get(name, {}).get("buckets", [])
            ]

        items: List[Dict[str, Any]] = []
        for hit in resp["hits"]["hits"]:
            source = dict(hit["_source"])
            source["doc_id"] = hit["_id"]
            items.append(source)

        total = resp["hits"]["total"]
        total_value = total["value"] if isinstance(total, dict) else total
        return {
            "query": q,
            "total": total_value,
            "items": items,
            "from": from_,
            "size": size,
            "valor_total": round(float(aggs.get("valor_total", {}).get("value") or 0.0), 2),
            "valor_medio": (
                round(float(aggs["valor_medio"]["value"]), 2)
                if isinstance(aggs.get("valor_medio", {}).get("value"), (int, float))
                else None
            ),
            "valor_maximo": round(float(aggs.get("valor_maximo", {}).get("value") or 0.0), 2) or None,
            "facets": {
                "estado": _buckets("by_estado"),
                "comarca": _buckets("by_comarca"),
                "tribunal": _buckets("by_tribunal"),
                "agente_execucao": _buckets("by_agente"),
                "ano": [
                    {"key": b.get("key_as_string"), "count": b["doc_count"]}
                    for b in aggs.get("by_ano", {}).get("buckets", [])
                ],
                "mes": [
                    {"key": b.get("key_as_string"), "count": b["doc_count"]}
                    for b in aggs.get("by_mes", {}).get("buckets", [])
                ],
            },
        }
    except Exception as exc:
        return {"error": str(exc), "items": [], "total": 0}


def execucoes_status(es: Optional[Elasticsearch] = None) -> Dict[str, Any]:
    """Volumetria do índice da Lista Pública de Execuções."""
    client = es or get_es_client()
    if not client:
        return {"error": "Elasticsearch indisponível"}
    ensure_indices(client)
    try:
        count = client.count(index=EXECUCOES_INDEX).get("count", 0)
        out: Dict[str, Any] = {"index": EXECUCOES_INDEX, "documents": count}
        if not count:
            return out

        resp = client.search(
            index=EXECUCOES_INDEX,
            body={
                "size": 0,
                "aggs": {
                    "min_date": {"min": {"field": "data_entrada", "format": "yyyy-MM-dd"}},
                    "max_date": {"max": {"field": "data_entrada", "format": "yyyy-MM-dd"}},
                    "valor_total": {"sum": {"field": "extra.valor_execucao"}},
                    "valor_medio": {"avg": {"field": "extra.valor_execucao"}},
                    "valor_maximo": {"max": {"field": "extra.valor_execucao"}},
                    "by_estado": {"terms": {"field": "extra.estado.keyword", "size": 15}},
                    "by_comarca": {"terms": {"field": "extra.comarca.keyword", "size": 25}},
                    "by_tribunal": {"terms": {"field": "extra.tribunal.keyword", "size": 25}},
                    "by_agente": {"terms": {"field": "extra.agente_execucao.keyword", "size": 25}},
                },
            },
        )
        aggs = resp.get("aggregations", {})

        def _buckets(name: str) -> List[Dict[str, Any]]:
            return [
                {"key": b["key"], "count": b["doc_count"]}
                for b in aggs.get(name, {}).get("buckets", [])
            ]

        out["min_date"] = (aggs.get("min_date", {}) or {}).get("value_as_string")
        out["max_date"] = (aggs.get("max_date", {}) or {}).get("value_as_string")
        out["valor_total"] = round(float(aggs.get("valor_total", {}).get("value") or 0.0), 2)
        out["valor_medio"] = (
            round(float(aggs["valor_medio"]["value"]), 2)
            if isinstance(aggs.get("valor_medio", {}).get("value"), (int, float))
            else None
        )
        out["valor_maximo"] = round(float(aggs.get("valor_maximo", {}).get("value") or 0.0), 2) or None
        out["by_estado"] = _buckets("by_estado")
        out["by_comarca"] = _buckets("by_comarca")
        out["by_tribunal"] = _buckets("by_tribunal")
        out["by_agente"] = _buckets("by_agente")
        return out
    except Exception as exc:
        return {"error": str(exc)}


def get_execucao(pub_id: str, es: Optional[Elasticsearch] = None) -> Dict[str, Any]:
    """Devolve um registo pelo ``pub_id``."""
    client = es or get_es_client()
    if not client:
        return {"error": "Elasticsearch indisponível"}
    ensure_indices(client)
    try:
        resp = client.get(index=EXECUCOES_INDEX, id=pub_id)
        source = dict(resp.get("_source") or {})
        source["doc_id"] = resp.get("_id")
        return source
    except Exception as exc:
        return {"error": str(exc)}


def delete_execucoes_run(run_id: str, es: Optional[Elasticsearch] = None) -> Dict[str, Any]:
    """Remove do índice todos os registos de uma recolha (``run_id``)."""
    client = es or get_es_client()
    if not client:
        return {"error": "Elasticsearch indisponível"}
    ensure_indices(client)
    try:
        resp = client.delete_by_query(
            index=EXECUCOES_INDEX,
            body={"query": {"term": {"run_id": run_id}}},
            refresh=True,
            conflicts="proceed",
        )
        return {"run_id": run_id, "deleted": resp.get("deleted", 0)}
    except Exception as exc:
        return {"run_id": run_id, "error": str(exc)}


def execucoes_runs_summary(run_ids: List[str], es: Optional[Elasticsearch] = None) -> Dict[str, int]:
    """Número de documentos indexados por ``run_id``."""
    client = es or get_es_client()
    if not client or not run_ids:
        return {}
    try:
        resp = client.search(
            index=EXECUCOES_INDEX,
            body={
                "size": 0,
                "query": {"terms": {"run_id": run_ids}},
                "aggs": {"by_run": {"terms": {"field": "run_id", "size": len(run_ids)}}},
            },
        )
        return {
            b["key"]: b["doc_count"]
            for b in resp.get("aggregations", {}).get("by_run", {}).get("buckets", [])
        }
    except Exception:
        return {}
