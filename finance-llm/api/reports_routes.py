"""Rotas do módulo «Relatórios» (`/reports/*`).

Três áreas, todas com sessão:

* **Cliente** (qualquer sessão) — catálogo, pedido de relatório, pagamento
  (MB Way para o número configurado) e download dos relatórios gerados.
  `GET /reports/catalogue`, `POST /reports/requests`, `GET /reports/requests`,
  `POST /reports/requests/{id}/payment`, `POST /reports/requests/{id}/cancel`,
  `GET /reports/requests/{id}/files/{file}` e `/reports/notifications`.

* **Backoffice** (administradores ou contas em `settings.backoffice_users`) —
  caixa de entrada dos pedidos, confirmação de pagamentos, mudança de estado,
  carregamento do relatório gerado e entrega. `/reports/backoffice/*`.

* **Administração** (papel `admin`) — número MB Way, chave de API, IVA, lista de
  contas de backoffice e catálogo (preços e pacotes). `/reports/admin/*`.

A consulta de notificações é o que faz o sino da interface: cada pedido novo
notifica a equipa de backoffice e cada mudança de estado notifica o cliente.
"""
from __future__ import annotations

import csv
import io
import logging
from typing import Annotated, Any, Dict, List, Optional

from fastapi import APIRouter, Body, Depends, File, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse, Response
from pydantic import BaseModel, Field

from api import auth_service as auth
from api import events_service as events
from api import reports_payments as payments
from api import reports_store as store
from api.auth_routes import CurrentSession, require_session

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/reports", tags=["reports"])

ADMIN_ROLES = {"admin"}


# --------------------------------------------------------------------- sessão
def _email(session: CurrentSession) -> str:
    return str(session.user.email or "").lower()


def _name(session: CurrentSession) -> str:
    return str(session.user.name or "") or _email(session)


def _role(session: CurrentSession) -> str:
    return str(session.user.role or "member")


def _admin_emails() -> List[str]:
    """Emails das contas `admin` (para avisar de pedidos novos)."""
    try:
        return [
            str(user.get("email") or "").lower()
            for user in auth.list_users(limit=200)
            if str(user.get("role") or "") in ADMIN_ROLES and user.get("email")
        ]
    except Exception as exc:  # noqa: BLE001 - o ES pode estar em baixo
        logger.warning("Relatórios: não foi possível listar administradores (%s)", exc)
        return []


def require_backoffice(session: Annotated[CurrentSession, Depends(require_session)]) -> CurrentSession:
    """Administradores ou contas marcadas como backoffice de relatórios."""
    if not store.is_backoffice(_email(session), _role(session)):
        raise HTTPException(
            status_code=403,
            detail="Sem acesso ao backoffice de relatórios. Peça a um administrador para o autorizar.",
        )
    return session


def require_admin(session: Annotated[CurrentSession, Depends(require_session)]) -> CurrentSession:
    if _role(session) not in ADMIN_ROLES:
        raise HTTPException(status_code=403, detail="Apenas administradores.")
    return session


ClienteSession = Annotated[CurrentSession, Depends(require_session)]
BackofficeSession = Annotated[CurrentSession, Depends(require_backoffice)]
AdminSession = Annotated[CurrentSession, Depends(require_admin)]


# -------------------------------------------------------------------- modelos
class Target(BaseModel):
    name: str = Field("", description="Nome da empresa alvo")
    nif: str = Field("", description="NIF/NIPC (opcional)")


class RequestCreate(BaseModel):
    package_id: str = Field(..., min_length=1, description="Id (ou código) do pacote do catálogo")
    targets: List[Target] = Field(default_factory=list)
    notes: str = Field("", max_length=store.MAX_NOTES)
    mbway_phone: str = Field("", description="Telemóvel do cliente para o pedido MB Way")


class PaymentDeclare(BaseModel):
    method: str = Field("mbway", description="mbway | transferencia | referencia | manual")
    mbway_phone: str = ""
    note: str = Field("", max_length=400)


class PaymentDecision(BaseModel):
    action: str = Field(..., pattern="^(confirm|reject)$")
    note: str = Field("", max_length=400)
    amount: Optional[float] = None


class StatusPatch(BaseModel):
    status: str = Field(..., description="Estado do pedido")
    note: str = Field("", max_length=store.MAX_NOTES)
    assigned_to: Optional[str] = None
    internal: bool = False


class NotePayload(BaseModel):
    message: str = Field(..., min_length=1, max_length=store.MAX_NOTES)
    internal: bool = False


