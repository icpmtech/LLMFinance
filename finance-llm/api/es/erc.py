"""ERC: entidades, pessoas e órgãos de comunicação social.

Módulo do pacote :mod:`api.es` — ver `api/elasticsearch_client.py`,
que continua a expor a API pública (os coletores/serviços importam de lá).
"""
import logging
from datetime import datetime
from typing import Any, Dict, Iterable, List, Optional, Sequence

from elasticsearch import Elasticsearch
from elasticsearch.helpers import bulk
from api.es.core import get_es_client
from api.es.indices import ERC_ENTIDADES_INDEX, ERC_OCS_INDEX, ERC_PESSOAS_INDEX
from api.es.mappings import ensure_indices

logger = logging.getLogger(__name__)




# ---------------------------------------------------------------------------
# Portal da Transparência da ERC
# ---------------------------------------------------------------------------

def _erc_wildcard(field: str, value: str) -> Dict[str, Any]:
    return {"wildcard": {field: {"value": f"*{value}*", "case_insensitive": True}}}




def index_erc_bulk(
    index: str,
    items: Iterable[Dict[str, Any]],
    es: Optional[Elasticsearch] = None,
    *,
    recriar: bool = False,
) -> Dict[str, Any]:
    """Indexa documentos da ERC num dos índices `finance_erc_*`.

    Cada item tem de trazer `doc_id` (usado como `_id`, para reindexar sem
    duplicar); reindexar o mesmo portal sobrepõe-se em vez de acumular.
    `recriar` apaga e volta a criar o índice — é o que se quer quando o mapping
    mudou, porque o Elasticsearch não deixa alterar tipos de campos existentes
    (os dados vêm sempre dos JSONL, por isso não se perde nada).
    """
    client = es or get_es_client()
    if not client:
        return {"error": "Elasticsearch indisponível", "indexed": 0}
    if recriar:
        try:
            client.indices.delete(index=index, ignore_unavailable=True)
        except Exception as exc:  # noqa: BLE001 - um índice inexistente não impede nada
            logger.debug("Não foi possível apagar %s: %s", index, exc)
    ensure_indices(client)
    now = datetime.utcnow().isoformat()
    actions = []
    for doc in items:
        doc_id = doc.get("doc_id")
        if not doc_id:
            continue
        source = dict(doc)
        source.setdefault("ingested_at", now)
        actions.append({"_op_type": "index", "_index": index, "_id": doc_id, **source})
    if not actions:
        return {"index": index, "indexed": 0}
    try:
        indexed, errors = bulk(client, actions, raise_on_error=False)
        client.indices.refresh(index=index)
        return {"index": index, "indexed": indexed, "errors": len(errors) if errors else 0}
    except Exception as exc:
        return {"error": str(exc), "index": index, "indexed": 0}




def _erc_search(
    index: str,
    *,
    q: Optional[str] = None,
    text_fields: Sequence[str] = (),
    keyword_fields: Sequence[str] = (),
    filters: Optional[Sequence[Dict[str, Any]]] = None,
    nested_should: Optional[Sequence[Dict[str, Any]]] = None,
    sort: Optional[List[Dict[str, Any]]] = None,
    size: int = 25,
    page: int = 1,
    es: Optional[Elasticsearch] = None,
) -> Dict[str, Any]:
    """Pesquisa genérica `bool` nos índices da ERC (texto + filtros + nested)."""
    client = es or get_es_client()
    if not client:
        return {"error": "Elasticsearch indisponível", "items": [], "total": 0}
    ensure_indices(client)

    must: List[Dict[str, Any]] = []
    if q:
        should: List[Dict[str, Any]] = []
        for field in text_fields:
            should.append({"match_phrase": {field: {"query": q, "boost": 6}}})
            should.append({"match": {field: {"query": q, "operator": "and", "boost": 3}}})
        for field in keyword_fields:
            should.append(_erc_wildcard(field, q))
        if nested_should:
            should.extend(nested_should)
        if should:
            must.append({"bool": {"should": should, "minimum_should_match": 1}})

    bool_query: Dict[str, Any] = {}
    if must:
        bool_query["must"] = must
    if filters:
        bool_query["filter"] = list(filters)
    query: Dict[str, Any] = {"bool": bool_query} if bool_query else {"match_all": {}}

    body: Dict[str, Any] = {
        "query": query,
        "from": max(0, (page - 1) * max(1, size)),
        "size": max(1, min(int(size), 500)),
        "track_total_hits": True,
    }
    if sort:
        body["sort"] = sort
    try:
        resp = client.search(index=index, body=body)
        return {
            "total": resp["hits"]["total"]["value"],
            "items": [{**hit["_source"], "doc_id": hit["_id"]} for hit in resp["hits"]["hits"]],
            "page": page,
            "size": size,
        }
    except Exception as exc:
        return {"error": str(exc), "items": [], "total": 0}




