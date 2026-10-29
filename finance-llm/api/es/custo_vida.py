"""Índice do custo de vida por concelho (`finance_custo_vida`).

Um documento por concelho, com os componentes que entram no orçamento mensal
(renda, gasóleo, IMI, eletricidade e gás) e o índice de custo de vida — 100 é a
mediana nacional. A construção dos documentos está em
`api/custo_vida_service.py`; aqui só se guarda, pesquisa e lê.

O índice existe para o mapa do site poder ler uma fotografia já calculada em
vez de recalcular 308 concelhos em cada pedido, e para se poder comparar, ao
longo do tempo, o que mudou (a recolha grava `atualizado_em`).
"""
import logging
from typing import Any, Dict, List, Optional

from elasticsearch import Elasticsearch
from elasticsearch.helpers import bulk

from api.es.core import _fold_text, _search_terms, _text_search, get_es_client
from api.es.indices import CUSTO_VIDA_INDEX
from api.es.mappings import ensure_indices

logger = logging.getLogger(__name__)

#: Campos pelos quais a lista se pode ordenar (os que a interface oferece).
ORDENACOES = {
    "indice": "indice",
    "custo": "custo_t2",
    "renda": "renda_m2",
    "gasoleo": "gasoleo_l",
    "imi": "imi_pct",
    "nome": "nome_keyword",
    "populacao": "populacao",
}


def indexar(docs: List[Dict[str, Any]], es: Optional[Elasticsearch] = None) -> Dict[str, Any]:
    """Substitui o índice pelo conjunto de documentos dado."""
    client = es or get_es_client()
    if not client:
        return {"error": "Elasticsearch indisponível", "indexed": 0}
    if not docs:
        return {"indexed": 0, "aviso": "sem documentos para indexar"}
    ensure_indices(client)

    acoes = []
    for doc in docs:
        fonte = {chave: valor for chave, valor in doc.items() if chave != "custo"}
        custo = doc.get("custo") or {}
        for tipologia, valor in custo.items():
            fonte[f"custo_{tipologia.lower()}"] = valor
        fonte["custo"] = custo
        acoes.append(
            {
                "_op_type": "index",
                "_index": CUSTO_VIDA_INDEX,
                "_id": doc["doc_id"],
                **fonte,
            }
        )
    try:
        indexados, erros = bulk(client, acoes, raise_on_error=False)
        client.indices.refresh(index=CUSTO_VIDA_INDEX)
        return {"indexed": indexados, "errors": len(erros) if erros else 0}
    except Exception as exc:  # índice fechado, mapping, cluster em baixo
        logger.warning("custo de vida: indexação falhou (%s)", exc)
        return {"error": str(exc), "indexed": 0}


def total(es: Optional[Elasticsearch] = None) -> int:
    client = es or get_es_client()
    if not client:
        return 0
    ensure_indices(client)
    try:
        return int(client.count(index=CUSTO_VIDA_INDEX).get("count") or 0)
    except Exception:
        return 0


def listar(
    q: Optional[str] = None,
    distrito: Optional[str] = None,
    nuts: Optional[str] = None,
    ordenar: str = "indice",
    ordem: str = "desc",
    size: int = 400,
    page: int = 1,
    es: Optional[Elasticsearch] = None,
) -> Dict[str, Any]:
    """Lista os concelhos, com filtros de texto e de geografia."""
    client = es or get_es_client()
    if not client:
        return {"error": "Elasticsearch indisponível", "items": [], "total": 0}
    ensure_indices(client)

    filtros: List[Dict[str, Any]] = []
    if distrito:
        filtros.append({"term": {"distrito": distrito}})
    if nuts:
        filtros.append({"term": {"nuts": nuts}})

    corpo: Dict[str, Any] = {
        "from": max(0, (max(1, page) - 1) * max(1, size)),
        "size": max(1, min(size, 500)),
        "sort": [
            {ORDENACOES.get(ordenar, "indice"): {"order": "asc" if str(ordem).lower() == "asc" else "desc", "missing": "_last"}},
            {"nome_keyword": {"order": "asc"}},
        ],
        "track_total_hits": True,
    }
    if q:
        # A pesquisa por nome passa por `_text_search`, que exige todos os
        # termos e só cai para OR quando a versão estrita devolve zero.
        corpo["query"] = {
            "bool": {
                "must": [
                    {
                        "bool": {
                            "should": [
                                {"match_phrase": {"nome": {"query": q, "boost": 6}}},
                                {"match": {"nome": {"query": q, "operator": "and", "boost": 3}}},
                                {"wildcard": {"nome_keyword": {"value": f"*{_fold(q)}*", "case_insensitive": True}}},
                            ],
                            "minimum_should_match": 1,
                        }
                    }
                ],
                "filter": filtros,
            }
        }
        if not _search_terms(q):
            corpo["query"] = {"bool": {"filter": filtros}} if filtros else {"match_all": {}}
    else:
        corpo["query"] = {"bool": {"filter": filtros}} if filtros else {"match_all": {}}

    try:
        resposta = _text_search(client, index=CUSTO_VIDA_INDEX, body=corpo, q=q)
        return {
            "total": resposta["hits"]["total"]["value"],
            "items": [{**hit["_source"], "doc_id": hit["_id"]} for hit in resposta["hits"]["hits"]],
            "page": page,
            "size": size,
        }
    except Exception as exc:
        return {"error": str(exc), "items": [], "total": 0}


def _fold(value: Any) -> str:
    return _fold_text(value)


def obter(nome: str, es: Optional[Elasticsearch] = None) -> Dict[str, Any]:
    """Ficha de um concelho, por nome ou por `doc_id` (slug)."""
    client = es or get_es_client()
    if not client:
        return {"error": "Elasticsearch indisponível"}
    ensure_indices(client)
    chave = _fold(nome).replace(" ", "-")
    try:
        resposta = client.get(index=CUSTO_VIDA_INDEX, id=chave)
        return {**resposta["_source"], "doc_id": resposta["_id"]}
    except Exception:
        pass
    resultado = listar(q=nome, size=1, es=client)
    itens = resultado.get("items") or []
    return itens[0] if itens else {"error": "concelho não encontrado", "nome": nome}


def status(es: Optional[Elasticsearch] = None) -> Dict[str, Any]:
    """Volumetria e cobertura do índice, para o painel e para os testes."""
    client = es or get_es_client()
    if not client:
        return {"error": "Elasticsearch indisponível", "total": 0}
    ensure_indices(client)
    try:
        resposta = client.search(
            index=CUSTO_VIDA_INDEX,
            body={
                "size": 0,
                "track_total_hits": True,
                "aggs": {
                    "por_distrito": {"terms": {"field": "distrito", "size": 25}},
                    "com_renda": {"filter": {"exists": {"field": "renda_m2"}}},
                    "completos": {"filter": {"term": {"completo": True}}},
                },
            },
        )
        aggs = resposta.get("aggregations") or {}
        return {
            "total": resposta["hits"]["total"]["value"],
            "com_renda": (aggs.get("com_renda") or {}).get("doc_count", 0),
            "completos": (aggs.get("completos") or {}).get("doc_count", 0),
            "distritos": [
                {"distrito": balde["key"], "concelhos": balde["doc_count"]}
                for balde in (aggs.get("por_distrito") or {}).get("buckets", [])
            ],
        }
    except Exception as exc:
        return {"error": str(exc), "total": 0}
