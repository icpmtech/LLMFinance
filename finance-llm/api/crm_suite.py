"""Motor da arquitetura de CRM do IQ OS.

Uma só peça de software serve os **24 módulos** do CRM definidos em
`api.crm_registry`: a lista, a ficha, os filtros, as ações, as estatísticas e a
auditoria são todas genéricas e derivam do registo. Acrescentar um módulo ou um
campo é acrescentar uma linha ao registo — não há código por módulo.

Três camadas:

1. **Dados** (`finance_crm`) — os registos de negócio, distinguidos pelo campo
   `kind`. Todos levam a marca da organização (`org_area`, `org_department`,
   `org_team`) e do dono (`owner_id`), para que o âmbito de visibilidade do
   perfil seja aplicado no Elasticsearch e não no cliente.
2. **Acesso** (`finance_crm_rbac`) — atribuições de cada utilizador
   (perfil/área/departamento/equipa), equipas, perfis personalizados e o registo
   de auditoria imutável.
3. **Inteligência** — geração de perceções (`ai-insight`) a partir de regras
   sobre os dados reais e um assistente que responde com factos do CRM
   (`ai-interaction`), com ou sem modelo de linguagem configurado.

Regra de ouro: o perfil do utilizador decide o que se pode ler, criar, alterar e
apagar **e** qual o âmbito (próprio, equipa, departamento, área ou organização).
"""
from __future__ import annotations

import logging
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

from api.elasticsearch_client import (
    CRM_INDEX,
    CRM_RBAC_INDEX,
    ensure_indices,
    get_es_client,
)
from api import crm_registry as registry

logger = logging.getLogger(__name__)

MAX_SIZE = 500
DEFAULT_SIZE = 100

ACTIONS = registry.ACTION_IDS
SCOPES = tuple(item["id"] for item in registry.SCOPES)

# Slugs que vivem no índice de administração (não em `finance_crm`).
RBAC_SLUGS = registry.RBAC_SLUGS


# ------------------------------------------------------------------ infraestrutura
def _now() -> str:
    """Instante atual em ISO-8601 UTC (formato aceite pelo Elasticsearch)."""
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _client() -> Optional[Any]:
    client = get_es_client()
    if not client:
        return None
    try:
        ensure_indices(client)
    except Exception as exc:  # pragma: no cover - depende do Elasticsearch
        logger.warning("CRM: não foi possível garantir os índices: %s", exc)
    return client


def index_for(module: registry.Module) -> str:
    """Índice onde vive um módulo (negócio ou administração)."""
    return CRM_RBAC_INDEX if module.slug in RBAC_SLUGS else CRM_INDEX


def new_id(module: registry.Module) -> str:
    return f"{module.id_prefix}_{uuid.uuid4().hex[:12]}"


def doc_id(module: registry.Module, record_id: str) -> str:
    if module.slug == "users":
        return f"member:{record_id}"
    return f"{module.kind}:{record_id}"


# --------------------------------------------------------------------- coerção
def _as_float(value: Any) -> Optional[float]:
    if value is None or value == "":
        return None
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return float(value)
    try:
        text = str(value).replace(" ", "").replace("€", "").replace("%", "")
        if "," in text and "." in text:
            text = text.replace(".", "") if text.rfind(",") > text.rfind(".") else text.replace(",", "")
        return float(text.replace(",", "."))
    except (TypeError, ValueError):
        return None


def _as_int(value: Any) -> Optional[int]:
    if isinstance(value, bool):
        return int(value)
    number = _as_float(value)
    return None if number is None else int(number)


def _as_bool(value: Any) -> Optional[bool]:
    if isinstance(value, bool):
        return value
    if value is None or value == "":
        return None
    if isinstance(value, (int, float)):
        return bool(value)
    return str(value).strip().lower() in {"1", "true", "sim", "yes", "on", "verdadeiro"}


def _as_list(value: Any) -> List[str]:
    if value is None or value == "":
        return []
    if isinstance(value, str):
        chunks: Iterable[Any] = value.split(",")
    elif isinstance(value, (list, tuple, set)):
        chunks = value
    else:
        return []
    seen: List[str] = []
    for chunk in chunks:
        text = str(chunk).strip()
        if text and text not in seen:
            seen.append(text)
    return seen[:64]


def _as_text(value: Any, limit: int = 20000) -> Optional[str]:
    if value is None:
        return None
    text = str(value).strip()
    return text[:limit]


def normalize(module: registry.Module, payload: Dict[str, Any]) -> Dict[str, Any]:
    """Filtra e converte os campos enviados para os campos declarados no módulo."""
    clean: Dict[str, Any] = {}
    for spec in module.writable_fields:
        if spec.key not in payload:
            continue
        value = payload[spec.key]
        if spec.type == "bool":
            clean[spec.key] = _as_bool(value)
        elif spec.type in ("multiselect",):
            clean[spec.key] = _as_list(value)
        elif spec.type in ("int",):
            clean[spec.key] = _as_int(value)
        elif spec.type in ("number", "percent"):
            clean[spec.key] = _as_float(value)
        elif spec.type == "json":
            clean[spec.key] = value if isinstance(value, (dict, list)) else None
        else:
            clean[spec.key] = _as_text(value)
    return clean


def _percent(part: Any, whole: Any) -> Optional[float]:
    top = _as_float(part)
    bottom = _as_float(whole)
    if top is None or not bottom:
        return None
    return round(top / bottom * 100.0, 2)


