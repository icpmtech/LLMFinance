"""Mapa ibérico e detalhe regional dos contratos (PT/ES/FR).

Módulo do pacote :mod:`api.es` — ver `api/elasticsearch_client.py`,
que continua a expor a API pública (os coletores/serviços importam de lá).
"""
import logging
from typing import Any, Dict, List, Optional

from elasticsearch import Elasticsearch
from api.es.contratos import _build_contract_query, _cpv_description_from_hits, _resolve_agg_target
from api.es.contratos_es import _build_contratos_es_query, _contratos_es_value_source, _top_hit_cpv_es_name
from api.es.contratos_fr import _build_contratos_fr_query, _contratos_fr_value_source, _top_hit_cpv_fr_name
from api.es.core import _fold_text, _sum_agg_value, _unescape_label, _with_required, get_es_client
from api.es.geo import _PT_DISTRICT_BY_KEY, _pt_district_from_local
from api.es.indices import CONTRACTS_INDEX, CONTRATOS_ES_INDEX, CONTRATOS_FR_INDEX
from api.es.mappings import ensure_indices

logger = logging.getLogger(__name__)




# Campos de texto para a pesquisa do mapa. Os nomes das partes entram por
# `adjudicantes.raw`/`adjudicatarios.raw` (texto) e não por `parsed.nome`, que é
# `keyword`: nesse campo só casaria o nome completo exato («METROPOLITANO DE
# LISBOA, S.A.»), nunca «Metropolitano de Lisboa».
_IBERIA_TEXT_FIELDS_PT = [
    "objectoContrato^3",
    "descContrato^2",
    "search_text",
    "adjudicantes.raw",
    "adjudicatarios.raw",
    "cpv.description",
]


_IBERIA_TEXT_FIELDS_ES = [
    "objeto^3",
    "adjudicatario_nombre^2",
    "organo_nombre^2",
    "descripcion",
    "search_text",
]




def _iberia_text_query(text: str, fields: List[str]) -> Dict[str, Any]:
    """`multi_match` que exige **todos** os termos (`operator: and`).

    A pesquisa livre dos contratos (páginas de pesquisa) usa `best_fields` sem
    mínimo de termos: «Hospital de Cascais» devolve 2,1 M contratos (basta o
    «de»). Num mapa isso acenderia o país inteiro, por isso a pesquisa do mapa
    exige todos os termos.
    """
    return {
        "multi_match": {
            "query": text,
            "fields": fields,
            "type": "best_fields",
            "operator": "and",
        }
    }




def _es_code_level(code: str) -> str:
    """Nível NUTS de um código espanhol: `ES300` (3), `ES30` (2), `ES3` (1) ou país."""
    body = code[2:]
    if body.isdigit():
        return {1: "nuts1", 2: "nuts2", 3: "nuts3"}.get(len(body), "pais")
    return "pais"




# Campos pesquisáveis do mapa para França (DECP).
_IBERIA_TEXT_FIELDS_FR = ["objet^4", "search_text", "acheteur_nom^2", "adjudicatario_nom^2"]




def _iberia_map_france(
    client: Elasticsearch,
    ano: Optional[int],
    q: Optional[str] = None,
    entidade: Optional[str] = None,
    cpv: Optional[str] = None,
) -> Dict[str, Any]:
    """Contratos de França agregados por local de execução, no formato ibérico."""
    from api.contratos_fr_map import get_contratos_fr_map

    texto = " ".join(part.strip() for part in (q, entidade) if part and part.strip())
    raw = get_contratos_fr_map(
        q=texto or None,
        ano=ano,
        cpv_code=cpv,
        es=client,
    )
    if raw.get("error"):
        return {
            "total_contracts": 0,
            "total_value": 0.0,
            "regions": [],
            "unspecified": {"count": 0, "total_value": 0.0},
            "other_locations": {"count": 0, "total_value": 0.0},
            "warnings": [raw["error"]],
        }

    regions: List[Dict[str, Any]] = []
    for item in raw.get("regions", []):
        regions.append({
            "pais": "FR",
            "code": str(item["code"]),
            "label": item["label"],
            "level": item.get("level", "departamento"),
            "count": int(item.get("contracts", 0)),
            "total_value": round(float(item.get("value", 0.0)), 2),
        })

    # O módulo francês separa offshore; aqui juntamos tudo nas regiões e
    # deixamos o frontend decidir o enquadramento, tal como para PT/ES.
    for item in raw.get("offshore", []):
        regions.append({
            "pais": "FR",
            "code": str(item["code"]),
            "label": item["label"],
            "level": item.get("level", "departamento"),
            "count": int(item.get("contracts", 0)),
            "total_value": round(float(item.get("value", 0.0)), 2),
        })

    not_plotted_count = 0
    not_plotted_value = 0.0
    for item in raw.get("not_plotted", []):
        not_plotted_count += int(item.get("contracts", 0))
        not_plotted_value += float(item.get("value", 0.0))
    for item in raw.get("countries", []):
        if item.get("code", "").upper() != "FR":
            not_plotted_count += int(item.get("contracts", 0))
            not_plotted_value += float(item.get("value", 0.0))

    return {
        "total_contracts": int(raw.get("total", 0)),
        "total_value": round(float(raw.get("value", 0.0)), 2),
        "regions": regions,
        "unspecified": {"count": not_plotted_count, "total_value": round(not_plotted_value, 2)},
        "other_locations": {"count": 0, "total_value": 0.0},
        "warnings": raw.get("warnings", []),
    }




