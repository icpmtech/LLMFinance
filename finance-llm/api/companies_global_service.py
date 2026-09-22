"""Empresas e entidades globais — uma vista única sobre todas as fontes do IQ OS.

Cada fonte tem o seu índice e o seu esquema (cadastro português, RNPC, INPI,
PLACSP espanhol, CRM), pelo que este serviço **normaliza** tudo no mesmo formato
e devolve uma lista ordenada, com a contagem por fonte ao lado.

Decisões:

- **Uma fonte não derruba as outras**: cada coletor tem o seu `try/except` e o
  erro fica assinalado no cartão daquela fonte.
- **Fontes de sessão** (CRM) só são pesquisadas quando há sessão — e nunca
  devolvem registos de outro utilizador.
- **Entrelaçado por fonte** na vista «Todas»: sem isto uma fonte com muitos
  resultados (por exemplo o cadastro português) tapava as restantes.
- **As entidades de Espanha são agregações**: no PLACSP cada documento é um
  contrato, pelo que os nomes dos órgãos adjudicantes e das empresas
  adjudicatárias vêm de um `terms` sobre o campo do nome (ver
  `elasticsearch_client.search_contratos_es_entities`).
"""
from __future__ import annotations

import logging
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from typing import Any, Dict, List, Optional

from api.elasticsearch_client import (
    ENTITIES_INDEX,
    FIRMAS_INDEX,
    TRADEMARKS_INDEX,
    CONTRATOS_ES_INDEX,
    ensure_indices,
    get_es_client,
    search_contratos_es_entities,
    search_entities,
    search_firmas,
    search_trademarks,
)

logger = logging.getLogger(__name__)

# ------------------------------------------------------------------- catálogo
SOURCES: List[Dict[str, Any]] = [
    {
        "id": "entity",
        "label": "Cadastro (PT)",
        "hint": "Entidades do portal base com contratos públicos",
        "country": "PT",
        "index": ENTITIES_INDEX,
    },
    {
        "id": "firma",
        "label": "Firmas (RNPC)",
        "hint": "Firmas e denominações registadas no RNPC",
        "country": "PT",
        "index": FIRMAS_INDEX,
    },
    {
        "id": "trademark",
        "label": "Marcas (INPI)",
        "hint": "Marcas registadas e respetivos titulares",
        "country": "PT",
        "index": TRADEMARKS_INDEX,
    },
    {
        "id": "organo_es",
        "label": "Entidades ES",
        "hint": "Órgãos adjudicantes de Espanha (PLACSP)",
        "country": "ES",
        "index": CONTRATOS_ES_INDEX,
        "entity_field": "organo_nombre.keyword",
    },
    {
        "id": "adjudicataria_es",
        "label": "Empresas ES",
        "hint": "Empresas adjudicatárias de Espanha (PLACSP)",
        "country": "ES",
        "index": CONTRATOS_ES_INDEX,
        "entity_field": "adjudicatario_nombre.keyword",
    },
    {
        "id": "crm",
        "label": "CRM",
        "hint": "Contas do CRM (privadas por utilizador)",
        "country": "—",
        "session": True,
    },
]
SOURCE_IDS = [source["id"] for source in SOURCES]
_ES_KIND = {"organo_es": "organo", "adjudicataria_es": "adjudicatario"}

# Cache da volumetria por fonte (a cardinalidade do PLACSP leva alguns segundos).
_SUMMARY_TTL = 300.0
_summary_cache: Dict[str, Optional[tuple]] = {"public": None, "session": None}


def _source(source_id: str) -> Dict[str, Any]:
    return next((item for item in SOURCES if item["id"] == source_id), {"id": source_id, "label": source_id})


def _label(source_id: str) -> str:
    return str(_source(source_id).get("label") or source_id)


def _num(value: Any) -> Optional[float]:
    return float(value) if isinstance(value, (int, float)) else None


