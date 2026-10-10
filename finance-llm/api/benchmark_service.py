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
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Dict, List, Optional, Tuple

from api.elasticsearch_client import (
    _top_hit_name,
    get_es_client,
)
from api import benchmark_countries as bc

logger = logging.getLogger(__name__)

#: Papel da entidade **no contrato**: `adjudicatario` = vende (fornecedor);
#: `adjudicante` = compra (entidade pública / comprador).
ROLES = (bc.SUPPLIER, bc.BUYER)

#: Quantos candidatos se recolhem em cada ranking (ordenado por valor).
_CANDIDATES = 50
#: Percentis do preço de referência.
_PERCENTS = [10, 25, 50, 75, 90]

#: Máximo de empresas comparáveis de uma vez.
MAX_COMPARE = 10

#: Quantos compradores/vendedores se recolhem por empresa na comparação (os
#: maiores por valor); serve para a lista e para os compradores em comum.
_BUYERS_CANDIDATES = 20
#: Quantos compradores se mostram por empresa na comparação.
_BUYERS_SHOW = 5
#: Quantos CPV se mostram por empresa na comparação.
_CPV_SHOW = 8

#: Tolerância do índice de preço para dizer «na linha do mercado».
_PRICE_TOLERANCE = 0.1

#: Timeout das pesquisas (o segmento sem CPV varre milhões de contratos).
_REQUEST_TIMEOUT = 120


def _counterpart_role(role: str) -> str:
    """O papel da contraparte (quem está do outro lado do contrato)."""
    return bc.BUYER if role == bc.SUPPLIER else bc.SUPPLIER


def _segment_filters(
    country: Optional[str],
    cpv_code: Optional[str],
    year_from: Optional[int],
    year_to: Optional[int],
    region: Optional[str],
) -> List[Dict[str, Any]]:
    """Filtros do segmento de mercado (CPV + anos + região), no dialeto do país."""
    filtros: List[Dict[str, Any]] = []
    cpv = bc.cpv_filter(country, cpv_code)
    if cpv:
        filtros.append(cpv)
    anos = bc.year_filter(country, year_from, year_to)
    if anos:
        filtros.append(anos)
    regiao = bc.region_filter(country, region)
    if regiao:
        filtros.append(regiao)
    return filtros


def _rows(
    agg: Optional[Dict[str, Any]],
    top: int,
    total_value: float,
    country: Optional[str] = "pt",
    role: str = bc.SUPPLIER,
) -> List[Dict[str, Any]]:
    """Linhas de um ranking de entidades (nested em PT/FR, plano em ES)."""
    return bc.rank_rows(country, role, agg, top, total_value)


def _entity_cpv_agg(country: Optional[str], size: int) -> Dict[str, Any]:
    """Perfil de CPV de uma entidade (nested `terms`, com descrição e valor)."""
    return bc.cpv_agg(country, size)
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


def _entity_hit_name(agg: Optional[Dict[str, Any]], country: Optional[str], role: str) -> str:
    """Nome da entidade a partir de `top_hits` sobre o documento do contrato."""
    hits = (((agg or {}).get("hits")) or {}).get("hits") or []
    for hit in hits:
        nome = bc.nome_da_entidade(hit.get("_source"), country, role)
        if nome:
            return nome
    return ""


def search_entities(
    *,
    q: Optional[str] = None,
    role: str = "adjudicatario",
    country: str = "pt",
    size: int = 8,
    es: Any = None,
) -> Dict[str, Any]:
    """Entidades de um país no papel pedido (para os seletores da página).

    Devolve `{nif, name, contracts, total_value}` por entidade — a mesma forma
    nos três países, para o seletor não ter de conhecer os dialetos. Em França
    os dados não têm nomes: a pesquisa é por SIRET e o `name` devolve o próprio
    identificador.
    """
    client = es or get_es_client(request_timeout=_REQUEST_TIMEOUT)
    if not client:
        return {"error": "Elasticsearch indisponível", "items": []}

    role = role if role in ROLES else bc.SUPPLIER
    country = bc.country_key(country)
    texto = (q or "").strip()
    if len(texto) < 2:
        return {"country": country, "role": role, "query": q, "items": [], "total": 0}

    size = max(1, min(int(size or 8), 25))
    dialeto = bc.dialect(country)
    # No ranking só contam as entidades que casam com a pesquisa: em PT/FR a
    # parte é `nested` e, sem este filtro interno, uma empresa que partilha
    # contratos com a procurada aparecia na lista.
    filtro_ranking = None
    if bc.is_nested(country, role):
        filtro_ranking = bc.entity_search_query(country, role, texto)
    try:
        resp = client.search(
            index=dialeto["index"],
            body={
                "size": 0,
                "track_total_hits": True,
                "query": {"bool": {"filter": [bc.entity_search_filter(country, role, texto)]}},
                "aggs": {"entidades": bc.rank_agg(country, role, size, filtro=filtro_ranking)},
            },
        )
    except Exception as exc:  # pragma: no cover - depende do cluster
        logger.warning("Pesquisa de entidades falhou (%s, %s): %s", country, role, exc)
        return {"error": str(exc), "items": []}

    linhas = bc.rank_rows(country, role, resp.get("aggregations", {}).get("entidades"), size, None)
    itens = [
        {
            "nif": linha["nif"],
            "name": linha["name"],
            "contracts": linha["count"],
            "total_value": (linha.get("value") or 0.0) or None,
        }
        for linha in linhas
    ]
    return {"country": country, "role": role, "query": q, "items": itens, "total": len(itens)}


def top_entities(
    *,
    countries: Optional[List[str]] = None,
    role: str = "adjudicatario",
    cpv_code: Optional[str] = None,
    year_from: Optional[int] = None,
    year_to: Optional[int] = None,
    size: int = 10,
    cpv_size: int = 6,
    es: Any = None,
) -> Dict[str, Any]:
    """Empresas (ou compradores) de cada país, com os seus CPV principais.

    Serve o quadro «Tudo» do benchmark: aí não se comparam empresas de países
    diferentes (os mercados não são comparáveis um a um), mas mostra-se quem
    domina cada mercado e **em que CPV** — a lista sai agrupada por país, para
    não dar a ler uma hierarquia que não existe.
    """
    client = es or get_es_client(request_timeout=_REQUEST_TIMEOUT)
    if not client:
        return {"error": "Elasticsearch indisponível"}

    role = role if role in ROLES else bc.SUPPLIER
    escolhidos = [bc.country_key(c) for c in (countries or list(bc.COUNTRIES))]
    escolhidos = [c for c in bc.COUNTRIES if c in escolhidos] or list(bc.COUNTRIES)
    size = max(1, min(int(size or 10), 30))
    cpv_size = max(1, min(int(cpv_size or 6), 20))

    resumo: List[Dict[str, Any]] = []
    itens: List[Dict[str, Any]] = []
    for pais in escolhidos:
        dialeto = bc.dialect(pais)
        filtros = [
            filtro
            for filtro in (bc.cpv_filter(pais, cpv_code), bc.year_filter(pais, year_from, year_to))
            if filtro
        ]
        try:
            corpo: Dict[str, Any] = {
                "size": 0,
                "track_total_hits": True,
                "query": ({"bool": {"filter": filtros}} if filtros else {"match_all": {}}),
                "aggs": {
                    "entidades": bc.rank_agg(pais, role, size, cpv_size=cpv_size),
                    "valor": {
                        "filter": {"bool": {"filter": bc.value_filters(pais)}},
                        "aggs": {"soma": bc.value_sum(pais)},
                    },
                },
            }
            resp = client.search(index=dialeto["index"], body=corpo)
        except Exception as exc:  # pragma: no cover - depende do cluster
            logger.warning("Empresas por CPV falhou (%s, %s): %s", pais, role, exc)
            resumo.append({"country": pais, "label": dialeto["label"], "short": dialeto["short"], "error": str(exc)})
            continue

        mercado = ((resp.get("aggregations", {}).get("valor") or {}).get("soma") or {}).get("value")
        contratos = int(((resp.get("hits", {}).get("total") or {}).get("value")) or 0)
        linhas = bc.rank_rows(pais, role, resp.get("aggregations", {}).get("entidades"), size, mercado)
        resumo.append(
            {
                "country": pais,
                "label": dialeto["label"],
                "short": dialeto["short"],
                "index": dialeto["index"],
                "contracts": contratos,
                "total_value": round(float(mercado), 2) if mercado else None,
                "entities": len(linhas),
            }
        )
        for linha in linhas:
            itens.append(
                {
                    "country": pais,
                    "country_label": dialeto["label"],
                    "short": dialeto["short"],
                    "rank": linha.get("rank"),
                    "nif": linha.get("nif"),
                    "name": linha.get("name"),
                    "contracts": linha.get("count"),
                    "value": linha.get("value"),
                    "share_pct": linha.get("share_pct"),
                    "last_date": linha.get("last_date"),
                    "cpvs": linha.get("cpvs") or [],
                }
            )

    notas: List[str] = []
    if role == bc.SUPPLIER:
        notas.append(
            "Só entidades com contratos no segmento filtrado: a lista mostra quem vende "
            "em cada mercado, não quem vendeu sempre."
        )
    else:
        notas.append(
            "Só entidades com contratos no segmento filtrado: a lista mostra quem compra "
            "em cada mercado, não quem comprou sempre."
        )
    if "fr" in escolhidos:
        notas.append(
            "Em França o DECP não traz nomes de entidades: identifica-se cada uma pelo SIRET."
        )

    return {
        "country": "all" if len(escolhidos) > 1 else escolhidos[0],
        "role": role,
        "countries": resumo,
        "items": itens,
        "notes": notas,
    }


