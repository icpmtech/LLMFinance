"""Empresas/entidades: cadastro, marcas, firmas, papéis e relações.

Módulo do pacote :mod:`api.es` — ver `api/elasticsearch_client.py`,
que continua a expor a API pública (os coletores/serviços importam de lá).
"""
import json
import logging
import os
import re
import threading
import time
import unicodedata
from typing import Any, Dict, Iterable, List, Optional, Tuple

from elasticsearch import Elasticsearch
from elasticsearch.helpers import bulk
from api.es.core import ROOT, _today, get_es_client
from api.es.geo import _region_filter
from api.es.indices import CONTRACTS_INDEX, ENTITIES_INDEX, FIRMAS_INDEX, TRADEMARKS_INDEX, WORLD_RELATIONS_INDEX
from api.es.mappings import ensure_indices

logger = logging.getLogger(__name__)




# --- Diretório de empresas (entidades) ---

def _entity_lookup_by_nif_query(nif: str) -> Dict[str, Any]:
    """Devolve uma query nested que procura uma entidade por NIF em ambos os papéis."""
    return {
        "bool": {
            "should": [
                {"nested": {"path": "adjudicantes.parsed", "query": {"term": {"adjudicantes.parsed.nif": nif}}}},
                {"nested": {"path": "adjudicatarios.parsed", "query": {"term": {"adjudicatarios.parsed.nif": nif}}}},
            ],
            "minimum_should_match": 1,
        }
    }




def get_company_by_nif(
    nif: str,
    es: Optional[Elasticsearch] = None,
) -> Dict[str, Any]:
    """Devolve resumo de uma entidade específica pelo NIF.

    Faz uma pesquisa nested com agregações por papel, devolvendo a estrutura
    CompanySummary (nif, name, total_value, adjudicante/adjudicatario, etc.).
    """
    client = es or get_es_client()
    if not client:
        return {"error": "Elasticsearch indisponível"}

    ensure_indices(client)

    try:
        resp = client.search(
            index=CONTRACTS_INDEX,
            body={
                "size": 0,
                "query": _entity_lookup_by_nif_query(nif),
                "aggs": {
                    "adjudicantes": {
                        "nested": {"path": "adjudicantes.parsed"},
                        "aggs": {
                            "filtered": {
                                "filter": {"term": {"adjudicantes.parsed.nif": nif}},
                                "aggs": {
                                    "name": {"top_hits": {"size": 1, "_source": ["adjudicantes.parsed.nome"]}},
                                    "total_value": {
                                        "reverse_nested": {},
                                        "aggs": {"value": {"sum": {"field": "precoContratual"}}},
                                    },
                                    "years": {
                                        "reverse_nested": {},
                                        "aggs": {"stats": {"stats": {"field": "Ano"}}},
                                    },
                                    "count": {"reverse_nested": {}},
                                },
                            }
                        },
                    },
                    "adjudicatarios": {
                        "nested": {"path": "adjudicatarios.parsed"},
                        "aggs": {
                            "filtered": {
                                "filter": {"term": {"adjudicatarios.parsed.nif": nif}},
                                "aggs": {
                                    "name": {"top_hits": {"size": 1, "_source": ["adjudicatarios.parsed.nome"]}},
                                    "total_value": {
                                        "reverse_nested": {},
                                        "aggs": {"value": {"sum": {"field": "precoContratual"}}},
                                    },
                                    "years": {
                                        "reverse_nested": {},
                                        "aggs": {"stats": {"stats": {"field": "Ano"}}},
                                    },
                                    "count": {"reverse_nested": {}},
                                },
                            }
                        },
                    },
                },
            },
        )

        aggs = resp["aggregations"]

        def fmt_money(v):
            return round(v, 2) if v is not None else None

        def build_role_summary(agg_key: str) -> Optional[Dict[str, Any]]:
            bucket = aggs.get(agg_key, {}).get("filtered", {})
            doc_count = bucket.get("doc_count", 0)
            if not doc_count:
                return None
            name_hits = bucket.get("name", {}).get("hits", {}).get("hits", [])
            name_from_hit: Optional[str] = None
            if name_hits:
                src = name_hits[0].get("_source", {})
                if isinstance(src, dict):
                    name_from_hit = src.get("nome")
            total_value_obj = bucket.get("total_value", {})
            value = total_value_obj.get("value", {}).get("value") if isinstance(total_value_obj.get("value"), dict) else total_value_obj.get("value")
            years_stats = bucket.get("years", {}).get("stats", {})
            first_year = years_stats.get("min")
            last_year = years_stats.get("max")
            return {
                "contracts_count": doc_count,
                "total_value": fmt_money(value) or 0.0,
                "avg_value": fmt_money(value / doc_count) if value and doc_count else None,
                "first_year": int(first_year) if first_year is not None else None,
                "last_year": int(last_year) if last_year is not None else None,
                "name": name_from_hit,
            }

        adjudicante = build_role_summary("adjudicantes")
        adjudicatario = build_role_summary("adjudicatarios")
        contracts_total = (adjudicante["contracts_count"] if adjudicante else 0) + (adjudicatario["contracts_count"] if adjudicatario else 0)
        total_value = (adjudicante["total_value"] if adjudicante else 0.0) + (adjudicatario["total_value"] if adjudicatario else 0.0)

        # Escolhe o nome mais comum entre os papéis
        names: List[str] = []
        for key in ("adjudicantes", "adjudicatarios"):
            role_summary = adjudicante if key == "adjudicantes" else adjudicatario
            if role_summary and role_summary.get("name"):
                names.append(role_summary["name"])
        name = names[0] if names else nif

        cae_principal = None
        caes_secundarios = None
        try:
            ids_res = client.search(
                index=ENTITIES_INDEX,
                body={
                    "size": 1,
                    "query": {"term": {"nif": nif}},
                    "_source": ["nif", "cae_principal", "caes_secundarios"],
                },
            )
            src = (ids_res.get("hits", {}).get("hits", [{}])[0] or {}).get("_source")
            if src:
                cae_principal = src.get("cae_principal") or None
                caes_secundarios = src.get("caes_secundarios") or None
        except Exception:
            pass

        return {
            "nif": nif,
            "name": name,
            "normalized_name": name,
            "contracts_total": contracts_total,
            "total_value": fmt_money(total_value) or 0.0,
            "adjudicante": adjudicante,
            "adjudicatario": adjudicatario,
            "cae_principal": cae_principal,
            "caes_secundarios": caes_secundarios,
        }
    except Exception as e:
        return {"error": str(e)}




def _company_role_filter(role: Optional[str]) -> Optional[List[Dict[str, Any]]]:
    """Devolve filtro de caminho nested conforme o papel pretendido."""
    if role == "adjudicante":
        return [{"nested": {"path": "adjudicantes.parsed", "query": {"exists": {"field": "adjudicantes.parsed.nif"}}}}]
    if role == "adjudicatario":
        return [{"nested": {"path": "adjudicatarios.parsed", "query": {"exists": {"field": "adjudicatarios.parsed.nif"}}}}]
    return None




def _entity_matches_query(name: Optional[str], nif: Optional[str], q: str) -> bool:
    """A entidade casa com a pesquisa pelo **próprio** nome (tokens, por qualquer ordem) ou NIF.

    A query de contratos (`_company_name_query`) encontra os contratos em que
    *alguma* das partes casa com a pesquisa, mas a agregação por papel devolve
    depois **todas** as entidades desses contratos — incluindo as contrapartes
    (quem comprou à empresa procurada). O campo de pesquisa pede entidades, pelo
    que a lista é limitada às que casam pelo seu nome; sem acentos e sem
    distinguir maiúsculas, com cada termo a casar o início de uma palavra.
    """
    termo = (q or "").strip()
    if not termo:
        return True
    if nif and termo == nif.strip():
        return True
    termos = [t for t in _searchable_name(termo).split() if t]
    if not termos:
        return False
    palavras = _searchable_name(name or "").split()
    return all(any(palavra.startswith(termo_) for palavra in palavras) for termo_ in termos)




def _searchable_name(value: str) -> str:
    """Nome comparável: sem acentos, minúsculas e pontuação reduzida a espaços."""
    text = unicodedata.normalize("NFKD", str(value or ""))
    text = "".join(char for char in text if not unicodedata.combining(char))
    return re.sub(r"[^a-z0-9]+", " ", text.casefold()).strip()




def _company_window_truncated(resp: Dict[str, Any], role: Optional[str] = None) -> bool:
    """A agregação por papel devolveu menos NIF do que os que casaram os filtros?

    O `terms` por papel devolve só os NIF de maior valor; `sum_other_doc_count`
    positivo significa que a janela foi cortada (o papel pedido, se indicado).
    """
    if role == "adjudicante":
        chaves: Tuple[str, ...] = ("adjudicantes",)
    elif role == "adjudicatario":
        chaves = ("adjudicatarios",)
    else:
        chaves = ("adjudicantes", "adjudicatarios")
    for agg_key in chaves:
        by_nif = resp.get("aggregations", {}).get(agg_key, {}).get("by_nif", {}) or {}
        if int(by_nif.get("sum_other_doc_count", 0) or 0) > 0:
            return True
    return False




def _company_name_query(q: Optional[str]) -> Optional[Dict[str, Any]]:
    """Query de texto para nome ou NIF de empresa em qualquer um dos papéis.

    O nome em `*.parsed.nome` é um campo `keyword` (só corresponde a nomes
    exatos), pelo que a pesquisa por nome parcial usa o campo de texto
    `*.raw` (ex.: ``"503933813 - Infraestruturas de Portugal"``), insensível a
    maiúsculas e a palavras parciais.
    """
    if not q:
        return None
    q_clean = q.strip()
    if not q_clean:
        return None
    should_clauses: List[Dict[str, Any]] = []
    for role_path in ("adjudicantes", "adjudicatarios"):
        should_clauses.append(
            {"match": {f"{role_path}.raw": {"query": q_clean, "operator": "and"}}}
        )
        should_clauses.append(
            {
                "nested": {
                    "path": f"{role_path}.parsed",
                    "query": {"match": {f"{role_path}.parsed.nome": {"query": q_clean, "operator": "and"}}},
                }
            }
        )
        should_clauses.append(
            {
                "nested": {
                    "path": f"{role_path}.parsed",
                    "query": {"term": {f"{role_path}.parsed.nif": q_clean}},
                }
            }
        )
    return {
        "bool": {
            "should": should_clauses,
            "minimum_should_match": 1,
        }
    }




