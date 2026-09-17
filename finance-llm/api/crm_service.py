"""Serviço do módulo de CRM do IQ OS.

Todo o módulo vive num único índice do Elasticsearch (`finance_crm`), onde o
campo `kind` distingue o tipo de registo:

- `account`  — conta (empresa cliente/prospecto), opcionalmente ligada a uma
               entidade do EmpresasIQ pelo NIF;
- `contact`  — pessoa dentro de uma conta;
- `deal`     — oportunidade do pipeline (fase, valor, probabilidade, data prevista);
- `activity` — atividade/compromisso (chamada, reunião, email, tarefa, nota).

Cada registo tem um dono (`owner_id` + `owner_email`). Por omissão cada
utilizador só vê os seus registos; os administradores veem os de toda a equipa
(`owner.see_all`).

Os ids são gerados neste serviço (`<prefixo>_<12 hex>`) e o `_id` do documento é
`<kind>:<id>`, o que permite obter/atualizar/apagar um registo sem pesquisar.
"""
from __future__ import annotations

import logging
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

from api.elasticsearch_client import CRM_INDEX, ensure_indices, get_entity_by_nif, get_es_client

logger = logging.getLogger(__name__)

# ------------------------------------------------------------------ constantes
ACCOUNT = "account"
CONTACT = "contact"
DEAL = "deal"
ACTIVITY = "activity"

KINDS: Tuple[str, ...] = (ACCOUNT, CONTACT, DEAL, ACTIVITY)
_ID_PREFIX = {ACCOUNT: "acc", CONTACT: "con", DEAL: "dea", ACTIVITY: "act"}

ACCOUNT_STATUSES: Tuple[str, ...] = ("prospect", "cliente", "inativo")
DEAL_STAGES: Tuple[str, ...] = ("prospeccao", "qualificacao", "proposta", "negociacao", "ganho", "perdido")
OPEN_STAGES: Tuple[str, ...] = DEAL_STAGES[:4]
CLOSED_STAGES: Tuple[str, ...] = DEAL_STAGES[4:]
ACTIVITY_TYPES: Tuple[str, ...] = ("chamada", "reuniao", "email", "tarefa", "nota")
PRIORITIES: Tuple[str, ...] = ("baixa", "media", "alta")
DEFAULT_CURRENCY = "EUR"

# Campos aceites por tipo de registo (tudo o resto é descartado). Os campos de
# sistema (`kind`, `owner_*`, `created_at`, `updated_at`) são geridos aqui.
FIELDS: Dict[str, Tuple[str, ...]] = {
    ACCOUNT: (
        "name", "nif", "sector", "status", "website", "email", "phone", "mobile",
        "address", "city", "country", "postal_code", "employees", "annual_revenue",
        "notes", "tags", "entity",
    ),
    CONTACT: (
        "account_id", "name", "title", "role", "email", "phone", "mobile",
        "linkedin", "is_primary", "notes", "tags",
    ),
    DEAL: (
        "account_id", "contact_id", "title", "amount", "currency", "stage",
        "probability", "expected_close_date", "closed_at", "loss_reason",
        "source", "notes", "tags",
    ),
    ACTIVITY: (
        "account_id", "contact_id", "deal_id", "type", "subject", "notes",
        "due_at", "done", "done_at", "priority", "tags",
    ),
}

# Campos numéricos (aceitam strings com vírgula decimal) e booleanos.
_NUMERIC = {"employees", "annual_revenue", "amount", "probability"}
_BOOLEAN = {"done", "is_primary"}

# Campos de pesquisa livre por tipo (pesos maiores à esquerda).
_SEARCH_FIELDS: Dict[str, List[str]] = {
    ACCOUNT: ["name^3", "nif", "email", "city", "sector", "website", "notes"],
    CONTACT: ["name^3", "title^2", "email", "phone", "mobile", "notes"],
    DEAL: ["title^3", "notes", "loss_reason", "source"],
    ACTIVITY: ["subject^3", "notes"],
}