class SettingsPatch(BaseModel):
    mbway_number: Optional[str] = None
    mbway_holder: Optional[str] = None
    mbway_enabled: Optional[bool] = None
    mbway_provider: Optional[str] = None
    mbway_api_key: Optional[str] = None
    mbway_api_url: Optional[str] = None
    auto_confirm_mbway_api: Optional[bool] = None
    iban: Optional[str] = None
    payment_instructions: Optional[str] = None
    vat_rate: Optional[float] = None
    default_delivery_days: Optional[float] = None
    backoffice_users: Optional[List[str]] = None
    notify_extra_emails: Optional[List[str]] = None


class CataloguePayload(BaseModel):
    id: Optional[str] = None
    code: Optional[str] = None
    title: Optional[str] = None
    subtitle: Optional[str] = None
    note: Optional[str] = None
    badge: Optional[str] = None
    price: Optional[float] = None
    list_price: Optional[float] = None
    delivery_days: Optional[int] = None
    max_targets: Optional[int] = None
    active: Optional[bool] = None
    features: Optional[List[str]] = None


def _fail(exc: ValueError) -> HTTPException:
    return HTTPException(status_code=400, detail=str(exc))


def _csv_response(*, status: str = "") -> Response:
    """CSV dos pedidos (separador `;` e BOM, para abrir bem no Excel)."""
    buffer = io.StringIO()
    writer = csv.writer(buffer, delimiter=";")
    for row in store.csv_rows(status=status):
        writer.writerow(row)
    return Response(
        content="\ufeff" + buffer.getvalue(),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": 'attachment; filename="relatorios.csv"'},
    )


def _admin_settings_view() -> Dict[str, Any]:
    """Configuração completa, com a chave mascarada."""
    data = store.settings()
    key = str(data.get("mbway_api_key") or "")
    return {
        **{k: v for k, v in data.items() if k != "mbway_api_key"},
        "mbway_api_set": bool(key),
        "mbway_api_hint": (f"…{key[-4:]}" if len(key) > 4 else ("configurada" if key else "")),
        "backoffice_effective": store.backoffice_users(),
    }


# ------------------------------------------------------------------ catálogo
@router.get("/catalogue")
def reports_catalogue(session: ClienteSession) -> Dict[str, Any]:
    """Catálogo visível ao cliente + o que precisa para pagar."""
    return {
        "packages": store.catalogue(only_active=True),
        "settings": store.public_settings(),
        "my_open": sum(
            1
            for item in store.requests_for(_email(session), limit=500)
            if item["status"] in {"aguarda_pagamento", "pagamento_confirmado", "em_producao"}
        ),
        "unread": store.unread_count(_email(session)),
        "statuses": store.REPORT_LABELS,
    }


@router.get("/summary")
def reports_summary(session: ClienteSession) -> Dict[str, Any]:
    """Indicadores da área «Relatórios» do utilizador."""
    items = store.requests_for(_email(session), limit=500)
    by_status: Dict[str, int] = {}
    for item in items:
        by_status[item["status"]] = by_status.get(item["status"], 0) + 1
    return {
        "total": len(items),
        "by_status": by_status,
        "labels": store.REPORT_LABELS,
        "styles": store.REPORT_STYLE,
        "payments": store.PAYMENT_LABELS,
        "unread": store.unread_count(_email(session)),
        "to_pay": sum(1 for item in items if item["status"] == "aguarda_pagamento"),
        "in_progress": sum(1 for item in items if item["status"] in {"pagamento_confirmado", "em_producao"}),
        "ready": sum(1 for item in items if item["status"] in {"gerado", "entregue"}),
        "methods": store.PAYMENT_METHODS,
    }


# -------------------------------------------------------------------- pedidos
@router.post("/requests", status_code=201)
def reports_create_request(payload: RequestCreate, session: ClienteSession) -> Dict[str, Any]:
    """Cria um pedido de relatório para a conta autenticada."""
    try:
        created = store.create_request(
            {"email": _email(session), "name": _name(session)},
            {
                "package_id": payload.package_id,
                "targets": [target.model_dump() for target in payload.targets],
                "notes": payload.notes,
                "mbway_phone": payload.mbway_phone,
                "_admins": _admin_emails(),
            },
        )
    except ValueError as exc:
        raise _fail(exc) from exc
    events.log_event(
        "info",
        "reports",
        f"Pedido de relatório {created['reference']} criado por {_email(session)}",
        data={"reference": created["reference"], "package": created["package_title"]},
    )
    return created