def _normalize_cae_codes(cae: Optional[str | list[str]]) -> List[str]:
    """Converte um ou mais códigos CAE numa lista limpa de strings."""
    if cae is None:
        return []
    if isinstance(cae, str):
        values = [cae]
    else:
        values = list(cae)
    codes: List[str] = []
    for raw in values:
        for part in str(raw).split(","):
            code = part.strip()
            if code:
                codes.append(code)
    return codes




def _cae_code_clause(field: str, code: str) -> Dict[str, Any]:
    """Cláusula ES para um código CAE completo (5 dígitos) ou parcial (prefix)."""
    code = code.strip()
    return (
        {"term": {field: code}}
        if re.fullmatch(r"\d{5}", code)
        else {"prefix": {field: code}}
    )




def entity_nifs_for_cae(
    cae: Optional[str | list[str]] = None,
    limit: int = 2000,
    es: Optional[Elasticsearch] = None,
) -> Dict[str, Any]:
    """NIFs do cadastro de entidades com o(s) CAE indicado(s) (principal ou secundário).

    O C.A.E. vive no **cadastro** de entidades, não nos contratos: para filtrar
    as entidades derivadas de contratos por CAE é preciso esta passagem prévia.
    Aceita um ou vários códigos (string, lista ou string separada por vírgulas).
    Código completo (5 dígitos) → termo; parcial → prefixo (`464` cobre `46460`).
    Trava a lista em `limit`; quando corta, o chamador é avisado (`truncated`).
    """
    client = es or get_es_client()
    codes = _normalize_cae_codes(cae)
    if not client or not codes:
        return {"nifs": [], "truncated": False, "matched": 0, "codes": codes}

    ensure_indices(client)

    limites = max(1, min(10000, limit))

    def _clauses_for_code(code: str) -> List[Dict[str, Any]]:
        return [_cae_code_clause("cae_principal", code), _cae_code_clause("caes_secundarios", code)]

    # Cada código CAE gera um grupo should[principal, secundarios]; os grupos
    # são combinados com should de códigos (OR entre CAEs) porque um NIF pode
    # ter qualquer um dos códigos selecionados.
    code_shoulds: List[Dict[str, Any]] = []
    for code in codes:
        clauses = _clauses_for_code(code)
        code_shoulds.append({"bool": {"should": clauses, "minimum_should_match": 1}})

    try:
        resp = client.search(
            index=ENTITIES_INDEX,
            body={
                "size": limites,
                "track_total_hits": True,
                "_source": ["nif", "name"],
                "query": {
                    "bool": {
                        "filter": [
                            {"bool": {"should": code_shoulds, "minimum_should_match": 1}}
                        ]
                    }
                },
            },
        )
    except Exception as exc:
        return {"error": str(exc), "nifs": [], "truncated": False, "matched": 0, "codes": codes}

    nifs: List[str] = []
    vistos: set[str] = set()
    for hit in resp.get("hits", {}).get("hits", []):
        nif = str((hit.get("_source") or {}).get("nif") or "").strip()
        if not nif or nif in vistos:
            continue
        vistos.add(nif)
        nifs.append(nif)
    total = resp.get("hits", {}).get("total", {})
    total_valor = total.get("value") if isinstance(total, dict) else total
    return {
        "nifs": nifs,
        "truncated": bool(total_valor and int(total_valor) > len(nifs)),
        "matched": len(nifs),
        "codes": codes,
    }




def search_companies(
    q: Optional[str] = None,
    role: Optional[str] = "all",
    region: Optional[str] = None,
    min_contracts: int = 1,
    min_value: Optional[float] = None,
    max_value: Optional[float] = None,
    year: Optional[int] = None,
    cpv: Optional[str] = None,
    cae: Optional[str | list[str]] = None,
    size: int = 20,
    from_: int = 0,
    es: Optional[Elasticsearch] = None,
    include_cae: bool = True,
) -> Dict[str, Any]:
    """Pesquisa entidades únicas derivadas dos contratos indexados.

    Utiliza duas agregações nested por NIF (adjudicantes/adjudicatarios) e depois
    combina os resultados em memória para devolver uma lista paginada de empresas.

    `cpv` filtra pelos contratos dessa classificação; `cae` cruza primeiro com o
    cadastro de entidades (é lá que o C.A.E. vive) e só considera contratos
    desses NIF.
    """
    client = es or get_es_client()
    if not client:
        return {"error": "Elasticsearch indisponível", "total": 0, "items": []}

    ensure_indices(client)

    notes: List[str] = []
    base_filters: List[Dict[str, Any]] = []
    if year:
        base_filters.append({"term": {"Ano": year}})
    if region:
        base_filters.append(_region_filter(region))
    role_filter = _company_role_filter(role)
    if role_filter:
        base_filters.extend(role_filter)
    if cpv:
        code = cpv.strip()
        if code:
            base_filters.append({
                "nested": {
                    "path": "cpv",
                    "query": (
                        {"term": {"cpv.code": code}}
                        if re.fullmatch(r"\d{8}(-\d)?", code)
                        else {"prefix": {"cpv.code": code}}
                    ),
                }
            })
            notes.append(f"Contratos filtrados pelo CPV {code}.")
    if cae:
        resolvido = entity_nifs_for_cae(cae, es=client)
        if resolvido.get("error"):
            return {"error": resolvido["error"], "total": 0, "items": []}
        nifs_cae = resolvido.get("nifs") or []
        codes = resolvido.get("codes") or []
        codes_text = ", ".join(codes)
        if not nifs_cae:
            return {
                "query": q,
                "total": 0,
                "items": [],
                "from": from_,
                "size": size,
                "notes": [f"Nenhuma entidade do cadastro com o CAE {codes_text}."],
            }
        base_filters.append({
            "bool": {
                "should": [
                    {"nested": {"path": "adjudicantes.parsed", "query": {"terms": {"adjudicantes.parsed.nif": nifs_cae}}}},
                    {"nested": {"path": "adjudicatarios.parsed", "query": {"terms": {"adjudicatarios.parsed.nif": nifs_cae}}}},
                ],
                "minimum_should_match": 1,
            }
        })
        notes.append(
            f"CAE {codes_text}: {len(nifs_cae)} entidades do cadastro com esse(s) CAE."
        )
        if resolvido.get("truncated"):
            notes.append(f"A lista de entidades do CAE foi limitada a {len(nifs_cae)}.")

    name_query = _company_name_query(q)

    # A janela de cada papel (`terms`) devolve os NIF de maior valor. Numa
    # pesquisa por nome o universo de contratos já vem estreitado pelo nome, pelo
    # que se alarga a janela para caberem as entidades correspondentes.
    role_terms_size = 5000 if name_query else 2000

    base_query: Dict[str, Any] = {"bool": {}}
    if base_filters:
        base_query["bool"]["filter"] = base_filters
    if name_query:
        base_query["bool"]["must"] = name_query
    if not base_query["bool"]:
        base_query = {"match_all": {}}

    try:
        resp = client.search(
            index=CONTRACTS_INDEX,
            body={
                "size": 0,
                "query": base_query,
                "aggs": {
                    "adjudicantes": {
                        "nested": {"path": "adjudicantes.parsed"},
                        "aggs": {
                            "by_nif": {
                                "terms": {
                                    "field": "adjudicantes.parsed.nif",
                                    "size": role_terms_size,
                                    "order": {"total_value": "desc"},
                                },
                                "aggs": {
                                    "name": {
                                        "top_hits": {"size": 1, "_source": ["adjudicantes.parsed.nome"]}
                                    },
                                    "total_value": {
                                        "reverse_nested": {},
                                        "aggs": {"value": {"sum": {"field": "precoContratual"}}},
                                    },
                                    "years": {
                                        "reverse_nested": {},
                                        "aggs": {"stats": {"stats": {"field": "Ano"}}},
                                    },
                                },
                            }
                        },
                    },
                    "adjudicatarios": {
                        "nested": {"path": "adjudicatarios.parsed"},
                        "aggs": {
                            "by_nif": {
                                "terms": {
                                    "field": "adjudicatarios.parsed.nif",
                                    "size": role_terms_size,
                                    "order": {"total_value": "desc"},
                                },
                                "aggs": {
                                    "name": {
                                        "top_hits": {"size": 1, "_source": ["adjudicatarios.parsed.nome"]}
                                    },
                                    "total_value": {
                                        "reverse_nested": {},
                                        "aggs": {"value": {"sum": {"field": "precoContratual"}}},
                                    },
                                    "years": {
                                        "reverse_nested": {},
                                        "aggs": {"stats": {"stats": {"field": "Ano"}}},
                                    },
                                },
                            }
                        },
                    },
                    # Contagens reais de NIF distintos (a lista acima é limitada aos
                    # 2000 maiores por papel, pelo que `total` é sempre um limite
                    # inferior do universo de entidades).
                    "unique_adjudicantes": {
                        "nested": {"path": "adjudicantes.parsed"},
                        "aggs": {
                            "nifs": {
                                "cardinality": {
                                    "field": "adjudicantes.parsed.nif",
                                    "precision_threshold": 40000,
                                }
                            }
                        },
                    },
                    "unique_adjudicatarios": {
                        "nested": {"path": "adjudicatarios.parsed"},
                        "aggs": {
                            "nifs": {
                                "cardinality": {
                                    "field": "adjudicatarios.parsed.nif",
                                    "precision_threshold": 40000,
                                }
                            }
                        },
                    },
                },
            },
        )

        companies: Dict[str, Dict[str, Any]] = {}

        def fmt_money(v):
            return round(v, 2) if v is not None else None

        for agg_key in ("adjudicantes", "adjudicatarios"):
            role_name = "adjudicante" if agg_key == "adjudicantes" else "adjudicatario"
            for b in resp["aggregations"][agg_key]["by_nif"]["buckets"]:
                nif = b["key"]
                name_hits = b.get("name", {}).get("hits", {}).get("hits", [])
                name = nif or "Nome desconhecido"
                if name_hits:
                    src = name_hits[0].get("_source", {})
                    if isinstance(src, dict):
                        name = src.get("nome") or name
                total_value_obj = b.get("total_value", {})
                value = total_value_obj.get("value", {}).get("value") if isinstance(total_value_obj.get("value"), dict) else total_value_obj.get("value")
                total_value = value or 0.0
                years_stats = b.get("years", {}).get("stats", {})
                first_year = years_stats.get("min")
                last_year = years_stats.get("max")
                count = b["doc_count"]

                if count < min_contracts:
                    continue
                if min_value is not None and total_value < min_value:
                    continue
                if max_value is not None and total_value > max_value:
                    continue

                if nif and nif not in companies:
                    companies[nif] = {
                        "nif": nif,
                        "name": name,
                        "normalized_name": name,
                        "contracts_total": 0,
                        "total_value": 0.0,
                        "adjudicante": None,
                        "adjudicatario": None,
                        "cae_principal": None,
                        "caes_secundarios": None,
                    }
                if not nif:
                    key = f"__no_nif__{name.lower().strip()}"
                    if key not in companies:
                        companies[key] = {
                            "nif": None,
                            "name": name,
                            "normalized_name": name,
                            "contracts_total": 0,
                            "total_value": 0.0,
                            "adjudicante": None,
                            "adjudicatario": None,
                            "cae_principal": None,
                            "caes_secundarios": None,
                        }

                entry = companies[nif if nif else key]
                role_summary = {
                    "contracts_count": count,
                    "total_value": fmt_money(total_value) or 0.0,
                    "avg_value": fmt_money(total_value / count) if count else None,
                    "first_year": int(first_year) if first_year is not None else None,
                    "last_year": int(last_year) if last_year is not None else None,
                }
                entry[role_name] = role_summary
                entry["contracts_total"] = (entry["contracts_total"] or 0) + count
                entry["total_value"] = (entry["total_value"] or 0.0) + total_value

        items = sorted(companies.values(), key=lambda x: (x.get("total_value") or 0, x.get("contracts_total") or 0), reverse=True)
        if cae and nifs_cae:
            # Sem isto a pesquisa por CAE devolvia também as contrapartes dessas
            # empresas (quem lhes comprou): o pedido é pelas entidades *com* o CAE.
            permitidos = set(nifs_cae)
            items = [item for item in items if (item.get("nif") or "") in permitidos]
        if role in ("adjudicante", "adjudicatario"):
            # `_company_role_filter` restringe os *contratos* considerados, mas a
            # lista juntava os dois papéis: pedir «adjudicantes» devolvia também
            # os adjudicatários desses contratos (as contrapartes). O pedido é
            # pelas entidades que efetivamente têm esse papel.
            items = [item for item in items if item.get(role)]
        if name_query:
            # A pesquisa por nome página os *contratos*: a lista trazia também as
            # contrapartes (quem comprou à empresa procurada). O campo pede
            # entidades, pelo que fica só quem casa pelo próprio nome (ou NIF).
            items = [
                item for item in items
                if _entity_matches_query(item.get("name"), item.get("nif"), q or "")
            ]
        total = len(items)
        page = items[from_: from_ + size]
        for it in page:
            it["total_value"] = fmt_money(it["total_value"]) or 0.0

        if include_cae:
            nifs_to_enrich = [it["nif"] for it in page if it.get("nif")]
            if nifs_to_enrich:
                try:
                    ids_res = client.search(
                        index=ENTITIES_INDEX,
                        body={
                            "size": len(nifs_to_enrich),
                            "query": {"terms": {"nif": nifs_to_enrich}},
                            "_source": ["nif", "cae_principal", "caes_secundarios"],
                        },
                    )
                    cae_by_nif: Dict[str, Dict[str, Any]] = {
                        h["_source"].get("nif"): h["_source"]
                        for h in ids_res.get("hits", {}).get("hits", [])
                        if h.get("_source", {}).get("nif")
                    }
                    for it in page:
                        src = cae_by_nif.get(it["nif"])
                        if src:
                            it["cae_principal"] = src.get("cae_principal") or None
                            it["caes_secundarios"] = src.get("caes_secundarios") or None
                except Exception:
                    pass

        unique_adjudicantes = resp["aggregations"].get("unique_adjudicantes", {}).get("nifs", {}).get("value", 0)
        unique_adjudicatarios = resp["aggregations"].get("unique_adjudicatarios", {}).get("nifs", {}).get("value", 0)

        if name_query:
            # Com pesquisa por nome as agregações descrevem os contratos (incluem
            # as contrapartes), pelo que as contagens passam a ser as das
            # entidades correspondentes — as que a lista mostra.
            unique_adjudicantes = sum(1 for item in items if item.get("adjudicante"))
            unique_adjudicatarios = sum(1 for item in items if item.get("adjudicatario"))
            # Nomes comuns (ex.: «construções») têm mais correspondências do que a
            # janela por papel consegue devolver: avisa-se, sem afirmar quantas.
            if _company_window_truncated(resp, role):
                notes.append(
                    f"A lista mostra as {total} entidades correspondentes de maior valor contratual; "
                    "pode haver mais resultados com esse nome."
                )
        else:
            # As agregações por papel devolvem apenas os NIF de maior valor, pelo
            # que a lista paginada pode ser mais curta do que o universo real:
            # sem o aviso, o total parecia contradizer a contagem de NIF distintos.
            distintos_do_papel = {
                "adjudicante": int(unique_adjudicantes or 0),
                "adjudicatario": int(unique_adjudicatarios or 0),
            }.get(role or "")
            if distintos_do_papel and distintos_do_papel > total:
                etiqueta = "adjudicantes" if role == "adjudicante" else "adjudicatárias"
                notes.append(
                    f"A lista mostra as {total} {etiqueta} de maior valor contratual; "
                    f"o universo filtrado tem {distintos_do_papel}."
                )

        return {
            "query": q,
            "total": total,
            "items": page,
            "from": from_,
            "size": size,
            "unique_adjudicantes": int(unique_adjudicantes or 0),
            "unique_adjudicatarios": int(unique_adjudicatarios or 0),
            "notes": notes,
        }
    except Exception as e:
        return {"query": q, "total": 0, "items": [], "error": str(e)}