def _iberia_map_portugal(
    client: Elasticsearch,
    ano: Optional[int],
    q: Optional[str] = None,
    entidade: Optional[str] = None,
    cpv: Optional[str] = None,
) -> Dict[str, Any]:
    """Contratos portugueses por distrito de execução (`localExecucao`).

    Os filtros de país (`cpv`, `ano`) vêm da pesquisa de contratos; o texto
    (objeto, entidades) usa uma pesquisa que exige todos os termos, para o mapa
    não mostrar o país inteiro com uma pesquisa de duas palavras.
    """
    texto = " ".join(part.strip() for part in (q, entidade) if part and part.strip())
    query = _build_contract_query(year=ano, cpv_code=cpv)
    if texto:
        query = _with_required(query, _iberia_text_query(texto, _IBERIA_TEXT_FIELDS_PT))
    resp = client.search(
        index=CONTRACTS_INDEX,
        body={
            "size": 0,
            "track_total_hits": True,
            "query": query,
            "aggs": {
                "total_value": {"sum": {"field": "precoContratual"}},
                "locais": {
                    "terms": {"field": "localExecucao", "size": 2000},
                    "aggs": {"total_value": {"sum": {"field": "precoContratual"}}},
                },
                "com_distrito": {
                    "filter": {"wildcard": {"localExecucao": {"value": "Portugal, *"}}},
                    "aggs": {"total_value": {"sum": {"field": "precoContratual"}}},
                },
            },
        },
    )
    aggs = resp.get("aggregations", {}) or {}
    districts: Dict[str, Dict[str, float]] = {}
    for bucket in aggs.get("locais", {}).get("buckets", []):
        raw = _pt_district_from_local(bucket.get("key"))
        if not raw:
            continue
        # O portal escreve o mesmo distrito com variantes (ex.: «Braganca» sem
        # cedilha): normalizamos para o nome canónico para não partir a região.
        # Valores que não são distritos («Portugal Continental», «Distrito não
        # determinado») ficam como região própria e o frontend lista-os à parte.
        distrito = _PT_DISTRICT_BY_KEY.get(_fold_text(raw), raw)
        entry = districts.setdefault(distrito, {"count": 0.0, "total_value": 0.0})
        entry["count"] += bucket.get("doc_count", 0)
        entry["total_value"] += _sum_agg_value(bucket.get("total_value"))

    total = resp.get("hits", {}).get("total", {}).get("value", 0)
    total_value = _sum_agg_value(aggs.get("total_value"))
    with_district = (aggs.get("com_distrito", {}) or {}).get("doc_count", 0)
    with_district_value = _sum_agg_value((aggs.get("com_distrito", {}) or {}).get("total_value"))

    regions = [
        {
            "pais": "PT",
            "code": name,
            "label": name,
            "level": "distrito",
            "count": int(values["count"]),
            "total_value": round(values["total_value"], 2),
        }
        for name, values in sorted(districts.items(), key=lambda item: item[1]["total_value"], reverse=True)
    ]
    return {
        "total_contracts": int(total),
        "total_value": round(total_value, 2),
        "regions": regions,
        "unspecified": {
            "count": max(int(total) - int(with_district), 0),
            "total_value": round(max(total_value - with_district_value, 0.0), 2),
        },
        "other_locations": {"count": 0, "total_value": 0.0},
    }




def _iberia_map_espanha(
    client: Elasticsearch,
    ano: Optional[int],
    q: Optional[str] = None,
    entidade: Optional[str] = None,
    cpv: Optional[str] = None,
) -> Dict[str, Any]:
    """Contratos de Espanha por província/NUTS (`nuts`).

    A `entidade` entra no texto livre: no PLACSP o nome do órgão e da
    adjudicatária são campos pesquisáveis do mesmo `multi_match`.
    """
    value_source = _contratos_es_value_source("valor_adjudicado")
    texto = " ".join(part.strip() for part in (q, entidade) if part and part.strip())
    query = _build_contratos_es_query(ano=ano, cpv_code=cpv)
    if texto:
        query = _with_required(query, _iberia_text_query(texto, _IBERIA_TEXT_FIELDS_ES))
    resp = client.search(
        index=CONTRATOS_ES_INDEX,
        body={
            "size": 0,
            "track_total_hits": True,
            "query": query,
            "aggs": {
                "total_value": {"sum": value_source},
                "codigos": {
                    "terms": {"field": "nuts", "size": 600},
                    "aggs": {"total_value": {"sum": value_source}},
                },
                "com_nuts": {
                    "filter": {"prefix": {"nuts": "ES"}},
                    "aggs": {"total_value": {"sum": value_source}},
                },
            },
        },
    )
    aggs = resp.get("aggregations", {}) or {}
    regions: List[Dict[str, Any]] = []
    other_count = 0
    other_value = 0.0
    for bucket in aggs.get("codigos", {}).get("buckets", []):
        code = str(bucket.get("key") or "").strip()
        if not code:
            continue
        value = _sum_agg_value(bucket.get("total_value"))
        if not code.startswith("ES"):
            # Local de execução fora de Espanha (o adjudicatário pode ser estrangeiro).
            other_count += bucket.get("doc_count", 0)
            other_value += value
            continue
        regions.append({
            "pais": "ES",
            "code": code,
            "label": code,
            "level": _es_code_level(code),
            "count": int(bucket.get("doc_count", 0)),
            "total_value": round(value, 2),
        })

    total = resp.get("hits", {}).get("total", {}).get("value", 0)
    total_value = _sum_agg_value(aggs.get("total_value"))
    with_nuts = (aggs.get("com_nuts", {}) or {}).get("doc_count", 0)
    with_nuts_value = _sum_agg_value((aggs.get("com_nuts", {}) or {}).get("total_value"))

    regions.sort(key=lambda row: row["total_value"], reverse=True)
    return {
        "total_contracts": int(total),
        "total_value": round(total_value, 2),
        "regions": regions,
        "unspecified": {
            "count": max(int(total) - int(with_nuts), 0),
            "total_value": round(max(total_value - with_nuts_value, 0.0), 2),
        },
        "other_locations": {
            "count": int(other_count),
            "total_value": round(other_value, 2),
        },
    }




