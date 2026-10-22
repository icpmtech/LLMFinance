"""Vendas de bens penhorados em processos executivos (CITIUS + e-leilões).

Módulo do pacote :mod:`api.es` — ver `api/elasticsearch_client.py`,
que continua a expor a API pública (os coletores/serviços importam de lá).
"""
import logging
from datetime import datetime
from typing import Any, Dict, List, Optional

from elasticsearch import Elasticsearch
from api.es.core import get_es_client
from api.es.entidades import _bulk_index_docs
from api.es.indices import VENDAS_PENHORADOS_INDEX
from api.es.mappings import ensure_indices

logger = logging.getLogger(__name__)


# --- Vendas penhoradas -------------------------------------------------------

def vendas_penhorados_existing_ids(
    venda_ids: List[str],
    es: Optional[Elasticsearch] = None,
) -> Dict[str, Any]:
    """Devolve quais dos ``venda_ids`` já existem no índice."""
    client = es or get_es_client()
    if not client or not venda_ids:
        return {"found": [], "known": 0, "checked": 0, "index": VENDAS_PENHORADOS_INDEX}

    unique = list(dict.fromkeys(str(item) for item in venda_ids if item))
    found: List[str] = []
    chunk_size = 5000
    try:
        ensure_indices(client)
        for start in range(0, len(unique), chunk_size):
            chunk = unique[start:start + chunk_size]
            resp = client.search(
                index=VENDAS_PENHORADOS_INDEX,
                body={
                    "size": len(chunk),
                    "track_total_hits": False,
                    "_source": ["venda_id"],
                    "query": {"terms": {"venda_id": chunk}},
                },
            )
            for hit in resp.get("hits", {}).get("hits", []):
                valor = (hit.get("_source") or {}).get("venda_id")
                if not valor:
                    valor = str(hit.get("_id", "")).split(":", 1)[-1]
                found.append(str(valor))
    except Exception as exc:
        return {
            "error": str(exc), "found": [], "known": 0,
            "checked": len(unique), "index": VENDAS_PENHORADOS_INDEX,
        }

    return {"found": found, "known": len(found), "checked": len(unique), "index": VENDAS_PENHORADOS_INDEX}


def index_vendas_penhorados_items(
    items: List[Dict[str, Any]],
    run_id: Optional[str] = None,
    skip_existing: bool = True,
    es: Optional[Elasticsearch] = None,
) -> Dict[str, Any]:
    """Indexa vendas de bens penhorados no índice ``VENDAS_PENHORADOS_INDEX``."""
    client = es or get_es_client()
    if not client:
        return {"error": "Elasticsearch indisponível", "indexed_count": 0, "total": 0}

    preparados: List[Dict[str, Any]] = []
    for item in items:
        doc = {k: v for k, v in item.items() if not k.startswith("_") and v is not None}
        if not doc.get("venda_id"):
            continue
        doc["source"] = doc.get("source") or "vendas_penhorados"
        if run_id:
            doc["run_id"] = run_id
        preparados.append(doc)

    ignorados: List[str] = []
    if skip_existing and preparados:
        existentes = vendas_penhorados_existing_ids(
            [str(d["venda_id"]) for d in preparados], es=client,
        )
        ja_no_indice = set(existentes.get("found") or [])
        ignorados = [str(d["venda_id"]) for d in preparados if str(d["venda_id"]) in ja_no_indice]
        preparados = [d for d in preparados if str(d["venda_id"]) not in ja_no_indice]
        if existentes.get("error"):
            logger.warning("Não foi possível verificar duplicados das vendas: %s", existentes["error"])

    now = datetime.utcnow().isoformat()
    docs = [{**doc, "ingested_at": now} for doc in preparados]
    result = _bulk_index_docs(VENDAS_PENHORADOS_INDEX, docs, id_field="venda_id", es=client)
    result["received"] = len(items)
    result["indexed_count"] = result.get("indexed_count", 0)
    result["skipped_existing"] = len(ignorados)
    result["candidates"] = len(preparados)
    return result