@router.get("/requests")
def reports_my_requests(
    session: ClienteSession,
    status: str = Query("", description="Filtrar por estado"),
    limit: int = Query(200, ge=1, le=1000),
) -> Dict[str, Any]:
    """Pedidos do utilizador autenticado (mais recentes primeiro)."""
    items = store.requests_for(_email(session), limit=limit)
    if status:
        items = [item for item in items if item["status"] == status]
    return {"items": items, "total": len(items), "labels": store.REPORT_LABELS, "styles": store.REPORT_STYLE}


@router.get("/requests/{request_id}")
def reports_get_request(request_id: str, session: ClienteSession) -> Dict[str, Any]:
    doc = store.get_request(request_id)
    if doc is None:
        raise HTTPException(status_code=404, detail="Pedido não encontrado.")
    mine = str((doc.get("requester") or {}).get("email") or "").lower() == _email(session)
    if not mine and not store.is_backoffice(_email(session), _role(session)):
        raise HTTPException(status_code=403, detail="Este pedido não é seu.")
    return store.request_view(doc, include_internal=store.is_backoffice(_email(session), _role(session)))


@router.post("/requests/{request_id}/payment")
def reports_declare_payment(request_id: str, payload: PaymentDeclare, session: ClienteSession) -> Dict[str, Any]:
    """Indica que o cliente pagou (ou pede o pagamento automático por MB Way)."""
    doc = store.get_request(request_id)
    if doc is None:
        raise HTTPException(status_code=404, detail="Pedido não encontrado.")
    settings_data = store.settings()
    automatic: Dict[str, Any] = {"ok": False, "configured": False, "message": ""}
    if payload.method == "mbway" and payments.api_configured(settings_data):
        phone = store.normalise_phone(payload.mbway_phone) or store.normalise_phone(
            (doc.get("payment") or {}).get("mbway_phone")
        )
        amount = store.money((doc.get("amounts") or {}).get("total"))
        if phone and amount > 0:
            automatic = payments.create_payment_request(
                settings_data,
                phone=phone,
                amount=amount,
                reference=str(doc.get("reference") or request_id),
                description=f"{doc.get('package_title')} — {doc.get('reference')}",
            )
    try:
        view = store.declare_payment(
            request_id,
            {"email": _email(session), "name": _name(session)},
            {"method": payload.method, "mbway_phone": payload.mbway_phone, "note": payload.note},
            admins=_admin_emails(),
        )
    except ValueError as exc:
        raise _fail(exc) from exc
    if automatic.get("ok") and automatic.get("request_id"):
        store.record_mbway_request(request_id, automatic["request_id"], automatic.get("status", ""))
        view = store.get_request_view(request_id, include_internal=True) or view
    return {"request": view, "automatic": automatic}


@router.get("/requests/{request_id}/payment/status")
def reports_payment_status(request_id: str, session: ClienteSession) -> Dict[str, Any]:
    """Consulta o estado do pedido de pagamento MB Way (quando automático)."""
    doc = store.get_request(request_id)
    if doc is None:
        raise HTTPException(status_code=404, detail="Pedido não encontrado.")
    mine = str((doc.get("requester") or {}).get("email") or "").lower() == _email(session)
    if not mine and not store.is_backoffice(_email(session), _role(session)):
        raise HTTPException(status_code=403, detail="Este pedido não é seu.")
    provider_id = str((doc.get("payment") or {}).get("provider_request_id") or "")
    if not provider_id:
        return {"ok": True, "automatic": False, "request": store.request_view(doc, include_internal=True)}
    result = payments.fetch_payment_status(store.settings(), request_id=provider_id)
    if result.get("paid"):
        store.register_automatic_payment(
            request_id,
            reference=str(doc.get("reference") or ""),
            amount=(doc.get("amounts") or {}).get("total"),
        )
    return {
        **result,
        "automatic": True,
        "request": store.get_request_view(request_id, include_internal=True),
    }


@router.post("/requests/{request_id}/cancel")
def reports_cancel_request(request_id: str, session: ClienteSession, payload: Optional[NotePayload] = None) -> Dict[str, Any]:
    try:
        return store.cancel(request_id, {"email": _email(session), "name": _name(session)}, (payload.message if payload else ""))
    except ValueError as exc:
        raise _fail(exc) from exc