def benchmark_entity(
    *,
    nif: Optional[str] = None,
    name: Optional[str] = None,
    role: str = "adjudicatario",
    country: str = "pt",
    cpv_code: Optional[str] = None,
    year_from: Optional[int] = None,
    year_to: Optional[int] = None,
    region: Optional[str] = None,
    top: int = 12,
    es: Any = None,
) -> Dict[str, Any]:
    """Benchmark de preços, concorrência e oportunidades de uma entidade + CPV.

    `country` escolhe o índice e o dialeto dos campos (`pt`, `es`, `fr`).
    """
    role = role if role in ROLES else "adjudicatario"
    if not (nif or (name or "").strip()):
        return {"error": "Indique a entidade (NIF ou nome)."}

    client = es or get_es_client(request_timeout=_REQUEST_TIMEOUT)
    if not client:
        return {"error": "Elasticsearch indisponível"}

    country = bc.country_key(country)
    dialeto = bc.dialect(country)
    counterpart_role = _counterpart_role(role)
    entity_filter = bc.entity_filter(country, role, nif=nif, name=name)
    filters = _segment_filters(country, cpv_code, year_from, year_to, region)
    query: Dict[str, Any] = {"bool": {"filter": filters}} if filters else {"match_all": {}}

    top = max(1, min(int(top or 12), 50))
    candidates = max(_CANDIDATES, top)

    valor_campo = dialeto["valor_campo"]
    # Só valores utilizáveis: positivos e abaixo do teto de sanidade do país.
    positivo = {"bool": {"filter": bc.value_filters(country)}}
    recente = dialeto["recent"]

    body: Dict[str, Any] = {
        "size": 0,
        "track_total_hits": True,
        "query": query,
        "aggs": {
            # --- preço de referência do mercado (só valores utilizáveis) ---
            "market_value": {"stats": {"field": valor_campo}},
            "market_priced": {
                "filter": positivo,
                "aggs": {
                    "stats": {"stats": {"field": valor_campo}},
                    "percentiles": {"percentiles": {"field": valor_campo, "percents": _PERCENTS}},
                },
            },
            # --- dimensão do mercado ---
            "market_peers": bc.cardinality_agg(country, role),
            "market_counterparts": bc.cardinality_agg(country, counterpart_role),
            # --- concorrência: pares (mesmo papel) por valor contratado ---
            "peers": bc.rank_agg(country, role, candidates),
            # --- mercado: contrapartes mais fortes do segmento ---
            "counterparts": bc.rank_agg(country, counterpart_role, max(top * 2, 40)),
            # --- a empresa no segmento ---
            "entity": {
                "filter": entity_filter,
                "aggs": {
                    "name": {"top_hits": {"size": 1, "_source": True}},
                    "stats": {"stats": {"field": valor_campo}},
                    "priced": {
                        "filter": positivo,
                        "aggs": {
                            "percentiles": {"percentiles": {"field": valor_campo, "percents": [25, 50, 75]}}
                        },
                    },
                    "last": {"max": {"field": dialeto["data"]}},
                    "by_year": {
                        "terms": {"field": dialeto["ano"], "size": 40, "order": {"_key": "desc"}},
                        "aggs": {"value": bc.value_sum(country)},
                    },
                    "cpv": bc.cpv_agg(country, 12),
                    # Historial: contrapartes com quem a empresa já contratou neste segmento.
                    "counterparts": bc.rank_agg(country, counterpart_role, max(top * 2, 40)),
                    "recent": {
                        "top_hits": {
                            "size": 8,
                            "sort": [{recente["data"]: {"order": "desc", "missing": "_last"}}],
                            "_source": [
                                recente["id"],
                                recente["objeto"],
                                recente["valor"],
                                recente["data"],
                                recente["data2"],
                                recente["proc"],
                                bc.party(country, role)["nested"].split(".")[0] if bc.is_nested(country, role) else bc.party(country, role)["nome"],
                                bc.party(country, counterpart_role)["nested"].split(".")[0] if bc.is_nested(country, counterpart_role) else bc.party(country, counterpart_role)["nome"],
                            ],
                        }
                    },
                },
            },
            # --- oportunidades: contrapartes do segmento que a empresa nunca serviu ---
            "opportunities": {
                "filter": {"bool": {"must_not": [entity_filter]}},
                "aggs": {"rank": bc.rank_agg(country, counterpart_role, max(top * 2, 40))},
            },
        },
    }

    try:
        resp = client.search(index=dialeto["index"], body=body)
    except Exception as exc:  # pragma: no cover - erro de cluster
        logger.warning("Benchmark falhou (%s): %s", country, exc)
        return {"error": str(exc)}

    aggs = resp.get("aggregations") or {}
    market_priced = aggs.get("market_priced") or {}
    market_stats = _stats(market_priced.get("stats"))
    market_pct = _percentiles(market_priced.get("percentiles"))
    market_total_value = market_stats.get("sum") or 0.0

    entity_agg = aggs.get("entity") or {}
    entity_stats = _stats(entity_agg.get("stats"))
    entity_priced_pct = _percentiles((entity_agg.get("priced") or {}).get("percentiles"))
    entity_name = _entity_hit_name(entity_agg.get("name"), country, role) or (name or "")
    entity_total_value = entity_stats.get("sum") or 0.0

    peers = _rows(aggs.get("peers"), candidates, market_total_value, country, role)
    entity_nif = (nif or "").strip()
    entity_rank: Optional[int] = None
    if entity_nif:
        for row in peers:
            if row["nif"] == entity_nif:
                entity_rank = row.get("rank")
                break
    peer_rows = peers[:top]

    counterparts = _rows(aggs.get("counterparts"), top, market_total_value, country, counterpart_role)
    history = _rows(entity_agg.get("counterparts"), top, entity_total_value, country, counterpart_role)
    known_nifs = {row["nif"] for row in history}

    vende = role == bc.SUPPLIER
    roles_label = f"vende ({bc.ROLE_LABELS[country][bc.SUPPLIER]})" if vende else f"compra ({bc.ROLE_LABELS[country][bc.BUYER]})"
    why_opportunity = (
        "Compra este CPV e nunca contratou com a empresa"
        if vende
        else "Vende este CPV e nunca contratou com a empresa"
    )
    opportunities = [
        {**row, "why": why_opportunity}
        for row in _rows(
            (aggs.get("opportunities") or {}).get("rank"),
            max(top * 2, 40),
            market_total_value,
            country,
            counterpart_role,
        )
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

    cpv_rows = bc.cpv_rows(country, entity_agg.get("cpv"))

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
                "idcontrato": source.get(recente["id"]),
                "objecto": source.get(recente["objeto"]),
                "value": source.get(recente["valor"]),
                "date": source.get(recente["data"]) or source.get(recente["data2"]),
                "procedure": source.get(recente["proc"]),
                "counterpart": bc.nome_da_entidade(source, country, counterpart_role),
            }
        )

    notes: List[str] = []
    notes.append(f"País: {dialeto['label']} (índice `{dialeto['index']}`).")
    if cpv_code:
        notes.append(f"Segmento: contratos com CPV {cpv_code}.")
    else:
        notes.append("Sem CPV selecionado: o preço de referência refere-se ao total do mercado filtrado.")
    notes.append("Percentis aproximados (TDigest do Elasticsearch) sobre valores positivos.")
    notes.append("Os rankings são por valor contratual; as listas mostram as maiores posições do segmento.")
    if country == "fr":
        notes.append(
            "Em França os compradores são identificados pelo SIRET (o campo do nome está vazio nos dados) "
            "e os titulares pelo par `titulaires.id`/`titulaires.nom`."
        )
    if entity_nif and entity_rank is None:
        notes.append(
            f"A empresa não está entre as {candidates} entidades de maior valor no segmento "
            "(a posição não é apresentada)."
        )
    if entity_nif and not (entity_stats.get("count") or 0):
        notes.append(f"Sem contratos no segmento com o papel {roles_label}.")

    return {
        "role": role,
        "country": country,
        "country_label": dialeto["label"],
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
            "peers": bc.cardinality_value(aggs.get("market_peers")),
            "counterparts": bc.cardinality_value(aggs.get("market_counterparts")),
        },
        "competitors": peer_rows,
        "counterparties": counterparts,
        "history": history,
        "opportunities": opportunities,
        "notes": notes,
    }


# ---------------------------------------- anomalias de preço e concentração

#: Quantos CPV da empresa entram na leitura de concentração/preço.
_ANOMALY_CPVS = 6
#: Contratos acima do p90 mostrados (os maiores).
_ANOMALY_CONTRACTS = 6
#: A partir de que rácio (empresa ÷ mediana do CPV) se diz «acima do mercado».
_PRICE_ABOVE = 1.25
#: Abaixo deste rácio diz-se «abaixo do mercado».
_PRICE_BELOW = 0.8
#: A partir de que quota de valor num CPV o mercado é «dominado».
_DOMINANT_SHARE = 60.0
#: Com este número de fornecedores (ou menos) o CPV é de «pouca concorrência».
_THIN_MARKET = 3
#: Contratos mínimos da entidade num CPV para se comparar o preço (abaixo disto é ruído).
_MIN_CPV_CONTRACTS = 5


