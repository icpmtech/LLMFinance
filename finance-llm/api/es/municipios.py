"""Municípios: despesas, vereadores e contratos.

Módulo do pacote :mod:`api.es` — ver `api/elasticsearch_client.py`,
que continua a expor a API pública (os coletores/serviços importam de lá).
"""
import logging
from datetime import datetime
from typing import Any, Dict, Iterable, List, Optional

from elasticsearch import Elasticsearch, NotFoundError
from elasticsearch.helpers import bulk
from api.es.core import get_es_client
from api.es.indices import CONTRACTS_INDEX, MUNICIPIOS_DESPESAS_INDEX, VEREADORES_INDEX
from api.es.mappings import ensure_indices

logger = logging.getLogger(__name__)




def index_vereadores_bulk(items: Iterable[Dict[str, Any]], es: Optional[Elasticsearch] = None) -> Dict[str, Any]:
    """Indexa documentos de vereadores no índice finance_vereadores.

    Cada item deve ter `doc_id`, `name`, `concelho`, `district`, `party`, `role`
    e, opcionalmente, `remuneration`, `nif`, `source_url` e `raw_data`.
    """
    client = es or get_es_client()
    if not client:
        return {"error": "Elasticsearch indisponível", "indexed": 0}
    ensure_indices(client)
    actions = []
    now = datetime.utcnow().isoformat()
    for doc in items:
        if not doc.get("doc_id") or not doc.get("name"):
            continue
        source = dict(doc)
        source.setdefault("ingested_at", now)
        source.setdefault("updated_at", now)
        actions.append({
            "_op_type": "index",
            "_index": VEREADORES_INDEX,
            "_id": source["doc_id"],
            **source,
        })
    if not actions:
        return {"indexed": 0}
    try:
        indexed, errors = bulk(client, actions, raise_on_error=False)
        client.indices.refresh(index=VEREADORES_INDEX)
        return {"indexed": indexed, "errors": len(errors) if errors else 0}
    except Exception as exc:
        return {"error": str(exc), "indexed": 0}




def search_vereadores(
    q: Optional[str] = None,
    district: Optional[str] = None,
    concelho: Optional[str] = None,
    party: Optional[str] = None,
    role: Optional[str] = None,
    size: int = 50,
    page: int = 1,
    es: Optional[Elasticsearch] = None,
) -> Dict[str, Any]:
    """Pesquisa no índice finance_vereadores."""
    client = es or get_es_client()
    if not client:
        return {"error": "Elasticsearch indisponível", "items": [], "total": 0}
    ensure_indices(client)

    must: List[Dict[str, Any]] = []
    filters: List[Dict[str, Any]] = []

    if q:
        must.append({
            "bool": {
                "should": [
                    {"match_phrase": {"name": {"query": q, "boost": 6}}},
                    {"match": {"name": {"query": q, "operator": "and", "boost": 3}}},
                    {"wildcard": {"party.keyword": {"value": f"*{q}*", "case_insensitive": True}}},
                    {"wildcard": {"concelho.keyword": {"value": f"*{q}*", "case_insensitive": True}}},
                ],
                "minimum_should_match": 1,
            }
        })
    if district:
        filters.append({"wildcard": {"district.keyword": {"value": f"*{district}*", "case_insensitive": True}}})
    if concelho:
        filters.append({"wildcard": {"concelho.keyword": {"value": f"*{concelho}*", "case_insensitive": True}}})
    if party:
        filters.append({"wildcard": {"party.keyword": {"value": f"*{party}*", "case_insensitive": True}}})
    if role:
        filters.append({"wildcard": {"role": {"value": f"*{role}*", "case_insensitive": True}}})

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
        "size": max(1, min(size, 500)),
        "sort": [{"_score": {"order": "desc"}}, {"name.keyword": {"order": "asc"}}],
        "track_total_hits": True,
    }

    try:
        resp = client.search(index=VEREADORES_INDEX, body=body)
        total = resp["hits"]["total"]["value"]
        return {
            "total": total,
            "items": [{**hit["_source"], "doc_id": hit["_id"]} for hit in resp["hits"]["hits"]],
            "from": from_,
            "size": size,
            "page": page,
        }
    except Exception as exc:
        return {"error": str(exc), "items": [], "total": 0}