@router.get("/requests/{request_id}/files/{file_id}")
def reports_download(request_id: str, file_id: str, session: ClienteSession) -> Response:
    """Descarrega um relatório gerado (o cliente só vê o que é seu)."""
    doc = store.get_request(request_id)
    if doc is None:
        raise HTTPException(status_code=404, detail="Pedido não encontrado.")
    mine = str((doc.get("requester") or {}).get("email") or "").lower() == _email(session)
    if not mine and not store.is_backoffice(_email(session), _role(session)):
        raise HTTPException(status_code=403, detail="Este pedido não é seu.")
    found = store.file_of(request_id, file_id)
    if found is None:
        raise HTTPException(status_code=404, detail="Ficheiro não encontrado.")
    path, meta = found
    if str(doc.get("status")) == "gerado" and mine:
        try:
            store.set_status(request_id, _email(session), "entregue", note="Relatório descarregado pelo cliente.")
        except ValueError:
            pass
    return FileResponse(path, media_type=meta.get("mime") or "application/octet-stream", filename=meta.get("name") or path.name)


# ------------------------------------------------------------- notificações
@router.get("/notifications")
def reports_notifications(session: ClienteSession, limit: int = Query(30, ge=1, le=200)) -> Dict[str, Any]:
    email = _email(session)
    return {
        "items": store.notifications_for(email, limit=limit),
        "unread": store.unread_count(email),
    }


@router.post("/notifications/read")
def reports_notifications_read(session: ClienteSession, payload: Dict[str, Any] = Body(default_factory=dict)) -> Dict[str, Any]:
    ids = payload.get("ids") if isinstance(payload, dict) else None
    changed = store.mark_read(_email(session), ids if isinstance(ids, list) else None)
    email = _email(session)
    return {"marked": changed, "unread": store.unread_count(email)}


# ---------------------------------------------------------------- backoffice
@router.get("/backoffice/me")
def reports_backoffice_me(session: ClienteSession) -> Dict[str, Any]:
    """Diz à interface se a conta pode abrir o backoffice de relatórios."""
    email = _email(session)
    allowed = store.is_backoffice(email, _role(session))
    return {
        "backoffice": allowed,
        "role": _role(session),
        "email": email,
        "unread": store.unread_count(email) if allowed else 0,
        "stats": store.stats() if allowed else {},
    }


@router.get("/backoffice/inbox")
def reports_backoffice_inbox(
    session: BackofficeSession,
    status: str = Query(""),
    q: str = Query(""),
    mine: bool = Query(False),
    limit: int = Query(300, ge=1, le=1000),
) -> Dict[str, Any]:
    items = store.all_requests(status=status, query=q, assigned_to=_email(session) if mine else "", only_backoffice=mine, limit=limit)
    return {
        "items": items,
        "total": len(items),
        "stats": store.stats(),
        "labels": store.REPORT_LABELS,
        "styles": store.REPORT_STYLE,
        "payment_labels": store.PAYMENT_LABELS,
        "payment_styles": store.PAYMENT_STYLE,
        "statuses": [{"id": key, "label": store.REPORT_LABELS[key]} for key in store.REPORT_STATUSES],
        "unread": store.unread_count(_email(session)),
        "activity": store.activity(limit=20),
        "me": {"email": _email(session), "name": _name(session)},
    }


@router.get("/backoffice/requests/{request_id}")
def reports_backoffice_request(request_id: str, session: BackofficeSession) -> Dict[str, Any]:
    view = store.get_request_view(request_id, include_internal=True)
    if view is None:
        raise HTTPException(status_code=404, detail="Pedido não encontrado.")
    return view


@router.patch("/backoffice/requests/{request_id}")
def reports_backoffice_patch(request_id: str, payload: StatusPatch, session: BackofficeSession) -> Dict[str, Any]:
    try:
        view = store.set_status(
            request_id,
            _email(session),
            payload.status,
            note=payload.note,
            assigned_to=payload.assigned_to,
            internal=payload.internal,
        )
    except ValueError as exc:
        raise _fail(exc) from exc
    events.log_event(
        "info",
        "reports",
        f"Pedido {view['reference']} → {view['status_label']} ({_email(session)})",
        data={"reference": view["reference"]},
    )
    return view


@router.post("/backoffice/requests/{request_id}/payment")
def reports_backoffice_payment(request_id: str, payload: PaymentDecision, session: BackofficeSession) -> Dict[str, Any]:
    try:
        view = store.set_payment_result(
            request_id,
            _email(session),
            payload.action,
            note=payload.note,
            amount=payload.amount,
        )
    except ValueError as exc:
        raise _fail(exc) from exc
    events.log_event(
        "info",
        "reports",
        f"Pagamento {'confirmado' if payload.action == 'confirm' else 'rejeitado'} — {view['reference']} ({_email(session)})",
        data={"reference": view["reference"]},
    )
    return view