# ---------------------------------------------------------------------------
# Resumo agregado por papel (dashboards de entidades)
# ---------------------------------------------------------------------------
#
# A agregação é intrinsecamente pesada: o ranking de entidades ordena um `terms`
# **aninhado** por um `reverse_nested` + `sum`, o que obriga o Elasticsearch a
# calcular o valor de **todos** os NIF (~11 mil adjudicantes, ~93 mil
# adjudicatários) antes de escolher o topo. Medido neste índice: ~20 s para um só
# papel e ~100 s para o resumo completo — mais do que o `request_timeout` de 30 s
# do cliente, o que dava `502 Connection timed out` na página.
#
# A `request cache` do Elasticsearch não resolve (o índice é reescrito
# continuamente pelas recolhas, e a cache é invalidada a cada refresh), por isso o
# resultado é materializado aqui: quem pede recebe já o valor anterior — marcado
# como `stale` — enquanto a versão nova é calculada em segundo plano.
ENTITY_ROLE_SUMMARY_TTL = float(os.getenv("ENTITY_ROLE_SUMMARY_TTL", "1800"))


ENTITY_ROLE_SUMMARY_TIMEOUT = int(os.getenv("ENTITY_ROLE_SUMMARY_TIMEOUT", "300"))


#: O serviço é reiniciado com frequência (builds, deploys): guardar a cache em
#: disco evita pagar a agregação outra vez a cada arranque.
ENTITY_ROLE_SUMMARY_CACHE_FILE = ROOT / "logs" / "_cache_entity_role_summary.json"


#: Idade máxima aceite do ficheiro — acima disto é preferível recalcular.
ENTITY_ROLE_SUMMARY_MAX_AGE = float(os.getenv("ENTITY_ROLE_SUMMARY_MAX_AGE", str(7 * 86400)))


_ENTITY_ROLE_SUMMARY_CACHE: Dict[Tuple[Any, ...], Tuple[float, Dict[str, Any]]] = {}


_ENTITY_ROLE_SUMMARY_LOCK = threading.Lock()


#: Constrói em curso, por chave — evita que o aquecimento e um pedido do
#: utilizador disparem a mesma agregação (dezenas de segundos) em paralelo.
_ENTITY_ROLE_SUMMARY_BUILDING: Dict[Tuple[Any, ...], threading.Event] = {}


_ENTITY_ROLE_SUMMARY_MAX = 12


#: O circuito de proteção do Elasticsearch é pequeno (~486 MB) e duas destas
#: agregações ao mesmo tempo disparam um 429; os cálculos ficam em série.
_ENTITY_ROLE_SUMMARY_BUILD_LOCK = threading.Lock()




def _entity_role_summary_key(
    role: Optional[str],
    q: Optional[str],
    year: Optional[int],
    region: Optional[str],
    min_value: Optional[float],
    max_value: Optional[float],
    min_contracts: int,
    top_n: int,
) -> Tuple[Any, ...]:
    return (
        role or "all",
        (q or "").strip().lower(),
        year,
        region or "",
        min_value,
        max_value,
        int(min_contracts),
        int(top_n),
    )




def _entity_role_summary_cache_get(
    key: Tuple[Any, ...],
) -> Tuple[Optional[Dict[str, Any]], bool]:
    """Devolve `(payload, stale)`. `stale` = existe mas passou o TTL."""
    with _ENTITY_ROLE_SUMMARY_LOCK:
        entry = _ENTITY_ROLE_SUMMARY_CACHE.get(key)
    if not entry:
        return None, False
    stamp, payload = entry
    return payload, (time.time() - stamp) > ENTITY_ROLE_SUMMARY_TTL