def vereadores_status(es: Optional[Elasticsearch] = None) -> Dict[str, Any]:
    """Volumetria rápida do índice de vereadores."""
    client = es or get_es_client()
    if not client:
        return {"error": "Elasticsearch indisponível"}
    ensure_indices(client)
    try:
        count = client.count(index=VEREADORES_INDEX).get("count", 0)
        out: Dict[str, Any] = {"index": VEREADORES_INDEX, "documents": count}
        if count:
            resp = client.search(
                index=VEREADORES_INDEX,
                body={
                    "size": 0,
                    "aggs": {
                        "by_role": {"terms": {"field": "role_keyword", "size": 20}},
                        "by_source": {"terms": {"field": "source", "size": 20}},
                        "by_party": {"terms": {"field": "party_keyword", "size": 20}},
                        "by_concelho": {"terms": {"field": "concelho_keyword", "size": 20}},
                    },
                },
            )
            aggs = resp.get("aggregations", {})
            out["by_role"] = [{"key": b["key"], "count": b["doc_count"]} for b in aggs.get("by_role", {}).get("buckets", [])]
            out["by_source"] = [{"key": b["key"], "count": b["doc_count"]} for b in aggs.get("by_source", {}).get("buckets", [])]
            out["by_party"] = [{"key": b["key"], "count": b["doc_count"]} for b in aggs.get("by_party", {}).get("buckets", [])]
            out["by_concelho"] = [{"key": b["key"], "count": b["doc_count"]} for b in aggs.get("by_concelho", {}).get("buckets", [])]
        return out
    except Exception as exc:
        return {"error": str(exc)}




# ---------------------------------------------------------------------------
# Despesas das câmaras municipais (INE/DGAL + contratação pública)
# ---------------------------------------------------------------------------

#: Campos pelos quais a lista de municípios pode ser ordenada. A ordenação é
#: feita no Elasticsearch, por isso só entram campos mapeados como número.
MUNICIPIOS_ORDENACOES = {
    "despesas": "despesas_total",
    "pessoal": "despesas_pessoal",
    "bens_servicos": "despesas_bens_servicos",
    "capital": "despesas_capital",
    "contratos": "contratos_valor",
    "contratos_total": "contratos_total",
    "nome": "nome_keyword",
}




def index_municipios_despesas_bulk(
    items: Iterable[Dict[str, Any]],
    es: Optional[Elasticsearch] = None,
) -> Dict[str, Any]:
    """Indexa as fichas dos municípios no índice `finance_municipios_despesas`.

    Cada item tem de trazer `doc_id` e `nome`; os restantes campos são opcionais
    (a ficha de um município sem despesa publicada continua a ser útil, porque
    pode ter contratação).
    """
    client = es or get_es_client()
    if not client:
        return {"error": "Elasticsearch indisponível", "indexed": 0}
    ensure_indices(client)
    actions = []
    now = datetime.utcnow().isoformat()
    for doc in items:
        if not doc.get("doc_id") or not doc.get("nome"):
            continue
        source = dict(doc)
        source.setdefault("ingested_at", now)
        source.setdefault("updated_at", now)
        actions.append({
            "_op_type": "index",
            "_index": MUNICIPIOS_DESPESAS_INDEX,
            "_id": source["doc_id"],
            **source,
        })
    if not actions:
        return {"indexed": 0}
    try:
        indexed, errors = bulk(client, actions, raise_on_error=False)
        client.indices.refresh(index=MUNICIPIOS_DESPESAS_INDEX)
        return {"indexed": indexed, "errors": len(errors) if errors else 0}
    except Exception as exc:
        return {"error": str(exc), "indexed": 0}




