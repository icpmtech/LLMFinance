"""Rotas do módulo de CRM (`/crm/*`).

O CRM é um módulo de trabalho comercial sobre os dados do IQ OS: contas
(empresas, opcionalmente ligadas ao cadastro do EmpresasIQ pelo NIF), contactos,
oportunidades (pipeline) e atividades/compromissos.

- `GET    /crm/meta`                        — metadados (fases, estados, tipos)
- `GET    /crm/overview`                    — indicadores do dashboard
- `GET    /crm/{tipo}`                      — listagem/pesquisa (accounts|contacts|deals|activities)
- `POST   /crm/{tipo}`                      — criar
- `GET    /crm/{tipo}/{id}`                 — obter
- `PATCH  /crm/{tipo}/{id}`                 — atualizar (parcial)
- `DELETE /crm/{tipo}/{id}`                 — apagar (uma conta arrasta os seus registos)
- `GET    /crm/accounts/{id}/timeline`      — conta + contactos + oportunidades + atividades
- `POST   /crm/accounts/from-entity`        — criar conta a partir de um NIF do EmpresasIQ
- `POST   /crm/accounts/{id}/sync-entity`   — atualizar o resumo do EmpresasIQ da conta
- `GET    /crm/entities/search`             — sugerir entidades do EmpresasIQ para ligar

Âmbito: cada utilizador só vê os seus registos; as contas com o papel `admin`
veem e gerem os de toda a equipa. Todas as rotas exigem sessão válida.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Annotated, Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from api import crm_service as crm
from api import events_service as events
from api.auth_routes import CurrentSession, require_session

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/crm", tags=["crm"])

RECORD_KINDS = {"accounts": crm.ACCOUNT, "contacts": crm.CONTACT, "deals": crm.DEAL, "activities": crm.ACTIVITY}
KIND_PATH = "^(accounts|contacts|deals|activities)$"


# --------------------------------------------------------------- dependências
@dataclass
class CrmOwner:
    """Âmbito de visibilidade do CRM para o utilizador autenticado."""

    id: str
    email: str
    see_all: bool
    session: CurrentSession

    def scope(self) -> Dict[str, Any]:
        return {"id": self.id, "email": self.email, "see_all": self.see_all}


def crm_owner(session: Annotated[CurrentSession, Depends(require_session)]) -> CrmOwner:
    return CrmOwner(
        id=session.user.id,
        email=session.user.email,
        see_all=(session.user.role or "member") == "admin",
        session=session,
    )


Owner = Annotated[CrmOwner, Depends(crm_owner)]


# -------------------------------------------------------------------- modelos
class AccountPayload(BaseModel):
    name: Optional[str] = None
    nif: Optional[str] = None
    sector: Optional[str] = None
    status: Optional[str] = Field(None, description="prospect | cliente | inativo")
    website: Optional[str] = None
    email: Optional[str] = None
    phone: Optional[str] = None
    mobile: Optional[str] = None
    address: Optional[str] = None
    city: Optional[str] = None
    country: Optional[str] = None
    postal_code: Optional[str] = None
    employees: Optional[int] = None
    annual_revenue: Optional[float] = None
    notes: Optional[str] = None
    tags: Optional[List[str]] = None


class ContactPayload(BaseModel):
    account_id: Optional[str] = None
    name: Optional[str] = None
    title: Optional[str] = None
    role: Optional[str] = None
    email: Optional[str] = None
    phone: Optional[str] = None
    mobile: Optional[str] = None
    linkedin: Optional[str] = None
    is_primary: Optional[bool] = None
    notes: Optional[str] = None
    tags: Optional[List[str]] = None


class DealPayload(BaseModel):
    account_id: Optional[str] = None
    contact_id: Optional[str] = None
    title: Optional[str] = None
    amount: Optional[float] = None
    currency: Optional[str] = None
    stage: Optional[str] = Field(None, description=" | ".join(crm.DEAL_STAGES))
    probability: Optional[int] = Field(None, ge=0, le=100)
    expected_close_date: Optional[str] = None
    loss_reason: Optional[str] = None
    source: Optional[str] = None
    notes: Optional[str] = None
    tags: Optional[List[str]] = None


class ActivityPayload(BaseModel):
    account_id: Optional[str] = None
    contact_id: Optional[str] = None
    deal_id: Optional[str] = None
    type: Optional[str] = Field(None, description=" | ".join(crm.ACTIVITY_TYPES))
    subject: Optional[str] = None
    notes: Optional[str] = None
    due_at: Optional[str] = None
    done: Optional[bool] = None
    priority: Optional[str] = Field(None, description=" | ".join(crm.PRIORITIES))
    tags: Optional[List[str]] = None


class FromEntityPayload(BaseModel):
    nif: str
    status: Optional[str] = None
    sector: Optional[str] = None
    notes: Optional[str] = None
    tags: Optional[List[str]] = None


PAYLOADS = {
    crm.ACCOUNT: AccountPayload,
    crm.CONTACT: ContactPayload,
    crm.DEAL: DealPayload,
    crm.ACTIVITY: ActivityPayload,
}


def _payload_model(kind_path: str):
    model = PAYLOADS.get(RECORD_KINDS.get(kind_path, ""))
    if model is None:
        raise HTTPException(status_code=404, detail=f"Tipo de registo desconhecido: {kind_path}")
    return model


def _record_kind(kind_path: str) -> str:
    kind = RECORD_KINDS.get(kind_path)
    if not kind:
        raise HTTPException(status_code=404, detail=f"Tipo de registo desconhecido: {kind_path}")
    return kind


def _fail(result: Dict[str, Any], status: int = 502) -> None:
    detail = result.get("error") or "Operação do CRM falhou"
    if detail == "Registo não encontrado":
        raise HTTPException(status_code=404, detail=detail)
    if detail.startswith("Sem permissão"):
        raise HTTPException(status_code=403, detail=detail)
    if "precisa de" in detail or "inválido" in detail:
        raise HTTPException(status_code=400, detail=detail)
    raise HTTPException(status_code=status, detail=detail)


# ------------------------------------------------------------------ metadados
@router.get("/meta")
def crm_meta(owner: Owner):
    """Fases, estados e tipos usados pela interface (fonte única de verdade)."""
    return {
        "kinds": list(crm.KINDS),
        "account_statuses": list(crm.ACCOUNT_STATUSES),
        "deal_stages": list(crm.DEAL_STAGES),
        "open_stages": list(crm.OPEN_STAGES),
        "closed_stages": list(crm.CLOSED_STAGES),
        "activity_types": list(crm.ACTIVITY_TYPES),
        "priorities": list(crm.PRIORITIES),
        "default_currency": crm.DEFAULT_CURRENCY,
        "scope": "all" if owner.see_all else "own",
    }


@router.get("/overview")
def crm_overview(owner: Owner, months: int = Query(6, ge=1, le=24)):
    """Indicadores do CRM: pipeline, previsão, conversão e agenda."""
    result = crm.overview(owner.scope(), months=months)
    if result.get("error"):
        _fail(result)
    return result


# ----------------------------------------------------------------- listagens
@router.get("/accounts")
def accounts_list(
    owner: Owner,
    q: Optional[str] = Query(None, description="Pesquisa por nome, NIF, email, cidade"),
    status: Optional[str] = None,
    sector: Optional[str] = None,
    country: Optional[str] = None,
    tag: Optional[str] = None,
    sort_by: Optional[str] = None,
    sort_order: Optional[str] = Query(None, pattern="^(asc|desc)$"),
    size: int = Query(200, ge=1, le=500),
    from_: int = Query(0, ge=0, alias="from"),
):
    """Contas (empresas) do utilizador."""
    result = crm.list_records(
        crm.ACCOUNT,
        owner.scope(),
        q=q,
        filters={"status": status, "sector": sector, "country": country, "tag": tag},
        size=size,
        from_=from_,
        sort_by=sort_by,
        sort_order=sort_order,
    )
    if result.get("error"):
        _fail(result)
    return result


@router.get("/contacts")
def contacts_list(
    owner: Owner,
    q: Optional[str] = None,
    account_id: Optional[str] = None,
    tag: Optional[str] = None,
    sort_by: Optional[str] = None,
    sort_order: Optional[str] = Query(None, pattern="^(asc|desc)$"),
    size: int = Query(200, ge=1, le=500),
    from_: int = Query(0, ge=0, alias="from"),
):
    """Contactos, opcionalmente filtrados por conta."""
    result = crm.list_records(
        crm.CONTACT,
        owner.scope(),
        q=q,
        filters={"account_id": account_id, "tag": tag},
        size=size,
        from_=from_,
        sort_by=sort_by,
        sort_order=sort_order,
    )
    if result.get("error"):
        _fail(result)
    return result


@router.get("/deals")
def deals_list(
    owner: Owner,
    q: Optional[str] = None,
    stage: Optional[str] = None,
    account_id: Optional[str] = None,
    contact_id: Optional[str] = None,
    tag: Optional[str] = None,
    sort_by: Optional[str] = None,
    sort_order: Optional[str] = Query(None, pattern="^(asc|desc)$"),
    size: int = Query(300, ge=1, le=500),
    from_: int = Query(0, ge=0, alias="from"),
):
    """Oportunidades do pipeline."""
    result = crm.list_records(
        crm.DEAL,
        owner.scope(),
        q=q,
        filters={"stage": stage, "account_id": account_id, "contact_id": contact_id, "tag": tag},
        size=size,
        from_=from_,
        sort_by=sort_by,
        sort_order=sort_order,
    )
    if result.get("error"):
        _fail(result)
    return result


@router.get("/activities")
def activities_list(
    owner: Owner,
    q: Optional[str] = None,
    account_id: Optional[str] = None,
    deal_id: Optional[str] = None,
    contact_id: Optional[str] = None,
    type: Optional[str] = None,
    done: Optional[bool] = None,
    priority: Optional[str] = None,
    tag: Optional[str] = None,
    sort_by: Optional[str] = None,
    sort_order: Optional[str] = Query(None, pattern="^(asc|desc)$"),
    size: int = Query(300, ge=1, le=500),
    from_: int = Query(0, ge=0, alias="from"),
):
    """Atividades e compromissos (agenda comercial)."""
    result = crm.list_records(
        crm.ACTIVITY,
        owner.scope(),
        q=q,
        filters={
            "account_id": account_id,
            "deal_id": deal_id,
            "contact_id": contact_id,
            "type": type,
            "done": done,
            "priority": priority,
            "tag": tag,
        },
        size=size,
        from_=from_,
        sort_by=sort_by,
        sort_order=sort_order,
    )
    if result.get("error"):
        _fail(result)
    return result


# --------------------------------------------------------------- EmpresasIQ
# Estas rotas têm de ser declaradas antes de `/{kind}/{record_id}`.
@router.get("/entities/search")
def entities_search(owner: Owner, q: str = Query(..., min_length=2), size: int = Query(10, ge=1, le=30)):
    """Sugestões de entidades do EmpresasIQ para ligar a uma conta."""
    result = crm.search_entity_candidates(q, size=size)
    if result.get("error"):
        _fail(result)
    return result


@router.post("/accounts/from-entity")
def account_from_entity(payload: FromEntityPayload, owner: Owner):
    """Cria uma conta de CRM a partir de um NIF do cadastro de entidades."""
    extra = payload.model_dump(exclude={"nif"}, exclude_none=True)
    result = crm.create_account_from_entity(payload.nif.strip(), owner.scope(), extra)
    if result.get("error"):
        _fail(result)
    if result.get("created"):
        events.log_event(
            "info",
            "crm",
            f"Conta criada a partir da entidade {payload.nif}",
            data={"nif": payload.nif, "account_id": result["item"].get("id")},
            user_id=owner.id,
            user_email=owner.email,
        )
    return result


@router.post("/accounts/{account_id}/sync-entity")
def account_sync_entity(account_id: str, owner: Owner):
    """Atualiza o resumo do EmpresasIQ guardado numa conta."""
    result = crm.refresh_account_entity(account_id, owner.scope())
    if result.get("error"):
        _fail(result)
    return result


@router.get("/accounts/{account_id}/timeline")
def account_timeline(account_id: str, owner: Owner):
    """Conta com os respetivos contactos, oportunidades e atividades."""
    result = crm.account_timeline(account_id, owner.scope())
    if result.get("error"):
        _fail(result)
    return result


# ------------------------------------------------------------------- CRUD
@router.get("/{kind}/{record_id}")
def record_get(kind: str, record_id: str, owner: Owner):
    """Devolve um registo do CRM."""
    result = crm.get_record(_record_kind(kind), record_id, owner.scope())
    if result.get("error"):
        _fail(result)
    return result


@router.post("/{kind}", status_code=201)
def record_create(kind: str, payload: Dict[str, Any], owner: Owner):
    """Cria um registo (o corpo é validado pelo modelo do tipo)."""
    record_kind = _record_kind(kind)
    model = _payload_model(kind)
    data = model(**payload).model_dump(exclude_unset=True)
    result = crm.save_record(record_kind, data, owner.scope())
    if result.get("error"):
        _fail(result)
    return result


@router.patch("/{kind}/{record_id}")
def record_update(kind: str, record_id: str, payload: Dict[str, Any], owner: Owner):
    """Atualiza parcialmente um registo (só os campos enviados)."""
    record_kind = _record_kind(kind)
    model = _payload_model(kind)
    data = model(**payload).model_dump(exclude_unset=True)
    if not data:
        raise HTTPException(status_code=400, detail="Nada para atualizar")
    result = crm.save_record(record_kind, data, owner.scope(), record_id=record_id)
    if result.get("error"):
        _fail(result)
    return result


@router.delete("/{kind}/{record_id}")
def record_delete(kind: str, record_id: str, owner: Owner):
    """Apaga um registo (apagar uma conta arrasta os registos ligados)."""
    record_kind = _record_kind(kind)
    result = crm.delete_record(record_kind, record_id, owner.scope())
    if result.get("error"):
        _fail(result)
    return result