# Filtros exatos aceites por tipo (chave do pedido → campo no índice).
_TERM_FILTERS: Dict[str, Dict[str, str]] = {
    ACCOUNT: {
        "status": "status",
        "sector": "sector",
        "nif": "nif",
        "city": "city",
        "country": "country",
        "owner_id": "owner_id",
        "tag": "tags",
    },
    CONTACT: {"account_id": "account_id", "owner_id": "owner_id", "tag": "tags"},
    DEAL: {
        "stage": "stage",
        "account_id": "account_id",
        "contact_id": "contact_id",
        "owner_id": "owner_id",
        "tag": "tags",
    },
    ACTIVITY: {
        "account_id": "account_id",
        "deal_id": "deal_id",
        "contact_id": "contact_id",
        "type": "type",
        "done": "done",
        "priority": "priority",
        "owner_id": "owner_id",
        "tag": "tags",
    },
}

_DEFAULT_SORT: Dict[str, List[Dict[str, Any]]] = {
    ACCOUNT: [{"updated_at": {"order": "desc", "missing": "_last"}}, {"name.keyword": {"order": "asc"}}],
    CONTACT: [{"name.keyword": {"order": "asc"}}, {"updated_at": {"order": "desc", "missing": "_last"}}],
    DEAL: [{"updated_at": {"order": "desc", "missing": "_last"}}],
    ACTIVITY: [
        {"done": {"order": "asc"}},
        {"due_at": {"order": "asc", "missing": "_last"}},
        {"updated_at": {"order": "desc", "missing": "_last"}},
    ],
}

_SORT_FIELDS: Dict[str, str] = {
    "name": "name.keyword",
    "title": "title.keyword",
    "subject": "subject.keyword",
    "amount": "amount",
    "probability": "probability",
    "stage": "stage",
    "status": "status",
    "due_at": "due_at",
    "expected_close_date": "expected_close_date",
    "created_at": "created_at",
    "updated_at": "updated_at",
    "priority": "priority",
    "type": "type",
}


# ------------------------------------------------------------------ utilitários
def _now() -> str:
    """Instante atual em ISO-8601 UTC (formato aceite pelo Elasticsearch)."""
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _new_id(kind: str) -> str:
    return f"{_ID_PREFIX[kind]}_{uuid.uuid4().hex[:12]}"


def _doc_id(kind: str, record_id: str) -> str:
    return f"{kind}:{record_id}"


def _as_float(value: Any) -> Optional[float]:
    if value is None or value == "":
        return None
    try:
        return float(str(value).replace(" ", "").replace("€", "").replace(",", "."))
    except (TypeError, ValueError):
        return None


def _as_int(value: Any) -> Optional[int]:
    number = _as_float(value)
    return None if number is None else int(number)


def _as_bool(value: Any) -> Optional[bool]:
    if isinstance(value, bool):
        return value
    if value is None or value == "":
        return None
    return str(value).strip().lower() in {"1", "true", "sim", "yes", "on"}


def _as_tags(value: Any) -> List[str]:
    if value is None:
        return []
    if isinstance(value, str):
        parts = [chunk.strip() for chunk in value.split(",")]
    elif isinstance(value, (list, tuple, set)):
        parts = [str(chunk).strip() for chunk in value]
    else:
        return []
    seen: List[str] = []
    for part in parts:
        if part and part not in seen:
            seen.append(part)
    return seen[:24]


def _clean_text(value: Any, limit: int = 20000) -> Optional[str]:
    if value is None:
        return None
    text = str(value).strip()
    return text[:limit] if text else ""