def _entity_role_summary_cache_put(key: Tuple[Any, ...], payload: Dict[str, Any]) -> None:
    with _ENTITY_ROLE_SUMMARY_LOCK:
        if len(_ENTITY_ROLE_SUMMARY_CACHE) > _ENTITY_ROLE_SUMMARY_MAX:
            _ENTITY_ROLE_SUMMARY_CACHE.clear()
        _ENTITY_ROLE_SUMMARY_CACHE[key] = (time.time(), payload)
    _entity_role_summary_cache_save()




def _entity_role_summary_cache_save() -> None:
    """Grava a cache em disco (falha em silêncio: é só uma otimização)."""
    try:
        with _ENTITY_ROLE_SUMMARY_LOCK:
            entries = [
                {"key": list(key), "at": stamp, "payload": payload}
                for key, (stamp, payload) in _ENTITY_ROLE_SUMMARY_CACHE.items()
            ]
        ENTITY_ROLE_SUMMARY_CACHE_FILE.write_text(
            json.dumps(entries, ensure_ascii=False), encoding="utf-8"
        )
    except Exception as exc:  # pragma: no cover - best effort
        logger.debug("Não foi possível gravar a cache do resumo por papel: %s", exc)




def _entity_role_summary_cache_load() -> None:
    """Recupera a cache do disco (chamado uma vez, no arranque)."""
    if not ENTITY_ROLE_SUMMARY_CACHE_FILE.exists():
        return
    try:
        entries = json.loads(ENTITY_ROLE_SUMMARY_CACHE_FILE.read_text(encoding="utf-8"))
    except Exception as exc:  # pragma: no cover - ficheiro corrompido
        logger.info("Cache do resumo por papel ilegível, a ignorar: %s", exc)
        return
    now = time.time()
    loaded = 0
    with _ENTITY_ROLE_SUMMARY_LOCK:
        for entry in entries or []:
            try:
                key = tuple(entry["key"])
                stamp = float(entry["at"])
                payload = entry["payload"]
            except Exception:
                continue
            if now - stamp > ENTITY_ROLE_SUMMARY_MAX_AGE:
                continue
            _ENTITY_ROLE_SUMMARY_CACHE[key] = (stamp, payload)
            loaded += 1
    if loaded:
        logger.info("Resumo por papel: %d entradas recuperadas do disco", loaded)




def _entity_role_summary_build(key: Tuple[Any, ...], params: Dict[str, Any]) -> Dict[str, Any]:
    """Calcula o resumo uma única vez por chave (os concorrentes esperam)."""
    with _ENTITY_ROLE_SUMMARY_LOCK:
        event = _ENTITY_ROLE_SUMMARY_BUILDING.get(key)
        leader = event is None
        if leader:
            event = threading.Event()
            _ENTITY_ROLE_SUMMARY_BUILDING[key] = event
    assert event is not None

    if not leader:
        # Já há um cálculo a decorrer para estes parâmetros: espera-se por ele.
        event.wait(timeout=ENTITY_ROLE_SUMMARY_TIMEOUT)
        payload, _ = _entity_role_summary_cache_get(key)
        return payload if payload is not None else _compute_entity_role_summary(**params)

    try:
        with _ENTITY_ROLE_SUMMARY_BUILD_LOCK:
            # Outro cálculo pode ter terminado enquanto esperávamos pela vez.
            cached, _ = _entity_role_summary_cache_get(key)
            if cached is not None:
                return cached
            payload = _compute_entity_role_summary(**params)
        if payload and not payload.get("error"):
            _entity_role_summary_cache_put(key, payload)
        return payload
    finally:
        with _ENTITY_ROLE_SUMMARY_LOCK:
            _ENTITY_ROLE_SUMMARY_BUILDING.pop(key, None)
        event.set()




def _entity_role_summary_refresh(key: Tuple[Any, ...], params: Dict[str, Any]) -> None:
    """Recalcula em segundo plano, devolvendo o pedido imediatamente."""

    def worker() -> None:
        try:
            _entity_role_summary_build(key, params)
        except Exception as exc:  # nunca deve derrubar o serviço
            logger.info("Reconstrução do resumo por papel falhou: %s", exc)

    threading.Thread(target=worker, name="role-summary-refresh", daemon=True).start()




def warm_entity_role_summaries(roles: Tuple[str, ...] = ("all", "adjudicante", "adjudicatario")) -> None:
    """Materializa em segundo plano os resumos que as páginas abrem por omissão.

    Sem isto, a primeira abertura do dashboard a seguir a um arranque pagaria os
    ~100 s da agregação à espera do utilizador.
    """

    def worker() -> None:
        for role in roles:
            try:
                get_entity_role_summary(role=role)
            except Exception as exc:  # pragma: no cover - aquecimento
                logger.info("Aquecimento do resumo %s falhou: %s", role, exc)

    threading.Thread(target=worker, name="role-summary-warmup", daemon=True).start()




def get_entity_role_summary(
    role: Optional[str] = "all",
    q: Optional[str] = None,
    year: Optional[int] = None,
    region: Optional[str] = None,
    min_value: Optional[float] = None,
    max_value: Optional[float] = None,
    min_contracts: int = 1,
    top_n: int = 25,
    es: Optional[Elasticsearch] = None,
    use_cache: bool = True,
    force: bool = False,
) -> Dict[str, Any]:
    """Resumo agregado do universo de entidades por papel (com cache).

    O cálculo vive em `_compute_entity_role_summary` e leva dezenas de segundos;
    aqui o resultado é servido da cache (TTL `ENTITY_ROLE_SUMMARY_TTL`). Se a
    entrada já tiver passado o TTL, devolve-se a versão antiga **e** dispara-se a
    reconstrução, para nenhum pedido ficar à espera da agregação.

    `use_cache=False` (ou `force=True`) força o cálculo imediato — usado por
    sondas/testes e para reconstruir quando se sabe que os dados mudaram.
    """
    params: Dict[str, Any] = {
        "role": role,
        "q": q,
        "year": year,
        "region": region,
        "min_value": min_value,
        "max_value": max_value,
        "min_contracts": min_contracts,
        "top_n": top_n,
        "es": es,
    }
    if not use_cache:
        return _compute_entity_role_summary(**params)

    key = _entity_role_summary_key(role, q, year, region, min_value, max_value, min_contracts, top_n)
    payload, stale = _entity_role_summary_cache_get(key)
    if payload is not None and not force:
        if stale:
            # Reconstrói sem partilhar o cliente do pedido (pode ter timeout curto).
            _entity_role_summary_refresh(key, {**params, "es": None})
        return payload

    result = _entity_role_summary_build(key, params)
    return result