def get_contracts_iberia_map(
    ano: Optional[int] = None,
    pais: str = "all",
    q: Optional[str] = None,
    entidade: Optional[str] = None,
    cpv: Optional[str] = None,
    es: Optional[Elasticsearch] = None,
) -> Dict[str, Any]:
    """Volume e valor de contratos por região, para o mapa de Portugal e Espanha.

    Uma só chamada devolve as duas geografias (distrito em Portugal, província em
    Espanha) e o que não é localizável, para o mapa não inventar posições. Aceita
    os mesmos filtros de pesquisa dos dois países (`q`, `entidade`, `cpv`, `ano`).
    """
    client = es or get_es_client(request_timeout=120)
    if not client:
        return {"error": "Elasticsearch indisponível", "regions": []}

    ensure_indices(client)

    selecao = (pais or "all").strip().lower()
    if selecao in ("pt", "portugal"):
        selecao = "pt"
    elif selecao in ("es", "espanha", "spain"):
        selecao = "es"
    elif selecao in ("fr", "franca", "france"):
        selecao = "fr"
    else:
        selecao = "all"

    result: Dict[str, Any] = {
        "ano": ano,
        "pais": selecao,
        "filters": {"q": q or None, "entidade": entidade or None, "cpv": cpv or None},
        "countries": [],
        "regions": [],
        "unspecified": {},
        "other_locations": {"count": 0, "total_value": 0.0},
    }
    warnings: List[str] = []

    parts = []
    if selecao in ("all", "pt"):
        try:
            parts.append(("PT", _iberia_map_portugal(client, ano, q=q, entidade=entidade, cpv=cpv)))
        except Exception as exc:  # noqa: BLE001 — um país indisponível não deve derrubar o mapa
            warnings.append(f"Portugal: {exc}")
    if selecao in ("all", "es"):
        try:
            parts.append(("ES", _iberia_map_espanha(client, ano, q=q, entidade=entidade, cpv=cpv)))
        except Exception as exc:  # noqa: BLE001
            warnings.append(f"Espanha: {exc}")
    if selecao in ("all", "fr"):
        try:
            parts.append(("FR", _iberia_map_france(client, ano, q=q, entidade=entidade, cpv=cpv)))
        except Exception as exc:  # noqa: BLE001
            warnings.append(f"Fran\u00e7a: {exc}")

    labels = {"PT": "Portugal", "ES": "Espanha", "FR": "Fran\u00e7a"}
    for code, part in parts:
        result["countries"].append({
            "code": code,
            "label": labels[code],
            "total_contracts": part["total_contracts"],
            "total_value": part["total_value"],
        })
        result["regions"].extend(part["regions"])
        result["unspecified"][code] = part["unspecified"]
        result["other_locations"]["count"] += part["other_locations"]["count"]
        result["other_locations"]["total_value"] += part["other_locations"]["total_value"]
        if part.get("warnings"):
            warnings.extend(part["warnings"])

    result["other_locations"]["total_value"] = round(result["other_locations"]["total_value"], 2)
    if warnings:
        result["warnings"] = warnings
    return result




# ---------------------------------------------------------------------------
# Ficha de uma região (aberta a partir do mapa)
# ---------------------------------------------------------------------------