def normalize_payload(kind: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    """Filtra e converte os campos enviados pelo cliente para o tipo indicado."""
    if kind not in KINDS:
        return {}
    clean: Dict[str, Any] = {}
    for field in FIELDS[kind]:
        if field not in payload:
            continue
        value = payload[field]
        if field in _NUMERIC:
            clean[field] = _as_int(value) if field in {"employees", "probability"} else _as_float(value)
        elif field in _BOOLEAN:
            clean[field] = _as_bool(value)
        elif field == "tags":
            clean[field] = _as_tags(value)
        elif field in {"entity"}:
            clean[field] = value if isinstance(value, dict) else None
        else:
            clean[field] = _clean_text(value)
    return clean


def _with_deal_derivatives(kind: str, doc: Dict[str, Any]) -> Dict[str, Any]:
    """Completa campos calculados das oportunidades (valor ponderado, fecho)."""
    if kind != DEAL:
        return doc
    amount = _as_float(doc.get("amount")) or 0.0
    probability = _as_int(doc.get("probability"))
    if probability is None:
        probability = 0
    probability = max(0, min(100, probability))
    doc["probability"] = probability
    doc["weighted_amount"] = round(amount * probability / 100.0, 2)
    if doc.get("stage") in CLOSED_STAGES and not doc.get("closed_at"):
        doc["closed_at"] = _now()
    if doc.get("stage") not in CLOSED_STAGES:
        doc["closed_at"] = None
    return doc


def _owner_filters(owner: Dict[str, Any]) -> List[Dict[str, Any]]:
    if owner.get("see_all"):
        return []
    return [{"term": {"owner_id": owner.get("id")}}]


def _query(kind: str, owner: Dict[str, Any], q: Optional[str], filters: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    must: List[Dict[str, Any]] = []
    if q:
        must.append(
            {
                "multi_match": {
                    "query": q,
                    "fields": _SEARCH_FIELDS[kind],
                    "operator": "and",
                    "fuzziness": "AUTO",
                }
            }
        )
    where = [{"term": {"kind": kind}}, *_owner_filters(owner)]
    allowed = _TERM_FILTERS[kind]
    for key, value in (filters or {}).items():
        field = allowed.get(key)
        if not field or value is None or value == "":
            continue
        if key == "done":
            converted = _as_bool(value)
            if converted is not None:
                where.append({"term": {field: converted}})
            continue
        where.append({"term": {field: value}})
    body: Dict[str, Any] = {"bool": {"filter": where}}
    if must:
        body["bool"]["must"] = must
    return body


def _sort_for(kind: str, sort_by: Optional[str], sort_order: Optional[str]) -> List[Dict[str, Any]]:
    field = _SORT_FIELDS.get(sort_by or "")
    if not field:
        return _DEFAULT_SORT[kind]
    order = "asc" if (sort_order or "desc").lower() == "asc" else "desc"
    spec: Dict[str, Any] = {"order": order}
    if field in {"due_at", "expected_close_date"}:
        spec["missing"] = "_last"
    return [{field: spec}, {"updated_at": {"order": "desc", "missing": "_last"}}]


def _hit_to_record(hit: Dict[str, Any]) -> Dict[str, Any]:
    src = dict(hit.get("_source") or {})
    doc_id = str(hit.get("_id") or "")
    record_id = src.get("id") or (doc_id.split(":", 1)[1] if ":" in doc_id else doc_id)
    src["id"] = record_id
    src["doc_id"] = doc_id
    return src


def _client_or_error() -> Tuple[Optional[Any], Optional[Dict[str, Any]]]:
    client = get_es_client()
    if not client:
        return None, {"error": "Elasticsearch indisponível"}
    ensure_indices(client)
    return client, None


# ------------------------------------------------------------------- pesquisas
def list_records(
    kind: str,
    owner: Dict[str, Any],
    *,
    q: Optional[str] = None,
    filters: Optional[Dict[str, Any]] = None,
    size: int = 200,
    from_: int = 0,
    sort_by: Optional[str] = None,
    sort_order: Optional[str] = None,
) -> Dict[str, Any]:
    """Lista/pesquisa registos de um tipo, limitados ao âmbito do utilizador."""
    if kind not in KINDS:
        return {"error": f"Tipo de registo inválido: {kind}", "items": [], "total": 0}
    client, error = _client_or_error()
    if error:
        return {**error, "items": [], "total": 0}

    try:
        resp = client.search(
            index=CRM_INDEX,
            body={
                "query": _query(kind, owner, q, filters),
                "from": max(0, from_),
                "size": max(1, min(500, size)),
                "sort": _sort_for(kind, sort_by, sort_order),
                "track_total_hits": True,
            },
        )
        hits = resp["hits"]
        return {
            "kind": kind,
            "total": hits["total"]["value"],
            "from": from_,
            "size": size,
            "items": [_hit_to_record(hit) for hit in hits["hits"]],
        }
    except Exception as exc:  # pragma: no cover - depende do Elasticsearch
        logger.warning("CRM: falha ao listar %s: %s", kind, exc)
        return {"error": str(exc), "items": [], "total": 0}


def get_record(kind: str, record_id: str, owner: Dict[str, Any]) -> Dict[str, Any]:
    """Devolve um registo pelo id (verificando o dono)."""
    if kind not in KINDS:
        return {"error": f"Tipo de registo inválido: {kind}"}
    client, error = _client_or_error()
    if error:
        return dict(error)

    try:
        if not client.exists(index=CRM_INDEX, id=_doc_id(kind, record_id)):
            return {"error": "Registo não encontrado"}
        hit = client.get(index=CRM_INDEX, id=_doc_id(kind, record_id))
    except Exception as exc:  # pragma: no cover
        return {"error": str(exc)}

    record = _hit_to_record(hit)
    if not owner.get("see_all") and record.get("owner_id") != owner.get("id"):
        return {"error": "Sem permissão para este registo"}
    return {"item": record}


def save_record(
    kind: str,
    payload: Dict[str, Any],
    owner: Dict[str, Any],
    record_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Cria (sem `record_id`) ou atualiza (com `record_id`) um registo."""
    if kind not in KINDS:
        return {"error": f"Tipo de registo inválido: {kind}"}
    client, error = _client_or_error()
    if error:
        return dict(error)

    fields = normalize_payload(kind, payload)
    existing: Optional[Dict[str, Any]] = None

    if record_id:
        try:
            if client.exists(index=CRM_INDEX, id=_doc_id(kind, record_id)):
                existing = _hit_to_record(client.get(index=CRM_INDEX, id=_doc_id(kind, record_id)))
        except Exception as exc:  # pragma: no cover
            return {"error": str(exc)}
        if existing is None:
            return {"error": "Registo não encontrado"}
        if not owner.get("see_all") and existing.get("owner_id") != owner.get("id"):
            return {"error": "Sem permissão para alterar este registo"}
    else:
        record_id = _new_id(kind)

    doc: Dict[str, Any] = dict(existing or {})
    doc.update(fields)
    doc["id"] = record_id
    doc["kind"] = kind
    doc["owner_id"] = doc.get("owner_id") or owner.get("id")
    doc["owner_email"] = doc.get("owner_email") or owner.get("email")
    doc["created_at"] = doc.get("created_at") or _now()
    doc["updated_at"] = _now()

    # Valores por omissão das oportunidades.
    if kind == DEAL:
        doc["stage"] = doc.get("stage") or DEAL_STAGES[0]
        doc["currency"] = doc.get("currency") or DEFAULT_CURRENCY
        if doc.get("probability") is None:
            doc["probability"] = 20 if doc["stage"] == DEAL_STAGES[0] else 50
        doc = _with_deal_derivatives(kind, doc)
    if kind == ACTIVITY:
        doc["type"] = doc.get("type") or "tarefa"
        doc["done"] = bool(doc.get("done"))
        if doc["done"] and not doc.get("done_at"):
            doc["done_at"] = _now()
        if not doc["done"]:
            doc["done_at"] = None
    if kind == ACCOUNT:
        doc["status"] = doc.get("status") or "prospect"
        if not doc.get("name"):
            return {"error": "A conta precisa de um nome"}
    if kind == CONTACT and not doc.get("name"):
        return {"error": "O contacto precisa de um nome"}
    if kind == DEAL and not doc.get("title"):
        return {"error": "A oportunidade precisa de um título"}
    if kind == ACTIVITY and not doc.get("subject"):
        return {"error": "A atividade precisa de um assunto"}

    doc.pop("doc_id", None)
    try:
        client.index(index=CRM_INDEX, id=_doc_id(kind, record_id), document=doc, refresh=True)
        return {"ok": True, "item": doc}
    except Exception as exc:  # pragma: no cover
        logger.warning("CRM: falha ao guardar %s %s: %s", kind, record_id, exc)
        return {"error": str(exc)}


def delete_record(kind: str, record_id: str, owner: Dict[str, Any]) -> Dict[str, Any]:
    """Apaga um registo (e, no caso de uma conta, os contactos/oportunidades/atividades ligados)."""
    if kind not in KINDS:
        return {"error": f"Tipo de registo inválido: {kind}"}
    client, error = _client_or_error()
    if error:
        return dict(error)

    found = get_record(kind, record_id, owner)
    if found.get("error"):
        return found

    try:
        client.delete(index=CRM_INDEX, id=_doc_id(kind, record_id), refresh=True)
    except Exception as exc:  # pragma: no cover
        return {"error": str(exc)}

    cascaded = 0
    if kind == ACCOUNT:
        link_fields = {"contact": "account_id", "deal": "account_id", "activity": "account_id"}
        for other, field in link_fields.items():
            query = _query(other, owner, None, {field: record_id})
            try:
                resp = client.delete_by_query(
                    index=CRM_INDEX, body={"query": query}, refresh=True, conflicts="proceed"
                )
                cascaded += int(resp.get("deleted", 0))
            except Exception as exc:  # pragma: no cover
                logger.warning("CRM: falha ao apagar %s da conta %s: %s", other, record_id, exc)
    return {"ok": True, "deleted": 1, "cascaded": cascaded}


# ------------------------------------------------------------------ indicadores
def _account_index(client: Any, owner: Dict[str, Any]) -> Dict[str, str]:
    """Mapa `account_id → nome` para etiquetar agregações e listas."""
    try:
        resp = client.search(
            index=CRM_INDEX,
            body={
                "query": _query(ACCOUNT, owner, None, None),
                "size": 500,
                "_source": ["id", "name", "nif", "status", "owner_id", "owner_email"],
            },
        )
        names: Dict[str, str] = {}
        for hit in resp["hits"]["hits"]:
            source = hit["_source"]
            # O `id` do registo é o sufixo do `_id` (`account:<id>`), mas vem
            # também no `_source`; usar o `_id` como reserva evita perdas.
            record_id = source.get("id") or str(hit.get("_id", "")).split(":", 1)[-1]
            names[record_id] = source.get("name") or "—"
        return names
    except Exception:  # pragma: no cover
        return {}


def _count(client: Any, kind: str, owner: Dict[str, Any], filters: Optional[Dict[str, Any]] = None) -> int:
    try:
        return int(client.count(index=CRM_INDEX, body={"query": _query(kind, owner, None, filters)})["count"])
    except Exception:  # pragma: no cover
        return 0


def overview(owner: Dict[str, Any], *, months: int = 6) -> Dict[str, Any]:
    """KPIs do CRM: pipeline por fase, previsão mensal, conversão e agenda."""
    client, error = _client_or_error()
    if error:
        return dict(error)

    now = datetime.now(timezone.utc)
    horizon = now + timedelta(days=31 * max(1, min(24, months)))
    last_year = (now - timedelta(days=365)).isoformat(timespec="seconds").replace("+00:00", "Z")

    accounts_map = _account_index(client, owner)
    stage_index = {stage: position for position, stage in enumerate(DEAL_STAGES)}

    try:
        deals_resp = client.search(
            index=CRM_INDEX,
            body={
                "query": _query(DEAL, owner, None, None),
                "size": 0,
                "aggs": {
                    "by_stage": {
                        "terms": {"field": "stage", "size": 20},
                        "aggs": {
                            "value": {"sum": {"field": "amount"}},
                            "weighted": {"sum": {"field": "weighted_amount"}},
                            "count": {"value_count": {"field": "id"}},
                        },
                    },
                    "open_by_month": {
                        "filter": {"terms": {"stage": list(OPEN_STAGES)}},
                        "aggs": {
                            "by_month": {
                                "date_histogram": {
                                    "field": "expected_close_date",
                                    "calendar_interval": "month",
                                    "min_doc_count": 0,
                                },
                                "aggs": {
                                    "value": {"sum": {"field": "amount"}},
                                    "weighted": {"sum": {"field": "weighted_amount"}},
                                },
                            }
                        },
                    },
                    "top_accounts": {
                        "filter": {"terms": {"stage": list(OPEN_STAGES)}},
                        "aggs": {
                            "by_account": {
                                "terms": {"field": "account_id", "size": 8},
                                "aggs": {"value": {"sum": {"field": "amount"}}},
                            }
                        },
                    },
                },
            },
        )
    except Exception as exc:  # pragma: no cover
        return {"error": str(exc)}

    aggs = deals_resp.get("aggregations", {})
    buckets = {bucket["key"]: bucket for bucket in aggs.get("by_stage", {}).get("buckets", [])}

    by_stage: List[Dict[str, Any]] = []
    open_value = 0.0
    weighted = 0.0
    open_count = 0
    for stage in DEAL_STAGES:
        bucket = buckets.get(stage)
        count = int(bucket["doc_count"]) if bucket else 0
        value = float(bucket["value"]["value"] or 0.0) if bucket else 0.0
        stage_weighted = float(bucket["weighted"]["value"] or 0.0) if bucket else 0.0
        if stage in OPEN_STAGES:
            open_value += value
            weighted += stage_weighted
            open_count += count
        by_stage.append(
            {"stage": stage, "count": count, "value": round(value, 2), "weighted": round(stage_weighted, 2)}
        )
    by_stage.sort(key=lambda item: stage_index.get(item["stage"], 99))

    won = buckets.get("ganho", {})
    lost = buckets.get("perdido", {})
    won_count = int(won.get("doc_count", 0)) if won else 0
    lost_count = int(lost.get("doc_count", 0)) if lost else 0
    won_value = float(won.get("value", {}).get("value") or 0.0) if won else 0.0
    decided = won_count + lost_count

    forecast: List[Dict[str, Any]] = []
    for bucket in aggs.get("open_by_month", {}).get("by_month", {}).get("buckets", []):
        stamp = str(bucket.get("key_as_string") or "")[:10]
        if not stamp:
            continue
        forecast.append(
            {
                "month": stamp[:7],
                "count": int(bucket["doc_count"]),
                "value": round(float(bucket["value"]["value"] or 0.0), 2),
                "weighted": round(float(bucket["weighted"]["value"] or 0.0), 2),
            }
        )
    forecast = [item for item in forecast if item["count"] > 0 and item["month"] <= horizon.strftime("%Y-%m")]

    top_accounts = [
        {
            "account_id": bucket["key"],
            "name": accounts_map.get(bucket["key"]) or "Conta removida",
            "count": int(bucket["doc_count"]),
            "value": round(float(bucket["value"]["value"] or 0.0), 2),
        }
        for bucket in aggs.get("top_accounts", {}).get("by_account", {}).get("buckets", [])
    ]

    today = now.date().isoformat()
    upcoming_filter = {"done": False}
    activities = list_records(
        ACTIVITY, owner, filters=upcoming_filter, size=200, sort_by="due_at", sort_order="asc"
    ).get("items", [])
    overdue = [item for item in activities if (item.get("due_at") or "")[:10] and str(item["due_at"])[:10] < today]
    week_limit = (now + timedelta(days=7)).date().isoformat()
    next_week = [
        item
        for item in activities
        if today <= (str(item.get("due_at") or "")[:10] or "") <= week_limit
    ]

    return {
        "generated_at": _now(),
        "totals": {
            "accounts": _count(client, ACCOUNT, owner),
            "contacts": _count(client, CONTACT, owner),
            "deals_open": open_count,
            "deals_won": won_count,
            "deals_lost": lost_count,
            "activities_open": _count(client, ACTIVITY, owner, {"done": False}),
        },
        "pipeline": {
            "open_value": round(open_value, 2),
            "weighted_value": round(weighted, 2),
            "average_deal": round(open_value / open_count, 2) if open_count else 0.0,
            "win_rate": round(won_count / decided * 100.0, 1) if decided else 0.0,
            "won_value_12m": round(won_value, 2),
        },
        "by_stage": by_stage,
        "forecast": forecast,
        "top_accounts": top_accounts,
        "agenda": {
            "overdue": overdue[:20],
            "overdue_count": len(overdue),
            "next_7_days": next_week[:20],
            "next_7_days_count": len(next_week),
            "upcoming": [item for item in activities if item not in overdue][:20],
        },
        "recent_activity": _recent_activity(client, owner, last_year),
    }


def _recent_activity(client: Any, owner: Dict[str, Any], since: str) -> List[Dict[str, Any]]:
    """Últimos registos criados/alterados, para o feed do dashboard."""
    try:
        resp = client.search(
            index=CRM_INDEX,
            body={
                "query": {
                    "bool": {
                        "filter": [*_owner_filters(owner)],
                        "must": [{"range": {"updated_at": {"gte": since}}}],
                    }
                },
                "size": 12,
                "sort": [{"updated_at": {"order": "desc"}}],
            },
        )
        return [_hit_to_record(hit) for hit in resp["hits"]["hits"]]
    except Exception:  # pragma: no cover
        return []


def account_timeline(account_id: str, owner: Dict[str, Any]) -> Dict[str, Any]:
    """Reúne a conta, os seus contactos, oportunidades e atividades."""
    account = get_record(ACCOUNT, account_id, owner)
    if account.get("error"):
        return account
    return {
        "account": account["item"],
        "contacts": list_records(CONTACT, owner, filters={"account_id": account_id}, size=200).get("items", []),
        "deals": list_records(DEAL, owner, filters={"account_id": account_id}, size=200).get("items", []),
        "activities": list_records(ACTIVITY, owner, filters={"account_id": account_id}, size=200).get("items", []),
    }


# ------------------------------------------------------- ligação ao EmpresasIQ
def _entity_snapshot(nif: str) -> Dict[str, Any]:
    """Resumo do EmpresasIQ a guardar na conta (contratos e valores importados)."""
    entity = get_entity_by_nif(nif)
    if entity.get("error"):
        return {}
    return {
        "nif": entity.get("nif") or nif,
        "name": entity.get("name"),
        "country": entity.get("country"),
        "contracts_count": entity.get("contracts_count"),
        "as_adjudicante_count": entity.get("as_adjudicante_count"),
        "as_adjudicatario_count": entity.get("as_adjudicatario_count"),
        "total_value": entity.get("total_value"),
        "as_adjudicante_value": entity.get("as_adjudicante_value"),
        "synced_at": _now(),
    }


def get_account_by_nif(nif: str, owner: Dict[str, Any]) -> Dict[str, Any]:
    """Procura, no âmbito do utilizador, a conta ligada a um NIF do EmpresasIQ."""
    result = list_records(ACCOUNT, owner, filters={"nif": nif}, size=1)
    items = result.get("items") or []
    return {"item": items[0]} if items else {"item": None}


def create_account_from_entity(nif: str, owner: Dict[str, Any], extra: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Cria (ou devolve) a conta correspondente a uma entidade do EmpresasIQ."""
    existing = get_account_by_nif(nif, owner).get("item")
    if existing:
        return {"ok": True, "created": False, "item": existing}

    entity = get_entity_by_nif(nif)
    if entity.get("error") and not entity.get("name"):
        return {"error": entity.get("error") or "Entidade não encontrada no cadastro"}

    payload: Dict[str, Any] = {
        "name": entity.get("name") or f"NIF {nif}",
        "nif": nif,
        "country": entity.get("country") or "",
        "status": "prospect",
        "source": "empresas_iq",
    }
    payload.update(extra or {})
    created = save_record(ACCOUNT, payload, owner)
    if created.get("error"):
        return created

    snapshot = _entity_snapshot(nif)
    if snapshot:
        record = created["item"]
        record["entity"] = snapshot
        client, error = _client_or_error()
        if not error:
            try:
                client.index(index=CRM_INDEX, id=_doc_id(ACCOUNT, record["id"]), document=record, refresh=True)
            except Exception as exc:  # pragma: no cover
                logger.warning("CRM: falha ao guardar snapshot da entidade %s: %s", nif, exc)
    return {"ok": True, "created": True, "item": created["item"]}


def refresh_account_entity(account_id: str, owner: Dict[str, Any]) -> Dict[str, Any]:
    """Recarrega o resumo do EmpresasIQ para uma conta ligada a um NIF."""
    account = get_record(ACCOUNT, account_id, owner)
    if account.get("error"):
        return account
    nif = (account["item"].get("nif") or "").strip()
    if not nif:
        return {"error": "A conta não tem NIF associado"}

    snapshot = _entity_snapshot(nif)
    if not snapshot:
        return {"error": "Entidade não encontrada no cadastro do EmpresasIQ"}

    record = dict(account["item"])
    record["entity"] = snapshot
    record["updated_at"] = _now()
    record.pop("doc_id", None)

    client, error = _client_or_error()
    if error:
        return dict(error)
    try:
        client.index(index=CRM_INDEX, id=_doc_id(ACCOUNT, account_id), document=record, refresh=True)
        return {"ok": True, "item": record}
    except Exception as exc:  # pragma: no cover
        return {"error": str(exc)}


def search_entity_candidates(q: str, size: int = 10) -> Dict[str, Any]:
    """Sugestões de entidades do EmpresasIQ para ligar a uma conta do CRM."""
    from api.elasticsearch_client import search_entities

    result = search_entities(q=q, size=size, sort_by="total_value", sort_order="desc")
    if result.get("error"):
        return {"error": result["error"], "items": []}
    return {
        "items": [
            {
                "nif": item.get("nif"),
                "name": item.get("name"),
                "country": item.get("country"),
                "contracts_count": item.get("contracts_count"),
                "total_value": item.get("total_value"),
            }
            for item in result.get("items", [])
        ]
    }
