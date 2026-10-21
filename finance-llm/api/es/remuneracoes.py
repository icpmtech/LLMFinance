"""Remunerações de titulares, territórios e administração pública.

Módulo do pacote :mod:`api.es` — ver `api/elasticsearch_client.py`,
que continua a expor a API pública (os coletores/serviços importam de lá).
"""
import logging
from datetime import datetime
from typing import Any, Dict, Iterable, List, Optional

from elasticsearch import Elasticsearch
from elasticsearch.helpers import bulk
from api.es.core import get_es_client
from api.es.indices import REMUNERACOES_AP_INDEX, REMUNERACOES_INDEX, REMUNERACOES_PESSOAS_INDEX, REMUNERACOES_TERRITORIOS_INDEX
from api.es.mappings import ensure_indices

logger = logging.getLogger(__name__)




# ---------------------------------------------------------------------------
# Abonos dos eleitos locais (remunerações)
# ---------------------------------------------------------------------------

def index_remuneracoes_bulk(
    items: Iterable[Dict[str, Any]],
    es: Optional[Elasticsearch] = None,
) -> Dict[str, Any]:
    """Indexa as linhas da tabela de abonos no índice `finance_remuneracoes`.

    Cada item deve ter `doc_id`, `ano`, `nivel`, `regime`, `grupo`, `cargo` e a
    lista `valores` (por escalão de eleitores).
    """
    client = es or get_es_client()
    if not client:
        return {"error": "Elasticsearch indisponível", "indexed": 0}
    ensure_indices(client)
    actions = []
    now = datetime.utcnow().isoformat()
    for doc in items:
        if not doc.get("doc_id"):
            continue
        source = dict(doc)
        source.setdefault("ingested_at", now)
        source.setdefault("updated_at", now)
        valorados = [v["valor"] for v in (source.get("valores") or []) if v.get("valor") is not None]
        source["valor_minimo"] = min(valorados) if valorados else None
        source["valor_maximo"] = max(valorados) if valorados else None
        actions.append({
            "_op_type": "index",
            "_index": REMUNERACOES_INDEX,
            "_id": source["doc_id"],
            **source,
        })
    if not actions:
        return {"indexed": 0}
    try:
        indexed, errors = bulk(client, actions, raise_on_error=False)
        client.indices.refresh(index=REMUNERACOES_INDEX)
        return {"indexed": indexed, "errors": len(errors) if errors else 0}
    except Exception as exc:
        return {"error": str(exc), "indexed": 0}




def search_remuneracoes(
    ano: Optional[int] = None,
    nivel: Optional[str] = None,
    regime: Optional[str] = None,
    q: Optional[str] = None,
    size: int = 200,
    es: Optional[Elasticsearch] = None,
) -> Dict[str, Any]:
    """Pesquisa linhas da tabela de abonos (todas as que existirem, por omissão)."""
    client = es or get_es_client()
    if not client:
        return {"error": "Elasticsearch indisponível", "items": [], "total": 0}
    ensure_indices(client)

    filters: List[Dict[str, Any]] = []
    if ano:
        filters.append({"term": {"ano": int(ano)}})
    if nivel:
        filters.append({"term": {"nivel": nivel}})
    if regime:
        filters.append({"term": {"regime": regime}})

    must: List[Dict[str, Any]] = []
    if q:
        must.append({
            "bool": {
                "should": [
                    {"match_phrase": {"cargo": {"query": q, "boost": 4}}},
                    {"match": {"grupo": {"query": q, "operator": "and", "boost": 2}}},
                    {"match": {"tabela_titulo": {"query": q, "operator": "and"}}},
                ],
                "minimum_should_match": 1,
            }
        })

    bool_query: Dict[str, Any] = {}
    if must:
        bool_query["must"] = must
    if filters:
        bool_query["filter"] = filters
    query = {"bool": bool_query} if bool_query else {"match_all": {}}

    body = {
        "query": query,
        "size": max(1, min(size, 500)),
        "sort": [
            {"ano": {"order": "desc"}},
            {"nivel": {"order": "asc"}},
            {"regime": {"order": "asc"}},
            {"cargo.keyword": {"order": "asc"}},
        ],
        "track_total_hits": True,
    }
    try:
        resp = client.search(index=REMUNERACOES_INDEX, body=body)
        return {
            "total": resp["hits"]["total"]["value"],
            "items": [{**hit["_source"], "doc_id": hit["_id"]} for hit in resp["hits"]["hits"]],
        }
    except Exception as exc:
        return {"error": str(exc), "items": [], "total": 0}