def _percentil(agg: Optional[Dict[str, Any]], chave: str) -> Optional[float]:
    valores = (((agg or {}).get("pc") or {}).get("values")) or {}
    valor = valores.get(chave)
    return round(float(valor), 2) if valor is not None else None


def money_pt(valor: Any) -> str:
    """Valor em euros no formato português (para os textos de explicação)."""
    if not isinstance(valor, (int, float)):
        return "—"
    return f"{valor:,.2f} €".replace(",", " ").replace(".", ",")


def benchmark_anomalies(
    *,
    nif: Optional[str] = None,
    name: Optional[str] = None,
    role: str = "adjudicatario",
    country: str = "pt",
    cpv_code: Optional[str] = None,
    year_from: Optional[int] = None,
    year_to: Optional[int] = None,
    region: Optional[str] = None,
    top_cpvs: int = _ANOMALY_CPVS,
    es: Any = None,
) -> Dict[str, Any]:
    """Anomalias de preço e de concentração de uma entidade no seu segmento.

    Responde a três perguntas de quem compra ou vende:

    1. **Preço fora do normal** — os contratos da entidade acima do p90 do
       segmento (quantas vezes o p90 valem) e se, nos CPV onde atua, a mediana
       dela está acima ou abaixo da mediana do mercado.
    2. **Concentração** — quantos fornecedores distintos existem em cada CPV e
       que fatia do valor a entidade tem ali (um só fornecedor ou um mercado
       dominado por ela é o oposto de concorrência).
    3. **Qualidade do dado** — contratos com valores fora dos limites de
       sanidade (negativos, nulos ou acima do teto) que ficam de fora das
       estatísticas, para a leitura não ser feita sobre números contaminados.

    Cada achado sai em `items` com uma explicação legível (`title`/`detail`),
    severidade e os números que o sustentam.
    """
    role = role if role in ROLES else bc.SUPPLIER
    if not (nif or (name or "").strip()):
        return {"error": "Indique a entidade (NIF ou nome)."}
    client = es or get_es_client(request_timeout=_REQUEST_TIMEOUT)
    if not client:
        return {"error": "Elasticsearch indisponível"}

    country = bc.country_key(country)
    dialeto = bc.dialect(country)
    valor_campo = dialeto["valor_campo"]
    spec_cpv = dialeto["cpv"]
    entidade_filtro = bc.entity_filter(country, role, nif=nif, name=name)
    filtros = _segment_filters(country, cpv_code, year_from, year_to, region)
    dentro: Dict[str, Any] = {"bool": {"filter": filtros}} if filtros else {"match_all": {}}
    limpos = {"bool": {"filter": bc.value_filters(country)}}
    sujos = {"bool": {"must_not": {"bool": {"filter": bc.value_filters(country)}}}}
    top_cpvs = max(1, min(int(top_cpvs or _ANOMALY_CPVS), 20))

    # A análise sai em duas pesquisas de propósito: a primeira é pequena (só os
    # contratos da entidade) e diz onde ela atua; a segunda olha para o mercado
    # **apenas nesses CPV** — uma agregação por CPV sobre o índice inteiro
    # esgotava o circuit breaker do cluster.
    recente = dialeto["recent"]
    # Campos que o `top_hits` dos contratos caros traz (só o necessário: o
    # `_source` completo desta agregação era o que pesava mais na pesquisa).
    contraparte = bc.party(country, _counterpart_role(role))
    campos_caros: List[str] = [
        valor_campo,
        recente["id"],
        recente["objeto"],
        recente["data"],
        recente["data2"],
        recente["valor"],
    ]
    if contraparte.get("nome"):
        campos_caros.append(str(contraparte["nome"]))
    if contraparte.get("nested"):
        raiz = str(contraparte["nested"]).split(".")[0]
        if raiz not in campos_caros:
            campos_caros.append(raiz)
    corpo_entidade: Dict[str, Any] = {
        "size": 0,
        "track_total_hits": True,
        "query": {"bool": {"filter": [entidade_filtro, *filtros]}},
        "aggs": {
            "limpos": {
                "filter": limpos,
                "aggs": {
                    "stats": {"stats": {"field": valor_campo}},
                    "pc": {"percentiles": {"field": valor_campo, "percents": [50, 90]}},
                    "caros": {
                        "top_hits": {
                            "size": _ANOMALY_CONTRACTS,
                            "sort": [{valor_campo: {"order": "desc"}}],
                            "_source": {"includes": campos_caros},
                        }
                    },
                },
            },
            "suspeitos": {"filter": sujos},
            "cpvs": {
                "nested": {"path": spec_cpv["nested"]},
                "aggs": {
                    "top": {
                        "terms": {"field": spec_cpv["code"], "size": top_cpvs, "order": {"_count": "desc"}},
                        "aggs": {
                            "descricao": {"top_hits": {"size": 1, "_source": True}},
                            "limpos": {
                                "reverse_nested": {},
                                "aggs": {
                                    "filter_limpos": {"filter": limpos, "aggs": {"pc": {"percentiles": {"field": valor_campo, "percents": [50]}}}}
                                },
                            },
                        },
                    }
                },
            },
        },
    }

    try:
        resp = client.search(index=dialeto["index"], body=corpo_entidade)
    except Exception as exc:  # pragma: no cover - depende do cluster
        logger.warning("Anomalias do benchmark falharam (%s): %s", country, exc)
        return {"error": str(exc)}

    aggs = resp.get("aggregations") or {}
    entidade_aggs = aggs.get("entidade") or aggs
    entidade_limpos = entidade_aggs.get("limpos") or {}
    entidade_stats = entidade_limpos.get("stats") or {}
    contratos_entidade = int(entidade_stats.get("count") or 0)
    valor_entidade = round(float(entidade_stats.get("sum") or 0.0), 2)
    mediana_entidade = _percentil(entidade_limpos, "50.0")
    p90_entidade = _percentil(entidade_limpos, "90.0")
    suspeitos = int((((entidade_aggs.get("suspeitos") or {}).get("doc_count")) or 0))
    nome = _entity_hit_name(entidade_aggs, country, role) or (name or nif or "")

    buckets_cpv = (((aggs.get("cpvs") or {}).get("top") or {}).get("buckets")) or []

    # --- mercado só nos CPV da entidade ------------------------------------
    filtros_cpv: Dict[str, Dict[str, Any]] = {}
    codigos: Dict[str, str] = {}
    for indice, bucket in enumerate(buckets_cpv):
        codigo = str(bucket.get("key") or "")
        filtro = bc.cpv_filter(country, codigo)
        if not codigo or not filtro:
            continue
        filtros_cpv[f"cpv{indice}"] = filtro
        codigos[f"cpv{indice}"] = codigo

    mediana_mercado = p90_mercado = None
    mercado_cpvs: Dict[str, Dict[str, Any]] = {}
    mercado_stats: Dict[str, Any] = {}
    if filtros_cpv:
        corpo_mercado: Dict[str, Any] = {
            "size": 0,
            "track_total_hits": False,
            "query": dentro,
            "aggs": {
                "mercado": {
                    "filter": limpos,
                    "aggs": {
                        "stats": {"stats": {"field": valor_campo}},
                        "pc": {"percentiles": {"field": valor_campo, "percents": [50, 90]}},
                    },
                },
                "por_cpv": {
                    "filters": {"filters": filtros_cpv},
                    "aggs": {
                        "pc": {"percentiles": {"field": valor_campo, "percents": [50]}},
                        "fornecedores": bc.cardinality_agg(country, role),
                    },
                },
            },
        }
        try:
            resp_mercado = client.search(index=dialeto["index"], body=corpo_mercado)
        except Exception as exc:  # pragma: no cover - depende do cluster
            logger.warning("Mercado por CPV falhou (%s): %s", country, exc)
            resp_mercado = {}
        aggs_mercado = resp_mercado.get("aggregations") or {}
        mercado = aggs_mercado.get("mercado") or {}
        mercado_stats = mercado.get("stats") or {}
        mediana_mercado = _percentil(mercado, "50.0")
        p90_mercado = _percentil(mercado, "90.0")
        for chave, bucket in ((aggs_mercado.get("por_cpv") or {}).get("buckets") or {}).items():
            codigo = codigos.get(chave)
            if codigo:
                mercado_cpvs[codigo] = bucket or {}

    # --- 1. contratos acima do p90 -----------------------------------------
    caros: List[Dict[str, Any]] = []
    for hit in (((entidade_limpos.get("caros") or {}).get("hits") or {}).get("hits")) or []:
        fonte = hit.get("_source") or {}
        valor = fonte.get(valor_campo)
        if not isinstance(valor, (int, float)):
            continue
        if p90_mercado and valor <= p90_mercado:
            continue
        caros.append(
            {
                "value": round(float(valor), 2),
                "times_p90": round(float(valor) / p90_mercado, 2) if p90_mercado else None,
                "object": str(fonte.get(recente["objeto"]) or "")[:200] or None,
                "date": str(fonte.get(recente["data"]) or fonte.get(recente["data2"]) or "")[:10] or None,
                "counterpart": bc.nome_da_entidade(fonte, country, _counterpart_role(role)) or None,
                "id": fonte.get(recente["id"]),
            }
        )

    # --- 2. concentração e preço por CPV -----------------------------------
    por_cpv: List[Dict[str, Any]] = []
    for bucket in buckets_cpv:
        codigo = str(bucket.get("key") or "")
        contratos_cpv = int(bucket.get("doc_count") or 0)
        mediana_empresa_cpv = _percentil((bucket.get("limpos") or {}).get("filter_limpos"), "50.0")
        mercado_cpv = mercado_cpvs.get(codigo) or {}
        fornecedores = bc.cardinality_value(mercado_cpv.get("fornecedores"))
        mediana_cpv = _percentil(mercado_cpv, "50.0")
        contratos_mercado_cpv = int(mercado_cpv.get("doc_count") or 0)
        quota = round(100.0 * contratos_cpv / contratos_mercado_cpv, 2) if contratos_mercado_cpv else None
        ratio = (
            round(mediana_empresa_cpv / mediana_cpv, 2)
            if mediana_empresa_cpv and mediana_cpv and contratos_cpv >= _MIN_CPV_CONTRACTS
            else None
        )
        if fornecedores <= 1:
            veredito_concorrencia = "um só fornecedor no período"
        elif quota is not None and quota >= _DOMINANT_SHARE:
            veredito_concorrencia = "mercado dominado pela empresa"
        elif fornecedores <= _THIN_MARKET:
            veredito_concorrencia = "pouca concorrência"
        else:
            veredito_concorrencia = "concorrencial"
        if ratio is None:
            veredito_preco = (
                "amostra pequena para comparar"
                if contratos_cpv and contratos_cpv < _MIN_CPV_CONTRACTS
                else "sem valores comparáveis"
            )
        elif ratio >= _PRICE_ABOVE:
            veredito_preco = "acima da mediana do CPV"
        elif ratio <= _PRICE_BELOW:
            veredito_preco = "abaixo da mediana do CPV"
        else:
            veredito_preco = "na linha da mediana do CPV"
        por_cpv.append(
            {
                "code": codigo,
                "description": bc.cpv_description(country, bucket.get("descricao"), codigo) or "",
                "contracts": contratos_cpv,
                "market_contracts": contratos_mercado_cpv,
                "market_median": mediana_cpv,
                "entity_median": mediana_empresa_cpv,
                "ratio": ratio,
                "suppliers": fornecedores,
                "share_pct": quota,
                "competition_verdict": veredito_concorrencia,
                "price_verdict": veredito_preco,
            }
        )

    # --- 3. achados legíveis -------------------------------------------------
    itens: List[Dict[str, Any]] = []
    if caros:
        maior = caros[0]
        itens.append(
            {
                "kind": "preco_fora_do_normal",
                "severity": "alta" if (maior.get("times_p90") or 0) >= 3 else "media",
                "title": f"{len(caros)} contrato(s) acima do p90 do segmento",
                "detail": (
                    f"O maior vale {money_pt(maior['value'])}"
                    + (f" ({maior['times_p90']:.1f}× o p90 de {money_pt(p90_mercado)})" if p90_mercado else "")
                    + f". O p90 do segmento é {money_pt(p90_mercado)}."
                ),
                "value": maior.get("times_p90"),
            }
        )
    if mediana_entidade and mediana_mercado:
        indice = round(mediana_entidade / mediana_mercado, 2)
        if indice >= _PRICE_ABOVE:
            itens.append(
                {
                    "kind": "preco_acima",
                    "severity": "media",
                    "title": "Preço mediano acima do mercado",
                    "detail": (
                        f"A mediana da empresa ({money_pt(mediana_entidade)}) é {indice:.2f}× a mediana do "
                        f"segmento ({money_pt(mediana_mercado)})."
                    ),
                    "value": indice,
                }
            )
        elif indice <= _PRICE_BELOW:
            itens.append(
                {
                    "kind": "preco_abaixo",
                    "severity": "info",
                    "title": "Preço mediano abaixo do mercado",
                    "detail": (
                        f"A mediana da empresa ({money_pt(mediana_entidade)}) é {indice:.2f}× a mediana do "
                        f"segmento ({money_pt(mediana_mercado)}) — margem potencial ou posição agressiva."
                    ),
                    "value": indice,
                }
            )
    acima = [linha for linha in por_cpv if linha["price_verdict"] == "acima da mediana do CPV"]
    if len(acima) >= 2:
        exemplos = ", ".join(f"{linha['code']} ({linha['ratio']:.2f}×)" for linha in acima[:3])
        itens.append(
            {
                "kind": "preco_sistematico",
                "severity": "media",
                "title": f"Preço acima do mercado em {len(acima)} dos {len(por_cpv)} CPV principais",
                "detail": f"Exemplos: {exemplos}.",
                "value": float(len(acima)),
            }
        )
    monopolios = [linha for linha in por_cpv if linha["competition_verdict"] == "um só fornecedor no período"]
    if monopolios:
        itens.append(
            {
                "kind": "fornecedor_unico",
                "severity": "media",
                "title": f"{len(monopolios)} CPV com um só fornecedor no período",
                "detail": (
                    "Sem alternativa visível nos dados: "
                    + ", ".join(f"{linha['code']} ({linha['contracts']} contratos)" for linha in monopolios[:3])
                    + ". Vale confirmar procedimento e concorrência real."
                ),
                "value": float(len(monopolios)),
            }
        )
    dominados = [linha for linha in por_cpv if linha["competition_verdict"] == "mercado dominado pela empresa"]
    if dominados:
        itens.append(
            {
                "kind": "mercado_dominado",
                "severity": "media",
                "title": f"Empresa domina {len(dominados)} CPV do seu perfil",
                "detail": (
                    "Quota de contratos acima de "
                    f"{_DOMINANT_SHARE:.0f}%: "
                    + ", ".join(f"{linha['code']} ({linha['share_pct']:.0f}%)" for linha in dominados[:3])
                    + "."
                ),
                "value": float(len(dominados)),
            }
        )
    if contratos_entidade and len(por_cpv) > 1:
        total_cpv = sum(linha["contracts"] for linha in por_cpv)
        maiores = sorted(por_cpv, key=lambda linha: linha["contracts"], reverse=True)[:3]
        contratos_top = sum(linha["contracts"] for linha in maiores)
        if total_cpv and contratos_top / total_cpv >= 0.8:
            itens.append(
                {
                    "kind": "concentracao_carteria",
                    "severity": "info",
                    "title": "Carteira concentrada em poucos CPV",
                    "detail": (
                        f"{round(100.0 * contratos_top / total_cpv)}% dos contratos com CPV da empresa estão em "
                        + ", ".join(linha["code"] for linha in maiores)
                        + " — dependência alta de poucos segmentos."
                    ),
                    "value": round(100.0 * contratos_top / total_cpv, 1),
                }
            )
    if suspeitos:
        itens.append(
            {
                "kind": "dados_suspeitos",
                "severity": "info",
                "title": f"{suspeitos} contrato(s) com valores fora dos limites",
                "detail": (
                    "Valores nulos, negativos (notas de crédito) ou acima do teto de sanidade do país: "
                    "ficaram de fora das estatísticas de preço."
                ),
                "value": float(suspeitos),
            }
        )

    severidade = {"alta": 0, "media": 1, "info": 2}
    itens.sort(key=lambda item: severidade.get(str(item.get("severity")), 3))

    return {
        "role": role,
        "country": country,
        "country_label": dialeto["label"],
        "entity": {
            "nif": nif,
            "name": nome,
            "contracts": contratos_entidade,
            "total_value": valor_entidade,
            "median": mediana_entidade,
            "p90": _percentil(entidade_limpos, "90.0"),
            "share_of_segment_pct": (
                round(100.0 * contratos_entidade / int(mercado_stats.get("count") or 1), 2)
                if mercado_stats.get("count")
                else None
            ),
        },
        "reference": {
            "contracts": int(mercado_stats.get("count") or 0),
            "median": mediana_mercado,
            "p90": p90_mercado,
        },
        "items": itens,
        "outliers": caros,
        "by_cpv": por_cpv,
        "data_quality": {"excluded_contracts": suspeitos, "excluded_value": None},
        "notes": [
            "Percentis aproximados (TDigest do Elasticsearch), sobre valores positivos e abaixo do teto do país.",
            "«Fornecedores» é o número de entidades distintas que venderam nesse CPV no período filtrado — "
            "não é o número de propostas de cada concurso (os dados não trazem os concorrentes perdedores).",
            "A comparação de preço por CPV usa as medianas das duas séries (empresa e mercado) no mesmo CPV e período; "
            f"abaixo de {_MIN_CPV_CONTRACTS} contratos da empresa no CPV não se conclui nada sobre o preço.",
        ],
    }