def search_erc_entidades(
    q: Optional[str] = None,
    distrito: Optional[str] = None,
    tipo_sociedade: Optional[str] = None,
    actividade: Optional[str] = None,
    detem_ocs: Optional[bool] = None,
    pessoa: Optional[str] = None,
    size: int = 25,
    page: int = 1,
    es: Optional[Elasticsearch] = None,
) -> Dict[str, Any]:
    """Pesquisa entidades proprietárias de OCS (`finance_erc_entidades`)."""
    filters: List[Dict[str, Any]] = []
    if distrito:
        filters.append(_erc_wildcard("distrito_keyword", distrito))
    if tipo_sociedade:
        filters.append(_erc_wildcard("tipo_sociedade.keyword", tipo_sociedade))
    if actividade:
        filters.append(_erc_wildcard("actividade_principal.keyword", actividade))
    if detem_ocs is not None:
        filters.append({"term": {"detem_ocs": bool(detem_ocs)}})
    if pessoa:
        filters.append({"nested": {"path": "pessoas", "query": {"match": {
            "pessoas.nome": {"query": pessoa, "operator": "and"},
        }}}})
    # O texto livre também chega às pessoas dos órgãos sociais e aos OCS detidos
    # (campos analisados, por isso sem acentos: «planicie» encontra «Planície»).
    nested_should = [
        {"nested": {"path": "pessoas", "query": {"match": {
            "pessoas.nome": {"query": q, "operator": "and", "boost": 4},
        }}, "score_mode": "max"}},
        {"nested": {"path": "ocs", "query": {"match": {
            "ocs.designacao": {"query": q, "operator": "and", "boost": 3},
        }}, "score_mode": "max"}},
    ] if q else None
    return _erc_search(
        ERC_ENTIDADES_INDEX,
        q=q,
        text_fields=("nome", "tipo_sociedade", "actividade_principal", "distrito"),
        keyword_fields=("nome.keyword", "distrito_keyword", "ocs_designacoes", "pessoas_nomes"),
        filters=filters,
        nested_should=nested_should,
        sort=[{"_score": {"order": "desc"}}, {"nome.keyword": {"order": "asc"}}],
        size=size,
        page=page,
        es=es,
    )




def search_erc_pessoas(
    q: Optional[str] = None,
    distrito: Optional[str] = None,
    detem_ocs: Optional[bool] = None,
    empresa: Optional[str] = None,
    funcao: Optional[str] = None,
    size: int = 25,
    page: int = 1,
    es: Optional[Elasticsearch] = None,
) -> Dict[str, Any]:
    """Pesquisa pessoas reguladas (`finance_erc_pessoas`)."""
    filters: List[Dict[str, Any]] = []
    if distrito:
        filters.append(_erc_wildcard("distrito_keyword", distrito))
    if detem_ocs is not None:
        filters.append({"term": {"detem_ocs": bool(detem_ocs)}})
    if empresa:
        filters.append({"nested": {"path": "orgaos", "query": {"bool": {"must": [
            {"match_phrase": {"orgaos.nome": {"query": empresa}}},
        ]}}}})
    if funcao:
        filters.append({"nested": {"path": "orgaos", "query": {"match": {
            "orgaos.funcao": {"query": funcao, "operator": "and"},
        }}}})
    return _erc_search(
        ERC_PESSOAS_INDEX,
        q=q,
        text_fields=("nome", "distrito"),
        keyword_fields=("nome.keyword", "empresas", "participacoes_nomes"),
        filters=filters,
        sort=[{"_score": {"order": "desc"}}, {"nome.keyword": {"order": "asc"}}],
        size=size,
        page=page,
        es=es,
    )




