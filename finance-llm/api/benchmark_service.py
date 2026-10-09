"""Benchmark de preços e concorrência por **empresa + CPV** (contratos públicos PT).

Responde a três perguntas de quem vende ou compra ao Estado:

1. **Preço de referência** — como se comportam os valores do segmento (um CPV,
   uma janela de anos) no mercado: mediana, quartis, média, mínimo e máximo.
   Serve de bitola para saber se um preço é bom ou caro.
2. **Concorrência** — quem são os pares (entidades no mesmo papel) nesse
   segmento, com quantos contratos e que valor, e em que posição fica a empresa.
3. **Oportunidades e historial** — as contrapartes do segmento (quem compra, se
   a empresa vende; quem vende, se a empresa compra), quem a empresa já conhece
   (historial) e quem nunca contratou com ela (oportunidade).

Tudo sai de **um** pedido ao índice `contratos` (agregações nested sobre
`adjudicantes.parsed`, `adjudicatarios.parsed` e `cpv`), pelo que a página é
utilizável sem uma bateria de chamadas.

Decisões que interessam:

- **Só valores positivos** entram nas estatísticas de preço: o índice tem notas
  de crédito/correções com `precoContratual` negativo que baixariam a mediana.
- Os rankings por valor são ordenados em Python a partir dos candidatos
  ordenados por nº de contratos (o Elasticsearch não ordena `terms` por uma
  métrica dentro de `reverse_nested`); a lista é ampla (100) para o ranking da
  empresa não ser enganador. Fica registado em `notes`.
- Sem CPV, o módulo devolve os CPV principais da empresa para se escolher um.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from api.elasticsearch_client import (
    CONTRACTS_INDEX,
    _cpv_description_from_hits,
    _region_filter,
    _top_hit_name,
    get_es_client,
)

logger = logging.getLogger(__name__)

#: Papel da entidade **no contrato**: `adjudicatario` = vende (fornecedor);
#: `adjudicante` = compra (entidade pública / comprador).
ROLES = ("adjudicatario", "adjudicante")

#: Caminho nested onde vive cada papel.
_ROLE_PATH = {"adjudicante": "adjudicantes.parsed", "adjudicatario": "adjudicatarios.parsed"}

#: Quantos candidatos se recolhem em cada ranking (ordenado por valor).
_CANDIDATES = 50
#: Percentis do preço de referência.
_PERCENTS = [10, 25, 50, 75, 90]

#: Timeout das pesquisas (o segmento sem CPV varre 2,2 M contratos).
_REQUEST_TIMEOUT = 120


def _counterpart_role(role: str) -> str:
    """O papel da contraparte (quem está do outro lado do contrato)."""
    return "adjudicante" if role == "adjudicatario" else "adjudicatario"


def _cpv_filter(cpv_code: Optional[str]) -> Optional[Dict[str, Any]]:
    """Filtro pelo CPV (prefixo: `90511000` casa `90511000-2`)."""
    code = (cpv_code or "").strip()
    if not code:
        return None
    return {"nested": {"path": "cpv", "query": {"prefix": {"cpv.code": code}}}}


def _entity_filter(
    role: str,
    nif: Optional[str] = None,
    name: Optional[str] = None,
) -> Dict[str, Any]:
    """Filtro nested que identifica a entidade no seu papel (por NIF ou nome)."""
    path = _ROLE_PATH[role]
    code = (nif or "").strip()
    if code:
        query: Dict[str, Any] = {"term": {f"{path}.nif": code}}
    else:
        query = {"match": {f"{path}.nome": (name or "").strip()}}
    return {"nested": {"path": path, "query": query}}


def _segment_filters(
    cpv_code: Optional[str],
    year_from: Optional[int],
    year_to: Optional[int],
    region: Optional[str],
) -> List[Dict[str, Any]]:
    """Filtros do segmento de mercado (CPV + anos + região)."""
    filters: List[Dict[str, Any]] = []
    cpv = _cpv_filter(cpv_code)
    if cpv:
        filters.append(cpv)
    year_range: Dict[str, Any] = {}
    if year_from is not None:
        year_range["gte"] = int(year_from)
    if year_to is not None:
        year_range["lte"] = int(year_to)
    if year_range:
        filters.append({"range": {"Ano": year_range}})
    if region:
        region_filter = _region_filter(region)
        if region_filter:
            filters.append(region_filter)
    return filters


def _role_rank_agg(path: str, size: int) -> Dict[str, Any]:
    """Nested `terms` por NIF de um papel, ordenado pelo valor somado.

    A ordenação usa o caminho `value>sum` (métrica dentro de `reverse_nested`),
    pelo que o ranking é por **valor** e não por nº de contratos.
    """
    return {
        "nested": {"path": path},
        "aggs": {
            "top": {
                "terms": {
                    "field": f"{path}.nif",
                    "size": size,
                    "order": {"value>sum": "desc"},
                },
                "aggs": {
                    "name": {"top_hits": {"size": 1, "_source": True}},
                    "value": {
                        "reverse_nested": {},
                        "aggs": {
                            "sum": {"sum": {"field": "precoContratual"}},
                            "last": {"max": {"field": "dataCelebracaoContrato"}},
                        },
                    },
                },
            }
        },
    }


def _rows(agg: Optional[Dict[str, Any]], top: int, total_value: float) -> List[Dict[str, Any]]:
    """Converte os buckets de um ranking em linhas ordenadas por valor."""
    buckets = (((agg or {}).get("top") or {}).get("buckets")) or []
    rows: List[Dict[str, Any]] = []
    for bucket in buckets:
        key = bucket.get("key")
        if not key:
            continue
        value_bucket = bucket.get("value") or {}
        value = (value_bucket.get("sum") or {}).get("value")
        last_bucket = value_bucket.get("last") or {}
        rows.append(
            {
                "nif": str(key),
                "name": _top_hit_name(bucket.get("name")) or str(key),
                "count": int(bucket.get("doc_count") or 0),
                "value": round(float(value), 2) if value is not None else None,
                "last_date": last_bucket.get("value_as_string") or None,
            }
        )
    rows.sort(key=lambda row: (row.get("value") or 0.0, row.get("count") or 0), reverse=True)
    for index, row in enumerate(rows):
        row["rank"] = index + 1
        row["share_pct"] = (
            round(100.0 * (row.get("value") or 0.0) / total_value, 2) if total_value else None
        )
    return rows[:top]


def _stats(agg: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """`count/sum/avg/min/max` de uma agregação `stats`, arredondada."""
    data = agg or {}
    count = data.get("count") or 0

    def money(key: str) -> Optional[float]:
        value = data.get(key)
        return round(float(value), 2) if value is not None and count else None

    return {"count": int(count), "sum": money("sum"), "avg": money("avg"), "min": money("min"), "max": money("max")}


def _percentiles(agg: Optional[Dict[str, Any]]) -> Dict[str, Optional[float]]:
    """Percentis de uma agregação `percentiles` (chave legível: `p50`)."""
    values = ((agg or {}).get("values")) or {}
    out: Dict[str, Optional[float]] = {}
    for key, value in values.items():
        label = f"p{int(float(key))}"
        out[label] = round(float(value), 2) if value is not None else None
    return out


def _cardinality(agg: Optional[Dict[str, Any]]) -> int:
    return int((((agg or {}).get("value")) or {}).get("value") or 0)


def _entity_hit_name(agg: Optional[Dict[str, Any]], role_path: str) -> str:
    """Nome da entidade a partir de `top_hits` sobre o documento do contrato."""
    hits = (((agg or {}).get("hits")) or {}).get("hits") or []
    for hit in hits:
        nome = _party_name(hit.get("_source"), role_path)
        if nome:
            return nome
    return ""


def _party_name(source: Optional[Dict[str, Any]], role_path: str) -> str:
    """Nome da entidade no seu papel, lido do documento do contrato.

    Os `top_hits` sobre o documento pai trazem o `_source` completo, onde a parte
    vive em `adjudicantes`/`adjudicatarios` → `parsed` → `{nif, nome}`.
    """
    root = role_path.split(".")[0]
    parties = (source or {}).get(root)
    if isinstance(parties, dict):
        parties = [parties]
    if not isinstance(parties, list):
        return ""
    for party in parties:
        parsed = party.get("parsed") if isinstance(party, dict) else None
        if isinstance(parsed, dict):
            nome = parsed.get("nome")
            if nome:
                return str(nome).strip()
        elif isinstance(parsed, list):
            for item in parsed:
                if isinstance(item, dict) and item.get("nome"):
                    return str(item["nome"]).strip()
    return ""


def benchmark_entity(
    *,
    nif: Optional[str] = None,
    name: Optional[str] = None,
    role: str = "adjudicatario",
    cpv_code: Optional[str] = None,
    year_from: Optional[int] = None,
    year_to: Optional[int] = None,
    region: Optional[str] = None,
    top: int = 12,
    es: Any = None,
) -> Dict[str, Any]:
    """Benchmark de preços, concorrência e oportunidades de uma entidade + CPV."""
    role = role if role in ROLES else "adjudicatario"
    if not (nif or (name or "").strip()):
        return {"error": "Indique a entidade (NIF ou nome)."}

    client = es or get_es_client(request_timeout=_REQUEST_TIMEOUT)
    if not client:
        return {"error": "Elasticsearch indisponível"}

    entity_role_path = _ROLE_PATH[role]
    counterpart_path = _ROLE_PATH[_counterpart_role(role)]
    entity_filter = _entity_filter(role, nif=nif, name=name)
    filters = _segment_filters(cpv_code, year_from, year_to, region)
    query: Dict[str, Any] = {"bool": {"filter": filters}} if filters else {"match_all": {}}

    top = max(1, min(int(top or 12), 50))
    candidates = max(_CANDIDATES, top)

    positive_price = {"range": {"precoContratual": {"gt": 0}}}

    body: Dict[str, Any] = {
        "size": 0,
        "track_total_hits": True,
        "query": query,
        "aggs": {
            # --- preço de referência do mercado (só valores positivos) ---
            "market_value": {"stats": {"field": "precoContratual"}},
            "market_priced": {
                "filter": positive_price,
                "aggs": {
                    "stats": {"stats": {"field": "precoContratual"}},
                    "percentiles": {"percentiles": {"field": "precoContratual", "percents": _PERCENTS}},
                },
            },
            # --- dimensão do mercado ---
            "market_peers": {
                "nested": {"path": entity_role_path},
                "aggs": {"value": {"cardinality": {"field": f"{entity_role_path}.nif"}}},
            },
            "market_counterparts": {
                "nested": {"path": counterpart_path},
                "aggs": {"value": {"cardinality": {"field": f"{counterpart_path}.nif"}}},
            },
            # --- concorrência: pares (mesmo papel) por valor contratado ---
            "peers": _role_rank_agg(entity_role_path, candidates),
            # --- mercado: contrapartes mais fortes do segmento ---
            "counterparts": _role_rank_agg(counterpart_path, max(top * 2, 40)),
            # --- a empresa no segmento ---
            "entity": {
                "filter": entity_filter,
                "aggs": {
                    "name": {"top_hits": {"size": 1, "_source": True}},
                    "stats": {"stats": {"field": "precoContratual"}},
                    "priced": {
                        "filter": positive_price,
                        "aggs": {
                            "percentiles": {
                                "percentiles": {"field": "precoContratual", "percents": [25, 50, 75]}
                            }
                        },
                    },
                    "last": {"max": {"field": "dataCelebracaoContrato"}},
                    "by_year": {
                        "terms": {"field": "Ano", "size": 40, "order": {"_key": "desc"}},
                        "aggs": {"value": {"sum": {"field": "precoContratual"}}},
                    },
                    "cpv": {
                        "nested": {"path": "cpv"},
                        "aggs": {
                            "top": {
                                "terms": {"field": "cpv.code", "size": 12, "order": {"_count": "desc"}},
                                "aggs": {
                                    "description": {"top_hits": {"size": 1, "_source": True}},
                                    "value": {
                                        "reverse_nested": {},
                                        "aggs": {"sum": {"sum": {"field": "precoContratual"}}},
                                    },
                                },
                            }
                        },
                    },
                    # Historial: contrapartes com quem a empresa já contratou neste segmento.
                    "counterparts": _role_rank_agg(counterpart_path, max(top * 2, 40)),
                    "recent": {
                        "top_hits": {
                            "size": 8,
                            "sort": [{"dataCelebracaoContrato": {"order": "desc", "missing": "_last"}}],
                            "_source": [
                                "idcontrato",
                                "objectoContrato",
                                "precoContratual",
                                "dataCelebracaoContrato",
                                "dataPublicacao",
                                "tipoprocedimento",
                                "adjudicantes",
                                "adjudicatarios",
                            ],
                        }
                    },
                },
            },
            # --- oportunidades: contrapartes do segmento que a empresa nunca serviu ---
            "opportunities": {
                "filter": {"bool": {"must_not": [entity_filter]}},
                "aggs": {"top": _role_rank_agg(counterpart_path, max(top * 2, 40))},
            },
        },
    }

    try:
        resp = client.search(index=CONTRACTS_INDEX, body=body)
    except Exception as exc:  # pragma: no cover - erro de cluster
        logger.warning("Benchmark falhou: %s", exc)
        return {"error": str(exc)}

    aggs = resp.get("aggregations") or {}
    market_priced = aggs.get("market_priced") or {}
    market_stats = _stats(market_priced.get("stats"))
    market_pct = _percentiles(market_priced.get("percentiles"))
    market_total_value = market_stats.get("sum") or 0.0

    entity_agg = aggs.get("entity") or {}
    entity_stats = _stats(entity_agg.get("stats"))
    entity_priced_pct = _percentiles((entity_agg.get("priced") or {}).get("percentiles"))
    entity_name = (
        _entity_hit_name(entity_agg.get("name"), entity_role_path)
        or _entity_hit_name(entity_agg.get("name"), counterpart_path)
        or (name or "")
    )
    entity_total_value = entity_stats.get("sum") or 0.0

    peers = _rows(aggs.get("peers"), candidates, market_total_value)
    entity_nif = (nif or "").strip()
    entity_rank: Optional[int] = None
    if entity_nif:
        for row in peers:
            if row["nif"] == entity_nif:
                entity_rank = row.get("rank")
                break
    peer_rows = peers[:top]

    counterparts = _rows(aggs.get("counterparts"), top, market_total_value)
    history = _rows(entity_agg.get("counterparts"), top, entity_total_value)
    known_nifs = {row["nif"] for row in history}

    roles_label = "vende (adjudicatário)" if role == "adjudicatario" else "compra (adjudicante)"
    why_opportunity = (
        "Compra este CPV e nunca contratou com a empresa"
        if role == "adjudicatario"
        else "Vende este CPV e nunca contratou com a empresa"
    )
    opportunities = [
        {**row, "why": why_opportunity}
        for row in _rows((aggs.get("opportunities") or {}).get("top"), max(top * 2, 40), market_total_value)
        if row["nif"] not in known_nifs and row["nif"] != entity_nif
    ][:top]

    market_median = market_pct.get("p50")
    entity_median = entity_priced_pct.get("p50")
    price_index = None
    if market_median and entity_median:
        price_index = round(entity_median / market_median, 3)

    count_share = None
    market_priced_count = market_stats.get("count") or 0
    if market_priced_count:
        count_share = round(100.0 * (entity_stats.get("count") or 0) / market_priced_count, 2)

    value_share = None
    if market_total_value:
        value_share = round(100.0 * entity_total_value / market_total_value, 2)

    cpv_rows: List[Dict[str, Any]] = []
    for bucket in (((entity_agg.get("cpv") or {}).get("top") or {}).get("buckets")) or []:
        value = (((bucket.get("value") or {}).get("sum")) or {}).get("value")
        cpv_rows.append(
            {
                "code": str(bucket.get("key")),
                "description": _cpv_description_from_hits(bucket.get("description"), bucket.get("key")),
                "count": int(bucket.get("doc_count") or 0),
                "value": round(float(value), 2) if value is not None else None,
            }
        )

    by_year = [
        {
            "year": str(bucket.get("key")),
            "count": int(bucket.get("doc_count") or 0),
            "value": round(float(((bucket.get("value") or {}).get("value")) or 0.0), 2),
        }
        for bucket in (((entity_agg.get("by_year") or {}).get("buckets")) or [])
    ]

    recent: List[Dict[str, Any]] = []
    for hit in ((((entity_agg.get("recent") or {}).get("hits")) or {}).get("hits")) or []:
        source = hit.get("_source") or {}
        recent.append(
            {
                "idcontrato": source.get("idcontrato"),
                "objecto": source.get("objectoContrato"),
                "value": source.get("precoContratual"),
                "date": source.get("dataCelebracaoContrato") or source.get("dataPublicacao"),
                "counterpart": _hit_counterpart(source, counterpart_path),
            }
        )

    notes: List[str] = []
    if cpv_code:
        notes.append(f"Segmento: contratos com CPV {cpv_code}.")
    else:
        notes.append("Sem CPV selecionado: o preço de referência refere-se ao total do mercado filtrado.")
    notes.append("Percentis aproximados (TDigest do Elasticsearch) sobre valores positivos.")
    notes.append("Os rankings são por valor contratual; as listas mostram as maiores posições do segmento.")
    if entity_nif and entity_rank is None:
        notes.append(
            f"A empresa não está entre as {candidates} entidades de maior valor no segmento "
            "(a posição não é apresentada)."
        )
    if entity_nif and not (entity_stats.get("count") or 0):
        notes.append(f"Sem contratos no segmento com o papel {roles_label}.")

    return {
        "role": role,
        "entity": {
            "nif": entity_nif or None,
            "name": entity_name,
            "contracts": entity_stats.get("count") or 0,
            "total_value": round(float(entity_total_value), 2),
            "avg_value": entity_stats.get("avg"),
            "median_value": entity_median,
            "last_date": ((entity_agg.get("last") or {}).get("value_as_string")) or None,
            "rank": entity_rank,
            "share_pct": value_share,
            "count_share_pct": count_share,
            "price_index": price_index,
            "present": bool(entity_stats.get("count") or 0),
            "by_year": by_year,
            "top_cpv": cpv_rows,
            "recent": recent,
        },
        "reference": {
            "scope": "mercado",
            "contracts": market_stats.get("count") or 0,
            "total_value": round(float(market_total_value), 2),
            "avg": market_stats.get("avg"),
            "median": market_median,
            "p10": market_pct.get("p10"),
            "p25": market_pct.get("p25"),
            "p75": market_pct.get("p75"),
            "p90": market_pct.get("p90"),
            "min": market_stats.get("min"),
            "max": market_stats.get("max"),
        },
        "market": {
            "contracts": ((resp.get("hits") or {}).get("total") or {}).get("value", 0),
            "peers": _cardinality(aggs.get("market_peers")),
            "counterparts": _cardinality(aggs.get("market_counterparts")),
        },
        "competitors": peer_rows,
        "counterparties": counterparts,
        "history": history,
        "opportunities": opportunities,
        "notes": notes,
    }


def _hit_counterpart(source: Dict[str, Any], counterpart_path: str) -> Optional[str]:
    """Nome da contraparte de um contrato (para o historial recente)."""
    root = counterpart_path.split(".")[0]
    parties = source.get(root)
    if isinstance(parties, dict):
        parties = [parties]
    if not isinstance(parties, list):
        return None
    names: List[str] = []
    for party in parties:
        parsed = party.get("parsed") if isinstance(party, dict) else None
        if isinstance(parsed, dict):
            name = parsed.get("nome")
            if name:
                names.append(str(name))
        elif isinstance(parsed, list):
            names.extend([str(item.get("nome")) for item in parsed if isinstance(item, dict) and item.get("nome")])
    return "; ".join(names) or None


def top_cpv(q: Optional[str] = None, size: int = 20, es: Any = None) -> Dict[str, Any]:
    """CPV mais usados no índice (para o seletor da página), com descrição."""
    client = es or get_es_client()
    if not client:
        return {"error": "Elasticsearch indisponível", "items": []}

    terms: Dict[str, Any] = {
        "terms": {
            "field": "cpv.code",
            "size": max(1, min(int(size or 20), 100)),
            "order": {"_count": "desc"},
        }
    }
    code = (q or "").strip()
    if code:
        terms["terms"]["include"] = f"{code}.*"

    body = {
        "size": 0,
        "query": {"match_all": {}},
        "aggs": {
            "cpv": {
                "nested": {"path": "cpv"},
                "aggs": {
                    "codes": {
                        **terms,
                        "aggs": {
                            "description": {"top_hits": {"size": 1, "_source": True}},
                            "value": {
                                "reverse_nested": {},
                                "aggs": {"sum": {"sum": {"field": "precoContratual"}}},
                            },
                        },
                    }
                },
            }
        },
    }
    try:
        resp = client.search(index=CONTRACTS_INDEX, body=body)
    except Exception as exc:  # pragma: no cover
        return {"error": str(exc), "items": []}

    items: List[Dict[str, Any]] = []
    for bucket in ((((resp.get("aggregations") or {}).get("cpv") or {}).get("codes") or {}).get("buckets")) or []:
        value = (((bucket.get("value") or {}).get("sum")) or {}).get("value")
        items.append(
            {
                "code": str(bucket.get("key")),
                "description": _cpv_description_from_hits(bucket.get("description"), bucket.get("key")),
                "count": int(bucket.get("doc_count") or 0),
                "value": round(float(value), 2) if value is not None else None,
            }
        )
    return {"query": q, "items": items}


def benchmark_meta(es: Any = None) -> Dict[str, Any]:
    """Volumetria do índice de contratos e anos disponíveis."""
    client = es or get_es_client()
    if not client:
        return {"error": "Elasticsearch indisponível", "total": 0, "years": []}
    try:
        total = client.count(index=CONTRACTS_INDEX).get("count", 0)
        resp = client.search(
            index=CONTRACTS_INDEX,
            body={"size": 0, "aggs": {"years": {"terms": {"field": "Ano", "size": 50, "order": {"_key": "desc"}}}}},
        )
        years = [int(bucket["key"]) for bucket in resp["aggregations"]["years"]["buckets"]]
        return {"total": total, "years": years, "roles": list(ROLES)}
    except Exception as exc:  # pragma: no cover
        return {"error": str(exc), "total": 0, "years": []}