# --------------------------------------------- oportunidades por comprador

#: Compradores da empresa usados como base da recomendação.
_GAPS_BUYERS = 25
#: CPV propostos por análise.
_GAPS_SIZE = 12
#: CPV distintos do perfil da empresa (para saber o que se exclui).
_GAPS_ENTITY_CPVS = 200


def benchmark_gaps(
    *,
    nif: Optional[str] = None,
    name: Optional[str] = None,
    role: str = "adjudicatario",
    country: str = "pt",
    year_from: Optional[int] = None,
    year_to: Optional[int] = None,
    region: Optional[str] = None,
    top_buyers: int = _GAPS_BUYERS,
    size: int = _GAPS_SIZE,
    es: Any = None,
) -> Dict[str, Any]:
    """Onde a empresa pode vender mais: CPV dos seus compradores que ela não serve.

    O raciocínio é o de quem vende: **quem já me compra compra também outras
    coisas**. Aqui cruza-se a carteira de compradores da empresa com o que esses
    compradores contratam no mesmo período e país, e retiram-se os CPV onde a
    empresa **não** tem contratos — ordenados por valor, com os compradores
    concretos, a mediana praticada e quem já vende ali.

    Só faz sentido para o papel `adjudicatario` (vende); no papel `adjudicante`
    o resultado são os CPV dos fornecedores dela que ela ainda não compra.
    """
    role = role if role in ROLES else bc.SUPPLIER
    if not (nif or (name or "").strip()):
        return {"error": "Indique a entidade (NIF ou nome)."}
    client = es or get_es_client(request_timeout=_REQUEST_TIMEOUT)
    if not client:
        return {"error": "Elasticsearch indisponível"}

    country = bc.country_key(country)
    dialeto = bc.dialect(country)
    valor_campo = dialeto["valor_campo"]
    spec_cpv = dialeto["cpv"]
    counterpart_role = _counterpart_role(role)
    entidade_filtro = bc.entity_filter(country, role, nif=nif, name=name)
    top_buyers = max(2, min(int(top_buyers or _GAPS_BUYERS), 60))
    size = max(1, min(int(size or _GAPS_SIZE), 40))
    # O filtro de CPV não entra: o objetivo é justamente encontrar outros CPV.
    filtros = [
        filtro
        for filtro in (
            bc.year_filter(country, year_from, year_to),
            bc.region_filter(country, region),
        )
        if filtro
    ]
    dentro: Dict[str, Any] = {"bool": {"filter": filtros}} if filtros else {"match_all": {}}

    # 1. quem compra à empresa e em que CPV ela vende.
    corpo_a: Dict[str, Any] = {
        "size": 0,
        "track_total_hits": True,
        "query": {"bool": {"filter": [entidade_filtro, *filtros]}},
        "aggs": {
            "compradores": bc.rank_agg(country, counterpart_role, top_buyers),
            "cpvs_empresa": {
                "nested": {"path": spec_cpv["nested"]},
                "aggs": {
                    "codigos": {
                        "terms": {"field": spec_cpv["code"], "size": _GAPS_ENTITY_CPVS},
                    }
                },
            },
        },
    }
    try:
        resp_a = client.search(index=dialeto["index"], body=corpo_a)
    except Exception as exc:  # pragma: no cover - depende do cluster
        logger.warning("Recomendações do benchmark falharam (%s): %s", country, exc)
        return {"error": str(exc)}

    aggs_a = resp_a.get("aggregations") or {}
    compradores = bc.rank_rows(country, counterpart_role, aggs_a.get("compradores"), top_buyers, None)
    codigos_empresa = {
        _codigo_cpv_base(str(bucket.get("key") or ""))
        for bucket in (((aggs_a.get("cpvs_empresa") or {}).get("codigos") or {}).get("buckets")) or []
    }
    ids = [str(linha["nif"]) for linha in compradores if linha.get("nif")]
    if not ids:
        return {
            "role": role,
            "country": country,
            "country_label": dialeto["label"],
            "buyers": [],
            "gaps": [],
            "notes": ["Sem contrapartes identificadas para esta entidade no período — nada a recomendar."],
        }

    # 2. o que esses compradores contratam (e em que CPV a empresa não vende).
    corpo_b: Dict[str, Any] = {
        "size": 0,
        "track_total_hits": True,
        "query": {
            "bool": {"filter": [bc.party_in_filter(country, counterpart_role, ids), *filtros]}
        },
        "aggs": {
            "cpvs": {
                "nested": {"path": spec_cpv["nested"]},
                "aggs": {
                    "top": {
                        "terms": {
                            "field": spec_cpv["code"],
                            "size": max(size * 4, 40),
                            "order": {"mercado>soma": "desc"},
                        },
                        "aggs": {
                            "descricao": {"top_hits": {"size": 1, "_source": True}},
                            "mercado": {
                                "reverse_nested": {},
                                "aggs": {
                                    "soma": bc.value_sum(country),
                                    "pc": {"percentiles": {"field": valor_campo, "percents": [50]}},
                                    "compradores": bc.rank_agg(country, counterpart_role, 4),
                                    "fornecedores": bc.rank_agg(country, role, 3),
                                },
                            },
                        },
                    }
                },
            }
        },
    }
    try:
        resp_b = client.search(index=dialeto["index"], body=corpo_b)
    except Exception as exc:  # pragma: no cover - depende do cluster
        logger.warning("Recomendações (compradores) falharam (%s): %s", country, exc)
        return {"error": str(exc)}

    aggs_b = resp_b.get("aggregations") or {}
    lacunas: List[Dict[str, Any]] = []
    for bucket in (((aggs_b.get("cpvs") or {}).get("top") or {}).get("buckets")) or []:
        codigo = str(bucket.get("key") or "")
        base = _codigo_cpv_base(codigo)
        if not base or base in codigos_empresa:
            continue
        mercado = bucket.get("mercado") or {}
        valor = (((mercado.get("soma") or {}).get("value")) or 0.0)
        contratos = int(bucket.get("doc_count") or 0)
        compradores_cpv = bc.rank_rows(country, counterpart_role, mercado.get("compradores"), 4, valor)
        fornecedores_cpv = bc.rank_rows(country, role, mercado.get("fornecedores"), 3, valor)
        lacunas.append(
            {
                "code": codigo,
                "description": bc.cpv_description(country, bucket.get("descricao"), codigo) or "",
                "contracts": contratos,
                "value": round(float(valor), 2),
                "median": _percentil(mercado, "50.0"),
                "buyers": compradores_cpv,
                "buyers_total": len(compradores_cpv),
                "competition": fornecedores_cpv,
            }
        )
    lacunas.sort(key=lambda linha: (linha["value"], linha["contracts"]), reverse=True)
    lacunas = lacunas[:size]

    nome = (name or nif or "").strip()
    notas = [
        "Base: os {0} maiores compradores desta entidade no período filtrado ({1} identificados).".format(
            top_buyers, len(compradores)
        ),
        "Só aparecem CPV onde a entidade **não** tem contratos no período — se já vende ali, não é oportunidade.",
        "O valor é o que esses compradores contrataram nesse CPV (todos os fornecedores), não o que está disponível para ganhar.",
        "`buyers_total` conta quantos dos compradores da entidade compram nesse CPV (a lista mostra os maiores).",
    ]
    if country == "fr":
        notas.append("Em França o DECP não traz nomes: as entidades são identificadas pelo SIRET.")

    return {
        "role": role,
        "country": country,
        "country_label": dialeto["label"],
        "entity": {"nif": nif, "name": nome, "cpvs_known": len(codigos_empresa)},
        "buyers": compradores,
        "gaps": lacunas,
        "notes": notas,
    }