@router.post("/backoffice/requests/{request_id}/files")
async def reports_backoffice_upload(
    request_id: str,
    session: BackofficeSession,
    file: UploadFile = File(..., description="Relatório gerado (PDF, DOCX, XLSX, ZIP…)"),
    mark_generated: bool = Query(True, description="Marcar o pedido como «Gerado»"),
) -> Dict[str, Any]:
    """Anexa o relatório produzido e (por omissão) marca o pedido como gerado."""
    data = await file.read()
    try:
        view = store.add_file(
            request_id,
            _email(session),
            name=file.filename or "relatorio.pdf",
            data=data,
            mime=file.content_type or "",
            mark_generated=mark_generated,
        )
    except ValueError as exc:
        raise _fail(exc) from exc
    events.log_event("info", "reports", f"Relatório anexado a {view['reference']} ({_email(session)})", data={"file": file.filename})
    return view


@router.post("/backoffice/requests/{request_id}/files/base64")
def reports_backoffice_upload_base64(request_id: str, session: BackofficeSession, payload: Dict[str, Any] = Body(...)) -> Dict[str, Any]:
    try:
        return store.add_file_base64(request_id, _email(session), payload)
    except ValueError as exc:
        raise _fail(exc) from exc


@router.delete("/backoffice/requests/{request_id}/files/{file_id}")
def reports_backoffice_remove_file(request_id: str, file_id: str, session: BackofficeSession) -> Dict[str, Any]:
    if not store.remove_file(request_id, file_id, _email(session)):
        raise HTTPException(status_code=404, detail="Ficheiro não encontrado.")
    return {"removed": True, "request": store.get_request_view(request_id, include_internal=True)}


@router.post("/backoffice/requests/{request_id}/note")
def reports_backoffice_note(request_id: str, payload: NotePayload, session: BackofficeSession) -> Dict[str, Any]:
    try:
        return store.attach_note(request_id, _email(session), payload.message, internal=payload.internal)
    except ValueError as exc:
        raise _fail(exc) from exc


@router.get("/backoffice/export.csv")
def reports_backoffice_export(session: BackofficeSession, status: str = Query("")) -> Response:
    """Exportação CSV dos pedidos (para folha de cálculo)."""
    return _csv_response(status=status)


# ------------------------------------------------------------------- admin
@router.get("/admin/settings")
def reports_admin_settings(session: AdminSession) -> Dict[str, Any]:
    return {
        "settings": _admin_settings_view(),
        "catalogue": store.catalogue(),
        "stats": store.stats(),
        "payments": payments.statuses(),
        "methods": store.PAYMENT_METHODS,
    }


@router.put("/admin/settings")
def reports_admin_save_settings(payload: SettingsPatch, session: AdminSession) -> Dict[str, Any]:
    patch = {key: value for key, value in payload.model_dump().items() if value is not None}
    if "mbway_api_key" in patch and "…" in str(patch["mbway_api_key"]):
        # A interface mostra a chave mascarada; não a voltar a gravar.
        patch.pop("mbway_api_key")
    try:
        store.save_settings(patch, actor=_email(session))
    except ValueError as exc:
        raise _fail(exc) from exc
    events.log_event("info", "reports", f"Configuração de relatórios alterada por {_email(session)}", data={})
    return _admin_settings_view()


@router.post("/admin/catalogue")
def reports_admin_save_package(payload: CataloguePayload, session: AdminSession) -> Dict[str, Any]:
    try:
        return store.save_package({key: value for key, value in payload.model_dump().items() if value is not None}, actor=_email(session))
    except ValueError as exc:
        raise _fail(exc) from exc


@router.delete("/admin/catalogue/{package_id}")
def reports_admin_delete_package(package_id: str, session: AdminSession) -> Dict[str, Any]:
    if not store.delete_package(package_id, actor=_email(session)):
        raise HTTPException(status_code=404, detail="Pacote não encontrado.")
    return {"removed": True, "catalogue": store.catalogue()}


@router.get("/admin/overview")
def reports_admin_overview(session: AdminSession) -> Dict[str, Any]:
    """Panorama para a administração: pedidos, receita e atividade."""
    return {
        "stats": store.stats(),
        "requests": store.all_requests(limit=50),
        "activity": store.activity(limit=30),
        "settings": _admin_settings_view(),
        "payments": payments.statuses(),
    }


@router.get("/admin/export.csv")
def reports_admin_export(session: AdminSession, status: str = Query("")) -> Response:
    return _csv_response(status=status)