def _row(
    source_id: str,
    item_id: str,
    name: str,
    *,
    detail: str = "",
    nif: str = "",
    region: str = "",
    date: Optional[str] = None,
    contracts_count: Optional[int] = None,
    total_value: Optional[float] = None,
    extra: Optional[Dict[str, Any]] = None,
    open_view: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """Linha normalizada (mesmo formato para todas as fontes)."""
    source = _source(source_id)
    return {
        "source": source_id,
        "source_label": source.get("label") or source_id,
        "country": source.get("country") or "",
        "id": str(item_id or name or ""),
        "name": (name or "").strip() or "(sem nome)",
        "detail": detail,
        "nif": nif or "",
        "region": region or "",
        "date": date,
        "contracts_count": contracts_count,
        "total_value": total_value,
        "extra": extra or {},
        "open": open_view,
    }


# ----------------------------------------------------------------- coletores
def _collect_entity(q: str, size: int, offset: int) -> Dict[str, Any]:
    result = search_entities(q=q or None, size=size, from_=offset, sort_by="contracts_count", sort_order="desc")
    if result.get("error"):
        return {"error": str(result["error"]), "items": [], "total": 0}
    rows = [
        _row(
            "entity",
            row.get("nif") or row.get("name") or "",
            row.get("name") or "",
            detail=" · ".join(filter(None, [row.get("country"), row.get("source")])),
            nif=str(row.get("nif") or ""),
            region=str(row.get("country") or ""),
            date=row.get("ingested_at"),
            contracts_count=int(row.get("contracts_count") or 0),
            total_value=_num(row.get("total_value")),
            extra={
                "adjudicante": row.get("as_adjudicante_count"),
                "adjudicatario": row.get("as_adjudicatario_count"),
            },
            open_view={"view": "company-detail", "arg": str(row.get("nif") or "")} if row.get("nif") else None,
        )
        for row in (result.get("items") or [])
    ]
    return {"items": rows, "total": int(result.get("total") or 0), "error": None}


def _collect_firma(q: str, size: int, offset: int) -> Dict[str, Any]:
    result = search_firmas(q=q or None, size=size, from_=offset)
    if result.get("error"):
        return {"error": str(result["error"]), "items": [], "total": 0}
    rows = [
        _row(
            "firma",
            row.get("numero_certificado") or row.get("nipc") or row.get("nome") or "",
            row.get("nome") or "",
            detail=" · ".join(filter(None, [row.get("situacao"), row.get("concelho"), row.get("cae_principal")])),
            nif=str(row.get("nipc") or ""),
            region=str(row.get("concelho") or ""),
            date=row.get("ingested_at"),
            extra={"cae": row.get("cae_principal"), "situacao": row.get("situacao")},
            open_view=(
                {"view": "trademark-holder", "arg": str(row.get("company_nif"))} if row.get("company_nif") else None
            ),
        )
        for row in (result.get("items") or [])
    ]
    return {"items": rows, "total": int(result.get("total") or 0), "error": None}


def _collect_trademark(q: str, size: int, offset: int) -> Dict[str, Any]:
    result = search_trademarks(q=q or None, size=size, from_=offset)
    if result.get("error"):
        return {"error": str(result["error"]), "items": [], "total": 0}
    rows = []
    for row in result.get("items") or []:
        nif = row.get("company_nif") or row.get("holder_nif")
        rows.append(
            _row(
                "trademark",
                row.get("process_number") or row.get("mark_name") or "",
                row.get("holder_name") or row.get("mark_name") or "",
                detail=" · ".join(
                    filter(None, [row.get("mark_name"), row.get("mark_type"), row.get("current_phase")])
                ),
                nif=str(nif or ""),
                date=row.get("application_date"),
                extra={"process_number": row.get("process_number"), "mark_name": row.get("mark_name")},
                open_view={"view": "company-detail", "arg": str(nif)} if nif else None,
            )
        )
    return {"items": rows, "total": int(result.get("total") or 0), "error": None}


def _collect_es(source_id: str, q: str, size: int, offset: int) -> Dict[str, Any]:
    result = search_contratos_es_entities(q=q or None, kind=_ES_KIND[source_id], size=size, from_=offset)
    if result.get("error"):
        return {"error": str(result["error"]), "items": [], "total": 0}
    rows = [
        _row(
            source_id,
            row.get("name") or "",
            row.get("name") or "",
            detail=" · ".join(filter(None, [row.get("city"), row.get("nuts")])),
            nif=str(row.get("nif") or ""),
            region=str(row.get("city") or row.get("nuts") or ""),
            contracts_count=int(row.get("count") or 0),
            total_value=_num(row.get("total_value")),
            extra={"dir3": row.get("organo_id"), "last_year": row.get("last_year")},
            open_view={"view": "contratos-es", "arg": str(row.get("name") or ""), "mode": str(row.get("kind") or "")},
        )
        for row in (result.get("items") or [])
    ]
    return {"items": rows, "total": int(result.get("total") or 0), "error": None}


def _collect_crm(q: str, size: int, offset: int, session_scope: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    if not session_scope:
        return {"error": None, "items": [], "total": 0, "skipped": True}
    from api import crm_service

    owner = {
        "id": session_scope.get("user_id"),
        "see_all": bool(session_scope.get("see_all")),
    }
    result = crm_service.list_records("accounts", owner, q=q or None, size=size, from_=offset)
    if result.get("error"):
        return {"error": str(result["error"]), "items": [], "total": 0}
    rows = [
        _row(
            "crm",
            row.get("id") or "",
            row.get("name") or "",
            detail=" · ".join(filter(None, [row.get("sector"), row.get("city"), row.get("status")])),
            nif=str(row.get("nif") or ""),
            region=str(row.get("city") or ""),
            date=row.get("updated_at") or row.get("created_at"),
            total_value=_num(row.get("annual_revenue")),
            extra={"stage": row.get("stage"), "owner": row.get("owner_email")},
            open_view={"view": "crm-account", "arg": str(row.get("id") or "")},
        )
        for row in (result.get("items") or [])
    ]
    return {"items": rows, "total": int(result.get("total") or 0), "error": None}


COLLECTORS = {
    "entity": lambda q, size, offset, scope: _collect_entity(q, size, offset),
    "firma": lambda q, size, offset, scope: _collect_firma(q, size, offset),
    "trademark": lambda q, size, offset, scope: _collect_trademark(q, size, offset),
    "organo_es": lambda q, size, offset, scope: _collect_es("organo_es", q, size, offset),
    "adjudicataria_es": lambda q, size, offset, scope: _collect_es("adjudicataria_es", q, size, offset),
    "crm": lambda q, size, offset, scope: _collect_crm(q, size, offset, scope),
}


# ------------------------------------------------------------------ pesquisa
def search(
    q: str,
    *,
    source: str = "all",
    size: int = 24,
    offset: int = 0,
    session_scope: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Pesquisa empresas/entidades em todas as fontes (ou numa só)."""
    query = (q or "").strip()
    size = max(1, min(int(size), 100))
    offset = max(0, int(offset))
    requested = [source] if source in SOURCE_IDS else list(SOURCE_IDS)
    if not session_scope:
        requested = [item for item in requested if not _source(item).get("session")]

    client = get_es_client()
    if not client:
        return {"query": query, "source": source, "total": 0, "items": [], "sources": SOURCES, "error": "Elasticsearch indisponível"}
    ensure_indices(client)

    started = datetime.now()
    cards: List[Dict[str, Any]] = []
    collected: Dict[str, List[Dict[str, Any]]] = {}

    if len(requested) == 1:
        source_id = requested[0]
        result = COLLECTORS[source_id](query, size, offset, session_scope)
        collected[source_id] = result.get("items") or []
        cards.append(
            {
                "id": source_id,
                "label": _label(source_id),
                "country": _source(source_id).get("country") or "",
                "total": int(result.get("total") or 0),
                "returned": len(collected[source_id]),
                "error": result.get("error"),
            }
        )
    else:
        with ThreadPoolExecutor(max_workers=min(4, max(1, len(requested)))) as pool:
            futures = {
                pool.submit(COLLECTORS[source_id], query, size, offset, session_scope): source_id
                for source_id in requested
            }
            for future, source_id in futures.items():
                try:
                    result = future.result(timeout=30)
                except Exception as exc:  # pragma: no cover - depende do Elasticsearch
                    logger.warning("Empresas globais: fonte %s falhou: %s", source_id, exc)
                    result = {"error": f"{type(exc).__name__}: {exc}", "items": [], "total": 0}
                collected[source_id] = result.get("items") or []
                cards.append(
                    {
                        "id": source_id,
                        "label": _label(source_id),
                        "country": _source(source_id).get("country") or "",
                        "total": int(result.get("total") or 0),
                        "returned": len(collected[source_id]),
                        "error": result.get("error"),
                    }
                )

    # Entrelaça as fontes para a lista não ficar só com a primeira.
    items: List[Dict[str, Any]] = []
    depth = max((len(rows) for rows in collected.values()), default=0)
    for index in range(depth):
        for source_id in requested:
            rows = collected.get(source_id) or []
            if index < len(rows):
                items.append(rows[index])

    order = {source_id: index for index, source_id in enumerate(SOURCE_IDS)}
    cards.sort(key=lambda card: order.get(card["id"], 99))
    took_ms = int((datetime.now() - started).total_seconds() * 1000)
    return {
        "query": query,
        "source": source,
        "size": size,
        "offset": offset,
        "took_ms": took_ms,
        "total": sum(card["total"] for card in cards),
        "items": items[:size],
        "sources": cards,
    }


def sources_summary(session_scope: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Catálogo de fontes com a volumetria indexada (para os separadores da app).

    A contagem das entidades espanholas é uma cardinalidade sobre 4 milhões de
    documentos, pelo que o resultado fica em cache durante alguns minutos.
    """
    cache_key = "session" if session_scope else "public"
    cached = _summary_cache.get(cache_key)
    if cached and time.time() - cached[0] < _SUMMARY_TTL:
        return cached[1]

    payload = _build_sources_summary(session_scope)
    _summary_cache[cache_key] = (time.time(), payload)
    return payload


def _build_sources_summary(session_scope: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    client = get_es_client()
    if not client:
        return {"items": SOURCES, "error": "Elasticsearch indisponível"}
    ensure_indices(client)

    def count_index(index: Optional[str]) -> Optional[int]:
        if not index:
            return None
        try:
            return int(client.count(index=index).get("count", 0))
        except Exception:  # pragma: no cover - índice pode não existir
            return None

    items: List[Dict[str, Any]] = []
    for entry in SOURCES:
        card = {key: value for key, value in entry.items() if key != "entity_field"}
        source_id = entry["id"]
        if entry.get("session"):
            if session_scope:
                from api import crm_service

                owner = {"id": session_scope.get("user_id"), "see_all": bool(session_scope.get("see_all"))}
                result = crm_service.list_records("accounts", owner, size=1)
                card["available"] = None if result.get("error") else int(result.get("total") or 0)
                card["available_label"] = "contas"
            else:
                card["available"] = None
                card["blocked"] = True
            items.append(card)
            continue

        if entry.get("entity_field"):
            # Entidades distintas no PLACSP: cardinalidade aproximada sobre o nome.
            try:
                resp = client.search(
                    index=CONTRATOS_ES_INDEX,
                    body={
                        "size": 0,
                        "track_total_hits": False,
                        "aggs": {
                            "entidades": {
                                "cardinality": {
                                    "field": entry["entity_field"],
                                    "precision_threshold": 40000,
                                }
                            }
                        },
                    },
                )
                card["available"] = int(resp.get("aggregations", {}).get("entidades", {}).get("value") or 0)
            except Exception:  # pragma: no cover
                card["available"] = None
            card["available_label"] = "entidades"
            card["documents"] = count_index(CONTRATOS_ES_INDEX)
            items.append(card)
            continue

        card["available"] = count_index(entry.get("index"))
        card["available_label"] = "registos"
        items.append(card)

    return {"items": items}