def _vendas_penhorados_query(
    *,
    q: Optional[str] = None,
    fonte: Optional[str] = None,
    referencia: Optional[str] = None,
    processo: Optional[str] = None,
    tribunal: Optional[str] = None,
    tribunal_comarca: Optional[str] = None,
    comarca_judicial: Optional[str] = None,
    tipo_bem: Optional[str] = None,
    modalidade: Optional[str] = None,
    estado: Optional[str] = None,
    distrito: Optional[str] = None,
    concelho: Optional[str] = None,
    morada: Optional[str] = None,
    nome: Optional[str] = None,
    nif: Optional[str] = None,
    data_from: Optional[str] = None,
    data_to: Optional[str] = None,
    valor_min: Optional[float] = None,
    valor_max: Optional[float] = None,
) -> Dict[str, Any]:
    """Constrói a query de pesquisa do índice de vendas penhoradas."""
    must: List[Dict[str, Any]] = []
    filters: List[Dict[str, Any]] = []

    if q:
        must.append(
            {
                "bool": {
                    "should": [
                        {
                            "multi_match": {
                                "query": q,
                                "fields": [
                                    "titulo^3",
                                    "descricao",
                                    "referencia^2",
                                    "processo^2",
                                    "processo_numero^2",
                                    "tribunal^2",
                                    "morada",
                                    "tipo_bem",
                                    "subtipo_bem",
                                    "modalidade",
                                ],
                                "operator": "and",
                            }
                        },
                        {
                            "nested": {
                                "path": "intervenientes",
                                "query": {
                                    "match": {"intervenientes.nome": {"query": q, "operator": "and"}}
                                },
                            }
                        },
                        {
                            "nested": {
                                "path": "executados",
                                "query": {
                                    "match": {"executados.nome": {"query": q, "operator": "and"}}
                                },
                            }
                        },
                    ],
                    "minimum_should_match": 1,
                }
            }
        )
    if nome:
        filters.append(
            {
                "bool": {
                    "should": [
                        {"nested": {"path": "intervenientes", "query": {"match": {"intervenientes.nome": nome}}}},
                        {"nested": {"path": "executados", "query": {"match": {"executados.nome": nome}}}},
                    ],
                    "minimum_should_match": 1,
                }
            }
        )
    if nif:
        filters.append(
            {
                "bool": {
                    "should": [
                        {"nested": {"path": "intervenientes", "query": {"term": {"intervenientes.nif": str(nif)}}}},
                        {"nested": {"path": "executados", "query": {"term": {"executados.nif": str(nif)}}}},
                    ],
                    "minimum_should_match": 1,
                }
            }
        )
    if fonte:
        filters.append({"term": {"fonte": str(fonte).strip().lower()}})
    if referencia:
        filters.append({"term": {"referencia": str(referencia)}})
    if processo:
        filters.append({"match": {"processo": processo}})
    if tribunal:
        filters.append({"match": {"tribunal": tribunal}})
    if tribunal_comarca:
        filters.append({"term": {"tribunal_comarca": tribunal_comarca}})
    if comarca_judicial:
        filters.append({"term": {"comarca_judicial": comarca_judicial}})
    if tipo_bem:
        filters.append({"term": {"tipo_bem": tipo_bem}})
    if modalidade:
        filters.append({"term": {"modalidade": modalidade}})
    if estado:
        filters.append({"term": {"estado": estado}})
    if distrito:
        filters.append({"term": {"distrito": distrito}})
    if concelho:
        filters.append({"term": {"concelho": concelho}})
    if morada:
        filters.append({"match": {"morada": morada}})
    if data_from or data_to:
        interval: Dict[str, str] = {}
        if data_from:
            interval["gte"] = data_from
        if data_to:
            interval["lte"] = data_to
        filters.append({"range": {"data_venda": interval}})
    if valor_min is not None or valor_max is not None:
        interval_val: Dict[str, Any] = {}
        if valor_min is not None:
            interval_val["gte"] = valor_min
        if valor_max is not None:
            interval_val["lte"] = valor_max
        filters.append({"range": {"valor_base": interval_val}})

    if must or filters:
        query: Dict[str, Any] = {"bool": {}}
        if must:
            query["bool"]["must"] = must
        if filters:
            query["bool"]["filter"] = filters
        return query
    return {"match_all": {}}