def index_remuneracoes_territorios_bulk(
    items: Iterable[Dict[str, Any]],
    es: Optional[Elasticsearch] = None,
) -> Dict[str, Any]:
    """Indexa os abonos aplicados a cada concelho/freguesia."""
    client = es or get_es_client()
    if not client:
        return {"error": "Elasticsearch indisponível", "indexed": 0}
    ensure_indices(client)
    actions = []
    now = datetime.utcnow().isoformat()
    for doc in items:
        if not doc.get("doc_id"):
            continue
        source = dict(doc)
        source.setdefault("ingested_at", now)
        source.setdefault("updated_at", now)
        actions.append({
            "_op_type": "index",
            "_index": REMUNERACOES_TERRITORIOS_INDEX,
            "_id": source["doc_id"],
            **source,
        })
    if not actions:
        return {"indexed": 0}
    try:
        indexed, errors = bulk(client, actions, raise_on_error=False)
        client.indices.refresh(index=REMUNERACOES_TERRITORIOS_INDEX)
        return {"indexed": indexed, "errors": len(errors) if errors else 0}
    except Exception as exc:
        return {"error": str(exc), "indexed": 0}




def search_remuneracoes_territorios(
    q: Optional[str] = None,
    nivel: Optional[str] = None,
    distrito: Optional[str] = None,
    concelho: Optional[str] = None,
    escalao_id: Optional[str] = None,
    min_eleitores: Optional[int] = None,
    max_eleitores: Optional[int] = None,
    size: int = 500,
    page: int = 1,
    es: Optional[Elasticsearch] = None,
) -> Dict[str, Any]:
    """Pesquisa os abonos por concelho/freguesia (eleitores, escalão e verbas)."""
    client = es or get_es_client()
    if not client:
        return {"error": "Elasticsearch indisponível", "items": [], "total": 0}
    ensure_indices(client)

    filters: List[Dict[str, Any]] = []
    if nivel:
        filters.append({"term": {"nivel": nivel}})
    if escalao_id:
        filters.append({"term": {"escalao_id": escalao_id}})
    if distrito:
        filters.append({"wildcard": {"distrito_keyword": {"value": f"*{distrito}*", "case_insensitive": True}}})
    if concelho:
        filters.append({"wildcard": {"concelho_keyword": {"value": f"*{concelho}*", "case_insensitive": True}}})
    if min_eleitores is not None or max_eleitores is not None:
        rng: Dict[str, Any] = {}
        if min_eleitores is not None:
            rng["gte"] = int(min_eleitores)
        if max_eleitores is not None:
            rng["lte"] = int(max_eleitores)
        filters.append({"range": {"eleitores": rng}})

    must: List[Dict[str, Any]] = []
    if q:
        must.append({
            "bool": {
                "should": [
                    {"match_phrase": {"nome": {"query": q, "boost": 6}}},
                    {"match": {"nome": {"query": q, "operator": "and", "boost": 3}}},
                    {"wildcard": {"concelho_keyword": {"value": f"*{q}*", "case_insensitive": True}}},
                    {"wildcard": {"distrito_keyword": {"value": f"*{q}*", "case_insensitive": True}}},
                ],
                "minimum_should_match": 1,
            }
        })

    bool_query: Dict[str, Any] = {}
    if must:
        bool_query["must"] = must
    if filters:
        bool_query["filter"] = filters
    query = {"bool": bool_query} if bool_query else {"match_all": {}}

    from_ = max(0, (page - 1) * size)
    body = {
        "query": query,
        "from": from_,
        "size": max(1, min(size, 1000)),
        "sort": [
            {"nivel": {"order": "asc"}},
            {"eleitores": {"order": "desc"}},
        ],
        "track_total_hits": True,
    }
    try:
        resp = client.search(index=REMUNERACOES_TERRITORIOS_INDEX, body=body)
        return {
            "total": resp["hits"]["total"]["value"],
            "items": [{**hit["_source"], "doc_id": hit["_id"]} for hit in resp["hits"]["hits"]],
            "page": page,
            "size": size,
        }
    except Exception as exc:
        return {"error": str(exc), "items": [], "total": 0}