def search_municipios_despesas(
    q: Optional[str] = None,
    distrito: Optional[str] = None,
    nuts: Optional[str] = None,
    ano: Optional[int] = None,
    ordenar: str = "despesas",
    ordem: str = "desc",
    min_despesas: Optional[float] = None,
    size: int = 30,
    page: int = 1,
    es: Optional[Elasticsearch] = None,
) -> Dict[str, Any]:
    """Lista e filtra os municípios por despesa e contratação."""
    client = es or get_es_client()
    if not client:
        return {"error": "Elasticsearch indisponível", "items": [], "total": 0}
    ensure_indices(client)

    must: List[Dict[str, Any]] = []
    filters: List[Dict[str, Any]] = []
    if q:
        termo = str(q).strip()
        must.append({
            "bool": {
                "should": [
                    {"match_phrase": {"nome": {"query": termo, "boost": 6}}},
                    {"match": {"nome": {"query": termo, "operator": "and", "boost": 3}}},
                    {"wildcard": {"nome_keyword": {"value": f"*{termo}*", "case_insensitive": True}}},
                    {"term": {"geocod": termo}},
                ],
                "minimum_should_match": 1,
            }
        })
    if distrito:
        filters.append({"wildcard": {"distrito": {"value": f"*{distrito}*", "case_insensitive": True}}})
    if nuts:
        filters.append({"term": {"nuts": str(nuts)}})
    if ano:
        filters.append({"term": {"anos": str(ano)}})
    if min_despesas is not None:
        filters.append({"range": {"despesas_total": {"gte": float(min_despesas)}}})

    bool_query: Dict[str, Any] = {}
    if must:
        bool_query["must"] = must
    if filters:
        bool_query["filter"] = filters
    query = {"bool": bool_query} if bool_query else {"match_all": {}}

    campo = MUNICIPIOS_ORDENACOES.get(str(ordenar or ""), "despesas_total")
    direcao = "asc" if str(ordem).lower() == "asc" else "desc"
    from_ = max(0, (max(1, page) - 1) * max(1, size))

    body = {
        "query": query,
        "from": from_,
        "size": max(1, min(size, 500)),
        "sort": [{campo: {"order": direcao, "missing": "_last"}}, {"nome_keyword": {"order": "asc"}}],
        "track_total_hits": True,
        "aggs": {
            "total_despesas": {"sum": {"field": "despesas_total"}},
            "total_contratos": {"sum": {"field": "contratos_valor"}},
            "por_distrito": {"terms": {"field": "distrito", "size": 30}},
        },
    }

    try:
        resp = client.search(index=MUNICIPIOS_DESPESAS_INDEX, body=body)
        total = resp["hits"]["total"]["value"]
        aggs = resp.get("aggregations", {})
        return {
            "total": total,
            "items": [{**hit["_source"], "doc_id": hit["_id"]} for hit in resp["hits"]["hits"]],
            "from": from_,
            "size": size,
            "page": page,
            "despesas_somadas": (aggs.get("total_despesas", {}) or {}).get("value") or 0.0,
            "contratos_somados": (aggs.get("total_contratos", {}) or {}).get("value") or 0.0,
            "distritos": [
                {"key": b["key"], "count": b["doc_count"]}
                for b in (aggs.get("por_distrito", {}) or {}).get("buckets", [])
            ],
        }
    except Exception as exc:
        return {"error": str(exc), "items": [], "total": 0}




def fornecedores_do_municipio(
    nomes_adjudicante: Iterable[str],
    *,
    ano: Optional[int] = None,
    maximo: int = 20000,
    es: Optional[Elasticsearch] = None,
) -> Dict[str, Any]:
    """**Todos** os fornecedores (adjudicatários) de um município, e não só o topo.

    A lista completa exige percorrer o `composite` (paginado por `after_key`),
    porque os `terms` só devolvem os N maiores. O filtro do ano vai na consulta
    (raiz), para o `composite` nunca contar contratos de outros anos.
    """
    client = es or get_es_client()
    if not client:
        return {"error": "Elasticsearch indisponível", "fornecedores": [], "total": 0}
    nomes = [str(n) for n in (nomes_adjudicante or []) if n]
    if not nomes:
        return {"total": 0, "fornecedores": [], "ano": ano}

    filtros: List[Dict[str, Any]] = [
        {"nested": {"path": "adjudicantes.parsed", "query": {"terms": {"adjudicantes.parsed.nome": nomes}}}}
    ]
    if ano:
        filtros.append(
            {"range": {"dataCelebracaoContrato": {"gte": f"{int(ano)}-01-01", "lte": f"{int(ano)}-12-31"}}}
        )

    fornecedores: Dict[str, Dict[str, Any]] = {}
    after: Optional[Dict[str, Any]] = None
    paginas = 0
    while paginas < 40:
        composite: Dict[str, Any] = {
            "size": 1000,
            "sources": [{"nome": {"terms": {"field": "adjudicatarios.parsed.nome"}}}],
        }
        if after:
            composite["after"] = after
        body = {
            "size": 0,
            "query": {"bool": {"filter": filtros}},
            "aggs": {
                "adjudicatarios": {
                    "nested": {"path": "adjudicatarios.parsed"},
                    "aggs": {
                        "nomes": {
                            "composite": composite,
                            "aggs": {
                                "raiz": {
                                    "reverse_nested": {},
                                    "aggs": {"valor": {"sum": {"field": "precoContratual"}}},
                                }
                            },
                        }
                    },
                }
            },
        }
        try:
            resp = client.search(index=CONTRACTS_INDEX, body=body)
        except Exception as exc:
            logger.warning("Fornecedores do município falharam: %s", exc)
            return {"error": str(exc), "fornecedores": [], "total": 0}
        bloco = ((resp.get("aggregations", {}).get("adjudicatarios", {}) or {}).get("nomes", {}) or {})
        baldes = bloco.get("buckets") or []
        for balde in baldes:
            # O `composite` devolve a chave como objeto (`{"nome": "…"}`) mesmo
            # com uma só origem: sem isto o fornecedor vinha como texto do dicionário.
            chave = balde.get("key")
            if isinstance(chave, dict):
                chave = chave.get("nome") or next(iter(chave.values()), "")
            nome = str(chave or "")
            if not nome:
                continue
            raiz = balde.get("raiz", {}) or {}
            actual = fornecedores.get(nome)
            contratos = int(raiz.get("doc_count") or 0)
            valor = (raiz.get("valor", {}) or {}).get("value") or 0.0
            if actual:
                actual["contratos"] += contratos
                actual["valor"] += valor
            else:
                fornecedores[nome] = {"nome": nome, "contratos": contratos, "valor": valor}
        after = bloco.get("after_key")
        paginas += 1
        if not after or not baldes or len(fornecedores) >= maximo:
            break

    lista = sorted(fornecedores.values(), key=lambda linha: -linha["valor"])
    return {"total": len(lista), "fornecedores": lista, "ano": int(ano) if ano else None, "paginas": paginas}