def search_vendas_penhorados(
    q: Optional[str] = None,
    fonte: Optional[str] = None,
    referencia: Optional[str] = None,
    processo: Optional[str] = None,
    tribunal: Optional[str] = None,
    tribunal_comarca: Optional[str] = None,
    comarca_judicial: Optional[str] = None,
    tipo_bem: Optional[str] = None,
    modalidade: Optional[str] = None,
    estado: Optional[str] = None,
    distrito: Optional[str] = None,
    concelho: Optional[str] = None,
    morada: Optional[str] = None,
    nome: Optional[str] = None,
    nif: Optional[str] = None,
    data_from: Optional[str] = None,
    data_to: Optional[str] = None,
    valor_min: Optional[float] = None,
    valor_max: Optional[float] = None,
    size: int = 20,
    from_: int = 0,
    search_after: Optional[List[Any]] = None,
    scan: bool = False,
    es: Optional[Elasticsearch] = None,
) -> Dict[str, Any]:
    """Pesquisa vendas de bens penhorados já indexadas."""
    client = es or get_es_client()
    if not client:
        return {"error": "Elasticsearch indisponível", "items": [], "total": 0}

    ensure_indices(client)

    query = _vendas_penhorados_query(
        q=q,
        fonte=fonte,
        referencia=referencia,
        processo=processo,
        tribunal=tribunal,
        tribunal_comarca=tribunal_comarca,
        comarca_judicial=comarca_judicial,
        tipo_bem=tipo_bem,
        modalidade=modalidade,
        estado=estado,
        distrito=distrito,
        concelho=concelho,
        morada=morada,
        nome=nome,
        nif=nif,
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
        "sort": [{"data_venda": {"order": "desc", "missing": "_last"}}, "_score"],
        "aggs": {
            "by_fonte": {"terms": {"field": "fonte", "size": 10}},
            "by_tipo_bem": {"terms": {"field": "tipo_bem", "size": 25}},
            "by_modalidade": {"terms": {"field": "modalidade", "size": 15}},
            "by_estado": {"terms": {"field": "estado", "size": 15}},
            "by_distrito": {"terms": {"field": "distrito", "size": 25}},
            "by_concelho": {"terms": {"field": "concelho", "size": 25}},
            "by_tribunal": {"terms": {"field": "tribunal.keyword", "size": 25}},
            "valor_total": {"sum": {"field": "valor_base"}},
            "valor_medio": {"avg": {"field": "valor_base"}},
            "valor_maximo": {"max": {"field": "valor_base"}},
            "by_data_venda": {
                "date_histogram": {"field": "data_venda", "calendar_interval": "month", "format": "yyyy-MM"}
            },
        },
    }

    if scan or search_after:
        body["sort"] = [
            {"data_venda": {"order": "desc", "missing": "_last"}},
            {"venda_id": {"order": "asc"}},
        ]
        body["size"] = max(1, min(size, 1000))
        body.pop("from", None)
        body.pop("aggs", None)
        if search_after:
            body["search_after"] = list(search_after)

    try:
        resp = client.search(index=VENDAS_PENHORADOS_INDEX, body=body)
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
        result: Dict[str, Any] = {
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
                "fonte": _buckets("by_fonte"),
                "tipo_bem": _buckets("by_tipo_bem"),
                "modalidade": _buckets("by_modalidade"),
                "estado": _buckets("by_estado"),
                "distrito": _buckets("by_distrito"),
                "concelho": _buckets("by_concelho"),
                "tribunal": _buckets("by_tribunal"),
                "data_venda": [
                    {"key": b.get("key_as_string"), "count": b["doc_count"]}
                    for b in aggs.get("by_data_venda", {}).get("buckets", [])
                ],
            },
        }
        if scan or search_after:
            result["next"] = (
                [hit["sort"] for hit in resp["hits"]["hits"]][-1]
                if resp["hits"]["hits"]
                else None
            )
        return result
    except Exception as exc:
        return {"error": str(exc), "items": [], "total": 0}