def search_erc_ocs(
    q: Optional[str] = None,
    tipo: Optional[str] = None,
    distrito: Optional[str] = None,
    proprietaria: Optional[str] = None,
    size: int = 25,
    page: int = 1,
    es: Optional[Elasticsearch] = None,
) -> Dict[str, Any]:
    """Pesquisa órgãos de comunicação social (`finance_erc_ocs`)."""
    filters: List[Dict[str, Any]] = []
    if tipo:
        filters.append(_erc_wildcard("tipo", tipo))
    if distrito:
        filters.append(_erc_wildcard("distrito_keyword", distrito))
    if proprietaria:
        filters.append(_erc_wildcard("entidade_proprietaria.keyword", proprietaria))
    return _erc_search(
        ERC_OCS_INDEX,
        q=q,
        text_fields=("designacao", "entidade_proprietaria", "distrito"),
        keyword_fields=("entidade_proprietaria.keyword",),
        filters=filters,
        sort=[{"_score": {"order": "desc"}}, {"designacao.keyword": {"order": "asc"}}],
        size=size,
        page=page,
        es=es,
    )




#: Ordenações aceites pelo ranking de análise de risco e de financeiro.
#: `unmapped_type` evita o erro do Elasticsearch quando o índice ainda não tem os
#: campos (ex.: antes da primeira indexação da análise): devolve vazio, não falha.
ERC_ORDENACOES: Dict[str, List[Dict[str, Any]]] = {
    "risco": [{"analise.risco.score": {"order": "desc", "missing": "_last", "unmapped_type": "integer"}}, {"nome.keyword": {"order": "asc"}}],
    "transparencia": [{"analise.transparencia.score": {"order": "desc", "missing": "_last", "unmapped_type": "integer"}}, {"nome.keyword": {"order": "asc"}}],
    "credito": [{"analise.credito.score": {"order": "desc", "missing": "_last", "unmapped_type": "integer"}}, {"nome.keyword": {"order": "asc"}}],
    "rendimentos": [{"ultimo_rendimentos": {"order": "desc", "missing": "_last", "unmapped_type": "double"}}, {"nome.keyword": {"order": "asc"}}],
    "resultados": [{"ultimo_resultados": {"order": "desc", "missing": "_last", "unmapped_type": "double"}}, {"nome.keyword": {"order": "asc"}}],
    "capital_proprio": [{"ultimo_capital_proprio": {"order": "desc", "missing": "_last", "unmapped_type": "double"}}, {"nome.keyword": {"order": "asc"}}],
    "autonomia": [{"ultimo_autonomia": {"order": "desc", "missing": "_last", "unmapped_type": "double"}}, {"nome.keyword": {"order": "asc"}}],
    "recentes": [{"ultimo_ano_financeiro": {"order": "desc", "missing": "_last", "unmapped_type": "integer"}}, {"nome.keyword": {"order": "asc"}}],
    "nome": [{"nome.keyword": {"order": "asc"}}],
}




def _erc_valores(valor: Any) -> List[str]:
    """Aceita um valor ou uma lista em texto (`a`, `a,b`) para os filtros `terms`."""
    if valor is None:
        return []
    if isinstance(valor, (list, tuple, set)):
        itens = [str(v).strip() for v in valor]
    else:
        itens = [parte.strip() for parte in str(valor).split(",")]
    return [item for item in itens if item]