def get_municipio_despesas(nome_ou_codigo: str, es: Optional[Elasticsearch] = None) -> Dict[str, Any]:
    """Ficha de um município, pelo código INE ou pelo nome (tolerante a acentos)."""
    client = es or get_es_client()
    if not client:
        return {"error": "Elasticsearch indisponível"}
    ensure_indices(client)
    alvo = str(nome_ou_codigo or "").strip()
    if not alvo:
        return {"error": "Indique o município."}

    try:
        resp = client.get(index=MUNICIPIOS_DESPESAS_INDEX, id=alvo, _source=True)
        return {**resp.get("_source", {}), "doc_id": resp.get("_id")}
    except NotFoundError:
        pass
    except Exception as exc:
        logger.debug("Leitura direta do município %s falhou: %s", alvo, exc)

    body = {
        "size": 1,
        "query": {
            "bool": {
                "should": [
                    {"term": {"geocod": alvo}},
                    {"term": {"nome_keyword": alvo.lower()}},
                    {"match_phrase": {"nome": {"query": alvo, "boost": 4}}},
                ],
                "minimum_should_match": 1,
            }
        },
    }
    try:
        resp = client.search(index=MUNICIPIOS_DESPESAS_INDEX, body=body)
    except Exception as exc:
        return {"error": str(exc)}
    hits = resp.get("hits", {}).get("hits", [])
    if not hits:
        return {"error": f"Município não encontrado: {alvo}", "total": 0}
    return {**hits[0]["_source"], "doc_id": hits[0]["_id"]}




def municipios_despesas_mapa(es: Optional[Elasticsearch] = None) -> List[Dict[str, Any]]:
    """Todos os municípios com o essencial para o mapa (nome, código, totais)."""
    client = es or get_es_client()
    if not client:
        return []
    ensure_indices(client)
    try:
        resp = client.search(
            index=MUNICIPIOS_DESPESAS_INDEX,
            body={
                "size": 500,
                "_source": [
                    "nome", "geocod", "codigo", "distrito", "nuts", "nuts_nome",
                    "ano_despesas", "despesas_total", "despesas_pessoal", "despesas_capital",
                    "contratos_total", "contratos_valor", "populacao_2021",
                ],
                "sort": [{"nome_keyword": {"order": "asc"}}],
            },
        )
        return [{**hit["_source"], "doc_id": hit["_id"]} for hit in resp["hits"]["hits"]]
    except Exception as exc:
        logger.warning("Mapa dos municípios falhou: %s", exc)
        return []