def _compute_entity_role_summary(
    role: Optional[str] = "all",
    q: Optional[str] = None,
    year: Optional[int] = None,
    region: Optional[str] = None,
    min_value: Optional[float] = None,
    max_value: Optional[float] = None,
    min_contracts: int = 1,
    top_n: int = 25,
    es: Optional[Elasticsearch] = None,
) -> Dict[str, Any]:
    """Resumo agregado do universo de entidades por papel (adjudicante/adjudicatário).

    Numa única pesquisa devolve tudo o que um dashboard de entidades precisa:
    volume e valor contratual, médias, entidades distintas, distribuição por
    ano/NUTS/CPV/procedimento/tipo de contrato, contrapartes mais frequentes,
    ranking das maiores entidades e a concentração do mercado.

    O parâmetro `role` aceita ``"adjudicante"``, ``"adjudicatario"`` ou
    ``"all"`` (empresas nos dois papéis, com a decomposição por papel).

    Nota: chamar directamente salta a cache de `get_entity_role_summary` e paga os
    ~100 s da agregação; é o que a reconstrução em segundo plano faz.
    """
    client = es or get_es_client(request_timeout=ENTITY_ROLE_SUMMARY_TIMEOUT)
    if not client:
        return {"error": "Elasticsearch indisponível", "role": role, "top_entities": []}

    ensure_indices(client)

    filters: List[Dict[str, Any]] = []
    if year:
        filters.append({"term": {"Ano": year}})
    if region:
        filters.append(_region_filter(region))
    role_filter = _company_role_filter(role)
    if role_filter:
        filters.extend(role_filter)
    if min_value is not None:
        filters.append({"range": {"precoContratual": {"gte": min_value}}})
    if max_value is not None:
        filters.append({"range": {"precoContratual": {"lte": max_value}}})

    name_query = _company_name_query(q)

    base_query: Dict[str, Any] = {"bool": {}}
    if filters:
        base_query["bool"]["filter"] = filters
    if name_query:
        base_query["bool"]["must"] = name_query
    if not base_query["bool"]:
        base_query = {"match_all": {}}

    procedure_agg = _resolve_agg_target(client, "tipoprocedimento")
    contract_agg = _resolve_agg_target(client, "tipoContrato")
    runtime_mappings: Dict[str, Any] = {}
    for resolved in (procedure_agg, contract_agg):
        if resolved.get("runtime"):
            runtime_mappings.update(resolved["runtime"])

    def _role_agg(path: str) -> Dict[str, Any]:
        """Agg nested com o ranking de NIF daquele papel e a contagem distinta."""
        return {
            "nested": {"path": f"{path}.parsed"},
            "aggs": {
                "by_nif": {
                    "terms": {
                        "field": f"{path}.parsed.nif",
                        "size": max(top_n, 10),
                        "order": {"total_value": "desc"},
                    },
                    "aggs": {
                        "name": {"top_hits": {"size": 1, "_source": [f"{path}.parsed.nome"]}},
                        "total_value": {
                            "reverse_nested": {},
                            "aggs": {"value": {"sum": {"field": "precoContratual"}}},
                        },
                        "years": {
                            "reverse_nested": {},
                            "aggs": {"stats": {"stats": {"field": "Ano"}}},
                        },
                    },
                },
                "nifs": {
                    "cardinality": {
                        "field": f"{path}.parsed.nif",
                        "precision_threshold": 40000,
                    }
                },
            },
        }

    # Contrapartes: quem contrata com as entidades do papel pedido.
    counterpart_path = "adjudicatarios" if role == "adjudicante" else "adjudicantes"

    body: Dict[str, Any] = {
        "size": 0,
        "track_total_hits": True,
        "query": base_query,
        "aggs": {
            "total_value": {"sum": {"field": "precoContratual"}},
            "avg_value": {"avg": {"field": "precoContratual"}},
            "max_value": {"max": {"field": "precoContratual"}},
            "by_year": {
                "terms": {"field": "Ano", "size": 50, "order": {"_key": "desc"}},
                "aggs": {"total_value": {"sum": {"field": "precoContratual"}}},
            },
            "by_region": {
                "terms": {"field": "NUTs", "size": 20, "missing": "Não especificado"},
                "aggs": {"total_value": {"sum": {"field": "precoContratual"}}},
            },
            "by_cpv": {
                "nested": {"path": "cpv"},
                "aggs": {
                    "codes": {
                        "terms": {"field": "cpv.code", "size": 15, "order": {"total_value": "desc"}},
                        "aggs": {
                            "description": {"top_hits": {"size": 1, "_source": ["cpv"]}},
                            "total_value": {
                                "reverse_nested": {},
                                "aggs": {"value": {"sum": {"field": "precoContratual"}}},
                            },
                        },
                    }
                },
            },
            "by_procedure_type": {
                "terms": {"field": procedure_agg["field"], "size": 15, "missing": "Não especificado"},
                "aggs": {"total_value": {"sum": {"field": "precoContratual"}}},
            },
            "by_contract_type": {
                "terms": {"field": contract_agg["field"], "size": 15, "missing": "Não especificado"},
                "aggs": {"total_value": {"sum": {"field": "precoContratual"}}},
            },
            "by_value_range": {
                "histogram": {"field": "precoContratual", "interval": 100000, "min_doc_count": 1}
            },
            "counterparties": {
                "nested": {"path": f"{counterpart_path}.parsed"},
                "aggs": {
                    "by_nif": {
                        "terms": {
                            "field": f"{counterpart_path}.parsed.nif",
                            "size": 20,
                            "order": {"total_value": "desc"},
                        },
                        "aggs": {
                            "name": {"top_hits": {"size": 1, "_source": [f"{counterpart_path}.parsed.nome"]}},
                            "total_value": {
                                "reverse_nested": {},
                                "aggs": {"value": {"sum": {"field": "precoContratual"}}},
                            },
                        },
                    }
                },
            },
        },
    }

    # Só se pede o ranking do papel que vai ser consumido (`role_paths` mais
    # abaixo): cada um custa dezenas de segundos, porque o `terms` aninhado tem
    # de calcular o valor de todos os NIF antes de ordenar. Nos dashboards de
    # «adjudicantes»/«adjudicatários» isto corta a consulta para metade.
    if role in (None, "all"):
        needed_role_aggs = ("adjudicantes", "adjudicatarios")
    elif role == "adjudicante":
        needed_role_aggs = ("adjudicantes",)
    else:
        needed_role_aggs = ("adjudicatarios",)
    for name in needed_role_aggs:
        body["aggs"][name] = _role_agg(name)
    if runtime_mappings:
        body["runtime_mappings"] = runtime_mappings

    def _fmt_money(value: Any) -> Optional[float]:
        return round(value, 2) if isinstance(value, (int, float)) else None

    def _agg_value(bucket: Dict[str, Any]) -> float:
        """Lê o valor de um sub-aggregation `total_value` (sum ou reverse_nested/sum)."""
        raw = bucket.get("total_value", {})
        if isinstance(raw.get("value"), dict):
            return float(raw["value"].get("value") or 0.0)
        return float(raw.get("value") or 0.0)

    try:
        resp = client.search(index=CONTRACTS_INDEX, body=body)
        aggs = resp.get("aggregations", {})

        total_contracts = (
            resp.get("hits", {}).get("total", {}).get("value", 0)
            if isinstance(resp.get("hits", {}).get("total"), dict)
            else resp.get("hits", {}).get("total", 0)
        ) or 0
        total_value = float(aggs.get("total_value", {}).get("value") or 0.0)
        avg_value = float(aggs.get("avg_value", {}).get("value") or 0.0)
        max_value = float(aggs.get("max_value", {}).get("value") or 0.0)

        def _rows(agg_name: str) -> List[Dict[str, Any]]:
            return [
                {
                    "key": str(b["key"]),
                    "count": b["doc_count"],
                    "total_value": _fmt_money(_agg_value(b)) or 0.0,
                }
                for b in aggs.get(agg_name, {}).get("buckets", [])
            ]

        by_year = _rows("by_year")
        by_region = _rows("by_region")
        by_procedure_type = _rows("by_procedure_type")
        by_contract_type = _rows("by_contract_type")

        # O histograma devolve chaves numéricas: publica-se o limite inferior
        # (em euros) e uma etiqueta legível para o intervalo. Os escalões
        # negativos (valores anómalos nos dados de origem) são ignorados.
        by_value_range: List[Dict[str, Any]] = []
        for b in aggs.get("by_value_range", {}).get("buckets", []):
            start = int(b["key"])
            if start < 0:
                continue
            if len(by_value_range) >= 12:
                break
            by_value_range.append({
                "key": str(start),
                "count": b["doc_count"],
                "total_value": _fmt_money(_agg_value(b)) or 0.0,
                "description": f"{start:,} – {start + 100000:,} €".replace(",", " "),
            })

        by_cpv: List[Dict[str, Any]] = []
        for b in aggs.get("by_cpv", {}).get("codes", {}).get("buckets", []):
            by_cpv.append({
                "key": str(b["key"]),
                "count": b["doc_count"],
                "total_value": _fmt_money(_agg_value(b)) or 0.0,
                "description": _cpv_description_from_hits(b.get("description"), b["key"]),
            })

        counterparties: List[Dict[str, Any]] = []
        for b in aggs.get("counterparties", {}).get("by_nif", {}).get("buckets", []):
            name_hits = b.get("name", {}).get("hits", {}).get("hits", [])
            label = b["key"]
            if name_hits:
                src = name_hits[0].get("_source", {})
                if isinstance(src, dict):
                    label = src.get("nome") or label
            counterparties.append({
                "key": str(b["key"]),
                "count": b["doc_count"],
                "total_value": _fmt_money(_agg_value(b)) or 0.0,
                "description": label,
            })
        # --- Ranking de entidades (união dos dois papéis quando role == "all") ---
        entities: Dict[str, Dict[str, Any]] = {}
        role_paths = (
            ("adjudicantes", "adjudicante"),
            ("adjudicatarios", "adjudicatario"),
        ) if role in (None, "all") else (
            (("adjudicantes", "adjudicante"),) if role == "adjudicante" else (("adjudicatarios", "adjudicatario"),)
        )

        for agg_key, role_name in role_paths:
            for b in aggs.get(agg_key, {}).get("by_nif", {}).get("buckets", []):
                nif = b.get("key")
                if not nif:
                    continue
                name = nif
                name_hits = b.get("name", {}).get("hits", {}).get("hits", [])
                if name_hits:
                    src = name_hits[0].get("_source", {})
                    if isinstance(src, dict):
                        name = src.get("nome") or name
                count = b["doc_count"]
                value = _agg_value(b)
                years_stats = b.get("years", {}).get("stats", {})
                first_year = years_stats.get("min")
                last_year = years_stats.get("max")

                entry = entities.setdefault(nif, {
                    "nif": nif,
                    "name": name,
                    "normalized_name": name,
                    "contracts_total": 0,
                    "total_value": 0.0,
                    "adjudicante": None,
                    "adjudicatario": None,
                })
                entry[role_name] = {
                    "contracts_count": count,
                    "total_value": _fmt_money(value) or 0.0,
                    "avg_value": _fmt_money(value / count) if count else None,
                    "first_year": int(first_year) if first_year is not None else None,
                    "last_year": int(last_year) if last_year is not None else None,
                }
                entry["contracts_total"] += count
                entry["total_value"] += value

        ranked = [e for e in entities.values() if e["contracts_total"] >= max(min_contracts, 1)]
        ranked.sort(key=lambda x: (x.get("total_value") or 0.0, x.get("contracts_total") or 0), reverse=True)
        top_entities = ranked[:top_n]
        for entry in top_entities:
            entry["total_value"] = _fmt_money(entry["total_value"]) or 0.0

        # Concentração: peso das maiores entidades no valor total (só é
        # significativa quando o ranking cobre todo o universo — sem filtros de
        # texto — pelo que é devolvida como indicador aproximado).
        def _share(n: int) -> Optional[float]:
            if total_value <= 0 or not ranked:
                return None
            top = sum(e.get("total_value") or 0.0 for e in ranked[:n])
            return round(min(1.0, top / total_value), 4)

        unique_adjudicantes = int(aggs.get("adjudicantes", {}).get("nifs", {}).get("value") or 0)
        unique_adjudicatarios = int(aggs.get("adjudicatarios", {}).get("nifs", {}).get("value") or 0)
        if role == "adjudicante":
            unique_entities: Optional[int] = unique_adjudicantes
        elif role == "adjudicatario":
            unique_entities = unique_adjudicatarios
        else:
            # A união exata dos dois papéis exigiria interseção de conjuntos; o
            # maior dos dois é um limite inferior do número de empresas únicas.
            unique_entities = max(unique_adjudicantes, unique_adjudicatarios)

        avg_per_entity = (
            round(total_value / unique_entities, 2) if unique_entities and total_value else None
        )

        return {
            "role": role or "all",
            "query": q,
            "year": year,
            "region": region,
            "total_contracts": int(total_contracts),
            "total_value": _fmt_money(total_value) or 0.0,
            "avg_value": _fmt_money(avg_value),
            "max_value": _fmt_money(max_value),
            "unique_entities": unique_entities,
            "unique_adjudicantes": unique_adjudicantes,
            "unique_adjudicatarios": unique_adjudicatarios,
            "avg_value_per_entity": avg_per_entity,
            "top_entities": top_entities,
            "counterparties": counterparties,
            "by_year": by_year,
            "by_region": by_region,
            "by_cpv": by_cpv,
            "by_procedure_type": by_procedure_type,
            "by_contract_type": by_contract_type,
            "by_value_range": by_value_range,
            "concentration": {
                "top1": _share(1),
                "top5": _share(5),
                "top10": _share(10),
                "top25": _share(25),
                "covered_entities": len(ranked),
            },
            "error": None,
        }
    except Exception as exc:  # pragma: no cover - dependente do cluster
        return {"error": str(exc), "role": role, "top_entities": []}