def search_erc_analise(
    q: Optional[str] = None,
    banda: Optional[str] = None,
    nivel_transparencia: Optional[str] = None,
    nivel_credito: Optional[str] = None,
    distrito: Optional[str] = None,
    risco_min: Optional[float] = None,
    risco_max: Optional[float] = None,
    transparencia_min: Optional[float] = None,
    credito_min: Optional[float] = None,
    com_financeiro: Optional[bool] = None,
    ordenar: str = "risco",
    size: int = 25,
    page: int = 1,
    es: Optional[Elasticsearch] = None,
) -> Dict[str, Any]:
    """Ranking das entidades por risco, transparência, crédito ou números."""
    filters: List[Dict[str, Any]] = []
    for campo, valor in (
        ("analise.risco.banda", banda),
        ("analise.transparencia.nivel", nivel_transparencia),
        ("analise.credito.nivel", nivel_credito),
    ):
        itens = _erc_valores(valor)
        if itens:
            filters.append({"terms": {campo: itens}})
    if distrito:
        filters.append(_erc_wildcard("distrito_keyword", distrito))
    for campo, minimo, maximo in (
        ("analise.risco.score", risco_min, risco_max),
        ("analise.transparencia.score", transparencia_min, None),
        ("analise.credito.score", credito_min, None),
    ):
        if minimo is None and maximo is None:
            continue
        intervalo: Dict[str, Any] = {}
        if minimo is not None:
            intervalo["gte"] = minimo
        if maximo is not None:
            intervalo["lte"] = maximo
        filters.append({"range": {campo: intervalo}})
    if com_financeiro is True:
        filters.append({"range": {"n_anos_financeiro": {"gte": 1}}})
    elif com_financeiro is False:
        filters.append({"bool": {"must_not": [{"range": {"n_anos_financeiro": {"gte": 1}}}]}})
    return _erc_search(
        ERC_ENTIDADES_INDEX,
        q=q,
        text_fields=("nome", "tipo_sociedade", "actividade_principal", "distrito"),
        keyword_fields=("nome.keyword", "pessoas_nomes", "ocs_designacoes"),
        filters=filters,
        sort=ERC_ORDENACOES.get(str(ordenar or "risco").lower(), ERC_ORDENACOES["risco"]),
        size=size,
        page=page,
        es=es,
    )