def municipios_despesas_status(es: Optional[Elasticsearch] = None) -> Dict[str, Any]:
    """Volumetria do índice de despesas municipais."""
    client = es or get_es_client()
    if not client:
        return {"error": "Elasticsearch indisponível"}
    ensure_indices(client)
    try:
        count = client.count(index=MUNICIPIOS_DESPESAS_INDEX).get("count", 0)
        out: Dict[str, Any] = {"index": MUNICIPIOS_DESPESAS_INDEX, "documents": count}
        if count:
            resp = client.search(
                index=MUNICIPIOS_DESPESAS_INDEX,
                body={
                    "size": 0,
                    "aggs": {
                        "por_distrito": {"terms": {"field": "distrito", "size": 30}},
                        "por_nuts": {"terms": {"field": "nuts", "size": 15}},
                        "total_despesas": {"sum": {"field": "despesas_total"}},
                        "total_contratos": {"sum": {"field": "contratos_valor"}},
                        "sem_despesas": {"filter": {"bool": {"must_not": [{"exists": {"field": "despesas_total"}}]}}},
                    },
                },
            )
            aggs = resp.get("aggregations", {})
            out["total_despesas"] = (aggs.get("total_despesas", {}) or {}).get("value") or 0.0
            out["total_contratos"] = (aggs.get("total_contratos", {}) or {}).get("value") or 0.0
            out["sem_despesas"] = (aggs.get("sem_despesas", {}) or {}).get("doc_count") or 0
            out["por_distrito"] = [{"key": b["key"], "count": b["doc_count"]} for b in (aggs.get("por_distrito", {}) or {}).get("buckets", [])]
            out["por_nuts"] = [{"key": b["key"], "count": b["doc_count"]} for b in (aggs.get("por_nuts", {}) or {}).get("buckets", [])]
        return out
    except Exception as exc:
        return {"error": str(exc)}