def vendas_penhorados_status(es: Optional[Elasticsearch] = None) -> Dict[str, Any]:
    """Volumetria do índice de vendas penhoradas."""
    client = es or get_es_client()
    if not client:
        return {"error": "Elasticsearch indisponível"}
    ensure_indices(client)
    try:
        count = client.count(index=VENDAS_PENHORADOS_INDEX).get("count", 0)
        out: Dict[str, Any] = {"index": VENDAS_PENHORADOS_INDEX, "documents": count}
        if not count:
            return out

        resp = client.search(
            index=VENDAS_PENHORADOS_INDEX,
            body={
                "size": 0,
                "aggs": {
                    "min_date": {"min": {"field": "data_venda", "format": "yyyy-MM-dd"}},
                    "max_date": {"max": {"field": "data_venda", "format": "yyyy-MM-dd"}},
                    "valor_total": {"sum": {"field": "valor_base"}},
                    "valor_medio": {"avg": {"field": "valor_base"}},
                    "valor_maximo": {"max": {"field": "valor_base"}},
                    "by_fonte": {"terms": {"field": "fonte", "size": 10}},
                    "by_tipo_bem": {"terms": {"field": "tipo_bem", "size": 25}},
                    "by_modalidade": {"terms": {"field": "modalidade", "size": 15}},
                    "by_estado": {"terms": {"field": "estado", "size": 15}},
                    "by_distrito": {"terms": {"field": "distrito", "size": 25}},
                    "by_concelho": {"terms": {"field": "concelho", "size": 25}},
                    "by_tribunal": {"terms": {"field": "tribunal.keyword", "size": 25}},
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
        out["by_fonte"] = _buckets("by_fonte")
        out["by_tipo_bem"] = _buckets("by_tipo_bem")
        out["by_modalidade"] = _buckets("by_modalidade")
        out["by_estado"] = _buckets("by_estado")
        out["by_distrito"] = _buckets("by_distrito")
        out["by_concelho"] = _buckets("by_concelho")
        out["by_tribunal"] = _buckets("by_tribunal")
        return out
    except Exception as exc:
        return {"error": str(exc)}


def get_venda_penhorada(venda_id: str, es: Optional[Elasticsearch] = None) -> Dict[str, Any]:
    """Devolve uma venda pelo ``venda_id``."""
    client = es or get_es_client()
    if not client:
        return {"error": "Elasticsearch indisponível"}
    try:
        resp = client.get(index=VENDAS_PENHORADOS_INDEX, id=f"{VENDAS_PENHORADOS_INDEX}:{venda_id}")
    except Exception as exc:
        return {"venda_id": venda_id, "error": str(exc)}
    source = dict(resp.get("_source") or {})
    source["doc_id"] = resp.get("_id")
    return source


def delete_vendas_penhorados_run(run_id: str, es: Optional[Elasticsearch] = None) -> Dict[str, Any]:
    """Remove do índice todas as vendas de uma recolha (``run_id``)."""
    client = es or get_es_client()
    if not client:
        return {"error": "Elasticsearch indisponível"}
    ensure_indices(client)
    try:
        resp = client.delete_by_query(
            index=VENDAS_PENHORADOS_INDEX,
            body={"query": {"term": {"run_id": run_id}}},
            refresh=True,
            conflicts="proceed",
        )
        return {"run_id": run_id, "deleted": resp.get("deleted", 0)}
    except Exception as exc:
        return {"run_id": run_id, "error": str(exc)}


def vendas_penhorados_runs_summary(run_ids: List[str], es: Optional[Elasticsearch] = None) -> Dict[str, int]:
    """Número de documentos indexados por ``run_id``."""
    client = es or get_es_client()
    if not client or not run_ids:
        return {}
    try:
        resp = client.search(
            index=VENDAS_PENHORADOS_INDEX,
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