def erc_financeiro_painel(es: Optional[Elasticsearch] = None) -> Dict[str, Any]:
    """Painel financeiro: totais por exercício e distribuição de risco.

    Os valores por ano saem de agregações `nested` sobre `financeiro` — é o mesmo
    documento, mas cada exercício soma-se por si (sem misturar anos).
    """
    client = es or get_es_client()
    if not client:
        return {"error": "Elasticsearch indisponível"}
    ensure_indices(client)
    out: Dict[str, Any] = {}
    try:
        resp = client.search(
            index=ERC_ENTIDADES_INDEX,
            body={"size": 0, "aggs": {
                "com_financeiro": {"filter": {"range": {"n_anos_financeiro": {"gte": 1}}}},
                "por_banda": {"terms": {"field": "analise.risco.banda", "size": 10}},
                "por_transparencia": {"terms": {"field": "analise.transparencia.nivel", "size": 10}},
                "por_credito": {"terms": {"field": "analise.credito.nivel", "size": 10}},
                "anos": {
                    "nested": {"path": "financeiro"},
                    "aggs": {
                        "por_ano": {
                            "terms": {"field": "financeiro.ano", "size": 30, "order": {"_key": "desc"}},
                            "aggs": {
                                "rendimentos": {"sum": {"field": "financeiro.rendimentos_totais"}},
                                "resultados": {"sum": {"field": "financeiro.resultados_liquidos"}},
                                "ativo": {"sum": {"field": "financeiro.ativo_total"}},
                                "capital_proprio": {"sum": {"field": "financeiro.capital_proprio"}},
                                "com_prejuizo": {"filter": {"range": {"financeiro.resultados_liquidos": {"lt": 0}}}},
                            },
                        },
                    },
                },
            }},
        )
        aggs = resp.get("aggregations", {})
        out["com_financeiro"] = aggs.get("com_financeiro", {}).get("doc_count", 0)
        out["por_banda"] = [{"key": b["key"], "count": b["doc_count"]} for b in aggs.get("por_banda", {}).get("buckets", [])]
        out["por_transparencia"] = [{"key": b["key"], "count": b["doc_count"]} for b in aggs.get("por_transparencia", {}).get("buckets", [])]
        out["por_credito"] = [{"key": b["key"], "count": b["doc_count"]} for b in aggs.get("por_credito", {}).get("buckets", [])]
        anos = []
        for balde in aggs.get("anos", {}).get("por_ano", {}).get("buckets", []):
            anos.append({
                "ano": int(balde["key"]),
                "balancos": balde["doc_count"],
                "rendimentos": round(balde["rendimentos"]["value"] or 0, 2),
                "resultados": round(balde["resultados"]["value"] or 0, 2),
                "ativo": round(balde["ativo"]["value"] or 0, 2),
                "capital_proprio": round(balde["capital_proprio"]["value"] or 0, 2),
                "com_prejuizo": balde["com_prejuizo"]["doc_count"],
            })
        out["anos"] = anos
    except Exception as exc:
        out["error"] = str(exc)
    return out




def erc_status(es: Optional[Elasticsearch] = None) -> Dict[str, Any]:
    """Volumetria e agregações rápidas dos índices do portal da ERC."""
    client = es or get_es_client()
    if not client:
        return {"error": "Elasticsearch indisponível"}
    ensure_indices(client)
    out: Dict[str, Any] = {}
    try:
        for key, index in (("entidades", ERC_ENTIDADES_INDEX), ("pessoas", ERC_PESSOAS_INDEX), ("ocs", ERC_OCS_INDEX)):
            out[key] = {"index": index, "documents": client.count(index=index).get("count", 0)}
    except Exception as exc:
        return {"error": str(exc)}
    try:
        resp = client.search(
            index=ERC_ENTIDADES_INDEX,
            body={"size": 0, "aggs": {
                "by_distrito": {"terms": {"field": "distrito_keyword", "size": 25}},
                "by_tipo": {"terms": {"field": "tipo_sociedade.keyword", "size": 25}},
                "by_actividade": {"terms": {"field": "actividade_principal.keyword", "size": 10}},
                "sem_ocs": {"filter": {"term": {"detem_ocs": False}}},
            }},
        )
        aggs = resp.get("aggregations", {})
        out["entidades"]["by_distrito"] = [{"key": b["key"], "count": b["doc_count"]} for b in aggs.get("by_distrito", {}).get("buckets", [])]
        out["entidades"]["by_tipo"] = [{"key": b["key"], "count": b["doc_count"]} for b in aggs.get("by_tipo", {}).get("buckets", [])]
        out["entidades"]["by_actividade"] = [{"key": b["key"], "count": b["doc_count"]} for b in aggs.get("by_actividade", {}).get("buckets", [])]
        out["entidades"]["sem_ocs"] = aggs.get("sem_ocs", {}).get("doc_count", 0)
    except Exception as exc:
        out["error"] = str(exc)
    try:
        resp = client.search(
            index=ERC_OCS_INDEX,
            body={"size": 0, "aggs": {"by_tipo": {"terms": {"field": "tipo", "size": 20}}}},
        )
        out["ocs"]["by_tipo"] = [{"key": b["key"], "count": b["doc_count"]} for b in resp.get("aggregations", {}).get("by_tipo", {}).get("buckets", [])]
    except Exception:
        pass
    return out