def contratos_do_municipio(
    nomes_adjudicante: Iterable[str],
    *,
    ano: Optional[int] = None,
    fornecedores: int = 12,
    anos: int = 12,
    es: Optional[Elasticsearch] = None,
) -> Dict[str, Any]:
    """Contratação pública em que o município é adjudicante.

    Recebe os nomes com que a câmara aparece no Portal BASE (ex.: «Município de
    Lisboa», «Câmara Municipal da Guarda», «Serviços Municipalizados … de
    Abrantes») e devolve totais, série anual e principais fornecedores.

    Com `ano`, o mesmo é calculado **para esse ano** (`ano_total`, `ano_valor`,
    `ano_fornecedores`, `ano_tipos`) sem se perder a série: a agregação do ano é
    um filtro dentro da consulta, não a consulta. É o que permite abrir a área de
    um município já no ano escolhido na lista.
    """
    client = es or get_es_client()
    if not client:
        return {"error": "Elasticsearch indisponível"}
    nomes = [str(n) for n in (nomes_adjudicante or []) if n]
    if not nomes:
        return {"total": 0, "valor": 0.0, "por_ano": {}, "fornecedores": []}

    query = {
        "nested": {
            "path": "adjudicantes.parsed",
            "query": {"terms": {"adjudicantes.parsed.nome": nomes}},
        }
    }

    def _fornecedores() -> Dict[str, Any]:
        return {
            "nested": {"path": "adjudicatarios.parsed"},
            "aggs": {
                "nomes": {
                    "terms": {"field": "adjudicatarios.parsed.nome", "size": max(1, fornecedores)},
                    "aggs": {"raiz": {"reverse_nested": {}, "aggs": {"valor": {"sum": {"field": "precoContratual"}}}}},
                }
            },
        }

    def _tipos() -> Dict[str, Any]:
        return {
            "terms": {"field": "tipoContrato", "size": 10},
            "aggs": {"valor": {"sum": {"field": "precoContratual"}}},
        }

    def _cpv() -> Dict[str, Any]:
        """Tipos de despesa pela **divisão do CPV** (os 2 primeiros dígitos).

        O CPV é a classificação europeia do objeto do contrato: `45…` é obra,
        `30…` equipamento informático, `55…` restauração, `79…` serviços
        profissionais. Agrupar pela divisão dá o «tipo de despesa»; o `top_hits`
        traz uma descrição real do BASE para servir de exemplo.
        """
        return {
            "nested": {"path": "cpv"},
            "aggs": {
                "divisoes": {
                    "terms": {
                        "script": {"source": "doc['cpv.code'].value.substring(0,2)"},
                        "size": 25,
                    },
                    "aggs": {
                        "contratos": {
                            "reverse_nested": {},
                            "aggs": {"valor": {"sum": {"field": "precoContratual"}}},
                        },
                        "exemplo": {"top_hits": {"size": 1, "_source": ["cpv.description"]}},
                    },
                }
            },
        }

    aggs: Dict[str, Any] = {
        "valor": {"sum": {"field": "precoContratual"}},
        "por_ano": {
            "date_histogram": {
                "field": "dataCelebracaoContrato",
                "calendar_interval": "year",
                "format": "yyyy",
                "min_doc_count": 1,
            },
            "aggs": {"valor": {"sum": {"field": "precoContratual"}}},
        },
        "fornecedores": _fornecedores(),
        "tipos": _tipos(),
        "cpv": _cpv(),
    }
    if ano:
        aggs["ano"] = {
            "filter": {
                "range": {
                    "dataCelebracaoContrato": {"gte": f"{int(ano)}-01-01", "lte": f"{int(ano)}-12-31"}
                }
            },
            "aggs": {
                "valor": {"sum": {"field": "precoContratual"}},
                "maximo": {"max": {"field": "precoContratual"}},
                "fornecedores": _fornecedores(),
                "tipos": _tipos(),
                "cpv": _cpv(),
            },
        }

    body = {"size": 0, "query": query, "aggs": aggs}
    try:
        resp = client.search(index=CONTRACTS_INDEX, body=body)
    except Exception as exc:
        logger.warning("Contratos do município falharam: %s", exc)
        return {"error": str(exc), "total": 0, "valor": 0.0, "por_ano": {}, "fornecedores": []}

    total = int((resp.get("hits", {}).get("total") or {}).get("value") or 0)
    aggs = resp.get("aggregations", {})
    serie = {
        str(b.get("key_as_string") or b.get("key")): {
            "contratos": b["doc_count"],
            "valor": (b.get("valor", {}) or {}).get("value") or 0.0,
        }
        for b in (aggs.get("por_ano", {}) or {}).get("buckets", [])
    }
    tops = [
        {
            "nome": b["key"],
            "contratos": b["doc_count"],
            "valor": ((b.get("raiz", {}) or {}).get("valor", {}) or {}).get("value") or 0.0,
        }
        for b in ((aggs.get("fornecedores", {}) or {}).get("nomes", {}) or {}).get("buckets", [])
    ]
    def _lista_tipos(bloco: Dict[str, Any]) -> List[Dict[str, Any]]:
        return [
            {
                "key": b["key"],
                "count": b["doc_count"],
                "valor": (b.get("valor", {}) or {}).get("value") or 0.0,
            }
            for b in (bloco.get("buckets", []) or [])
        ]

    def _lista_cpv(bloco: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Tipos de despesa por divisão de CPV, do maior valor para o menor."""
        linhas = []
        for b in ((bloco.get("divisoes", {}) or {}).get("buckets") or []):
            contratos_cpv = b.get("contratos", {}) or {}
            exemplos = ((b.get("exemplo", {}) or {}).get("hits", {}) or {}).get("hits") or []
            descricao = None
            if exemplos:
                cpvs = (exemplos[0].get("_source") or {}).get("cpv") or []
                if cpvs:
                    descricao = cpvs[0].get("description")
            linhas.append(
                {
                    "divisao": str(b["key"]),
                    "descricao": descricao,
                    "contratos": int(contratos_cpv.get("doc_count") or 0),
                    "valor": (contratos_cpv.get("valor", {}) or {}).get("value") or 0.0,
                }
            )
        return sorted(linhas, key=lambda linha: -linha["valor"])

    resposta = {
        "total": total,
        "valor": (aggs.get("valor", {}) or {}).get("value") or 0.0,
        "por_ano": dict(sorted(serie.items(), reverse=True)[: max(1, anos)]),
        "fornecedores": tops,
        "tipos": _lista_tipos(aggs.get("tipos", {}) or {}),
        "cpv": _lista_cpv(aggs.get("cpv", {}) or {}),
    }

    bloco_ano = aggs.get("ano") or {}
    if ano and bloco_ano:
        resposta["ano"] = int(ano)
        resposta["ano_total"] = int(bloco_ano.get("doc_count") or 0)
        resposta["ano_valor"] = (bloco_ano.get("valor", {}) or {}).get("value") or 0.0
        resposta["ano_maximo"] = (bloco_ano.get("maximo", {}) or {}).get("value")
        resposta["ano_fornecedores"] = [
            {
                "nome": b["key"],
                "contratos": b["doc_count"],
                "valor": ((b.get("raiz", {}) or {}).get("valor", {}) or {}).get("value") or 0.0,
            }
            for b in ((bloco_ano.get("fornecedores", {}) or {}).get("nomes", {}) or {}).get("buckets", [])
        ]
        resposta["ano_tipos"] = _lista_tipos(bloco_ano.get("tipos", {}) or {})
        resposta["ano_cpv"] = _lista_cpv(bloco_ano.get("cpv", {}) or {})
    return resposta