def index_remuneracoes_pessoas_bulk(
    items: Iterable[Dict[str, Any]],
    es: Optional[Elasticsearch] = None,
) -> Dict[str, Any]:
    """Indexa as pessoas eleitas (presidente de câmara e vereadores)."""
    client = es or get_es_client()
    if not client:
        return {"error": "Elasticsearch indisponível", "indexed": 0}
    ensure_indices(client)
    actions = []
    now = datetime.utcnow().isoformat()
    for doc in items:
        if not doc.get("doc_id"):
            continue
        source = dict(doc)
        source.setdefault("ingested_at", now)
        source.setdefault("updated_at", now)
        actions.append({
            "_op_type": "index",
            "_index": REMUNERACOES_PESSOAS_INDEX,
            "_id": source["doc_id"],
            **source,
        })
    if not actions:
        return {"indexed": 0}
    try:
        indexed, errors = bulk(client, actions, raise_on_error=False)
        client.indices.refresh(index=REMUNERACOES_PESSOAS_INDEX)
        return {"indexed": indexed, "errors": len(errors) if errors else 0}
    except Exception as exc:
        return {"error": str(exc), "indexed": 0}




def search_remuneracoes_pessoas(
    q: Optional[str] = None,
    distrito: Optional[str] = None,
    concelho: Optional[str] = None,
    cargo: Optional[str] = None,
    sigla: Optional[str] = None,
    min_remuneracao: Optional[float] = None,
    size: int = 100,
    page: int = 1,
    es: Optional[Elasticsearch] = None,
) -> Dict[str, Any]:
    """Pesquisa **pessoas** eleitas: por nome, município, partido ou cargo."""
    client = es or get_es_client()
    if not client:
        return {"error": "Elasticsearch indisponível", "items": [], "total": 0}
    ensure_indices(client)

    filters: List[Dict[str, Any]] = []
    if distrito:
        filters.append({"term": {"distrito": distrito}})
    if concelho:
        filters.append({"wildcard": {"concelho.keyword": {"value": f"*{concelho}*", "case_insensitive": True}}})
    if cargo:
        filters.append({"wildcard": {"cargo": {"value": f"*{cargo}*", "case_insensitive": True}}})
    if sigla:
        filters.append({"wildcard": {"sigla": {"value": f"*{sigla}*", "case_insensitive": True}}})
    if min_remuneracao is not None:
        filters.append({"range": {"remuneracao_mensal": {"gte": min_remuneracao}}})

    must: List[Dict[str, Any]] = []
    if q:
        must.append({
            "multi_match": {
                "query": q,
                "fields": ["nome^3", "concelho^2", "sigla", "cargo", "distrito"],
                "fuzziness": "AUTO",
            }
        })
    body = {
        "query": {"bool": {"must": must or [{"match_all": {}}], "filter": filters}},
        "from": max(0, (page - 1) * size),
        "size": size,
        "sort": [{"remuneracao_mensal": {"order": "desc", "missing": "_last"}}, {"nome.keyword": "asc"}],
    }
    try:
        resp = client.search(index=REMUNERACOES_PESSOAS_INDEX, body=body)
        return {
            "total": resp["hits"]["total"]["value"],
            "items": [{**hit["_source"], "doc_id": hit["_id"]} for hit in resp["hits"]["hits"]],
            "page": page,
            "size": size,
        }
    except Exception as exc:
        return {"error": str(exc), "items": [], "total": 0}