# --- Marcas INPI (por entidade) e firmas RNPC (Pesquisa de Nomes Existentes) ---

def _enrich_docs_with_company(
    docs: List[Dict[str, Any]],
    company_nif: Optional[str] = None,
    company_name: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """Acrescenta company_nif/company_name a cada documento antes de indexar."""
    enriched = []
    for doc in docs:
        item = dict(doc)
        if company_nif:
            item["company_nif"] = str(company_nif)
        if company_name:
            item["company_name"] = company_name
        enriched.append(item)
    return enriched




def _bulk_index_docs(
    index: str,
    docs: List[Dict[str, Any]],
    id_field: str,
    es: Optional[Elasticsearch] = None,
) -> Dict[str, Any]:
    """Indexa documentos num índice, usando id_field para o _id (idempotente)."""
    client = es or get_es_client()
    if not client:
        return {"error": "Elasticsearch indisponível", "indexed_count": 0}

    ensure_indices(client)
    if not docs:
        return {"index": index, "indexed_count": 0, "total": 0}

    actions = []
    for doc in docs:
        doc_id = doc.get(id_field)
        action: Dict[str, Any] = {"_index": index, "_source": doc}
        if doc_id not in (None, ""):
            action["_id"] = f"{index}:{doc_id}"
        actions.append(action)

    try:
        success, errors = bulk(client, actions, raise_on_error=False, stats_only=False)
        error_count = len(errors) if isinstance(errors, list) else 0
        # Elasticsearch é near-real-time: refrescar garante que os dados ficam
        # imediatamente visíveis na ficha da empresa após o enriquecimento.
        try:
            client.indices.refresh(index=index)
        except Exception:
            pass
        return {
            "index": index,
            "indexed_count": success,
            "errors": error_count,
            "total": len(docs),
            "error_details": [str(e)[:300] for e in errors[:5]] if error_count else [],
        }
    except Exception as exc:
        return {"index": index, "error": str(exc), "indexed_count": 0, "total": len(docs)}




def _delete_stale_company_docs(
    index: str,
    company_nif: str,
    keep_ids: List[str],
    es: Optional[Elasticsearch] = None,
) -> int:
    """Remove documentos de uma empresa que já não constam do resultado atual.

    Evita acumular registos obsoletos quando a ficha é reenriquecida com um
    conjunto de resultados diferente (ex.: marcas entretanto expiradas).
    """
    return _delete_stale_docs(index, "company_nif", company_nif, keep_ids, es=es)




def index_company_trademarks(
    company_nif: Optional[str],
    company_name: str,
    trademarks: List[Dict[str, Any]],
    replace_existing: bool = True,
    es: Optional[Elasticsearch] = None,
) -> Dict[str, Any]:
    """Indexa as marcas INPI de uma empresa no índice TRADEMARKS_INDEX."""
    docs = _enrich_docs_with_company(trademarks, company_nif=company_nif, company_name=company_name)
    result = _bulk_index_docs(TRADEMARKS_INDEX, docs, id_field="nord", es=es)
    if replace_existing and company_nif:
        keep_ids = [f"{TRADEMARKS_INDEX}:{d.get('nord')}" for d in docs if d.get("nord") is not None]
        result["deleted_stale"] = _delete_stale_company_docs(TRADEMARKS_INDEX, str(company_nif), keep_ids, es=es)
    result["company_nif"] = company_nif
    result["company_name"] = company_name
    return result




def index_company_firmas(
    company_nif: Optional[str],
    company_name: str,
    firmas: List[Dict[str, Any]],
    replace_existing: bool = True,
    es: Optional[Elasticsearch] = None,
) -> Dict[str, Any]:
    """Indexa firmas/nomes comerciais (RNPC/PNS) de uma empresa no índice FIRMAS_INDEX."""
    docs = _enrich_docs_with_company(firmas, company_nif=company_nif, company_name=company_name)
    # Usar NIPC quando existe; caso contrário o nome pesquisado + nome da firma.
    for doc in docs:
        doc.setdefault("_doc_key", doc.get("nipc") or f"{doc.get('search_query', '')}|{doc.get('nome', '')}")
    for doc in docs:
        doc["_source_id"] = doc.pop("_doc_key", None)
    result = _bulk_index_docs(FIRMAS_INDEX, docs, id_field="_source_id", es=es)
    if replace_existing and company_nif:
        keep_ids = [f"{FIRMAS_INDEX}:{d.get('_source_id')}" for d in docs if d.get("_source_id")]
        result["deleted_stale"] = _delete_stale_company_docs(FIRMAS_INDEX, str(company_nif), keep_ids, es=es)
    for doc in docs:
        doc.pop("_source_id", None)
    result["company_nif"] = company_nif
    result["company_name"] = company_name
    return result




def get_company_trademarks(
    company_nif: Optional[str] = None,
    company_name: Optional[str] = None,
    holder_name: Optional[str] = None,
    q: Optional[str] = None,
    size: int = 100,
    from_: int = 0,
    es: Optional[Elasticsearch] = None,
) -> Dict[str, Any]:
    """Lê as marcas indexadas de uma empresa (por NIF, nome de empresa ou titular)."""
    client = es or get_es_client()
    if not client:
        return {"error": "Elasticsearch indisponível", "items": [], "total": 0}

    ensure_indices(client)

    should: List[Dict[str, Any]] = []
    if company_nif:
        should.append({"term": {"company_nif": str(company_nif)}})
    if company_name:
        should.append({"match_phrase": {"holder_name": company_name}})
        should.append({"match": {"company_name": company_name}})
    if holder_name:
        should.append({"match_phrase": {"holder_name": holder_name}})
    if q:
        should.append({"match": {"mark_name": q}})

    if not should:
        query: Dict[str, Any] = {"match_all": {}}
    else:
        query = {"bool": {"should": should, "minimum_should_match": 1}}

    try:
        resp = client.search(
            index=TRADEMARKS_INDEX,
            body={
                "query": query,
                "from": from_,
                "size": size,
                "track_total_hits": True,
                # Semelhança do titular primeiro (docs antigos ficam no fim), depois data.
                "sort": [
                    {"holder_similarity": {"order": "desc", "missing": "_last"}},
                    {"application_date": {"order": "desc", "missing": "_last"}},
                ],
            },
        )
        items = [{**hit["_source"], "doc_id": hit["_id"]} for hit in resp["hits"]["hits"]]
        return {
            "company_nif": company_nif,
            "company_name": company_name,
            "total": resp["hits"]["total"]["value"],
            "items": items,
            "from": from_,
            "size": size,
        }
    except Exception as exc:
        return {"error": str(exc), "items": [], "total": 0}




def search_trademarks(
    q: Optional[str] = None,
    holder_name: Optional[str] = None,
    nice_class: Optional[str] = None,
    mark_type: Optional[str] = None,
    current_phase: Optional[str] = None,
    size: int = 20,
    from_: int = 0,
    es: Optional[Elasticsearch] = None,
) -> Dict[str, Any]:
    """Pesquisa global de marcas indexadas no Elasticsearch."""
    client = es or get_es_client()
    if not client:
        return {"error": "Elasticsearch indisponível", "items": [], "total": 0}

    ensure_indices(client)

    must: List[Dict[str, Any]] = []
    filters: List[Dict[str, Any]] = []
    if q:
        must.append({
            "multi_match": {
                "query": q,
                "fields": ["mark_name^3", "holder_name^2", "process_number"],
                "operator": "and",
            }
        })
    if holder_name:
        must.append({"match_phrase": {"holder_name": holder_name}})
    if nice_class:
        filters.append({"term": {"nice_classes": nice_class}})
    if mark_type:
        filters.append({"term": {"mark_type": mark_type}})
    if current_phase:
        filters.append({"term": {"current_phase": current_phase}})

    query: Dict[str, Any]
    if must or filters:
        query = {"bool": {}}
        if must:
            query["bool"]["must"] = must
        if filters:
            query["bool"]["filter"] = filters
    else:
        query = {"match_all": {}}

    try:
        resp = client.search(
            index=TRADEMARKS_INDEX,
            body={
                "query": query,
                "from": from_,
                "size": size,
                "track_total_hits": True,
                "sort": [
                    {"application_date": {"order": "desc", "missing": "_last"}},
                    "_score",
                ],
            },
        )
        items = [{**hit["_source"], "doc_id": hit["_id"], "relevance": hit.get("_score")} for hit in resp["hits"]["hits"]]
        return {"query": q, "total": resp["hits"]["total"]["value"], "items": items, "from": from_, "size": size}
    except Exception as exc:
        return {"error": str(exc), "items": [], "total": 0}




def get_company_firmas(
    company_nif: Optional[str] = None,
    company_name: Optional[str] = None,
    q: Optional[str] = None,
    size: int = 100,
    from_: int = 0,
    es: Optional[Elasticsearch] = None,
) -> Dict[str, Any]:
    """Lê as firmas/nomes comerciais indexados de uma empresa (RNPC/PNS)."""
    client = es or get_es_client()
    if not client:
        return {"error": "Elasticsearch indisponível", "items": [], "total": 0}

    ensure_indices(client)

    should: List[Dict[str, Any]] = []
    if company_nif:
        should.append({"term": {"company_nif": str(company_nif)}})
        should.append({"term": {"nipc": str(company_nif)}})
    if company_name:
        should.append({"match": {"nome": company_name}})
        should.append({"term": {"search_query": company_name}})
    if q:
        should.append({"match": {"nome": q}})

    if not should:
        query: Dict[str, Any] = {"match_all": {}}
    else:
        query = {"bool": {"should": should, "minimum_should_match": 1}}

    try:
        resp = client.search(
            index=FIRMAS_INDEX,
            body={
                "query": query,
                "from": from_,
                "size": size,
                "track_total_hits": True,
                # Semelhança do nome primeiro, depois o score de confundibilidade do RNPC.
                "sort": [
                    {"name_similarity": {"order": "desc", "missing": "_last"}},
                    {"score": {"order": "desc", "missing": "_last"}},
                ],
            },
        )
        items = [{**hit["_source"], "doc_id": hit["_id"]} for hit in resp["hits"]["hits"]]
        return {
            "company_nif": company_nif,
            "company_name": company_name,
            "total": resp["hits"]["total"]["value"],
            "items": items,
            "from": from_,
            "size": size,
        }
    except Exception as exc:
        return {"error": str(exc), "items": [], "total": 0}




def search_firmas(
    q: Optional[str] = None,
    concelho: Optional[str] = None,
    cae: Optional[str] = None,
    situacao: Optional[str] = None,
    min_score: Optional[float] = None,
    size: int = 20,
    from_: int = 0,
    es: Optional[Elasticsearch] = None,
) -> Dict[str, Any]:
    """Pesquisa firmas/nomes comerciais (RNPC) indexados no Elasticsearch."""
    client = es or get_es_client()
    if not client:
        return {"error": "Elasticsearch indisponível", "items": [], "total": 0}

    ensure_indices(client)

    must: List[Dict[str, Any]] = []
    filters: List[Dict[str, Any]] = []
    if q:
        must.append({"match": {"nome": {"query": q, "operator": "and"}}})
    if concelho:
        filters.append({"term": {"concelho": concelho}})
    if cae:
        filters.append({"term": {"cae_principal": cae}})
    if situacao:
        filters.append({"term": {"situacao": situacao}})
    if min_score is not None:
        filters.append({"range": {"score": {"gte": min_score}}})

    query: Dict[str, Any]
    if must or filters:
        query = {"bool": {}}
        if must:
            query["bool"]["must"] = must
        if filters:
            query["bool"]["filter"] = filters
    else:
        query = {"match_all": {}}

    try:
        resp = client.search(
            index=FIRMAS_INDEX,
            body={
                "query": query,
                "from": from_,
                "size": size,
                "track_total_hits": True,
                "sort": [{"score": {"order": "desc", "missing": "_last"}}, "_score"],
            },
        )
        items = [{**hit["_source"], "doc_id": hit["_id"]} for hit in resp["hits"]["hits"]]
        return {"query": q, "total": resp["hits"]["total"]["value"], "items": items, "from": from_, "size": size}
    except Exception as exc:
        return {"error": str(exc), "items": [], "total": 0}




# --- Cadastro de entidades do portal base (finance_entities) ---

def index_entities(
    docs: Iterable[Dict[str, Any]],
    chunk_size: int = 2000,
    max_records: Optional[int] = None,
    refresh: bool = False,
    es: Optional[Elasticsearch] = None,
) -> Dict[str, Any]:
    """Indexa entidades normalizadas no índice ENTITIES_INDEX.

    Aceita qualquer iterável (por exemplo o gerador de ``iter_normalized_entities``),
    pelo que não é necessário carregar o ficheiro todo em memória. O ``_id`` é o NIF
    ou um hash do nome, garantindo reingestões idempotentes.
    """
    from api.entities_service import entity_doc_id

    client = es or get_es_client()
    if not client:
        return {"error": "Elasticsearch indisponível", "indexed_count": 0, "total": 0}

    ensure_indices(client)

    indexed = 0
    errors = 0
    seen = 0
    buffer: List[Dict[str, Any]] = []

    try:
        for doc in docs:
            if max_records is not None and seen >= max_records:
                break
            seen += 1
            source = {k: v for k, v in doc.items() if not k.startswith("_")}
            source["ingested_at"] = _today()
            buffer.append({"_index": ENTITIES_INDEX, "_id": f"{ENTITIES_INDEX}:{entity_doc_id(doc)}", "_source": source})

            if len(buffer) >= chunk_size:
                success, errs = bulk(client, buffer, raise_on_error=False, stats_only=False)
                indexed += success
                errors += len(errs) if isinstance(errs, list) else 0
                buffer = []

        if buffer:
            success, errs = bulk(client, buffer, raise_on_error=False, stats_only=False)
            indexed += success
            errors += len(errs) if isinstance(errs, list) else 0

        if refresh:
            try:
                client.indices.refresh(index=ENTITIES_INDEX)
            except Exception:
                pass

        return {
            "index": ENTITIES_INDEX,
            "indexed_count": indexed,
            "total": seen,
            "errors": errors,
            "message": f"{indexed} entidades indexadas de {seen}",
        }
    except Exception as exc:
        return {"index": ENTITIES_INDEX, "error": str(exc), "indexed_count": indexed, "total": seen}




def entity_nifs_for_cpv(
    cpv_code: str,
    limit: int = 3000,
    es: Optional[Elasticsearch] = None,
) -> Dict[str, Any]:
    """Entidades que contrataram num CPV (aceita código completo ou parcial).

    O CPV vive nos **contratos**, não no cadastro de entidades: para filtrar a
    pesquisa de entidades por CPV é preciso primeiro descobrir quem contratou
    nessa classificação. A lista entra depois num filtro `terms`, pelo que é
    limitada (`limit`); quando o corte acontece, isso vai dito ao chamador
    (`truncated`) para o resultado não ser lido como completo.
    """
    client = es or get_es_client()
    code = (cpv_code or "").strip()
    if not client or not code:
        return {"nifs": [], "truncated": False, "matched": 0, "code": code}

    cpv_query = (
        {"term": {"cpv.code": code}}
        if re.fullmatch(r"\d{8}(-\d)?", code)
        else {"prefix": {"cpv.code": code}}
    )
    limites = max(1, min(10000, limit))

    def _nested_path(path: str) -> Dict[str, Any]:
        return {
            "nested": {"path": path},
            "aggs": {
                "nifs": {
                    "terms": {
                        "field": f"{path}.nif",
                        "size": limites,
                        "order": {"valor": "desc"},
                    },
                    "aggs": {
                        "valor": {
                            "reverse_nested": {},
                            "aggs": {"v": {"sum": {"field": "precoContratual"}}},
                        }
                    },
                }
            },
        }

    try:
        resp = client.search(
            index=CONTRACTS_INDEX,
            body={
                "size": 0,
                "track_total_hits": False,
                "query": {"nested": {"path": "cpv", "query": cpv_query, "score_mode": "none"}},
                "aggs": {
                    "adjudicatarios_cpv": _nested_path("adjudicatarios.parsed"),
                    "adjudicantes_cpv": _nested_path("adjudicantes.parsed"),
                },
            },
        )
    except Exception as exc:
        return {"error": str(exc), "nifs": [], "truncated": False, "matched": 0, "code": code}

    nifs: List[str] = []
    vistos: set[str] = set()
    truncado = False
    for nome in ("adjudicatarios_cpv", "adjudicantes_cpv"):
        bucket_agg = (resp.get("aggregations") or {}).get(nome, {}).get("nifs", {})
        if bucket_agg.get("sum_other_doc_count"):
            truncado = True
        for bucket in bucket_agg.get("buckets", []):
            nif = str(bucket.get("key") or "").strip()
            if not nif or nif in vistos:
                continue
            vistos.add(nif)
            nifs.append(nif)
    return {"nifs": nifs, "truncated": truncado, "matched": len(nifs), "code": code}




def search_entities(
    q: Optional[str] = None,
    country: Optional[str] = None,
    only_with_nif: Optional[bool] = None,
    min_contracts: Optional[int] = None,
    max_contracts: Optional[int] = None,
    min_value: Optional[float] = None,
    max_value: Optional[float] = None,
    role: Optional[str] = "all",
    cae: Optional[str | list[str]] = None,
    cpv: Optional[str] = None,
    sort_by: Optional[str] = "total_value",
    sort_order: Optional[str] = "desc",
    size: int = 20,
    from_: int = 0,
    es: Optional[Elasticsearch] = None,
) -> Dict[str, Any]:
    """Pesquisa o cadastro de entidades com filtros e ordenação.

    ``role`` permite restringir a entidades que aparecem como adjudicante
    (``totAdjudicante``), adjudicatário (``totAdjudicatario``) ou ambos.
    ``cae`` filtra pelo C.A.E. e ``cpv`` por classificação dos contratos.
    """
    client = es or get_es_client()
    if not client:
        return {"error": "Elasticsearch indisponível", "items": [], "total": 0}

    ensure_indices(client)

    must: List[Dict[str, Any]] = []
    filters: List[Dict[str, Any]] = []
    notes: List[str] = []
    text_query: Optional[Dict[str, Any]] = None

    if q:
        term = q.strip()
        if term:
            # Combina: NIF exato, nome exato (frase) e correspondência incremental
            # por prefixo (edge-ngram), para que "SONAE" encontre "SONAECOM".
            # O prefixo também exige todos os termos: sem isso, «COVID-19» trazia
            # «1996 Ponto Infinito» e «MAN 1964 Architects» (casavam só o «19»).
            text_query = {
                "bool": {
                    "should": [
                        {"term": {"nif": term}},
                        {"match_phrase": {"name": {"query": term, "boost": 5}}},
                        {"multi_match": {"query": term, "fields": ["name^3"], "operator": "and", "boost": 3}},
                        {"match": {"name.autocomplete": {"query": term, "operator": "and", "boost": 1}}},
                    ],
                    "minimum_should_match": 1,
                }
            }
    if country:
        filters.append({"term": {"country": country}})
    if only_with_nif:
        filters.append({"term": {"has_nif": True}})
    if min_contracts is not None:
        filters.append({"range": {"contracts_count": {"gte": min_contracts}}})
    if max_contracts is not None:
        filters.append({"range": {"contracts_count": {"lte": max_contracts}}})
    if min_value is not None:
        filters.append({"range": {"total_value": {"gte": min_value}}})
    if max_value is not None:
        filters.append({"range": {"total_value": {"lte": max_value}}})
    if role == "adjudicante":
        filters.append({"range": {"as_adjudicante_count": {"gte": 1}}})
    elif role == "adjudicatario":
        filters.append({"range": {"as_adjudicatario_count": {"gte": 1}}})
    if cae:
        codes = _normalize_cae_codes(cae)
        if codes:
            code_shoulds: List[Dict[str, Any]] = []
            for code in codes:
                code_shoulds.extend([
                    {"term": {"cae_principal": code}},
                    {"term": {"caes_secundarios": code}},
                ])
                # Códigos parciais (menos de 5 dígitos) também fazem prefixo.
                if not re.fullmatch(r"\d{5}", code):
                    code_shoulds.extend([
                        {"prefix": {"cae_principal": code}},
                        {"prefix": {"caes_secundarios": code}},
                    ])
            filters.append({
                "bool": {
                    "should": code_shoulds,
                    "minimum_should_match": 1,
                }
            })
    if cpv:
        resolvido = entity_nifs_for_cpv(cpv, es=client)
        if resolvido.get("error"):
            return {"error": resolvido["error"], "items": [], "total": 0}
        nifs_cpv = resolvido.get("nifs") or []
        if not nifs_cpv:
            return {
                "query": q,
                "total": 0,
                "items": [],
                "from": from_,
                "size": size,
                "notes": [f"Nenhuma entidade com contratos no CPV {cpv.strip()}."],
            }
        filters.append({"terms": {"nif": nifs_cpv}})
        notes.append(
            f"CPV {resolvido.get('code')}: {len(nifs_cpv)} entidades com contratos "
            "nessa classificação."
        )
        if resolvido.get("truncated"):
            notes.append(
                f"A lista de entidades do CPV foi limitada a {len(nifs_cpv)} (as maiores por valor)."
            )

    query: Dict[str, Any]
    if text_query or filters:
        query = {"bool": {}}
        if text_query:
            query["bool"]["must"] = [text_query]
        if filters:
            query["bool"]["filter"] = filters
    else:
        query = {"match_all": {}}

    allowed_sort = {
        "name", "contracts_count", "total_value", "as_adjudicante_value",
        "as_adjudicante_count", "as_adjudicatario_count",
    }
    sort_field = sort_by if sort_by in allowed_sort else "total_value"
    order = "asc" if (sort_order or "desc").lower() == "asc" else "desc"
    # Em empates ordena por nome para garantir paginação estável.
    sort_spec: List[Any] = [{sort_field: {"order": order}}, {"name.keyword": {"order": "asc"}}]

    try:
        resp = client.search(
            index=ENTITIES_INDEX,
            body={
                "query": query,
                "from": from_,
                "size": size,
                "track_total_hits": True,
                "sort": sort_spec,
            },
        )
        items = [{**hit["_source"], "doc_id": hit["_id"]} for hit in resp["hits"]["hits"]]
        return {
            "query": q,
            "total": resp["hits"]["total"]["value"],
            "items": items,
            "from": from_,
            "size": size,
            "notes": notes,
        }
    except Exception as exc:
        return {"error": str(exc), "items": [], "total": 0}




def get_entity_stats(es: Optional[Elasticsearch] = None) -> Dict[str, Any]:
    """Estatísticas agregadas do cadastro de entidades (totais, países, com/sem NIF)."""
    client = es or get_es_client()
    if not client:
        return {"error": "Elasticsearch indisponível"}

    ensure_indices(client)

    try:
        resp = client.search(
            index=ENTITIES_INDEX,
            body={
                "size": 0,
                "track_total_hits": True,
                "aggs": {
                    "with_nif": {"filter": {"term": {"has_nif": True}}},
                    "without_nif": {"filter": {"term": {"has_nif": False}}},
                    "countries": {
                        "terms": {"field": "country", "size": 15, "order": {"_count": "desc"}},
                        "aggs": {"value": {"sum": {"field": "total_value"}}},
                    },
                    "total_value": {"sum": {"field": "total_value"}},
                    "total_contracts": {"sum": {"field": "contracts_count"}},
                    "as_adjudicante": {"filter": {"range": {"as_adjudicante_count": {"gte": 1}}}},
                    "as_adjudicatario": {"filter": {"range": {"as_adjudicatario_count": {"gte": 1}}}},
                },
            },
        )
        aggs = resp["aggregations"]
        countries = [
            {
                "country": b["key"],
                "count": b["doc_count"],
                "total_value": round(b.get("value", {}).get("value") or 0.0, 2),
            }
            for b in aggs.get("countries", {}).get("buckets", [])
        ]
        return {
            "total": resp["hits"]["total"]["value"],
            "with_nif": aggs.get("with_nif", {}).get("doc_count", 0),
            "without_nif": aggs.get("without_nif", {}).get("doc_count", 0),
            "total_value": round(aggs.get("total_value", {}).get("value") or 0.0, 2),
            "total_contracts": int(aggs.get("total_contracts", {}).get("value") or 0),
            "adjudicante_count": aggs.get("as_adjudicante", {}).get("doc_count", 0),
            "adjudicatario_count": aggs.get("as_adjudicatario", {}).get("doc_count", 0),
            "countries": countries,
        }
    except Exception as exc:
        return {"error": str(exc)}




def get_entity_by_nif(nif: str, es: Optional[Elasticsearch] = None) -> Dict[str, Any]:
    """Devolve o registo do cadastro de entidades para um NIF."""
    client = es or get_es_client()
    if not client:
        return {"error": "Elasticsearch indisponível"}

    ensure_indices(client)

    try:
        resp = client.search(
            index=ENTITIES_INDEX,
            body={"query": {"bool": {"should": [{"term": {"nif": nif}}, {"term": {"_id": f"{ENTITIES_INDEX}:{nif}"}}], "minimum_should_match": 1}}, "size": 1},
        )
        hits = resp["hits"]["hits"]
        if not hits:
            return {"nif": nif, "error": "Entidade não encontrada no cadastro"}
        return {"nif": nif, **hits[0]["_source"], "doc_id": hits[0]["_id"]}
    except Exception as exc:
        return {"error": str(exc)}




def save_entity_societario_timeline(
    nif: str,
    markdown: str,
    total: int,
    backend_used: str,
    es: Optional[Elasticsearch] = None,
) -> Dict[str, Any]:
    """Guarda a timeline societária gerada por IA na ficha da entidade (ENTITIES_INDEX)."""
    client = es or get_es_client()
    if not client:
        return {"error": "Elasticsearch indisponível", "nif": nif}

    ensure_indices(client)

    doc = {
        "societario_timeline": {
            "markdown": markdown,
            "total": total,
            "backend_used": backend_used,
            "generated_at": _today(),
        }
    }

    try:
        resp = client.update(
            index=ENTITIES_INDEX,
            id=f"{ENTITIES_INDEX}:{nif}",
            body={"doc": doc, "doc_as_upsert": True},
            refresh=True,
        )
        return {"nif": nif, "updated": resp.get("result") in ("updated", "created")}
    except Exception as exc:
        return {"error": str(exc), "nif": nif}




def get_entity_relations(nif: str, size: int = 50, es: Optional[Elasticsearch] = None) -> Dict[str, Any]:
    """Relações de ontologia guardadas para uma entidade, nos dois sentidos.

    Cada item vem normalizado: `direction` é `out` quando a entidade é a origem e
    `in` quando é o alvo, e `other_*` aponta sempre para o outro lado da aresta
    (é o que a ficha mostra, sem o consumidor ter de saber a direção).
    """
    client = es or get_es_client()
    if not client:
        return {"nif": nif, "total": 0, "items": [], "by_kind": {}, "error": "Elasticsearch indisponível"}

    ensure_indices(client)

    body = {
        "query": {
            "bool": {
                "should": [{"term": {"source_ref": nif}}, {"term": {"target_ref": nif}}],
                "minimum_should_match": 1,
            }
        },
        "size": max(1, min(200, size)),
    }
    try:
        resp = client.search(index=WORLD_RELATIONS_INDEX, body=body)
    except Exception as exc:
        return {"nif": nif, "total": 0, "items": [], "by_kind": {}, "error": str(exc)}

    items: List[Dict[str, Any]] = []
    by_kind: Dict[str, int] = {}
    for hit in resp["hits"]["hits"]:
        src = hit.get("_source") or {}
        outgoing = str(src.get("source_ref") or "") == nif
        kind = str(src.get("kind") or "related")
        by_kind[kind] = by_kind.get(kind, 0) + 1
        evidence = src.get("evidence")
        if isinstance(evidence, str):
            evidence = [evidence]
        items.append({
            "relation_id": src.get("relation_id") or hit.get("_id"),
            "kind": kind,
            "direction": "out" if outgoing else "in",
            "source_ref": src.get("source_ref"),
            "source_name": src.get("source_name"),
            "source_type": src.get("source_type"),
            "target_ref": src.get("target_ref"),
            "target_name": src.get("target_name"),
            "target_type": src.get("target_type"),
            "other_ref": src.get("target_ref") if outgoing else src.get("source_ref"),
            "other_name": src.get("target_name") if outgoing else src.get("source_name"),
            "other_type": src.get("target_type") if outgoing else src.get("source_type"),
            "evidence": evidence or [],
            "country": src.get("country"),
            "updated_at": src.get("updated_at"),
        })

    total = resp["hits"]["total"]
    total_value = total.get("value") if isinstance(total, dict) else total
    return {
        "nif": nif,
        "total": int(total_value or len(items)),
        "items": items,
        "by_kind": by_kind,
        "error": None,
    }




def list_entity_countries(es: Optional[Elasticsearch] = None) -> List[Dict[str, Any]]:
    """Lista os países presentes no cadastro de entidades, com contagem."""
    client = es or get_es_client()
    if not client:
        return []

    ensure_indices(client)

    try:
        resp = client.search(
            index=ENTITIES_INDEX,
            body={"size": 0, "aggs": {"countries": {"terms": {"field": "country", "size": 300, "order": {"_key": "asc"}}}}},
        )
        return [
            {"country": b["key"], "count": b["doc_count"]}
            for b in resp["aggregations"]["countries"]["buckets"]
            if b["key"]
        ]
    except Exception:
        return []

# Importações no fim do módulo: evitam ciclos de importação
# (os nomes já estão definidos quando estes módulos são carregados).
from api.es.contratos import _cpv_description_from_hits, _resolve_agg_target  # noqa: E402
from api.es.societario import _delete_stale_docs  # noqa: E402