def _pt_region_detail(
    client: Elasticsearch,
    code: str,
    ano: Optional[int],
    q: Optional[str],
    cpv: Optional[str],
    top_n: int,
    contracts_size: int,
) -> Dict[str, Any]:
    """Ficha de um distrito português: entidades, empresas, analíticas e contratos.

    Uma só pesquisa devolve tudo — incluindo os maiores contratos, em `top_hits` —
    para que as métricas e a lista de contratos venham sempre do mesmo conjunto
    (a pesquisa do mapa exige todos os termos; é a mesma aqui).
    """
    query = _build_contract_query(year=ano, region=code, cpv_code=cpv)
    if q:
        query = _with_required(query, _iberia_text_query(q, _IBERIA_TEXT_FIELDS_PT))

    procedure_agg = _resolve_agg_target(client, "tipoprocedimento")
    contract_agg = _resolve_agg_target(client, "tipoContrato")
    runtime_mappings: Dict[str, Any] = {}
    for resolved in (procedure_agg, contract_agg):
        if resolved.get("runtime"):
            runtime_mappings.update(resolved["runtime"])

    def role_agg(path: str) -> Dict[str, Any]:
        """Ranking de NIF de um papel (adjudicantes/adjudicatários) por valor."""
        return {
            "nested": {"path": f"{path}.parsed"},
            "aggs": {
                "by_nif": {
                    "terms": {
                        "field": f"{path}.parsed.nif",
                        "size": top_n,
                        "order": {"total_value": "desc"},
                    },
                    "aggs": {
                        "name": {"top_hits": {"size": 1, "_source": [f"{path}.parsed.nome"]}},
                        "total_value": {
                            "reverse_nested": {},
                            "aggs": {"value": {"sum": {"field": "precoContratual"}}},
                        },
                        "anos": {
                            "reverse_nested": {},
                            "aggs": {"stats": {"stats": {"field": "Ano"}}},
                        },
                    },
                },
                "nifs": {"cardinality": {"field": f"{path}.parsed.nif", "precision_threshold": 40000}},
            },
        }

    body: Dict[str, Any] = {
        "size": 0,
        "track_total_hits": True,
        "query": query,
        "aggs": {
            "total_value": {"sum": {"field": "precoContratual"}},
            "avg_value": {"avg": {"field": "precoContratual"}},
            "max_value": {"max": {"field": "precoContratual"}},
            "by_year": {
                "terms": {"field": "Ano", "size": 50, "order": {"_key": "desc"}},
                "aggs": {"total_value": {"sum": {"field": "precoContratual"}}},
            },
            "by_cpv": {
                "nested": {"path": "cpv"},
                "aggs": {
                    "codes": {
                        "terms": {"field": "cpv.code", "size": top_n, "order": {"total_value": "desc"}},
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
            "by_procedure": {
                "terms": {"field": procedure_agg["field"], "size": 10, "missing": "Não especificado"},
                "aggs": {"total_value": {"sum": {"field": "precoContratual"}}},
            },
            "by_contract_type": {
                "terms": {"field": contract_agg["field"], "size": 10, "missing": "Não especificado"},
                "aggs": {"total_value": {"sum": {"field": "precoContratual"}}},
            },
            "by_value_range": {
                "histogram": {"field": "precoContratual", "interval": 100000, "min_doc_count": 1}
            },
            "adjudicantes": role_agg("adjudicantes"),
            "adjudicatarios": role_agg("adjudicatarios"),
            "top_contracts": {
                "top_hits": {
                    "size": contracts_size,
                    "sort": [
                        {"precoContratual": {"order": "desc", "missing": "_last", "unmapped_type": "float"}}
                    ],
                    "_source": [
                        "objectoContrato",
                        "precoContratual",
                        "Ano",
                        "adjudicantes.parsed",
                        "adjudicatarios.parsed",
                        "dataCelebracaoContrato",
                        "dataPublicacao",
                        "idcontrato",
                    ],
                }
            },
        },
    }
    if runtime_mappings:
        body["runtime_mappings"] = runtime_mappings

    resp = client.search(index=CONTRACTS_INDEX, body=body)
    aggs = resp.get("aggregations", {}) or {}

    def agg_value(bucket: Optional[Dict[str, Any]]) -> float:
        """Valor de um `sum` (incluindo os encaixados em `reverse_nested`)."""
        raw = (bucket or {}).get("total_value", {})
        value = raw.get("value") if isinstance(raw, dict) else None
        if isinstance(value, dict):
            value = value.get("value")
        return float(value or 0.0)

    total_contracts = resp.get("hits", {}).get("total", {}).get("value", 0)
    total_value = float(aggs.get("total_value", {}).get("value") or 0.0)

    def rows(agg_name: str) -> List[Dict[str, Any]]:
        return [
            {"key": str(b["key"]), "count": b["doc_count"], "total_value": round(agg_value(b), 2)}
            for b in (aggs.get(agg_name, {}) or {}).get("buckets", [])
        ]

    value_ranges: List[Dict[str, Any]] = []
    for bucket in (aggs.get("by_value_range", {}) or {}).get("buckets", []):
        start = bucket.get("key")
        if start is None or start < 0 or len(value_ranges) >= 12:
            continue
        value_ranges.append({
            "key": str(int(start)),
            "count": bucket.get("doc_count", 0),
            "total_value": round(agg_value(bucket), 2),
            "description": f"{int(start):,} – {int(start) + 100000:,} €".replace(",", " "),
        })

    cpv_rows: List[Dict[str, Any]] = []
    for bucket in (aggs.get("by_cpv", {}) or {}).get("codes", {}).get("buckets", []):
        cpv_rows.append({
            "key": str(bucket["key"]),
            "count": bucket["doc_count"],
            "total_value": round(agg_value(bucket), 2),
            "description": _cpv_description_from_hits(bucket.get("description"), bucket["key"]),
        })

    def entity_rows(path: str) -> List[Dict[str, Any]]:
        out: List[Dict[str, Any]] = []
        for bucket in (aggs.get(path, {}) or {}).get("by_nif", {}).get("buckets", []):
            nif = bucket.get("key")
            if not nif:
                continue
            name = str(nif)
            hits = ((bucket.get("name") or {}).get("hits") or {}).get("hits") or []
            if hits:
                source = hits[0].get("_source") or {}
                name = str(source.get("nome") or name)
            value = agg_value(bucket)
            count = bucket.get("doc_count", 0)
            stats = ((bucket.get("anos") or {}).get("stats") or {})
            out.append({
                "nif": str(nif),
                "name": _unescape_label(name),
                "count": count,
                "total_value": round(value, 2),
                "avg_value": round(value / count, 2) if count else None,
                "share": round(value / total_value, 4) if total_value > 0 else None,
                "first_year": int(stats["min"]) if stats.get("min") is not None else None,
                "last_year": int(stats["max"]) if stats.get("max") is not None else None,
            })
        return out

    contract_rows: List[Dict[str, Any]] = []
    for hit in ((aggs.get("top_contracts", {}) or {}).get("hits", {}) or {}).get("hits", []):
        source = hit.get("_source") or {}
        contract_rows.append({
            "doc_id": hit.get("_id") or source.get("idcontrato"),
            "title": source.get("objectoContrato") or "",
            "awarder": _party_names(source.get("adjudicantes")),
            "supplier": _party_names(source.get("adjudicatarios")),
            "value": source.get("precoContratual"),
            "ano": source.get("Ano"),
            "date": source.get("dataCelebracaoContrato") or source.get("dataPublicacao"),
        })

    return {
        "pais": "PT",
        "code": code,
        "ano": ano,
        "filters": {"q": q or None, "cpv": cpv or None},
        "totals": {
            "contracts": int(total_contracts),
            "value": round(total_value, 2),
            "avg": round(float(aggs.get("avg_value", {}).get("value") or 0.0), 2) or None,
            "max": round(float(aggs.get("max_value", {}).get("value") or 0.0), 2) or None,
            "awarders": int((aggs.get("adjudicantes", {}) or {}).get("nifs", {}).get("value") or 0),
            "suppliers": int((aggs.get("adjudicatarios", {}) or {}).get("nifs", {}).get("value") or 0),
        },
        "by_year": rows("by_year"),
        "by_cpv": cpv_rows,
        "by_procedure": rows("by_procedure"),
        "by_contract_type": rows("by_contract_type"),
        "by_value_range": value_ranges,
        "awarders": entity_rows("adjudicantes"),
        "suppliers": entity_rows("adjudicatarios"),
        "contracts": contract_rows,
        "error": None,
    }




def _party_names(parties: Any) -> str:
    """Nomes das partes de um contrato português (`adjudicantes`/`adjudicatarios`)."""
    entries = parties if isinstance(parties, list) else [parties] if parties else []
    names: List[str] = []
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        for parsed in entry.get("parsed") or []:
            if isinstance(parsed, dict) and parsed.get("nome"):
                names.append(_unescape_label(parsed["nome"]))
    return ", ".join(names[:3])




def _es_region_detail(
    client: Elasticsearch,
    code: str,
    ano: Optional[int],
    q: Optional[str],
    cpv: Optional[str],
    top_n: int,
    contracts_size: int,
) -> Dict[str, Any]:
    """Ficha de uma província/NUTS espanhola: órgãos, empresas, analíticas e contratos.

    Uma só pesquisa (incluindo os maiores contratos em `top_hits`) para que a
    pesquisa da janela filtre métricas, entidades e contratos ao mesmo tempo.
    """
    value_source = _contratos_es_value_source("valor_adjudicado")
    query = _build_contratos_es_query(nuts=code, ano=ano, cpv_code=cpv)
    if q:
        query = _with_required(query, _iberia_text_query(q, _IBERIA_TEXT_FIELDS_ES))

    def with_value(agg: Dict[str, Any]) -> Dict[str, Any]:
        return {**agg, "aggs": {"total_value": {"sum": value_source}}}

    body: Dict[str, Any] = {
        "size": 0,
        "track_total_hits": True,
        "query": query,
        "aggs": {
            "total_value": {"sum": value_source},
            "avg_value": {"avg": value_source},
            "max_value": {"max": value_source},
            "by_year": {
                "terms": {"field": "ano", "size": 50, "order": {"_key": "desc"}},
                "aggs": {"total_value": {"sum": value_source}},
            },
            "top_organos": {
                "terms": {"field": "organo_id", "size": top_n, "order": {"total_value": "desc"}},
                "aggs": {
                    "total_value": {"sum": value_source},
                    "name": {"top_hits": {"size": 1, "_source": ["organo_nombre", "organo_ciudad"]}},
                },
            },
            "top_adjudicatarios": {
                "terms": {
                    "field": "adjudicatario_nif",
                    "size": top_n,
                    "order": {"total_value": "desc"},
                },
                "aggs": {
                    "total_value": {"sum": value_source},
                    "name": {"top_hits": {"size": 1, "_source": ["adjudicatario_nombre"]}},
                },
            },
            "top_cpv": {
                "nested": {"path": "cpv"},
                "aggs": {
                    "codes": {
                        "terms": {"field": "cpv.code", "size": top_n, "order": {"total_value": "desc"}},
                        "aggs": {
                            "nombre": {"top_hits": {"size": 1, "_source": ["cpv.code", "cpv.nombre"]}},
                            "total_value": {"reverse_nested": {}, "aggs": {"value": {"sum": value_source}}},
                        },
                    }
                },
            },
            "procedure_types": with_value({
                "terms": {"field": "procedimiento_label", "size": 10, "missing": "N/A"},
            }),
            "contract_types": with_value({
                "terms": {"field": "tipo_contrato_label", "size": 10, "missing": "N/A"},
            }),
            "by_value_range": {
                "histogram": {"script": value_source["script"], "interval": 1000000, "min_doc_count": 1}
            },
            "organos": {"cardinality": {"field": "organo_id", "precision_threshold": 4000}},
            "adjudicatarios": {"cardinality": {"field": "adjudicatario_nif", "precision_threshold": 40000}},
            "top_contracts": {
                "top_hits": {
                    "size": contracts_size,
                    "sort": [
                        {"valor_adjudicado": {"order": "desc", "missing": "_last", "unmapped_type": "float"}}
                    ],
                    "_source": [
                        "objeto",
                        "descripcion",
                        "organo_nombre",
                        "adjudicatario_nombre",
                        "valor_adjudicado",
                        "valor_base",
                        "ano",
                        "fecha_adjudicacion",
                        "fecha_publicacion",
                        "id_expediente",
                    ],
                }
            },
        },
    }

    resp = client.search(index=CONTRATOS_ES_INDEX, body=body)
    aggs = resp.get("aggregations", {}) or {}

    def agg_value(bucket: Dict[str, Any]) -> float:
        raw = (bucket or {}).get("total_value", {})
        value = raw.get("value") if isinstance(raw, dict) else None
        if isinstance(value, dict):  # reverse_nested/sum encaixado
            value = value.get("value")
        return round(float(value or 0.0), 2)

    def rows(agg_name: str, label_field: Optional[str] = None) -> List[Dict[str, Any]]:
        out = []
        for bucket in (aggs.get(agg_name, {}) or {}).get("buckets", []):
            row = {"key": str(bucket.get("key")), "count": bucket.get("doc_count", 0), "total_value": agg_value(bucket)}
            if label_field:
                row["description"] = row["key"]
            out.append(row)
        return out

    cpv_rows = []
    for bucket in (aggs.get("top_cpv", {}) or {}).get("codes", {}).get("buckets", []):
        cpv_rows.append({
            "key": str(bucket.get("key")),
            "count": bucket.get("doc_count", 0),
            "total_value": agg_value(bucket),
            "description": _top_hit_cpv_es_name(bucket.get("nombre"), bucket.get("key")),
        })

    value_ranges = []
    for bucket in (aggs.get("by_value_range", {}) or {}).get("buckets", []):
        start = bucket.get("key")
        if start is None or start < 0 or len(value_ranges) >= 12:
            continue
        value_ranges.append({
            "key": str(int(start)),
            "count": bucket.get("doc_count", 0),
            "total_value": agg_value(bucket),
            "description": f"{int(start):,} – {int(start) + 1000000:,} €".replace(",", " "),
        })

    top_value = float(aggs.get("total_value", {}).get("value") or 0.0)

    def entity_rows(agg_name: str, name_field: str) -> List[Dict[str, Any]]:
        """Linhas de entidades a partir de um `terms` por identificador (DIR3/NIF).

        A chave do bucket é o identificador da entidade e o nome vem dos
        `top_hits` — é o que permite abrir a ficha (dossiê ou contratos) da linha.
        """
        out = []
        for bucket in (aggs.get(agg_name, {}) or {}).get("buckets", []):
            value = agg_value(bucket)
            count = bucket.get("doc_count", 0)
            identifier = str(bucket.get("key") or "")
            name = identifier
            hits = ((bucket.get("name") or {}).get("hits") or {}).get("hits") or []
            if hits:
                source = hits[0].get("_source") or {}
                name = str(source.get(name_field) or name)
            out.append({
                "nif": identifier or None,
                "name": _unescape_label(name),
                "count": count,
                "total_value": value,
                "avg_value": round(value / count, 2) if count else None,
                "share": round(value / top_value, 4) if top_value > 0 else None,
            })
        return out

    contract_rows = []
    for hit in ((aggs.get("top_contracts", {}) or {}).get("hits", {}) or {}).get("hits", []):
        source = hit.get("_source") or {}
        value = source.get("valor_adjudicado")
        contract_rows.append({
            "doc_id": hit.get("_id") or source.get("id_expediente"),
            "title": source.get("objeto") or source.get("descripcion") or "",
            "awarder": _unescape_label(source.get("organo_nombre")),
            "supplier": _unescape_label(source.get("adjudicatario_nombre")),
            "value": value if value is not None else source.get("valor_base"),
            "ano": source.get("ano"),
            "date": source.get("fecha_adjudicacion") or source.get("fecha_publicacion"),
        })

    return {
        "pais": "ES",
        "code": code,
        "ano": ano,
        "filters": {"q": q or None, "cpv": cpv or None},
        "totals": {
            "contracts": resp.get("hits", {}).get("total", {}).get("value", 0),
            "value": round(top_value, 2),
            "avg": round(float(aggs.get("avg_value", {}).get("value") or 0.0), 2) or None,
            "max": round(float(aggs.get("max_value", {}).get("value") or 0.0), 2) or None,
            "awarders": int((aggs.get("organos", {}) or {}).get("value") or 0),
            "suppliers": int((aggs.get("adjudicatarios", {}) or {}).get("value") or 0),
        },
        "by_year": rows("by_year"),
        "by_cpv": cpv_rows,
        "by_procedure": rows("procedure_types", label_field="key"),
        "by_contract_type": rows("contract_types", label_field="key"),
        "by_value_range": value_ranges,
        "awarders": entity_rows("top_organos", "organo_nombre"),
        "suppliers": entity_rows("top_adjudicatarios", "adjudicatario_nombre"),
        "contracts": contract_rows,
        "error": None,
    }




def _fr_region_detail(
    client: Elasticsearch,
    code: str,
    level: str,
    ano: Optional[int],
    q: Optional[str],
    cpv: Optional[str],
    top_n: int,
    contracts_size: int,
) -> Dict[str, Any]:
    """Ficha de uma região francesa: departamento, região ou país.

    Usa a mesma base da pesquisa da página de França, filtrando por
    `lieu_execution_code` e `lieu_execution_type`. O `level` diz se o código é
    um departamento (`departamento`), uma região (`regiao`) ou o país (`pais`).
    """
    from api.contratos_fr_map import TIPOS_DEPARTAMENTO, TIPOS_PREFIXO

    value_source = _contratos_fr_value_source("montant")

    if level == "pais":
        lieu_type = "Code pays"
    elif level == "regiao":
        lieu_type = "Code région"
    else:
        lieu_type = None

    query = _build_contratos_fr_query(
        q=q,
        ano=ano,
        cpv_code=cpv,
        lieu_execution_code=code,
        lieu_execution_type=lieu_type,
    )
    if level == "departamento":
        text = " ".join(part.strip() for part in (q,) if part and part.strip())
        must = query["bool"].get("must", [])
        filters = [f for f in query["bool"].get("filter", [])]
        # Código exato (Code département) OU prefixo dos tipos postais/comunais.
        loc_filter = {
            "bool": {
                "should": [
                    {
                        "bool": {
                            "filter": [
                                {"term": {"lieu_execution_code": code}},
                                {"terms": {"lieu_execution_type": list(TIPOS_DEPARTAMENTO)}},
                            ]
                        }
                    },
                    {
                        "bool": {
                            "filter": [
                                {"terms": {"lieu_execution_type": list(TIPOS_PREFIXO)}},
                                {"prefix": {"lieu_execution_code": code}},
                            ]
                        }
                    },
                ],
                "minimum_should_match": 1,
            }
        }
        filters = [f for f in filters if not (isinstance(f, dict) and f.get("prefix", {}).get("lieu_execution_code"))]
        filters = [f for f in filters if not (isinstance(f, dict) and f.get("term", {}).get("lieu_execution_type"))]
        query = {"bool": {"must": must, "filter": filters + [loc_filter]}}
        if text:
            query = _with_required(query, _iberia_text_query(text, _IBERIA_TEXT_FIELDS_FR))
    elif q:
        query = _with_required(query, _iberia_text_query(q, _IBERIA_TEXT_FIELDS_FR))

    def with_value(agg: Dict[str, Any]) -> Dict[str, Any]:
        return {**agg, "aggs": {"total_value": {"sum": value_source}}}

    body: Dict[str, Any] = {
        "size": 0,
        "track_total_hits": True,
        "query": query,
        "aggs": {
            "total_value": {"sum": value_source},
            "avg_value": {"avg": value_source},
            "max_value": {"max": value_source},
            "by_year": {
                "terms": {"field": "ano", "size": 50, "order": {"_key": "desc"}},
                "aggs": {"total_value": {"sum": value_source}},
            },
            "top_acheteurs": {
                "terms": {"field": "acheteur_nom.keyword", "size": top_n, "order": {"total_value": "desc"}},
                "aggs": {"total_value": {"sum": value_source}},
            },
            "top_adjudicatarios": {
                "terms": {"field": "adjudicatario_nom.keyword", "size": top_n, "order": {"total_value": "desc"}},
                "aggs": {"total_value": {"sum": value_source}},
            },
            "top_cpv": {
                "nested": {"path": "cpv"},
                "aggs": {
                    "codes": {
                        "terms": {"field": "cpv.code", "size": top_n, "order": {"total_value": "desc"}},
                        "aggs": {
                            "nom": {"top_hits": {"size": 1, "_source": ["cpv.code", "cpv.nom"]}},
                            "total_value": {"reverse_nested": {}, "aggs": {"value": {"sum": value_source}}},
                        },
                    }
                },
            },
            "procedures": with_value({"terms": {"field": "procedure", "size": 10, "missing": "N/A"}}),
            "natures": with_value({"terms": {"field": "nature", "size": 10, "missing": "N/A"}}),
            "by_value_range": {
                "histogram": {"script": value_source["script"], "interval": 100000, "min_doc_count": 1}
            },
            "top_contracts": {
                "top_hits": {
                    "size": contracts_size,
                    "sort": [{"montant": {"order": "desc", "missing": "_last", "unmapped_type": "float"}}],
                    "_source": [
                        "objet",
                        "acheteur_nom",
                        "adjudicatario_nom",
                        "montant",
                        "montant_estime",
                        "ano",
                        "date_notification",
                        "date_publication",
                        "uid",
                    ],
                }
            },
        },
    }

    resp = client.search(index=CONTRATOS_FR_INDEX, body=body)
    aggs = resp.get("aggregations", {}) or {}

    def agg_value(bucket: Dict[str, Any]) -> float:
        raw = (bucket or {}).get("total_value", {})
        value = raw.get("value") if isinstance(raw, dict) else None
        if isinstance(value, dict):
            value = value.get("value")
        return round(float(value or 0.0), 2)

    def rows(agg_name: str) -> List[Dict[str, Any]]:
        return [
            {"key": str(b["key"]), "count": b["doc_count"], "total_value": agg_value(b)}
            for b in (aggs.get(agg_name, {}) or {}).get("buckets", [])
        ]

    cpv_rows = []
    for bucket in (aggs.get("top_cpv", {}) or {}).get("codes", {}).get("buckets", []):
        cpv_rows.append({
            "key": str(bucket.get("key")),
            "count": bucket.get("doc_count", 0),
            "total_value": agg_value(bucket),
            "description": _top_hit_cpv_fr_name(bucket.get("nom"), bucket.get("key")),
        })

    value_ranges = []
    for bucket in (aggs.get("by_value_range", {}) or {}).get("buckets", []):
        start = bucket.get("key")
        if start is None or start < 0 or len(value_ranges) >= 12:
            continue
        value_ranges.append({
            "key": str(int(start)),
            "count": bucket.get("doc_count", 0),
            "total_value": agg_value(bucket),
            "description": f"{int(start):,} – {int(start) + 100000:,} €".replace(",", " "),
        })

    top_value = float(aggs.get("total_value", {}).get("value") or 0.0)

    def entity_rows(agg_name: str) -> List[Dict[str, Any]]:
        out = []
        for bucket in (aggs.get(agg_name, {}) or {}).get("buckets", []):
            value = agg_value(bucket)
            count = bucket.get("doc_count", 0)
            name = str(bucket.get("key") or "")
            out.append({
                "nif": None,
                "name": _unescape_label(name),
                "count": count,
                "total_value": value,
                "avg_value": round(value / count, 2) if count else None,
                "share": round(value / top_value, 4) if top_value > 0 else None,
            })
        return out

    contract_rows = []
    for hit in ((aggs.get("top_contracts", {}) or {}).get("hits", {}) or {}).get("hits", []):
        source = hit.get("_source") or {}
        value = source.get("montant")
        contract_rows.append({
            "doc_id": hit.get("_id") or source.get("uid"),
            "title": source.get("objet") or "",
            "awarder": _unescape_label(source.get("acheteur_nom")),
            "supplier": _unescape_label(source.get("adjudicatario_nom")),
            "value": value if value is not None else source.get("montant_estime"),
            "ano": source.get("ano"),
            "date": source.get("date_notification") or source.get("date_publication"),
        })

    return {
        "pais": "FR",
        "code": code,
        "level": level,
        "ano": ano,
        "filters": {"q": q or None, "cpv": cpv or None},
        "totals": {
            "contracts": resp.get("hits", {}).get("total", {}).get("value", 0),
            "value": round(top_value, 2),
            "avg": round(float(aggs.get("avg_value", {}).get("value") or 0.0), 2) or None,
            "max": round(float(aggs.get("max_value", {}).get("value") or 0.0), 2) or None,
            "awarders": len((aggs.get("top_acheteurs", {}) or {}).get("buckets", [])),
            "suppliers": len((aggs.get("top_adjudicatarios", {}) or {}).get("buckets", [])),
        },
        "by_year": rows("by_year"),
        "by_cpv": cpv_rows,
        "by_procedure": rows("procedures"),
        "by_contract_type": rows("natures"),
        "by_value_range": value_ranges,
        "awarders": entity_rows("top_acheteurs"),
        "suppliers": entity_rows("top_adjudicatarios"),
        "contracts": contract_rows,
        "error": None,
    }




def get_contract_region_detail(
    pais: str,
    code: str,
    ano: Optional[int] = None,
    q: Optional[str] = None,
    cpv: Optional[str] = None,
    top_n: int = 12,
    contracts_size: int = 20,
    level: Optional[str] = None,
    es: Optional[Elasticsearch] = None,
) -> Dict[str, Any]:
    """Contratos, entidades (adjudicantes e adjudicatárias) e métricas de uma região.

    `pais="PT"` espera o **distrito** de execução («Bragança»); `pais="ES"` espera o
    **código NUTS** («ES300»); `pais="FR"` espera o **código de departamento/região**
    (ex.: «75» ou «11»). Alimenta a janela aberta no menu de contexto do mapa,
    onde `q` (texto) e `cpv` filtram métricas, entidades e contratos ao mesmo tempo.

    Para França, o parâmetro `level` indica se o código é `departamento`, `regiao`
    ou `pais` (necessário porque alguns códigos colidem entre regiões e
    departamentos).
    """
    client = es or get_es_client(request_timeout=120)
    if not client:
        return {"error": "Elasticsearch indisponível"}

    ensure_indices(client)

    try:
        pais_norm = (pais or "").strip().upper()
        if pais_norm == "ES":
            return _es_region_detail(client, code, ano, q, cpv, top_n, contracts_size)
        if pais_norm == "FR":
            return _fr_region_detail(client, code, level or "departamento", ano, q, cpv, top_n, contracts_size)
        return _pt_region_detail(client, code, ano, q, cpv, top_n, contracts_size)
    except Exception as exc:  # pragma: no cover - dependente do cluster
        return {"error": str(exc)}