def index_remuneracoes_ap_bulk(
    items: Iterable[Dict[str, Any]],
    es: Optional[Elasticsearch] = None,
) -> Dict[str, Any]:
    """Indexa as linhas do quadro de remunerações da AP.

    Cada item é um nível da TRU, uma posição remuneratória de uma carreira ou um
    cargo dirigente, com o ano e o valor mensal publicado (`tipo` distingue os
    três). O `doc_id` é estável por ano, para uma recolha nova substituir a
    anterior em vez de duplicar.
    """
    client = es or get_es_client()
    if not client:
        return {"error": "Elasticsearch indisponível", "indexed": 0}
    ensure_indices(client)
    actions = []
    now = datetime.utcnow().isoformat()
    for doc in items:
        if not doc.get("doc_id"):
            continue
        source = dict(doc)
        source.setdefault("ingested_at", now)
        source.setdefault("updated_at", now)
        actions.append({
            "_op_type": "index",
            "_index": REMUNERACOES_AP_INDEX,
            "_id": source["doc_id"],
            **source,
        })
    if not actions:
        return {"indexed": 0}
    try:
        indexed, errors = bulk(client, actions, raise_on_error=False)
        client.indices.refresh(index=REMUNERACOES_AP_INDEX)
        return {"indexed": indexed, "errors": len(errors) if errors else 0}
    except Exception as exc:
        return {"error": str(exc), "indexed": 0}




def search_remuneracoes_ap(
    q: Optional[str] = None,
    *,
    ano: Optional[int] = None,
    tipo: Optional[str] = None,
    nivel: Optional[int] = None,
    remuneracao_minima: Optional[float] = None,
    remuneracao_maxima: Optional[float] = None,
    size: int = 40,
    page: int = 1,
    es: Optional[Elasticsearch] = None,
) -> Dict[str, Any]:
    """Pesquisa no quadro de remunerações da AP (por ano, tipo e texto).

    Serve o simulador e a pesquisa da página: «assistente técnico», «chefe de
    divisão», «nível 40» — cada linha traz o valor mensal publicado e a secção
    do quadro de onde saiu.
    """
    client = es or get_es_client()
    if not client:
        return {"error": "Elasticsearch indisponível", "items": [], "total": 0}
    ensure_indices(client)

    must: List[Dict[str, Any]] = []
    filters: List[Dict[str, Any]] = []
    if q:
        must.append({
            "multi_match": {
                "query": str(q).strip(),
                "fields": ["texto^3", "carreira^2", "categoria^2", "cargo^2", "ambito", "seccao"],
                "type": "best_fields",
            }
        })
    if ano:
        filters.append({"term": {"ano": int(ano)}})
    if tipo:
        filters.append({"term": {"tipo": str(tipo)}})
    if nivel:
        filters.append({"term": {"nivel": int(nivel)}})
    if remuneracao_minima is not None:
        filters.append({"range": {"remuneracao": {"gte": float(remuneracao_minima)}}})
    if remuneracao_maxima is not None:
        filters.append({"range": {"remuneracao": {"lte": float(remuneracao_maxima)}}})

    bool_query: Dict[str, Any] = {}
    if must:
        bool_query["must"] = must
    if filters:
        bool_query["filter"] = filters
    query = {"bool": bool_query} if bool_query else {"match_all": {}}

    body = {
        "query": query,
        "from": max(0, (max(1, page) - 1) * max(1, size)),
        "size": max(1, min(size, 500)),
        "sort": [{"remuneracao": {"order": "desc", "missing": "_last"}}, {"ano": {"order": "desc"}}],
        "track_total_hits": True,
    }
    try:
        resp = client.search(index=REMUNERACOES_AP_INDEX, body=body)
        return {
            "total": resp["hits"]["total"]["value"],
            "items": [{**hit["_source"], "doc_id": hit["_id"]} for hit in resp["hits"]["hits"]],
            "page": page,
            "size": size,
        }
    except Exception as exc:
        return {"error": str(exc), "items": [], "total": 0}