def _price_position(index: Optional[float]) -> Optional[str]:
    """Leitura do índice de preço: abaixo / na linha / acima do mercado."""
    if index is None:
        return None
    if index < 1 - _PRICE_TOLERANCE:
        return "abaixo"
    if index > 1 + _PRICE_TOLERANCE:
        return "acima"
    return "na linha"


def benchmark_compare(
    *,
    entities: List[Dict[str, Any]],
    role: str = "adjudicatario",
    country: str = "pt",
    cpv_code: Optional[str] = None,
    year_from: Optional[int] = None,
    year_to: Optional[int] = None,
    region: Optional[str] = None,
    top: int = 10,
    es: Any = None,
) -> Dict[str, Any]:
    """Compara até `MAX_COMPARE` entidades no mesmo segmento (papel + CPV + anos).

    Uma só pesquisa: o preço de referência do mercado é calculado uma vez e cada
    entidade é um `filter` com nome próprio (`e0`…`e9`) dentro de uma agregação
    `filters`, o que dá a cada uma os seus indicadores sem repetir o mercado.
    `country` escolhe o índice e o dialeto dos campos.
    """
    role = role if role in ROLES else "adjudicatario"
    country = bc.country_key(country)
    dialeto = bc.dialect(country)
    limpos: List[Dict[str, Any]] = []
    for item in entities or []:
        if not isinstance(item, dict):
            continue
        nif = str(item.get("nif") or "").strip()
        nome = str(item.get("name") or "").strip()
        if nif or nome:
            limpos.append({"nif": nif or None, "name": nome or None})
    if not limpos:
        return {"error": "Indique pelo menos uma entidade para comparar."}
    if len(limpos) > MAX_COMPARE:
        return {"error": f"Só é possível comparar até {MAX_COMPARE} empresas de cada vez."}

    client = es or get_es_client(request_timeout=_REQUEST_TIMEOUT)
    if not client:
        return {"error": "Elasticsearch indisponível"}

    counterpart_role = _counterpart_role(role)
    filters = _segment_filters(country, cpv_code, year_from, year_to, region)
    query: Dict[str, Any] = {"bool": {"filter": filters}} if filters else {"match_all": {}}

    top = max(1, min(int(top or 10), 50))
    valor_campo = dialeto["valor_campo"]
    positivo = {"bool": {"filter": bc.value_filters(country)}}

    chaves = [f"e{index}" for index in range(len(limpos))]
    named_filters = {
        chave: bc.entity_filter(country, role, nif=entidade.get("nif"), name=entidade.get("name"))
        for chave, entidade in zip(chaves, limpos)
    }

    body: Dict[str, Any] = {
        "size": 0,
        "track_total_hits": True,
        "query": query,
        "aggs": {
            "market_value": {"stats": {"field": valor_campo}},
            "market_priced": {
                "filter": positivo,
                "aggs": {
                    "stats": {"stats": {"field": valor_campo}},
                    "percentiles": {"percentiles": {"field": valor_campo, "percents": [25, 50, 75]}},
                },
            },
            "market_peers": bc.cardinality_agg(country, role),
            # Ranking do segmento: dá a posição de cada empresa comparada.
            "peers": bc.rank_agg(country, role, _CANDIDATES),
            # Uma «coluna» por entidade, com os indicadores do segmento.
            "entities": {
                "filters": {"filters": named_filters, "other_bucket": False},
                "aggs": {
                    "name": {"top_hits": {"size": 1, "_source": True}},
                    "stats": {"stats": {"field": valor_campo}},
                    "priced": {
                        "filter": positivo,
                        "aggs": {"percentiles": {"percentiles": {"field": valor_campo, "percents": [25, 50, 75]}}},
                    },
                    "last": {"max": {"field": dialeto["data"]}},
                    # CPV em que cada empresa atua dentro do segmento.
                    "top_cpv": bc.cpv_agg(country, _CPV_SHOW),
                    # Quem compra a cada empresa (contrapartes do segmento).
                    "buyers": bc.rank_agg(country, counterpart_role, _BUYERS_CANDIDATES),
                    "buyers_total": bc.cardinality_agg(country, counterpart_role),
                },
            },
        },
    }

    try:
        resp = client.search(index=dialeto["index"], body=body)
    except Exception as exc:  # pragma: no cover - erro de cluster
        logger.warning("Comparação de benchmark falhou (%s): %s", country, exc)
        return {"error": str(exc)}

    aggs = resp.get("aggregations") or {}
    market_stats = _stats((aggs.get("market_priced") or {}).get("stats"))
    market_pct = _percentiles((aggs.get("market_priced") or {}).get("percentiles"))
    market_total_value = market_stats.get("sum") or 0.0
    market_median = market_pct.get("p50")

    # Perfil de CPV de cada empresa. Com um CPV escolhido, a pesquisa principal só
    # devolveria esse CPV (é o filtro do segmento), pelo que o perfil vem de uma
    # pesquisa própria **sem** o filtro de CPV — assim vê-se em que áreas cada
    # empresa atua e pode escolher-se o CPV a partir daí.
    perfil_cpv: Dict[str, List[Dict[str, Any]]] = {}
    if cpv_code:
        filtros_perfil = _segment_filters(country, None, year_from, year_to, region)
        try:
            resp_perfil = client.search(
                index=dialeto["index"],
                body={
                    "size": 0,
                    "query": ({"bool": {"filter": filtros_perfil}} if filtros_perfil else {"match_all": {}}),
                    "aggs": {
                        "entities": {
                            "filters": {"filters": named_filters, "other_bucket": False},
                            "aggs": {"top_cpv": bc.cpv_agg(country, _CPV_SHOW)},
                        }
                    },
                },
            )
            buckets_perfil = ((resp_perfil.get("aggregations") or {}).get("entities") or {}).get("buckets") or {}
            for chave, bucket_perfil in buckets_perfil.items():
                perfil_cpv[chave] = bc.cpv_rows(country, bucket_perfil.get("top_cpv"))
        except Exception as exc:  # pragma: no cover - perfil é complementar
            logger.warning("Perfil de CPV das empresas falhou: %s", exc)

    peers = _rows(aggs.get("peers"), _CANDIDATES, market_total_value, country, role)
    por_nif = {row["nif"]: row for row in peers}
    selecionados = {entidade["nif"] for entidade in limpos if entidade.get("nif")}
    # Nome por NIF, para o ranking poder marcar as empresas comparadas.
    nome_por_nif = {entidade["nif"]: entidade["name"] for entidade in limpos if entidade.get("nif")}

    buckets = ((aggs.get("entities") or {}).get("buckets")) or {}
    linhas: List[Dict[str, Any]] = []
    for index, (chave, entidade) in enumerate(zip(chaves, limpos)):
        bucket = buckets.get(chave) or {}
        stats = _stats(bucket.get("stats"))
        pct = _percentiles((bucket.get("priced") or {}).get("percentiles"))
        valor = stats.get("sum") or 0.0
        mediana = pct.get("p50")
        indice = round(mediana / market_median, 3) if mediana and market_median else None
        nif = entidade.get("nif") or ""
        nome = (
            _entity_hit_name(bucket.get("name"), country, role)
            or _entity_hit_name(bucket.get("name"), country, counterpart_role)
            or entidade.get("name")
            or nif
            or f"Empresa {index + 1}"
        )
        posicao = por_nif.get(nif) if nif else None

        # Com CPV escolhido usa-se o perfil (fora do filtro de CPV); sem CPV, os
        # CPV do próprio segmento já são o perfil da empresa.
        cpvs = perfil_cpv.get(chave) or bc.cpv_rows(country, bucket.get("top_cpv"))

        compradores = _rows(bucket.get("buyers"), _BUYERS_CANDIDATES, valor, country, counterpart_role)

        linhas.append(
            {
                "nif": nif or None,
                "name": nome,
                "contracts": stats.get("count") or 0,
                "total_value": round(float(valor), 2),
                "avg_value": stats.get("avg"),
                "median_value": mediana,
                "p25": pct.get("p25"),
                "p75": pct.get("p75"),
                "share_pct": round(100.0 * valor / market_total_value, 2) if market_total_value else None,
                "count_share_pct": (
                    round(100.0 * (stats.get("count") or 0) / (market_stats.get("count") or 1), 2)
                    if market_stats.get("count")
                    else None
                ),
                "rank": posicao.get("rank") if posicao else None,
                "price_index": indice,
                "price_position": _price_position(indice),
                "last_date": ((bucket.get("last") or {}).get("value_as_string")) or None,
                "present": bool(stats.get("count") or 0),
                "top_cpv": cpvs,
                "buyers": compradores[:_BUYERS_SHOW],
                "buyers_total": bc.cardinality_value(bucket.get("buyers_total")),
            }
        )

    linhas.sort(key=lambda linha: (linha.get("total_value") or 0.0), reverse=True)
    for posicao, linha in enumerate(linhas):
        linha["order"] = posicao + 1

    # Ranking do segmento: o top pedido, mais as empresas comparadas que fiquem
    # fora dele (senão a sua posição não aparecia em lado nenhum).
    ranking: List[Dict[str, Any]] = [
        {**row, "selected": row["nif"] in selecionados, "label": nome_por_nif.get(row["nif"])}
        for row in peers[:top]
    ]
    ja_listadas = {row["nif"] for row in ranking}
    extras = [
        {**por_nif[nif], "selected": True, "label": nome_por_nif.get(nif)}
        for nif in selecionados - ja_listadas
        if nif in por_nif
    ]
    if extras:
        ranking = sorted([*ranking, *extras], key=lambda row: row.get("rank") or 0)

    # Compradores em comum: contrapartes que aparecem em duas ou mais das
    # empresas comparadas (calculado sobre os maiores compradores de cada uma,
    # que é o que a agregação trouxe).
    comuns: Dict[str, Dict[str, Any]] = {}
    for linha in linhas:
        for comprador in linha["buyers"]:
            registo = comuns.setdefault(
                comprador["nif"],
                {"nif": comprador["nif"], "name": comprador["name"], "companies": [], "value": 0.0},
            )
            registo["companies"].append(linha["name"])
            registo["value"] = round(float(registo["value"]) + float(comprador.get("value") or 0.0), 2)
    compradores_comuns = [
        {**registo, "companies_total": len(registo["companies"])}
        for registo in comuns.values()
        if len(registo["companies"]) >= 2
    ]
    compradores_comuns.sort(key=lambda item: (item["companies_total"], item["value"]), reverse=True)

    # CPV em comum: classificações em que duas ou mais das empresas comparadas
    # atuam (mesma lógica dos compradores em comum) — é onde competem de facto.
    cpvs_comuns: Dict[str, Dict[str, Any]] = {}
    for linha in linhas:
        for cpv in linha["top_cpv"]:
            registo = cpvs_comuns.setdefault(
                cpv["code"],
                {
                    "code": cpv["code"],
                    "description": cpv.get("description") or "",
                    "companies": [],
                    "value": 0.0,
                    "count": 0,
                },
            )
            registo["companies"].append(linha["name"])
            registo["value"] = round(float(registo["value"]) + float(cpv.get("value") or 0.0), 2)
            registo["count"] += int(cpv.get("count") or 0)
    cpvs_em_comum = [
        {**registo, "companies_total": len(registo["companies"])}
        for registo in cpvs_comuns.values()
        if len(registo["companies"]) >= 2
    ]
    cpvs_em_comum.sort(key=lambda item: (item["companies_total"], item["value"]), reverse=True)

    notes: List[str] = []
    notes.append(f"País: {dialeto['label']} (índice `{dialeto['index']}`).")
    notes.append(f"Segmento: {('CPV ' + cpv_code) if cpv_code else 'todo o mercado filtrado'}.")
    notes.append("Percentis aproximados (TDigest do Elasticsearch) sobre valores positivos.")
    notes.append(
        "A posição é por valor contratual; sem CPV, o mercado tem milhões de contratos e a posição só "
        "aparece para quem está entre os maiores."
    )
    notes.append(
        f"Os «compradores em comum» são calculados sobre os {_BUYERS_CANDIDATES} maiores compradores de "
        "cada empresa (não sobre a lista completa)."
    )
    if country == "fr":
        notes.append(
            "Em França os compradores são identificados pelo SIRET (o campo do nome está vazio nos dados) "
            "e os titulares pelo par `titulaires.id`/`titulaires.nom`."
        )
    if cpv_code:
        notes.append(
            "Com um CPV escolhido, a lista «CPV principais» de cada empresa vem de fora do filtro de CPV "
            "(é o perfil da empresa no período), para se escolher o segmento a partir dela."
        )
    ausentes = [linha["name"] for linha in linhas if not linha["present"]]
    if ausentes:
        notes.append("Sem contratos no segmento: " + ", ".join(ausentes) + ".")

    return {
        "role": role,
        "country": country,
        "country_label": dialeto["label"],
        "counterpart_role": counterpart_role,
        "reference": {
            "scope": "mercado",
            "contracts": market_stats.get("count") or 0,
            "total_value": round(float(market_total_value), 2),
            "avg": market_stats.get("avg"),
            "median": market_median,
            "p25": market_pct.get("p25"),
            "p75": market_pct.get("p75"),
        },
        "market": {
            "contracts": ((resp.get("hits") or {}).get("total") or {}).get("value", 0),
            "peers": bc.cardinality_value(aggs.get("market_peers")),
        },
        "entities": linhas,
        "ranking": ranking,
        "shared_buyers": compradores_comuns,
        "shared_cpvs": cpvs_em_comum,
        "notes": notes,
    }