def apply_derived(module: registry.Module, doc: Dict[str, Any]) -> Dict[str, Any]:
    """Calcula os campos derivados do módulo (totais, margens, taxas, estados)."""
    slug = module.slug

    if slug == "opportunities":
        amount = _as_float(doc.get("amount")) or 0.0
        probability = _as_int(doc.get("probability"))
        probability = 20 if probability is None else max(0, min(100, probability))
        doc["probability"] = probability
        doc["weighted_amount"] = round(amount * probability / 100.0, 2)
    elif slug == "orders":
        subtotal = _as_float(doc.get("subtotal")) or 0.0
        discount = _as_float(doc.get("discount")) or 0.0
        tax = _as_float(doc.get("tax_rate")) or 0.0
        doc["total"] = round(subtotal * (1 - discount / 100.0) * (1 + tax / 100.0), 2)
    elif slug == "quotes":
        lines = doc.get("lines") if isinstance(doc.get("lines"), list) else []
        subtotal = 0.0
        for line in lines:
            if not isinstance(line, dict):
                continue
            subtotal += (_as_float(line.get("quantity")) or 0.0) * (_as_float(line.get("unit_price")) or 0.0)
        discount = _as_float(doc.get("discount")) or 0.0
        tax = _as_float(doc.get("tax_rate")) or 0.0
        doc["subtotal"] = round(subtotal, 2)
        doc["total"] = round(subtotal * (1 - discount / 100.0) * (1 + tax / 100.0), 2)
    elif slug == "products":
        price = _as_float(doc.get("price"))
        cost = _as_float(doc.get("cost"))
        if price is not None and cost is not None:
            doc["margin"] = round(price - cost, 2)
            doc["margin_pct"] = _percent(price - cost, price)
    elif slug == "forecasts":
        target = _as_float(doc.get("target")) or 0.0
        won = _as_float(doc.get("won")) or 0.0
        doc["attainment_pct"] = _percent(won, target)
        doc["gap"] = round(target - won, 2) if target else None
    elif slug == "campaigns":
        cost = _as_float(doc.get("actual_cost"))
        budget = _as_float(doc.get("budget"))
        revenue = _as_float(doc.get("won_revenue"))
        leads = _as_int(doc.get("leads_generated"))
        responses = _as_int(doc.get("responses"))
        target_size = _as_int(doc.get("target_size"))
        doc["roi"] = _percent((revenue or 0.0) - cost, cost) if cost else None
        doc["cost_per_lead"] = round(cost / leads, 2) if cost and leads else None
        doc["response_rate"] = _percent(responses, target_size)
    elif slug == "marketing-activities":
        sent = _as_int(doc.get("sent"))
        doc["open_rate"] = _percent(doc.get("opened"), sent)
        doc["ctr"] = _percent(doc.get("clicked"), sent)
        doc["conversion_rate"] = _percent(doc.get("converted"), sent)
    elif slug == "marketing-journeys":
        enrolled = _as_int(doc.get("enrolled"))
        doc["completion_rate"] = _percent(doc.get("completed"), enrolled)
        doc["conversion_rate"] = _percent(doc.get("converted"), enrolled)
    elif slug == "events":
        start = doc.get("start_at")
        end = doc.get("end_at")
        if start and end:
            try:
                start_at = datetime.fromisoformat(str(start).replace("Z", "+00:00"))
                end_at = datetime.fromisoformat(str(end).replace("+00:00", "Z").replace("Z", "+00:00"))
                doc["duration_minutes"] = max(0, int((end_at - start_at).total_seconds() // 60))
            except (TypeError, ValueError):
                doc["duration_minutes"] = None
    elif slug == "leads":
        if doc.get("score") in (None, ""):
            score = 30
            score += {"quente": 40, "morna": 20, "fria": 5}.get(str(doc.get("rating") or ""), 10)
            if _as_bool(doc.get("has_authority")):
                score += 15
            if _as_float(doc.get("budget")):
                score += 10
            score += {"imediato": 15, "3-meses": 10, "6-meses": 5}.get(str(doc.get("timeline") or ""), 0)
            doc["score"] = max(0, min(100, score))

    # Fecho automático nos módulos com um campo de estado "final".
    if module.closed_field and "closed_at" in module.field_map:
        closed = str(doc.get(module.closed_field) or "") in module.closed_values
        if closed and not doc.get("closed_at"):
            doc["closed_at"] = _now()
        if not closed:
            doc["closed_at"] = None
    return doc


# ---------------------------------------------------------------------- RBAC
_MEMBER_CACHE: Dict[str, Any] = {"synced_at": None}
SYNC_INTERVAL_SECONDS = 60


def default_assignment(user: Any) -> Dict[str, Any]:
    """Atribuição inicial de um utilizador sem perfil de CRM definido."""
    auth_role = str(getattr(user, "role", None) or "member")
    key = "admin" if auth_role == "admin" else registry.DEFAULT_ROLE_KEY
    definition = registry.ROLE_BY_KEY.get(key) or registry.ROLE_BY_KEY[registry.DEFAULT_ROLE_KEY]
    return {
        "user_id": str(getattr(user, "id", "") or getattr(user, "email", "")),
        "email": str(getattr(user, "email", "") or ""),
        "name": str(getattr(user, "name", "") or ""),
        "role": definition.key,
        "area": definition.area,
        "department": definition.department,
        "team_id": "",
        "team": "",
        "job_title": str(getattr(user, "title", "") or ""),
        "phone": str(getattr(user, "phone", "") or ""),
        "quota": None,
        "status": "ativo",
        "last_login_at": getattr(user, "last_login_at", None),
        "builtin_scope": auth_role,
        "created_at": _now(),
        "updated_at": _now(),
        "updated_by": "sistema",
    }


def get_assignment(user: Any) -> Dict[str, Any]:
    """Atribuição de CRM do utilizador (cria a predefinição se não existir)."""
    user_id = str(getattr(user, "id", "") or getattr(user, "email", "") or "")
    client = _client()
    if not client or not user_id:
        return default_assignment(user)
    try:
        if client.exists(index=CRM_RBAC_INDEX, id=doc_id(registry.MODULE_BY_SLUG["users"], user_id)):
            source = client.get(index=CRM_RBAC_INDEX, id=doc_id(registry.MODULE_BY_SLUG["users"], user_id))["_source"]
            document = dict(source)
            document["user_id"] = user_id
            return document
    except Exception as exc:  # pragma: no cover
        logger.debug("CRM: atribuição de %s não lida: %s", user_id, exc)

    document = default_assignment(user)
    try:
        client.index(
            index=CRM_RBAC_INDEX,
            id=doc_id(registry.MODULE_BY_SLUG["users"], user_id),
            document={**document, "kind": "crm_user", "id": user_id},
            refresh=True,
        )
    except Exception as exc:  # pragma: no cover
        logger.debug("CRM: atribuição de %s não gravada: %s", user_id, exc)
    return document


def sync_members(force: bool = False) -> int:
    """Garante que todos os utilizadores da plataforma têm atribuição de CRM."""
    stamp = _MEMBER_CACHE.get("synced_at")
    if not force and stamp and (datetime.now(timezone.utc) - stamp).total_seconds() < SYNC_INTERVAL_SECONDS:
        return 0
    _MEMBER_CACHE["synced_at"] = datetime.now(timezone.utc)

    from api import auth_service

    client = _client()
    if not client:
        return 0
    created = 0
    for user in auth_service.list_users(limit=1000):
        user_id = str(user.get("id") or user.get("email") or "")
        if not user_id:
            continue
        try:
            key = doc_id(registry.MODULE_BY_SLUG["users"], user_id)
            if client.exists(index=CRM_RBAC_INDEX, id=key):
                continue
            document = default_assignment(_SimpleUser(user))
            document["last_login_at"] = user.get("last_login_at")
            client.index(
                index=CRM_RBAC_INDEX,
                id=key,
                document={**document, "kind": "crm_user", "id": user_id},
                refresh=True,
            )
            created += 1
        except Exception as exc:  # pragma: no cover
            logger.debug("CRM: membro %s não sincronizado: %s", user_id, exc)
    return created


class _SimpleUser:
    """Adaptador de um dicionário de utilizador ao protocolo esperado."""

    def __init__(self, data: Dict[str, Any]):
        self.id = data.get("id")
        self.email = data.get("email")
        self.name = data.get("name")
        self.role = data.get("role")
        self.title = data.get("title")
        self.phone = data.get("phone")
        self.last_login_at = data.get("last_login_at")


def _rbac_record_by_id(record_id: str) -> Optional[Dict[str, Any]]:
    client = _client()
    if not client:
        return None
    try:
        if client.exists(index=CRM_RBAC_INDEX, id=record_id):
            return dict(client.get(index=CRM_RBAC_INDEX, id=record_id)["_source"])
    except Exception as exc:  # pragma: no cover
        logger.debug("CRM: registo %s não lido: %s", record_id, exc)
    return None


def effective_roles() -> Dict[str, Dict[str, Any]]:
    """Catálogo de perfis: os de sistema substituídos/acrescentados pelos próprios."""
    catalog: Dict[str, Dict[str, Any]] = {role.key: role.to_public() for role in registry.ROLES}
    client = _client()
    if not client:
        return catalog
    try:
        resp = client.search(
            index=CRM_RBAC_INDEX,
            body={"query": {"term": {"kind": "crm_role"}}, "size": 200},
        )
        for hit in resp["hits"]["hits"]:
            source = dict(hit["_source"])
            key = str(source.get("key") or source.get("id") or "").strip()
            if not key:
                continue
            builtin = key in catalog
            catalog[key] = {
                "key": key,
                "label": source.get("label") or key,
                "area": source.get("area") or "",
                "department": source.get("department") or "",
                "scope": source.get("scope") or "own",
                "modules": _as_list(source.get("modules")),
                "actions": _as_list(source.get("actions")),
                "rank": _as_int(source.get("rank")) or (catalog[key]["rank"] if builtin else 50),
                "builtin": builtin,
                "description": source.get("description") or "",
            }
    except Exception as exc:  # pragma: no cover
        logger.debug("CRM: perfis personalizados não lidos: %s", exc)
    return catalog


def permissions(assignment: Dict[str, Any], *, auth_role: str = "") -> Dict[str, Any]:
    """Resolve o que o utilizador pode fazer, a partir da sua atribuição."""
    catalog = effective_roles()
    key = str(assignment.get("role") or registry.DEFAULT_ROLE_KEY).strip()
    definition = catalog.get(key)
    if auth_role == "admin":
        definition = catalog.get("admin")
        key = "admin"
    if not definition:
        definition = catalog.get(registry.DEFAULT_ROLE_KEY) or {
            "key": registry.DEFAULT_ROLE_KEY,
            "label": "Comercial",
            "area": "comercial",
            "department": "vendas",
            "scope": "own",
            "modules": ["accounts", "contacts"],
            "actions": ["read"],
            "rank": 9,
        }
        key = definition["key"]

    modules = list(definition.get("modules") or [])
    if "*" in modules:
        modules = list(registry.ALL_MODULES)
    actions = list(definition.get("actions") or [])
    if "*" in actions:
        actions = list(ACTIONS)

    area = str(assignment.get("area") or definition.get("area") or "")
    department = str(assignment.get("department") or definition.get("department") or "")
    scope = str(definition.get("scope") or "own")

    return {
        "user_id": str(assignment.get("user_id") or ""),
        "email": str(assignment.get("email") or ""),
        "name": str(assignment.get("name") or ""),
        "role": key,
        "role_label": definition.get("label") or key,
        "area": area,
        "department": department,
        "team_id": str(assignment.get("team_id") or ""),
        "team": str(assignment.get("team") or ""),
        "job_title": str(assignment.get("job_title") or ""),
        "quota": assignment.get("quota"),
        "status": str(assignment.get("status") or "ativo"),
        "scope": scope,
        "modules": modules,
        "actions": actions,
        "is_admin": key == "admin",
        "see_all": scope == "all" or key == "admin",
        "admin_only_modules": [slug for slug in registry.ALL_MODULES if registry.MODULE_BY_SLUG[slug].admin_only],
    }


def can(perm: Dict[str, Any], slug: str, action: str) -> bool:
    """Decide se o perfil pode executar uma ação num módulo."""
    module = registry.MODULE_BY_SLUG.get(slug)
    if module is None:
        return False
    if perm.get("is_admin"):
        return True
    if slug not in (perm.get("modules") or []):
        return False
    actions = perm.get("actions") or []
    if action not in actions:
        return False
    if module.admin_only and "manage" not in actions:
        return False
    if module.read_only and action in ("create", "update", "delete"):
        return False
    if slug == "users" and action in ("create", "delete"):
        # Os utilizadores vêm da autenticação; aqui só se ajusta a atribuição.
        return False
    return True


def can_read(perm: Dict[str, Any], slug: str) -> bool:
    return can(perm, slug, "read")


def visible_modules(perm: Dict[str, Any]) -> List[str]:
    return [slug for slug in registry.ALL_MODULES if can_read(perm, slug)]


def scope_clauses(perm: Dict[str, Any], module: Optional[registry.Module] = None) -> List[Dict[str, Any]]:
    """Cláusulas do Elasticsearch que limitam a visibilidade ao âmbito do perfil."""
    scope = str(perm.get("scope") or "own")
    if perm.get("is_admin") or scope == "all":
        return []
    user_id = perm.get("user_id") or ""
    should: List[Dict[str, Any]] = [{"term": {"owner_id": user_id}}]
    if scope in ("team", "department", "area"):
        if perm.get("team_id"):
            should.append({"term": {"org_team": perm["team_id"]}})
        if perm.get("department"):
            should.append({"term": {"org_department": perm["department"]}})
    if scope == "area" and perm.get("area"):
        should.append({"term": {"org_area": perm["area"]}})
    return [{"bool": {"should": should, "minimum_should_match": 1}}]


def rbac_scope_clauses(perm: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Âmbito para o módulo de utilizadores (documentos de atribuição)."""
    scope = str(perm.get("scope") or "own")
    if perm.get("is_admin") or scope == "all":
        return []
    user_id = perm.get("user_id") or ""
    should: List[Dict[str, Any]] = [{"term": {"user_id": user_id}}]
    if scope in ("team", "department", "area"):
        if perm.get("team_id"):
            should.append({"term": {"team_id": perm["team_id"]}})
        if perm.get("department"):
            should.append({"term": {"department": perm["department"]}})
    if scope == "area" and perm.get("area"):
        should.append({"term": {"area": perm["area"]}})
    return [{"bool": {"should": should, "minimum_should_match": 1}}]


# ---------------------------------------------------------------- auditoria
def _audit_document(
    *,
    action: str,
    module: str,
    perm: Dict[str, Any],
    record_id: str = "",
    record_label: str = "",
    summary: str = "",
    changes: Optional[Sequence[str]] = None,
    before: Optional[Dict[str, Any]] = None,
    after: Optional[Dict[str, Any]] = None,
    ip: str = "",
    user_agent: str = "",
) -> Dict[str, Any]:
    record_id_value = f"aud_{uuid.uuid4().hex[:12]}"
    return {
        "kind": "crm_audit",
        "id": record_id_value,
        "at": _now(),
        "actor_id": perm.get("user_id") or "",
        "actor_email": perm.get("email") or "",
        "action": action,
        "module": module,
        "record_id": record_id or "",
        "record_label": record_label[:512],
        "summary": summary[:2000],
        "changes": list(changes or []),
        "area": perm.get("area") or "",
        "department": perm.get("department") or "",
        "before": before or None,
        "after": after or None,
        "ip": ip,
        "user_agent": user_agent[:512],
        "created_at": _now(),
    }


def audit(**kwargs: Any) -> None:
    """Escreve um registo de auditoria (nunca lança)."""
    client = _client()
    if not client:
        return
    try:
        document = _audit_document(**kwargs)
        client.index(index=CRM_RBAC_INDEX, id=doc_id(registry.MODULE_BY_SLUG["audit"], document["id"]), document=document, refresh=True)
    except Exception as exc:  # pragma: no cover
        logger.debug("CRM: auditoria não gravada: %s", exc)


# ------------------------------------------------------------------ consultas
_TEXT_TYPES = ("text", "textarea", "email", "phone", "url")


def _search_fields(module: registry.Module) -> List[str]:
    fields: List[str] = []
    for spec in module.fields:
        if not spec.searchable:
            continue
        boost = spec.search or 1
        fields.append(f"{spec.key}^{boost + 1}" if boost > 1 else spec.key)
    return fields or ["id"]


def _build_query(
    module: registry.Module,
    perm: Dict[str, Any],
    *,
    q: Optional[str] = None,
    filters: Optional[Dict[str, Any]] = None,
    ids: Optional[Sequence[str]] = None,
    extra: Optional[Sequence[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    where: List[Dict[str, Any]] = [{"term": {"kind": module.kind}}]
    if module.slug in RBAC_SLUGS:
        where.extend(rbac_scope_clauses(perm))
    else:
        where.extend(scope_clauses(perm, module))
    where.extend(extra or [])
    if ids:
        where.append({"terms": {"id": [str(item) for item in ids]}})

    allowed = {spec.key: spec for spec in module.filter_fields}
    for key, value in (filters or {}).items():
        spec = allowed.get(key)
        if spec is None or value in (None, "", []):
            continue
        if spec.type == "bool":
            converted = _as_bool(value)
            if converted is not None:
                where.append({"term": {spec.key: converted}})
        elif spec.type in ("multiselect",):
            where.append({"terms": {spec.key: _as_list(value)}})
        else:
            where.append({"term": {spec.key: value}})

    body: Dict[str, Any] = {"bool": {"filter": where}}
    if q:
        body["bool"]["must"] = [
            {
                "multi_match": {
                    "query": q,
                    "fields": _search_fields(module),
                    "operator": "and",
                    "fuzziness": "AUTO",
                }
            }
        ]
    return body


def _sort_for(
    module: registry.Module, sort_by: Optional[str], sort_order: Optional[str]
) -> List[Dict[str, Any]]:
    spec = module.field_map.get(sort_by or "")
    order = "desc" if (sort_order or "desc").lower() != "asc" else "asc"
    if spec is not None and spec.sortable:
        entry: Dict[str, Any] = {"order": order}
        if spec.type in ("date", "datetime"):
            entry["missing"] = "_last"
        return [{spec.sort_field: entry}, {"updated_at": {"order": "desc", "missing": "_last"}}]
    if module.default_sort:
        return [
            {field: {"order": direction, "missing": "_last"}} for field, direction in module.default_sort
        ]
    return [{"updated_at": {"order": "desc", "missing": "_last"}}]


def _record(hit: Dict[str, Any], module: registry.Module) -> Dict[str, Any]:
    source = dict(hit.get("_source") or {})
    raw_id = str(hit.get("_id") or "")
    record_id = source.get("id") or (raw_id.split(":", 1)[1] if ":" in raw_id else raw_id)
    source["id"] = record_id
    source["doc_id"] = raw_id
    source["module"] = module.slug
    source["label"] = module.label_of(source)
    return source


def list_module(
    module: registry.Module,
    perm: Dict[str, Any],
    *,
    q: Optional[str] = None,
    filters: Optional[Dict[str, Any]] = None,
    size: int = DEFAULT_SIZE,
    from_: int = 0,
    sort_by: Optional[str] = None,
    sort_order: Optional[str] = None,
    ids: Optional[Sequence[str]] = None,
) -> Dict[str, Any]:
    """Lista/pesquisa registos de um módulo, dentro do âmbito do utilizador."""
    client = _client()
    if not client:
        return {"error": "Elasticsearch indisponível", "items": [], "total": 0}
    if module.slug == "users":
        sync_members()
    try:
        resp = client.search(
            index=index_for(module),
            body={
                "query": _build_query(module, perm, q=q, filters=filters, ids=ids),
                "from": max(0, from_),
                "size": max(1, min(MAX_SIZE, size)),
                "sort": _sort_for(module, sort_by, sort_order),
                "track_total_hits": True,
            },
        )
    except Exception as exc:  # pragma: no cover - depende do Elasticsearch
        logger.warning("CRM: falha ao listar %s: %s", module.slug, exc)
        return {"error": str(exc), "items": [], "total": 0}

    hits = resp["hits"]
    return {
        "module": module.slug,
        "kind": module.kind,
        "total": hits["total"]["value"],
        "from": from_,
        "size": size,
        "items": [_record(hit, module) for hit in hits["hits"]],
    }


def get_module(module: registry.Module, record_id: str, perm: Dict[str, Any]) -> Dict[str, Any]:
    """Devolve um registo (verificando o âmbito do utilizador)."""
    client = _client()
    if not client:
        return {"error": "Elasticsearch indisponível"}
    try:
        if not client.exists(index=index_for(module), id=doc_id(module, record_id)):
            return {"error": "Registo não encontrado"}
        hit = client.get(index=index_for(module), id=doc_id(module, record_id))
    except Exception as exc:  # pragma: no cover
        return {"error": str(exc)}

    record = _record(hit, module)
    if module.slug not in RBAC_SLUGS and scope_clauses(perm, module):
        owner = record.get("owner_id")
        team = record.get("org_team")
        department = record.get("org_department")
        area = record.get("org_area")
        scope = perm.get("scope")
        allowed = (
            owner == perm.get("user_id")
            or (scope in ("team", "department", "area") and perm.get("team_id") and team == perm.get("team_id"))
            or (
                scope in ("team", "department", "area")
                and perm.get("department")
                and department == perm.get("department")
            )
            or (scope == "area" and perm.get("area") and area == perm.get("area"))
        )
        if not allowed:
            return {"error": "Sem permissão para este registo"}
    return {"item": record}


# -------------------------------------------------------------------- escrita
def _stamp(module: registry.Module, doc: Dict[str, Any], perm: Dict[str, Any], *, creating: bool) -> Dict[str, Any]:
    document = dict(doc)
    if creating:
        document["owner_id"] = document.get("owner_id") or perm.get("user_id") or ""
        document["owner_email"] = document.get("owner_email") or perm.get("email") or ""
        document["org_area"] = document.get("org_area") or perm.get("area") or ""
        document["org_department"] = document.get("org_department") or perm.get("department") or ""
        document["org_team"] = document.get("org_team") or perm.get("team_id") or ""
        document["assigned_to"] = document.get("assigned_to") or perm.get("user_id") or ""
        document["created_by"] = perm.get("email") or perm.get("user_id") or ""
        document["created_at"] = document.get("created_at") or _now()
    document["updated_by"] = perm.get("email") or perm.get("user_id") or ""
    document["updated_at"] = _now()
    # O dono e a marca da organização podem ser passados num pedido de "atribuição".
    if document.get("org_area") is None:
        document.pop("org_area", None)
    return document


def _changes(before: Dict[str, Any], after: Dict[str, Any]) -> List[str]:
    keys: List[str] = []
    for key, value in after.items():
        if key in ("updated_at", "updated_by", "doc_id", "label", "module"):
            continue
        if before.get(key) != value:
            keys.append(key)
    return keys[:40]


def save_module(
    module: registry.Module,
    payload: Dict[str, Any],
    perm: Dict[str, Any],
    record_id: Optional[str] = None,
    *,
    ip: str = "",
    user_agent: str = "",
) -> Dict[str, Any]:
    """Cria ou atualiza um registo de qualquer módulo."""
    client = _client()
    if not client:
        return {"error": "Elasticsearch indisponível"}
    if module.read_only:
        return {"error": f"O módulo {module.label} é só de leitura"}
    if module.slug == "users":
        return update_assignment(record_id or str(payload.get("id") or ""), payload, perm, ip=ip, user_agent=user_agent)

    fields = normalize(module, payload)
    if module.slug == "roles":
        # Um perfil é identificado pela chave: o registo é sempre `crm_role:<chave>`.
        fields.setdefault("key", record_id or payload.get("key"))
        key = str(fields.get("key") or "").strip()
        if not key:
            return {"error": "O perfil precisa de uma chave"}
        fields["key"] = key
        record_id = key

    existing: Optional[Dict[str, Any]] = None
    if record_id:
        found = get_module(module, record_id, perm)
        if found.get("error"):
            return found
        existing = found["item"]
    else:
        record_id = new_id(module)

    defaults = {key: value for key, value in module.defaults_map().items() if key not in fields}
    document: Dict[str, Any] = dict(existing or {})
    document.update(defaults)
    document.update(fields)
    document["id"] = record_id
    document["kind"] = module.kind

    if module.slug == "roles" and record_id in registry.ROLE_BY_KEY:
        # Um perfil de sistema pode ser afinado, mas nunca perder a chave.
        document["builtin"] = True

    for spec in module.fields:
        if spec.required and not document.get(spec.key) and not spec.computed:
            if spec.system:
                continue
            return {"error": f"O campo «{spec.label}» é obrigatório"}

    document = _stamp(module, document, perm, creating=existing is None)
    document = apply_derived(module, document)
    document.pop("doc_id", None)
    document.pop("label", None)
    document.pop("module", None)

    try:
        client.index(index=index_for(module), id=doc_id(module, record_id), document=document, refresh=True)
    except Exception as exc:  # pragma: no cover
        logger.warning("CRM: falha ao guardar %s/%s: %s", module.slug, record_id, exc)
        return {"error": str(exc)}

    if module.slug in ("roles", "teams"):
        _MEMBER_CACHE["synced_at"] = None  # força releitura do catálogo

    audit(
        action="create" if existing is None else "update",
        module=module.slug,
        perm=perm,
        record_id=record_id,
        record_label=module.label_of(document),
        summary=(
            f"{module.singular} {'criado' if existing is None else 'alterado'}: {module.label_of(document)}"
        ),
        changes=sorted(document.keys()) if existing is None else _changes(existing, document),
        before=existing,
        after=document,
        ip=ip,
        user_agent=user_agent,
    )
    document["label"] = module.label_of(document)
    document["module"] = module.slug
    return {"ok": True, "item": document}


def delete_module(
    module: registry.Module,
    record_id: str,
    perm: Dict[str, Any],
    *,
    ip: str = "",
    user_agent: str = "",
) -> Dict[str, Any]:
    """Apaga um registo. Numa conta, apaga em cascata os registos ligados."""
    client = _client()
    if not client:
        return {"error": "Elasticsearch indisponível"}
    if module.read_only:
        return {"error": f"O módulo {module.label} é só de leitura"}
    if module.slug == "users":
        return {"error": "Os utilizadores gerem-se na autenticação; aqui só se altera a atribuição"}
    if module.slug == "roles" and record_id in registry.ROLE_BY_KEY:
        # Um perfil de sistema pode ser reposto (elimina o ajuste), não apagado.
        try:
            client.delete(index=CRM_RBAC_INDEX, id=doc_id(module, record_id), refresh=True)
            audit(
                action="delete",
                module=module.slug,
                perm=perm,
                record_id=record_id,
                record_label=record_id,
                summary=f"Ajuste do perfil {record_id} reposto para o valor de sistema",
                ip=ip,
                user_agent=user_agent,
            )
            return {"ok": True, "deleted": 1, "reset": True}
        except Exception as exc:  # pragma: no cover
            return {"error": str(exc)}

    found = get_module(module, record_id, perm)
    if found.get("error"):
        return found
    record = found["item"]

    try:
        client.delete(index=index_for(module), id=doc_id(module, record_id), refresh=True)
    except Exception as exc:  # pragma: no cover
        return {"error": str(exc)}

    cascaded = _cascade_delete(client, module, record_id, perm)
    audit(
        action="delete",
        module=module.slug,
        perm=perm,
        record_id=record_id,
        record_label=module.label_of(record),
        summary=f"{module.singular} apagado: {module.label_of(record)}",
        before=record,
        ip=ip,
        user_agent=user_agent,
    )
    return {"ok": True, "deleted": 1, "cascaded": cascaded}


# Ligações onde apagar a origem arrasta os dependentes (campo → módulo).
_CASCADE: Dict[str, Tuple[Tuple[str, str], ...]] = {
    "accounts": (
        ("account_id", "contacts"),
        ("account_id", "opportunities"),
        ("account_id", "activities"),
        ("account_id", "cases"),
        ("account_id", "orders"),
        ("account_id", "contracts"),
        ("account_id", "quotes"),
        ("account_id", "documents"),
        ("account_id", "events"),
    ),
    "opportunities": (
        ("opportunity_id", "activities"),
        ("opportunity_id", "quotes"),
        ("opportunity_id", "documents"),
    ),
    "campaigns": (
        ("campaign_id", "campaign-members"),
        ("campaign_id", "marketing-activities"),
    ),
    "leads": (("lead_id", "campaign-members"),),
    "products": (("product_id", "cases"),),
}


def _cascade_delete(client: Any, module: registry.Module, record_id: str, perm: Dict[str, Any]) -> int:
    total = 0
    for field, target_slug in _CASCADE.get(module.slug, ()):
        target = registry.MODULE_BY_SLUG.get(target_slug)
        if target is None:
            continue
        body = _build_query(target, perm, filters={field: record_id})
        try:
            resp = client.delete_by_query(
                index=index_for(target), body={"query": body}, refresh=True, conflicts="proceed"
            )
            total += int(resp.get("deleted", 0))
        except Exception as exc:  # pragma: no cover
            logger.debug("CRM: cascata %s→%s falhou: %s", module.slug, target_slug, exc)
    return total


# ------------------------------------------------------- utilizadores (RBAC)
def update_assignment(
    user_id: str,
    payload: Dict[str, Any],
    perm: Dict[str, Any],
    *,
    ip: str = "",
    user_agent: str = "",
) -> Dict[str, Any]:
    """Ajusta o perfil/área/departamento/equipa de um utilizador do CRM."""
    client = _client()
    if not client:
        return {"error": "Elasticsearch indisponível"}
    user_id = str(user_id or "").strip()
    if not user_id:
        return {"error": "Utilizador não indicado"}

    module = registry.MODULE_BY_SLUG["users"]
    key = doc_id(module, user_id)
    try:
        exists = client.exists(index=CRM_RBAC_INDEX, id=key)
        current = dict(client.get(index=CRM_RBAC_INDEX, id=key)["_source"]) if exists else {}
    except Exception as exc:  # pragma: no cover
        return {"error": str(exc)}
    if not current:
        sync_members()
        try:
            current = dict(client.get(index=CRM_RBAC_INDEX, id=key)["_source"])
        except Exception:
            return {"error": "Utilizador não encontrado"}

    fields = normalize(module, payload)
    catalogue = effective_roles()
    if "role" in fields and fields["role"] not in catalogue:
        return {"error": f"Perfil desconhecido: {fields['role']}"}
    definition = catalogue.get(fields.get("role") or current.get("role") or "")
    if definition and isinstance(definition, dict):
        # A área e o departamento seguem o perfil, a menos que sejam explícitos.
        if "area" not in fields:
            fields["area"] = current.get("area") or definition.get("area")
        if "department" not in fields:
            fields["department"] = current.get("department") or definition.get("department")

    team_id = fields.get("team_id", current.get("team_id"))
    team_name = current.get("team") or ""
    if team_id:
        team = _rbac_record_by_id(doc_id(registry.MODULE_BY_SLUG["teams"], str(team_id)))
        if team:
            team_name = team.get("name") or team_id
    elif "team_id" in fields:
        team_name = ""

    document = {
        **current,
        **fields,
        "team": team_name,
        "kind": "crm_user",
        "id": user_id,
        "user_id": user_id,
        "updated_at": _now(),
        "updated_by": perm.get("email") or perm.get("user_id") or "",
    }
    try:
        client.index(index=CRM_RBAC_INDEX, id=key, document=document, refresh=True)
    except Exception as exc:  # pragma: no cover
        return {"error": str(exc)}

    audit(
        action="assign",
        module="users",
        perm=perm,
        record_id=user_id,
        record_label=document.get("name") or document.get("email") or user_id,
        summary=(
            f"Atribuição de {document.get('name') or user_id}: perfil {document.get('role')}, "
            f"área {document.get('area')}, departamento {document.get('department')}"
        ),
        changes=_changes(current, document),
        before=current or None,
        after=document,
        ip=ip,
        user_agent=user_agent,
    )
    return {"ok": True, "item": {**document, "module": "users", "label": module.label_of(document)}}


# ----------------------------------------------------------------- estatística
def module_stats(module: registry.Module, perm: Dict[str, Any]) -> Dict[str, Any]:
    """Indicadores de um módulo: totais, distribuição por escolha, somas e evolução."""
    client = _client()
    if not client:
        return {"error": "Elasticsearch indisponível"}

    choice_fields = [spec for spec in module.fields if spec.type == "select" and not spec.system][:4]
    money_fields = [spec for spec in module.fields if spec.type in ("number", "int", "percent") and not spec.computed][:4]
    date_field = next((spec for spec in module.fields if spec.type in ("date", "datetime") and spec.column), None)
    if date_field is None:
        date_field = next((spec for spec in module.fields if spec.type in ("date", "datetime")), None)

    aggs: Dict[str, Any] = {"total_kind": {"value_count": {"field": "id"}}}
    for spec in choice_fields:
        aggs[f"by_{spec.key}"] = {"terms": {"field": spec.key, "size": 12}}
    for spec in money_fields:
        aggs[f"sum_{spec.key}"] = {"stats": {"field": spec.key}}
    if date_field is not None:
        aggs["timeline"] = {
            "date_histogram": {
                "field": date_field.key,
                "calendar_interval": "month",
                "min_doc_count": 0,
            }
        }

    query = _build_query(module, perm)
    try:
        resp = client.search(index=index_for(module), body={"query": query, "size": 0, "aggs": aggs})
    except Exception as exc:  # pragma: no cover
        return {"error": str(exc)}

    aggregations = resp.get("aggregations") or {}
    total = int(resp["hits"]["total"]["value"])

    groups: List[Dict[str, Any]] = []
    for spec in choice_fields:
        buckets = aggregations.get(f"by_{spec.key}", {}).get("buckets", [])
        options = {value: label for value, label in spec.options}
        groups.append(
            {
                "field": spec.key,
                "label": spec.label,
                "buckets": [
                    {
                        "key": bucket["key"],
                        "label": options.get(str(bucket["key"]), str(bucket["key"])),
                        "count": int(bucket["doc_count"]),
                    }
                    for bucket in buckets
                ],
            }
        )

    metrics: List[Dict[str, Any]] = []
    for spec in money_fields:
        stats = aggregations.get(f"sum_{spec.key}") or {}
        metrics.append(
            {
                "field": spec.key,
                "label": spec.label,
                "count": int(stats.get("count") or 0),
                "sum": round(float(stats.get("sum") or 0.0), 2),
                "avg": round(float(stats.get("avg") or 0.0), 2),
                "min": round(float(stats.get("min") or 0.0), 2),
                "max": round(float(stats.get("max") or 0.0), 2),
            }
        )

    timeline = [
        {"month": str(bucket.get("key_as_string") or "")[:7], "count": int(bucket["doc_count"])}
        for bucket in (aggregations.get("timeline") or {}).get("buckets", [])
        if bucket.get("key_as_string")
    ]
    timeline = [item for item in timeline if item["count"]][-12:]

    return {
        "module": module.slug,
        "label": module.label,
        "total": total,
        "groups": [group for group in groups if group["buckets"]],
        "metrics": metrics,
        "timeline": timeline,
    }


def reference_options(module: registry.Module, perm: Dict[str, Any], size: int = 300) -> Dict[str, Any]:
    """Mapa `id → etiqueta` para cada campo de referência do módulo."""
    result: Dict[str, Dict[str, str]] = {}
    for spec in module.fields:
        if spec.type != "reference" or not spec.reference:
            continue
        target = registry.MODULE_BY_SLUG.get(spec.reference)
        if target is None or not can_read(perm, target.slug):
            continue
        listed = list_module(target, perm, size=size)
        result[spec.key] = {
            str(item.get("id")): str(item.get("label") or item.get("id")) for item in listed.get("items", [])
        }
    return {"module": module.slug, "references": result}


# ---------------------------------------------------------------------- meta
def suite_meta(perm: Dict[str, Any]) -> Dict[str, Any]:
    """Metadados de toda a arquitetura, filtrados pelo perfil do utilizador."""
    modules = []
    for slug in registry.ALL_MODULES:
        module = registry.MODULE_BY_SLUG[slug]
        entry = module.to_public()
        entry["allowed"] = can_read(perm, slug)
        entry["permissions"] = {
            action: can(perm, slug, action) for action in ACTIONS
        }
        modules.append(entry)

    roles = [
        {
            "key": role["key"],
            "label": role["label"],
            "area": role["area"],
            "department": role["department"],
            "scope": role["scope"],
            "rank": role["rank"],
            "modules": role["modules"],
            "actions": role["actions"],
        }
        for role in effective_roles().values()
    ]
    roles.sort(key=lambda item: (item.get("rank") or 99, item["label"]))

    return {
        "groups": list(registry.GROUPS),
        "modules": modules,
        "areas": list(registry.AREAS),
        "departments": list(registry.DEPARTMENTS),
        "roles": roles,
        "actions": list(registry.ACTIONS),
        "scopes": list(registry.SCOPES),
        "me": perm,
        "visible_modules": visible_modules(perm),
        "visible_groups": [
            group["id"]
            for group in registry.GROUPS
            if any(
                can_read(perm, module.slug) for module in registry.MODULES if module.group == group["id"]
            )
        ],
        "generated_at": _now(),
    }


def overview(perm: Dict[str, Any]) -> Dict[str, Any]:
    """Painel geral do CRM: volume por módulo, pipeline, previsão e alertas."""
    client = _client()
    if not client:
        return {"error": "Elasticsearch indisponível"}

    counts: Dict[str, int] = {}
    for slug in visible_modules(perm):
        module = registry.MODULE_BY_SLUG[slug]
        if module.slug == "audit":
            continue
        try:
            counts[slug] = int(
                client.count(index=index_for(module), body={"query": _build_query(module, perm)})["count"]
            )
        except Exception:  # pragma: no cover
            counts[slug] = 0

    pipeline = module_stats(registry.MODULE_BY_SLUG["opportunities"], perm) if can_read(perm, "opportunities") else {}
    cases = module_stats(registry.MODULE_BY_SLUG["cases"], perm) if can_read(perm, "cases") else {}
    campaigns = module_stats(registry.MODULE_BY_SLUG["campaigns"], perm) if can_read(perm, "campaigns") else {}

    open_value = 0.0
    open_count = 0
    if pipeline:
        for group in pipeline.get("groups", []):
            if group["field"] != "stage":
                continue
            for bucket in group["buckets"]:
                if str(bucket["key"]) in ("ganho", "perdido"):
                    continue
                open_count += bucket["count"]
        for metric in pipeline.get("metrics", []):
            if metric["field"] == "amount":
                open_value = metric["sum"]

    return {
        "generated_at": _now(),
        "scope": perm.get("scope"),
        "counts": counts,
        "pipeline": {"open_count": open_count, "open_value": round(open_value, 2), "stats": pipeline},
        "cases": cases,
        "campaigns": campaigns,
        "insights": list_module(
            registry.MODULE_BY_SLUG["ai-insights"], perm, size=5, sort_by="generated_at", sort_order="desc"
        ).get("items", [])
        if can_read(perm, "ai-insights")
        else [],
        "audit": list_module(registry.MODULE_BY_SLUG["audit"], perm, size=8).get("items", [])
        if can_read(perm, "audit")
        else [],
    }


# ------------------------------------------------------------------------ IA
_SIGNATURES: Tuple[str, ...] = (
    "oportunidades-paradas",
    "fecho-em-atraso",
    "sem-proximo-passo",
    "contas-sem-contacto",
    "atividades-em-atraso",
    "casos-criticos-abertos",
    "leads-sem-seguimento",
    "previsao-abaixo-do-objetivo",
    "campanhas-sem-conversao",
)


def _insight_document(
    *,
    signature: str,
    title: str,
    insight_type: str,
    severity: str,
    summary: str,
    recommendation: str,
    evidence: Dict[str, Any],
    module: str = "",
    record_id: str = "",
    record_label: str = "",
    account_id: str = "",
    metric: str = "",
    value: Optional[float] = None,
    baseline: Optional[float] = None,
    confidence: int = 70,
) -> Dict[str, Any]:
    delta = None
    if value is not None and baseline:
        delta = round((value - baseline) / baseline * 100.0, 2)
    return {
        "signature": signature,
        "title": title,
        "insight_type": insight_type,
        "severity": severity,
        "status": "novo",
        "module": module,
        "record_id": record_id,
        "record_label": record_label,
        "account_id": account_id,
        "metric": metric,
        "value": value,
        "baseline": baseline,
        "delta_pct": delta,
        "confidence": confidence,
        "summary": summary,
        "recommendation": recommendation,
        "evidence": evidence,
        "model": "regras-crm/1",
        "generated_at": _now(),
    }


def generate_insights(perm: Dict[str, Any], *, limit: int = 40) -> Dict[str, Any]:
    """Analisa os dados reais do CRM e cria/atualiza perceções (`ai-insight`)."""
    client = _client()
    if not client:
        return {"error": "Elasticsearch indisponível"}
    if not can_read(perm, "ai-insights") or not can(perm, "ai-insights", "create"):
        return {"error": "Sem permissão para gerar perceções"}

    module = registry.MODULE_BY_SLUG["ai-insights"]
    now = datetime.now(timezone.utc)
    today = now.date().isoformat()
    stale_limit = (now - timedelta(days=21)).isoformat(timespec="seconds").replace("+00:00", "Z")
    inactive_limit = (now - timedelta(days=60)).isoformat(timespec="seconds").replace("+00:00", "Z")

    produced: List[Dict[str, Any]] = []

    # 1. Oportunidades abertas sem movimento.
    if can_read(perm, "opportunities"):
        stalled = list_module(
            registry.MODULE_BY_SLUG["opportunities"],
            perm,
            filters={"stage": None},
            size=limit,
            sort_by="updated_at",
            sort_order="asc",
        ).get("items", [])
        stalled = [
            item
            for item in stalled
            if str(item.get("stage")) not in ("ganho", "perdido")
            and str(item.get("updated_at") or "") < stale_limit
        ]
        if stalled:
            total = sum(float(item.get("amount") or 0) for item in stalled)
            produced.append(
                _insight_document(
                    signature="oportunidades-paradas",
                    title=f"{len(stalled)} oportunidades sem movimento há mais de 21 dias",
                    insight_type="risco",
                    severity="alta" if len(stalled) >= 5 else "media",
                    summary=(
                        f"Existem {len(stalled)} oportunidades abertas sem qualquer atualização desde "
                        f"{stale_limit[:10]}, num valor total de {total:,.2f} €. "
                        "Uma oportunidade sem contacto é a principal causa de perda por inação."
                    ),
                    recommendation=(
                        "Agendar atividade de seguimento nas oportunidades listadas e rever a fase "
                        "real de cada uma. Se não houver resposta em duas semanas, mover para «perdido» com motivo."
                    ),
                    evidence={
                        "limite": stale_limit[:10],
                        "valor_total": round(total, 2),
                        "oportunidades": [
                            {
                                "id": item.get("id"),
                                "titulo": item.get("title"),
                                "valor": item.get("amount"),
                                "fase": item.get("stage"),
                                "atualizado_em": str(item.get("updated_at") or "")[:10],
                            }
                            for item in stalled[:10]
                        ],
                    },
                    module="opportunities",
                    metric="oportunidades_sem_movimento",
                    value=float(len(stalled)),
                    confidence=85,
                )
            )

        overdue = [
            item
            for item in list_module(
                registry.MODULE_BY_SLUG["opportunities"],
                perm,
                size=MAX_SIZE,
                sort_by="expected_close_date",
                sort_order="asc",
            ).get("items", [])
            if str(item.get("stage")) not in ("ganho", "perdido")
            and str(item.get("expected_close_date") or "")[:10]
            and str(item["expected_close_date"])[:10] < today
        ]
        if overdue:
            produced.append(
                _insight_document(
                    signature="fecho-em-atraso",
                    title=f"{len(overdue)} oportunidades com fecho previsto já ultrapassado",
                    insight_type="previsao",
                    severity="media",
                    summary=(
                        f"{len(overdue)} oportunidades mantêm uma data de fecho anterior a {today}. "
                        "A previsão de tesouraria fica inflacionada enquanto as datas não forem corrigidas."
                    ),
                    recommendation=(
                        "Rever as datas de fecho com o responsável de cada oportunidade e atualizar o "
                        "campo «Fecho previsto», ou fechar as que já não estão ativas."
                    ),
                    evidence={
                        "data_de_hoje": today,
                        "oportunidades": [
                            {
                                "id": item.get("id"),
                                "titulo": item.get("title"),
                                "fecho_previsto": item.get("expected_close_date"),
                                "valor": item.get("amount"),
                            }
                            for item in overdue[:10]
                        ],
                    },
                    module="opportunities",
                    metric="oportunidades_com_fecho_em_atraso",
                    value=float(len(overdue)),
                    confidence=80,
                )
            )

    # 2. Atividades em atraso.
    if can_read(perm, "activities"):
        open_activities = list_module(
            registry.MODULE_BY_SLUG["activities"], perm, filters={"done": False}, size=MAX_SIZE, sort_by="due_at", sort_order="asc"
        ).get("items", [])
        late = [
            item
            for item in open_activities
            if str(item.get("due_at") or "")[:10] and str(item["due_at"])[:10] < today
        ]
        if late:
            produced.append(
                _insight_document(
                    signature="atividades-em-atraso",
                    title=f"{len(late)} atividades em atraso",
                    insight_type="risco",
                    severity="alta" if len(late) >= 10 else "baixa",
                    summary=(
                        f"Há {len(late)} atividades comerciais com prazo ultrapassado e ainda abertas "
                        f"(de {len(open_activities)} abertas). Cada atraso reduz a probabilidade de resposta do cliente."
                    ),
                    recommendation="Concluir, reagendar ou reatribuir as atividades em atraso durante a próxima revisão diária.",
                    evidence={
                        "atividades_abertas": len(open_activities),
                        "exemplos": [
                            {
                                "id": item.get("id"),
                                "assunto": item.get("subject"),
                                "prazo": item.get("due_at"),
                                "prioridade": item.get("priority"),
                            }
                            for item in late[:10]
                        ],
                    },
                    module="activities",
                    metric="atividades_em_atraso",
                    value=float(len(late)),
                    confidence=95,
                )
            )

    # 3. Contas sem contacto recente com oportunidades abertas.
    if can_read(perm, "accounts") and can_read(perm, "activities"):
        accounts = list_module(registry.MODULE_BY_SLUG["accounts"], perm, size=200).get("items", [])
        open_deals = [
            item
            for item in list_module(registry.MODULE_BY_SLUG["opportunities"], perm, size=MAX_SIZE).get("items", [])
            if str(item.get("stage")) not in ("ganho", "perdido")
        ]
        account_ids = {str(item.get("account_id")) for item in open_deals if item.get("account_id")}
        activities = list_module(registry.MODULE_BY_SLUG["activities"], perm, size=MAX_SIZE).get("items", [])
        last_activity: Dict[str, str] = {}
        for item in activities:
            account_id = str(item.get("account_id") or "")
            stamp = str(item.get("due_at") or item.get("updated_at") or "")
            if account_id and (account_id not in last_activity or stamp > last_activity[account_id]):
                last_activity[account_id] = stamp
        quiet = [
            item
            for item in accounts
            if str(item.get("id")) in account_ids
            and last_activity.get(str(item.get("id")), "") < inactive_limit
        ]
        if quiet:
            produced.append(
                _insight_document(
                    signature="contas-sem-contacto",
                    title=f"{len(quiet)} contas com oportunidades abertas sem contacto há mais de 60 dias",
                    insight_type="risco",
                    severity="alta",
                    summary=(
                        "Estas contas têm negócio em aberto mas não registam qualquer atividade recente. "
                        "É o padrão típico de oportunidades que morrem em silêncio."
                    ),
                    recommendation="Definir um plano de contacto para as contas listadas e registar a atividade no CRM.",
                    evidence={
                        "contas": [
                            {
                                "id": item.get("id"),
                                "nome": item.get("name"),
                                "ultima_atividade": last_activity.get(str(item.get("id")), "sem registo"),
                            }
                            for item in quiet[:10]
                        ]
                    },
                    module="accounts",
                    metric="contas_sem_contacto",
                    value=float(len(quiet)),
                    confidence=75,
                )
            )

    # 4. Casos críticos abertos fora do SLA.
    if can_read(perm, "cases"):
        cases = list_module(registry.MODULE_BY_SLUG["cases"], perm, size=MAX_SIZE).get("items", [])
        critical = [
            item
            for item in cases
            if str(item.get("status")) not in ("resolvido", "fechado", "cancelado")
            and str(item.get("priority")) in ("alta", "critica")
            and str(item.get("opened_at") or "")[:10]
            and (now.date() - datetime.fromisoformat(str(item["opened_at"])[:10]).date()).days >= 3
        ]
        if critical:
            produced.append(
                _insight_document(
                    signature="casos-criticos-abertos",
                    title=f"{len(critical)} casos de prioridade alta ou crítica abertos há 3 dias ou mais",
                    insight_type="risco",
                    severity="critica",
                    summary=(
                        "Casos de prioridade elevada sem resolução prolongada degradam a satisfação e "
                        "costumam preceder pedidos de indemnização ou churn."
                    ),
                    recommendation="Escalonar os casos listados e comunicar ao cliente uma data de resolução.",
                    evidence={
                        "casos": [
                            {
                                "id": item.get("id"),
                                "assunto": item.get("subject"),
                                "prioridade": item.get("priority"),
                                "aberto_em": item.get("opened_at"),
                            }
                            for item in critical[:10]
                        ]
                    },
                    module="cases",
                    metric="casos_criticos_abertos",
                    value=float(len(critical)),
                    confidence=85,
                )
            )

    # 5. Leads sem seguimento.
    if can_read(perm, "leads"):
        leads = list_module(registry.MODULE_BY_SLUG["leads"], perm, size=MAX_SIZE).get("items", [])
        pending = [
            item
            for item in leads
            if str(item.get("status")) in ("novo", "contactado")
            and str(item.get("created_at") or "")[:10]
            and (now.date() - datetime.fromisoformat(str(item["created_at"])[:10]).date()).days >= 7
        ]
        if pending:
            produced.append(
                _insight_document(
                    signature="leads-sem-seguimento",
                    title=f"{len(pending)} leads sem qualificação há mais de 7 dias",
                    insight_type="oportunidade",
                    severity="media",
                    summary=(
                        "Leads sem contacto na primeira semana perdem grande parte da probabilidade de conversão. "
                        f"Estão {len(pending)} neste estado."
                    ),
                    recommendation="Distribuir os leads por responsável e marcar a primeira chamada nas próximas 48 horas.",
                    evidence={
                        "leads": [
                            {
                                "id": item.get("id"),
                                "empresa": item.get("name"),
                                "origem": item.get("source"),
                                "criado_em": str(item.get("created_at") or "")[:10],
                                "pontuacao": item.get("score"),
                            }
                            for item in pending[:10]
                        ]
                    },
                    module="leads",
                    metric="leads_sem_qualificacao",
                    value=float(len(pending)),
                    confidence=70,
                )
            )

    # 6. Previsão abaixo do objetivo.
    if can_read(perm, "forecasts"):
        forecasts = list_module(
            registry.MODULE_BY_SLUG["forecasts"], perm, size=50, sort_by="year", sort_order="desc"
        ).get("items", [])
        for item in forecasts[:3]:
            attainment = item.get("attainment_pct")
            target = float(item.get("target") or 0)
            won = float(item.get("won") or 0)
            if target and attainment is not None and float(attainment) < 80:
                produced.append(
                    _insight_document(
                        signature=f"previsao-abaixo-do-objetivo-{item.get('id')}",
                        title=f"Previsão «{item.get('name')}» com {attainment}% do objetivo",
                        insight_type="previsao",
                        severity="alta",
                        summary=(
                            f"O objetivo é {target:,.0f} € e o valor ganho é {won:,.0f} € "
                            f"(desvio de {float(item.get('gap') or 0):,.0f} €)."
                        ),
                        recommendation=(
                            "Reforçar o pipeline comprometido: acelerar as oportunidades em negociação e "
                            "antecipar renovações previstas para o período."
                        ),
                        evidence={
                            "objetivo": target,
                            "ganho": won,
                            "comprometido": item.get("committed"),
                            "melhor_cenario": item.get("best_case"),
                            "pipeline": item.get("pipeline"),
                        },
                        module="forecasts",
                        record_id=str(item.get("id") or ""),
                        record_label=str(item.get("name") or ""),
                        metric="cumprimento_do_objetivo",
                        value=float(attainment),
                        baseline=100.0,
                        confidence=80,
                    )
                )

    # 7. Campanhas sem conversão.
    if can_read(perm, "campaigns"):
        campaigns = list_module(registry.MODULE_BY_SLUG["campaigns"], perm, size=100).get("items", [])
        weak = [
            item
            for item in campaigns
            if str(item.get("status")) in ("ativa", "concluida")
            and not item.get("leads_generated")
            and float(item.get("actual_cost") or 0) > 0
        ]
        if weak:
            produced.append(
                _insight_document(
                    signature="campanhas-sem-conversao",
                    title=f"{len(weak)} campanhas com custo e sem leads gerados",
                    insight_type="anomalia",
                    severity="media",
                    summary="Há campanhas com investimento registado e nenhum lead associado — ou o retorno não foi registado ou a campanha não converteu.",
                    recommendation="Confirmar a atribuição de leads às campanhas e, se o resultado se confirmar, suspender as que não convertem.",
                    evidence={
                        "campanhas": [
                            {
                                "id": item.get("id"),
                                "nome": item.get("name"),
                                "custo": item.get("actual_cost"),
                                "leads": item.get("leads_generated"),
                            }
                            for item in weak[:10]
                        ]
                    },
                    module="campaigns",
                    metric="campanhas_sem_leads",
                    value=float(len(weak)),
                    confidence=65,
                )
            )

    # Persistência: a mesma assinatura atualiza a perceção existente.
    created = 0
    updated = 0
    skipped = 0
    for document in produced:
        previous = _find_by_signature(client, perm, document["signature"])
        if previous and str(previous.get("status")) in ("aplicado", "ignorado"):
            skipped += 1
            continue
        if previous:
            merged = {**previous, **document, "id": previous["id"], "status": previous.get("status") or "novo"}
            merged["generated_at"] = _now()
            try:
                client.index(
                    index=CRM_INDEX,
                    id=doc_id(module, str(previous["id"])),
                    document={k: v for k, v in merged.items() if k not in ("doc_id", "label", "module")},
                    refresh=True,
                )
                updated += 1
            except Exception:  # pragma: no cover
                pass
        else:
            document["id"] = new_id(module)
            document["kind"] = module.kind
            document["owner_id"] = perm.get("user_id") or ""
            document["owner_email"] = perm.get("email") or ""
            document["org_area"] = perm.get("area") or ""
            document["org_department"] = perm.get("department") or ""
            document["org_team"] = perm.get("team_id") or ""
            document["created_at"] = _now()
            document["updated_at"] = _now()
            try:
                client.index(index=CRM_INDEX, id=doc_id(module, document["id"]), document=document, refresh=True)
                created += 1
            except Exception:  # pragma: no cover
                pass

    audit(
        action="ai",
        module="ai-insights",
        perm=perm,
        summary=f"Motor de IA gerou perceções: {created} novas, {updated} atualizadas, {skipped} preservadas",
        changes=["generated_at"],
    )
    return {"ok": True, "created": created, "updated": updated, "preserved": skipped, "total": len(produced)}


def _find_by_signature(client: Any, perm: Dict[str, Any], signature: str) -> Optional[Dict[str, Any]]:
    module = registry.MODULE_BY_SLUG["ai-insights"]
    try:
        resp = client.search(
            index=CRM_INDEX,
            body={
                "query": {
                    "bool": {
                        "filter": [
                            {"term": {"kind": module.kind}},
                            {"term": {"signature": signature}},
                            *scope_clauses(perm, module),
                        ]
                    }
                },
                "size": 1,
                "sort": [{"generated_at": {"order": "desc"}}],
            },
        )
        hits = resp["hits"]["hits"]
        return _record(hits[0], module) if hits else None
    except Exception:  # pragma: no cover
        return None


_INTENT_HINTS: Tuple[Tuple[str, str], ...] = (
    ("pipeline", "analise"),
    ("oportunidade", "analise"),
    ("negocio", "analise"),
    ("previs", "previsao"),
    ("objetivo", "previsao"),
    ("conta", "consulta"),
    ("cliente", "consulta"),
    ("contacto", "consulta"),
    ("lead", "consulta"),
    ("caso", "consulta"),
    ("apoio", "consulta"),
    ("campanha", "analise"),
    ("marketing", "analise"),
    ("risco", "recomendacao"),
    ("recomenda", "recomendacao"),
    ("que devo", "recomendacao"),
    ("prioridade", "recomendacao"),
    ("atividade", "consulta"),
    ("tarefa", "consulta"),
    ("contrato", "consulta"),
    ("encomenda", "consulta"),
    ("fatura", "consulta"),
    ("perce", "analise"),
)


def detect_intent(question: str) -> str:
    text = (question or "").lower()
    for needle, intent in _INTENT_HINTS:
        if needle in text:
            return intent
    return "consulta"


def _facts(perm: Dict[str, Any]) -> Dict[str, Any]:
    """Factos do CRM que servem de base a qualquer resposta do assistente."""
    facts: Dict[str, Any] = {"âmbito": perm.get("scope"), "perfil": perm.get("role")}
    counts: Dict[str, int] = {}
    for slug in visible_modules(perm):
        if slug in ("audit", "ai-insights", "ai-interactions"):
            continue
        module = registry.MODULE_BY_SLUG[slug]
        listed = list_module(module, perm, size=1)
        counts[slug] = int(listed.get("total") or 0)
    facts["contagens"] = counts

    if can_read(perm, "opportunities"):
        stats = module_stats(registry.MODULE_BY_SLUG["opportunities"], perm)
        facts["pipeline"] = {
            "total": stats.get("total"),
            "por_fase": {
                bucket["key"]: bucket["count"]
                for group in stats.get("groups", [])
                if group["field"] == "stage"
                for bucket in group["buckets"]
            },
            "valores": {metric["field"]: metric["sum"] for metric in stats.get("metrics", [])},
        }
    if can_read(perm, "forecasts"):
        forecasts = list_module(registry.MODULE_BY_SLUG["forecasts"], perm, size=10, sort_by="year", sort_order="desc").get("items", [])
        facts["previsoes"] = [
            {
                "nome": item.get("name"),
                "ano": item.get("year"),
                "trimestre": item.get("quarter"),
                "objetivo": item.get("target"),
                "ganho": item.get("won"),
                "cumprimento": item.get("attainment_pct"),
            }
            for item in forecasts[:5]
        ]
    if can_read(perm, "cases"):
        cases = list_module(registry.MODULE_BY_SLUG["cases"], perm, size=MAX_SIZE).get("items", [])
        facts["casos"] = {
            "total": len(cases),
            "abertos": sum(1 for item in cases if str(item.get("status")) not in ("resolvido", "fechado", "cancelado")),
            "criticos": sum(
                1
                for item in cases
                if str(item.get("priority")) in ("alta", "critica")
                and str(item.get("status")) not in ("resolvido", "fechado", "cancelado")
            ),
        }
    if can_read(perm, "ai-insights"):
        insights = list_module(
            registry.MODULE_BY_SLUG["ai-insights"], perm, size=5, sort_by="generated_at", sort_order="desc"
        ).get("items", [])
        facts["percecoes"] = [
            {"titulo": item.get("title"), "severidade": item.get("severity"), "estado": item.get("status")}
            for item in insights
        ]
    return facts


def _spoken(value: Any) -> str:
    if value is None or value == "":
        return "sem registo"
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return f"{value:,.2f}".replace(",", " ").replace(".", ",").replace(" ", ".")
    return str(value)


def grounded_answer(question: str, facts: Dict[str, Any]) -> str:
    """Resposta determinística, sempre baseada nos factos recolhidos do CRM."""
    intent = detect_intent(question)
    counts = facts.get("contagens") or {}
    lines: List[str] = []
    lines.append(f"Com base nos dados do CRM a que tem acesso (âmbito: {facts.get('âmbito', 'próprio')}):")

    pipeline = facts.get("pipeline")
    if pipeline:
        stages = pipeline.get("por_fase") or {}
        amounts = pipeline.get("valores") or {}
        open_total = sum(
            value for key, value in stages.items() if key not in ("ganho", "perdido")
        )
        lines.append(
            f"• Pipeline: {_spoken(pipeline.get('total'))} oportunidades, "
            f"{open_total} em aberto, valor total de {_spoken(amounts.get('amount'))} € "
            f"e valor ponderado de {_spoken(amounts.get('weighted_amount'))} €."
        )
        if stages:
            detail = ", ".join(f"{key}: {value}" for key, value in stages.items())
            lines.append(f"• Distribuição por fase — {detail}.")

    if counts:
        interesting = [
            (slug, value)
            for slug, value in counts.items()
            if value and slug in ("accounts", "contacts", "leads", "cases", "orders", "contracts", "campaigns", "products", "quotes")
        ]
        if interesting:
            lines.append(
                "• Volume: "
                + ", ".join(
                    f"{registry.MODULE_BY_SLUG[slug].label.lower()} {value}" for slug, value in interesting
                )
                + "."
            )

    forecasts = facts.get("previsoes") or []
    if forecasts:
        item = forecasts[0]
        lines.append(
            f"• Previsão mais recente ({item.get('nome')}): objetivo {_spoken(item.get('objetivo'))} €, "
            f"ganho {_spoken(item.get('ganho'))} €, cumprimento {item.get('cumprimento') or 0}%."
        )

    cases = facts.get("casos")
    if cases:
        lines.append(
            f"• Apoio ao cliente: {cases.get('abertos')} casos abertos, dos quais "
            f"{cases.get('criticos')} de prioridade alta ou crítica."
        )

    insights = facts.get("percecoes") or []
    if insights:
        lines.append(
            "• Perceções recentes: " + "; ".join(str(item.get("titulo")) for item in insights[:3]) + "."
        )

    if intent == "recomendacao":
        lines.append(
            "Recomendação: começar pelas perceções de severidade alta, agendar seguimento nas "
            "oportunidades sem movimento e fechar as atividades em atraso."
        )
    elif intent == "previsao":
        lines.append(
            "Para a previsão, o que conta é o valor comprometido e as oportunidades com fecho previsto "
            "no período — não o pipeline total."
        )
    else:
        lines.append(
            "Pode pedir-me para gerar perceções (módulo «Perceções de IA») para transformar estes números "
            "em ações concretas."
        )
    return "\n".join(lines)


def ask(
    question: str,
    perm: Dict[str, Any],
    *,
    session: Any = None,
    backend: Optional[str] = None,
    module: str = "",
    record_id: str = "",
) -> Dict[str, Any]:
    """Assistente de CRM: responde com factos reais e registar a interação."""
    import asyncio

    facts = _facts(perm)
    intent = detect_intent(question)
    answer = grounded_answer(question, facts)
    provider = ""
    model = ""
    status = "ok"
    tokens_prompt = None
    tokens_completion = None
    started = datetime.now(timezone.utc)

    # Com um fornecedor de IA configurado, a resposta é redigida pelo modelo a
    # partir dos mesmos factos (nunca sem eles).
    if session is not None:
        try:
            from api import ontology_ai

            resolved = ontology_ai.available_backend(session, backend)
            if resolved.get("kind") == "cloud":
                prompt = (
                    "Factos do CRM (JSON):\n"
                    f"{facts}\n\n"
                    f"Pergunta do utilizador: {question}\n\n"
                    "Responde em português de Portugal, em texto corrido e curto, usando apenas estes factos. "
                    "Se um dado não estiver nos factos, diz que não está disponível."
                )
                try:
                    loop = asyncio.get_running_loop()
                except RuntimeError:
                    loop = None
                if loop is not None:
                    raise RuntimeError("contexto assíncrono")
                text = asyncio.run(
                    ontology_ai.ask_model(
                        resolved,
                        system=(
                            "És o assistente de CRM da plataforma IQ OS. Trabalhas apenas com os factos "
                            "fornecidos e nunca inventas números."
                        ),
                        prompt=prompt,
                        max_tokens=700,
                        temperature=0.1,
                    )
                )
                if text:
                    answer = text
                    provider = str(resolved.get("provider") or "")
                    model = str(resolved.get("model") or "")
        except Exception as exc:  # pragma: no cover - depende de fornecedores
            logger.debug("CRM: assistente sem modelo (%s)", exc)
            if not provider:
                status = "sem-modelo"

    latency = int((datetime.now(timezone.utc) - started).total_seconds() * 1000)

    interaction_module = registry.MODULE_BY_SLUG["ai-interactions"]
    result = save_module(
        interaction_module,
        {
            "question": question,
            "answer": answer,
            "intent": intent,
            "status": status,
            "module": module,
            "record_id": record_id,
            "provider": provider,
            "model": model,
            "context": {"facts": facts, "backend": backend or ""},
            "confidence": 80 if provider else 65,
            "latency_ms": latency,
            "tokens_prompt": tokens_prompt,
            "tokens_completion": tokens_completion,
            "asked_at": _now(),
        },
        perm,
    )
    if result.get("error"):
        return {"error": result["error"], "answer": answer, "facts": facts}
    return {
        "ok": True,
        "answer": answer,
        "intent": intent,
        "provider": provider,
        "model": model,
        "status": status,
        "latency_ms": latency,
        "facts": facts,
        "interaction": result.get("item"),
    }