def remuneracoes_status(es: Optional[Elasticsearch] = None) -> Dict[str, Any]:
    """Volumetria dos índices de remunerações, por ano, nível e escalão."""
    client = es or get_es_client()
    if not client:
        return {"error": "Elasticsearch indisponível"}
    ensure_indices(client)
    out: Dict[str, Any] = {"indices": {}}
    try:
        out["indices"][REMUNERACOES_INDEX] = client.count(index=REMUNERACOES_INDEX).get("count", 0)
        out["indices"][REMUNERACOES_TERRITORIOS_INDEX] = client.count(
            index=REMUNERACOES_TERRITORIOS_INDEX
        ).get("count", 0)
        out["indices"][REMUNERACOES_PESSOAS_INDEX] = client.count(
            index=REMUNERACOES_PESSOAS_INDEX
        ).get("count", 0)
        out["indices"][REMUNERACOES_AP_INDEX] = client.count(
            index=REMUNERACOES_AP_INDEX
        ).get("count", 0)
    except Exception as exc:
        return {"error": str(exc)}

    def _buckets(resp: Dict[str, Any], name: str) -> List[Dict[str, Any]]:
        return [
            {"key": b["key"], "count": b["doc_count"]}
            for b in (resp.get("aggregations", {}).get(name, {}) or {}).get("buckets", [])
        ]

    try:
        if out["indices"][REMUNERACOES_INDEX]:
            resp = client.search(
                index=REMUNERACOES_INDEX,
                body={
                    "size": 0,
                    "aggs": {
                        "by_ano": {"terms": {"field": "ano", "size": 20}},
                        "by_nivel": {"terms": {"field": "nivel", "size": 10}},
                        "by_regime": {"terms": {"field": "regime", "size": 10}},
                        "by_natureza": {"terms": {"field": "natureza", "size": 20}},
                    },
                },
            )
            out["by_ano"] = _buckets(resp, "by_ano")
            out["by_nivel"] = _buckets(resp, "by_nivel")
            out["by_regime"] = _buckets(resp, "by_regime")
            out["by_natureza"] = _buckets(resp, "by_natureza")
        if out["indices"][REMUNERACOES_TERRITORIOS_INDEX]:
            resp = client.search(
                index=REMUNERACOES_TERRITORIOS_INDEX,
                body={
                    "size": 0,
                    "aggs": {
                        "by_nivel": {"terms": {"field": "nivel", "size": 10}},
                        "by_escalao": {"terms": {"field": "escalao_id", "size": 20}},
                        "by_distrito": {"terms": {"field": "distrito_keyword", "size": 30}},
                        "eleitores": {"sum": {"field": "eleitores"}},
                    },
                },
            )
            out["territorios_by_nivel"] = _buckets(resp, "by_nivel")
            out["territorios_by_escalao"] = _buckets(resp, "by_escalao")
            out["territorios_by_distrito"] = _buckets(resp, "by_distrito")
            out["total_eleitores"] = int(
                (resp.get("aggregations", {}).get("eleitores", {}) or {}).get("value", 0)
            )
        if out["indices"][REMUNERACOES_PESSOAS_INDEX]:
            resp = client.search(
                index=REMUNERACOES_PESSOAS_INDEX,
                body={
                    "size": 0,
                    "aggs": {
                        "by_tipo": {"terms": {"field": "tipo", "size": 10}},
                        "by_distrito": {"terms": {"field": "distrito", "size": 30}},
                        "by_sigla": {"terms": {"field": "sigla", "size": 30}},
                        "remuneracao_media": {"avg": {"field": "remuneracao_mensal"}},
                        "remuneracao_total": {"sum": {"field": "remuneracao_mensal"}},
                    },
                },
            )
            out["pessoas_by_tipo"] = _buckets(resp, "by_tipo")
            out["pessoas_by_distrito"] = _buckets(resp, "by_distrito")
            out["pessoas_by_sigla"] = _buckets(resp, "by_sigla")
            agregacoes = resp.get("aggregations", {}) or {}
            out["pessoas_remuneracao_media"] = round(
                float((agregacoes.get("remuneracao_media", {}) or {}).get("value") or 0), 2
            )
            out["total_mensal_presidentes_e_vereadores"] = round(
                float((agregacoes.get("remuneracao_total", {}) or {}).get("value") or 0), 2
            )
    except Exception as exc:
        out["agg_error"] = str(exc)
    return out