# ------------------------------------------------- cruzar países (empresa × CPV)

#: Máximo de empresas cruzadas de uma vez (a página mostra até este número).
MAX_CROSS = 6
#: Contrapartes por empresa consideradas no cruzamento.
_CROSS_HISTORY = 25
#: CPV por empresa considerados no cruzamento.
_CROSS_CPV = 12
#: Contratos recentes por empresa mostrados no cruzamento.
_CROSS_RECENT = 6


def _normalizar_cpvs(cpvs: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Junta os CPV de uma empresa na chave comum aos três países.

    Portugal grava o CPV com dígito de controlo (`33600000-6`) e Espanha/França
    sem ele (`33600000`); sem esta normalização o mesmo CPV não se cruzava entre
    países. Repetições dentro da mesma empresa somam-se.
    """
    juntos: Dict[str, Dict[str, Any]] = {}
    for cpv in cpvs or []:
        base = _codigo_cpv_base(str(cpv.get("code") or ""))
        if not base:
            continue
        registo = juntos.setdefault(
            base,
            {
                "code": base,
                "description": cpv.get("description") or "",
                "count": 0,
                "value": 0.0,
                "median": cpv.get("median"),
            },
        )
        if not registo["description"] and cpv.get("description"):
            registo["description"] = cpv["description"]
        registo["count"] += int(cpv.get("count") or 0)
        registo["value"] = round(float(registo["value"]) + float(cpv.get("value") or 0.0), 2)
    return list(juntos.values())


def _cruzar_itens(
    itens_por_empresa: List[tuple],
    chave: str,
    min_companies: int,
) -> List[Dict[str, Any]]:
    """Itens (CPV ou contrapartes) presentes em pelo menos `min_companies` empresas.

    Recebe pares `(empresa, itens)` e devolve, por identificador, as empresas que
    o têm — com o volume e o valor de cada uma. É o que sustenta a leitura «onde
    é que estas empresas se cruzam».
    """
    agregado: Dict[str, Dict[str, Any]] = {}
    for empresa, itens in itens_por_empresa:
        for item in itens or []:
            ident = str(item.get(chave) or "").strip()
            if not ident:
                continue
            registo = agregado.setdefault(
                ident,
                {
                    chave: ident,
                    "description": item.get("description"),
                    "name": item.get("name"),
                    "companies": [],
                    "contracts": 0,
                    "value": 0.0,
                },
            )
            if not registo.get("description") and item.get("description"):
                registo["description"] = item.get("description")
            if not registo.get("name") and item.get("name"):
                registo["name"] = item.get("name")
            registo["companies"].append(
                {
                    "nif": empresa.get("nif"),
                    "name": empresa.get("name"),
                    "short": empresa.get("short"),
                    "count": int(item.get("count") or 0),
                    "value": round(float(item.get("value") or 0.0), 2) if item.get("value") is not None else None,
                }
            )
            registo["contracts"] += int(item.get("count") or 0)
            registo["value"] = round(float(registo["value"]) + float(item.get("value") or 0.0), 2)

    comuns = [registo for registo in agregado.values() if len(registo["companies"]) >= min_companies]
    for registo in comuns:
        registo["companies_count"] = len(registo["companies"])
        registo["companies"].sort(key=lambda linha: (linha.get("count") or 0), reverse=True)
    comuns.sort(key=lambda item: (item["companies_count"], item["contracts"]), reverse=True)
    return comuns


def benchmark_cross(
    *,
    entities: List[Dict[str, Any]],
    role: str = "adjudicatario",
    cpv_code: Optional[str] = None,
    year_from: Optional[int] = None,
    year_to: Optional[int] = None,
    min_companies: int = 2,
    top: int = 0,
    es: Any = None,
) -> Dict[str, Any]:
    """Cruza empresas de países diferentes: preços, CPV e contrapartes em comum.

    Cada empresa é analisada **no seu próprio mercado** (índice e dialeto do seu
    país) e a comparação entre países faz-se pelo **CPV** — a única classificação
    comum aos três registos. Os preços não se comparam diretamente entre países
    (mercados, moedas de reporte e práticas de contratação diferentes): o que se
    compara é a posição de cada empresa **dentro** do seu mercado (índice de
    preço e quota) e depois o que têm em comum (CPV e contrapartes).
    """
    alvos = [
        alvo
        for alvo in (entities or [])
        if (alvo or {}).get("nif") or str((alvo or {}).get("name") or "").strip()
    ]
    if len(alvos) < 2:
        return {"error": "Escolha pelo menos duas empresas (de países diferentes, se quiser)."}
    if len(alvos) > MAX_CROSS:
        alvos = alvos[:MAX_CROSS]
    role = role if role in ROLES else bc.SUPPLIER
    min_companies = max(2, min(int(min_companies or 2), len(alvos)))
    historico = max(_CROSS_HISTORY, int(top or 0) * 2)

    def _analisar(alvo: Dict[str, Any]) -> Dict[str, Any]:
        return benchmark_entity(
            nif=alvo.get("nif"),
            name=alvo.get("name"),
            role=role,
            country=alvo.get("country") or "pt",
            cpv_code=cpv_code,
            year_from=year_from,
            year_to=year_to,
            top=historico,
            es=es,
        )

    with ThreadPoolExecutor(max_workers=min(4, len(alvos))) as pool:
        resultados = list(pool.map(_analisar, alvos))

    empresas: List[Dict[str, Any]] = []
    for alvo, dados in zip(alvos, resultados):
        pais = bc.country_key(alvo.get("country"))
        dialeto = bc.dialect(pais)
        if dados.get("error"):
            empresas.append(
                {
                    "country": pais,
                    "country_label": dialeto["label"],
                    "short": dialeto["short"],
                    "nif": alvo.get("nif"),
                    "name": alvo.get("name") or alvo.get("nif") or "",
                    "present": False,
                    "contracts": 0,
                    "total_value": 0.0,
                    "market": {"contracts": 0, "median": None, "label": dialeto["label"]},
                    "cpvs": [],
                    "counterparties": [],
                    "error": str(dados.get("error")),
                }
            )
            continue
        entidade = dados.get("entity") or {}
        referencia = dados.get("reference") or {}
        empresas.append(
            {
                "country": pais,
                "country_label": dados.get("country_label") or dialeto["label"],
                "short": dialeto["short"],
                "nif": entidade.get("nif") or alvo.get("nif"),
                "name": entidade.get("name") or alvo.get("name") or alvo.get("nif") or "",
                "present": bool(entidade.get("present")),
                "contracts": int(entidade.get("contracts") or 0),
                "total_value": float(entidade.get("total_value") or 0.0),
                "median": entidade.get("median_value"),
                "price_index": entidade.get("price_index"),
                "rank": entidade.get("rank"),
                "share_pct": entidade.get("share_pct"),
                "market": {
                    "contracts": int(referencia.get("contracts") or 0),
                    "median": referencia.get("median"),
                    "label": dados.get("country_label") or dialeto["label"],
                },
                "cpvs": (entidade.get("top_cpv") or [])[:_CROSS_CPV],
                "counterparties": (dados.get("history") or [])[:historico],
                "recent": (entidade.get("recent") or [])[:_CROSS_RECENT],
            }
        )

    pares_cpv = [(empresa, _normalizar_cpvs(empresa["cpvs"])) for empresa in empresas]
    pares_contraparte = [(empresa, empresa["counterparties"]) for empresa in empresas]
    cpvs_comuns = _cruzar_itens(pares_cpv, "code", min_companies)
    contrapartes_comuns = _cruzar_itens(pares_contraparte, "nif", min_companies)

    counterpart_role = _counterpart_role(role)
    nome_contraparte = "Compradores" if role == bc.SUPPLIER else "Fornecedores"
    notas: List[str] = [
        "Cada empresa é analisada no mercado do seu país; a comparação entre países faz-se pelo CPV.",
        "Os preços não se comparam diretamente entre países — compare-se o índice de preço "
        "(mediana da empresa ÷ mediana do mercado dela) e a quota de valor.",
        (
            f"As contrapartes em comum são os compradores que contrataram duas ou mais destas "
            f"empresas; o cálculo usa as {historico} maiores contrapartes de cada uma (não a lista completa)."
            if role == bc.SUPPLIER
            else f"As contrapartes em comum são os fornecedores de duas ou mais destas empresas; "
            f"o cálculo usa as {historico} maiores contrapartes de cada uma (não a lista completa)."
        ),
        "Os CPV por empresa são os mais usados por ela no período (não o universo todo).",
    ]
    if any(empresa["country"] == "fr" for empresa in empresas):
        notas.append("Em França o DECP não traz nomes: as entidades são identificadas pelo SIRET.")
    ausentes = [empresa["name"] for empresa in empresas if not empresa["present"]]
    if ausentes:
        notas.append("Sem contratos no segmento: " + ", ".join(ausentes) + ".")

    return {
        "role": role,
        "counterpart_role": counterpart_role,
        "counterparty_label": nome_contraparte,
        "cpv_filter": cpv_code or None,
        "companies": empresas,
        "shared_cpvs": cpvs_comuns,
        "shared_counterparties": contrapartes_comuns,
        "notes": notas,
    }


# --------------------------------------------------------- «tudo», por CPV

def _codigo_cpv_base(codigo: str) -> str:
    """Normaliza um CPV para comparar entre países (PT usa `33600000-6`, ES/FR `33600000`)."""
    return (codigo or "").split("-")[0].strip()[:8]


def benchmark_by_cpv(
    *,
    countries: Optional[List[str]] = None,
    cpv_code: Optional[str] = None,
    year_from: Optional[int] = None,
    year_to: Optional[int] = None,
    top: int = 40,
    es: Any = None,
) -> Dict[str, Any]:
    """Quadro de CPV com o volume e o preço de cada país (página «Portugal+Espanha+França»).

    Faz uma pesquisa por país (cada índice tem o seu dialeto) e junta as linhas
    pelo **código CPV normalizado** (os oito dígitos, sem o dígito de controlo),
    devolvendo por CPV o total e a parcela de cada país.
    """
    client = es or get_es_client(request_timeout=_REQUEST_TIMEOUT)
    if not client:
        return {"error": "Elasticsearch indisponível"}

    escolhidos = [bc.country_key(c) for c in (countries or list(bc.COUNTRIES))]
    escolhidos = [c for c in bc.COUNTRIES if c in escolhidos] or list(bc.COUNTRIES)
    top = max(1, min(int(top or 40), 200))

    linhas: Dict[str, Dict[str, Any]] = {}
    por_pais: Dict[str, Dict[str, Any]] = {}
    for pais in escolhidos:
        dialeto = bc.dialect(pais)
        filtros = [f for f in (bc.cpv_filter(pais, cpv_code), bc.year_filter(pais, year_from, year_to)) if f]
        try:
            resp = client.search(
                index=dialeto["index"],
                body={
                    "size": 0,
                    "track_total_hits": True,
                    "query": ({"bool": {"filter": filtros}} if filtros else {"match_all": {}}),
                    "aggs": {
                        "cpv": bc.cpv_agg(pais, top, com_mediana=True),
                        "priced": {
                            "filter": {"bool": {"filter": bc.value_filters(pais)}},
                            "aggs": {
                                "stats": {"stats": {"field": dialeto["valor_campo"]}},
                                "percentiles": {
                                    "percentiles": {
                                        "field": dialeto["valor_campo"],
                                        "percents": [50],
                                    }
                                },
                            },
                        },
                    },
                },
            )
        except Exception as exc:  # pragma: no cover - erro de cluster
            logger.warning("Benchmark por CPV falhou (%s): %s", pais, exc)
            return {"error": str(exc)}

        aggs = resp.get("aggregations") or {}
        precos = _stats((aggs.get("priced") or {}).get("stats"))
        percentis = _percentiles((aggs.get("priced") or {}).get("percentiles"))
        por_pais[pais] = {
            "country": pais,
            "label": dialeto["label"],
            "short": dialeto["short"],
            "index": dialeto["index"],
            "contracts": ((resp.get("hits") or {}).get("total") or {}).get("value", 0),
            "priced_contracts": precos.get("count") or 0,
            "total_value": precos.get("sum") or 0.0,
            "median": percentis.get("p50"),
        }
        for linha in bc.cpv_rows(pais, aggs.get("cpv")):
            base = _codigo_cpv_base(linha["code"])
            if not base:
                continue
            registo = linhas.setdefault(
                base,
                {
                    "code": base,
                    "description": "",
                    "example": linha["code"],
                    "contracts": 0,
                    "value": 0.0,
                    "by_country": {},
                },
            )
            if not registo["description"] and linha.get("description"):
                registo["description"] = linha["description"]
            registo["contracts"] += linha["count"]
            registo["value"] = round(float(registo["value"]) + float(linha.get("value") or 0.0), 2)
            registo["by_country"][pais] = {
                "contracts": linha["count"],
                "value": linha.get("value"),
                "median": linha.get("median"),
            }

    rows = sorted(linhas.values(), key=lambda item: (item["value"], item["contracts"]), reverse=True)[:top]
    for posicao, row in enumerate(rows):
        row["rank"] = posicao + 1

    return {
        "countries": [por_pais[p] for p in escolhidos],
        "cpv_filter": cpv_code,
        "items": rows,
        "notes": [
            "Uma pesquisa por país; as linhas juntam os CPV pelo código base (oito dígitos, sem o dígito de controlo).",
            "O valor e a mediana de cada país usam o campo de valor do respetivo índice e ignoram valores "
            "negativos e sentinelas (Portugal/ Espanha/ França têm tetos diferentes).",
        ],
    }


def top_cpv(
    q: Optional[str] = None,
    size: int = 20,
    country: str = "pt",
    es: Any = None,
) -> Dict[str, Any]:
    """CPV mais usados no país (para o seletor da página), com descrição."""
    client = es or get_es_client()
    if not client:
        return {"error": "Elasticsearch indisponível", "items": []}

    country = bc.country_key(country)
    dialeto = bc.dialect(country)
    limpo = max(1, min(int(size or 20), 100))
    filtro = bc.cpv_filter(country, (q or "").strip() or None)

    body: Dict[str, Any] = {
        "size": 0,
        "query": filtro or {"match_all": {}},
        "aggs": {"cpv": bc.cpv_agg(country, limpo)},
    }
    try:
        resp = client.search(index=dialeto["index"], body=body)
    except Exception as exc:  # pragma: no cover
        return {"error": str(exc), "items": []}

    return {
        "country": country,
        "query": q,
        "items": bc.cpv_rows(country, (resp.get("aggregations") or {}).get("cpv")),
    }


def benchmark_meta(country: Optional[str] = None, es: Any = None) -> Dict[str, Any]:
    """Volumetria e anos disponíveis. Sem país, devolve o resumo dos três."""
    client = es or get_es_client()
    if not client:
        return {"error": "Elasticsearch indisponível", "countries": []}

    paises = list(bc.COUNTRIES) if bc.is_all(country) else [bc.country_key(country)]
    resumo: List[Dict[str, Any]] = []
    for pais in paises:
        dialeto = bc.dialect(pais)
        try:
            total = client.count(index=dialeto["index"]).get("count", 0)
            resp = client.search(index=dialeto["index"], body={"size": 0, "aggs": {"years": bc.ano_agg(pais)}})
            anos = [int(bucket["key"]) for bucket in resp["aggregations"]["years"]["buckets"]]
        except Exception as exc:  # pragma: no cover
            logger.warning("Meta do benchmark falhou (%s): %s", pais, exc)
            total, anos = 0, []
        resumo.append(
            {
                "country": pais,
                "label": dialeto["label"],
                "short": dialeto["short"],
                "index": dialeto["index"],
                "total": total,
                "years": anos,
                "roles": [bc.SUPPLIER, bc.BUYER],
                "role_labels": bc.ROLE_LABELS[pais],
            }
        )

    if len(resumo) == 1:
        return {**resumo[0], "countries": resumo}
    return {
        "country": "all",
        "label": "Portugal, Espanha e França",
        "countries": resumo,
        "total": sum(item["total"] for item in resumo),
        "years": sorted({ano for item in resumo for ano in item["years"]}, reverse=True),
        "roles": [bc.SUPPLIER, bc.BUYER],
    }
