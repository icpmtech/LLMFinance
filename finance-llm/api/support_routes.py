"""Rotas e WebSocket do apoio ao cliente.

Duas superfícies, um só modelo de dados (ver `api/support_service.py`):

- **público** (`/support/*`) — o widget das páginas do portal usa um token de
  visitante assinado (30 dias) para abrir/retomar a conversa, enviar mensagens,
  atualizar a página onde está, abrir tickets e avaliar o atendimento;
- **backoffice** (`/admin/support/*`) — só contas `admin`. Lista a fila de
  conversas, mostra a transcrição, permite assumir/libertar/fechar, responder,
  gerir tickets e ver os registos e a presença dos operadores.

O tempo real passa por `/support/ws`:

- visitante: `?role=visitor&token=…&session_id=…`
- operador: `?role=operator&token=…` (token da sessão de administração)

O *hub* vive em memória do processo. O backend corre com um único worker
(`uvicorn --workers 1`); com mais do que um processo seria preciso um pub/sub
externo, que aqui não é necessário.
"""
from __future__ import annotations

import asyncio
import logging
from datetime import timedelta
from pathlib import Path
from typing import Annotated, Any, Dict, List, Optional, Set

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel, Field
from starlette.concurrency import run_in_threadpool

from api import auth_service as auth
from api import support_service as support
from api.admin_routes import require_admin
from api.auth_routes import CurrentSession, optional_session

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/support", tags=["support"])
admin_router = APIRouter(prefix="/admin/support", tags=["support-admin"])

VISITOR_TOKEN_PREFIX = "visitor:"
VISITOR_TOKEN_TTL = timedelta(days=30)
WIDGET_PATH = Path(__file__).with_name("support_widget.js")

AdminSession = Annotated[CurrentSession, Depends(require_admin)]


# ------------------------------------------------------------------- modelos
class VisitorBootstrap(BaseModel):
    visitor_id: Optional[str] = None
    profile: Optional[Dict[str, Any]] = None
    context: Optional[Dict[str, Any]] = None


class SessionStart(BaseModel):
    profile: Optional[Dict[str, Any]] = None
    context: Optional[Dict[str, Any]] = None
    subject: str = ""


class MessageIn(BaseModel):
    body: str = Field(..., description="Texto da mensagem")
    client_id: str = ""


class FormResponseIn(BaseModel):
    values: Dict[str, Any] = Field(default_factory=dict)


class ContextIn(BaseModel):
    context: Dict[str, Any] = Field(default_factory=dict)
    profile: Optional[Dict[str, Any]] = None


class TicketIn(BaseModel):
    subject: str
    description: str = ""
    category: str = ""
    priority: str = "normal"


class RatingIn(BaseModel):
    rating: int
    comment: str = ""


class AdminMessageIn(BaseModel):
    body: str = ""
    client_id: str = ""
    internal: bool = False
    kind: str = support.MESSAGE_TEXT
    payload: Optional[Dict[str, Any]] = None


class TicketPatch(BaseModel):
    status: Optional[str] = None
    priority: Optional[str] = None
    category: Optional[str] = None
    note: str = ""


class OperatorStatusIn(BaseModel):
    status: str = "online"


# ------------------------------------------------------------------- helpers
def _auth_error(error: support.SupportError) -> HTTPException:
    return HTTPException(status_code=error.status_code, detail=error.message)


def _client_info(request: Request) -> Dict[str, str]:
    forwarded = request.headers.get("x-forwarded-for") or ""
    ip = (forwarded.split(",")[0].strip() if forwarded else (request.client.host if request.client else "")) or ""
    return {"ip": ip, "user_agent": request.headers.get("user-agent") or ""}


def _visitor_token(visitor_id: str) -> str:
    token, _ = auth.issue_token(VISITOR_TOKEN_PREFIX + visitor_id, "visitor", VISITOR_TOKEN_TTL)
    return token


def _visitor_from_token(token: str) -> str:
    payload = auth.read_token(token) if token else None
    session_id = str((payload or {}).get("sid") or "")
    if not payload or (payload or {}).get("sub") != "visitor" or not session_id.startswith(VISITOR_TOKEN_PREFIX):
        raise HTTPException(status_code=401, detail="Token de visitante inválido ou expirado.")
    visitor_id = session_id[len(VISITOR_TOKEN_PREFIX) :].strip()
    if not visitor_id:
        raise HTTPException(status_code=401, detail="Token de visitante inválido.")
    return visitor_id


def _visitor_from_header(x_support_token: Annotated[Optional[str], Header()] = None) -> str:
    return _visitor_from_token(x_support_token or "")


VisitorId = Annotated[str, Depends(_visitor_from_header)]


def _operator_from_token(token: str) -> Optional[Dict[str, Any]]:
    payload = auth.read_token(token) if token else None
    if not payload:
        return None
    auth_session = auth.get_session(str(payload.get("sid")))
    if not auth_session:
        return None
    user = auth.get_user_by_id(str(payload.get("sub")))
    if not user or (user.get("role") or "member") != "admin":
        return None
    return auth.public_user(user)


def _owned_session(session_id: str, visitor_id: str) -> Dict[str, Any]:
    try:
        document = support.require_session(session_id)
    except support.SupportError as error:
        raise _auth_error(error) from error
    if str(document.get("visitor_id") or "") != visitor_id:
        raise HTTPException(status_code=403, detail="Esta conversa não pertence a este visitante.")
    return document


def _operator_of(session: CurrentSession) -> Dict[str, Any]:
    return {
        "id": session.user.id,
        "name": session.user.name,
        "email": session.user.email,
    }


# --------------------------------------------------------------------- hub
class SupportHub:
    """Ligações WebSocket vivas: visitantes por id, operadores por id."""

    def __init__(self) -> None:
        self._visitors: Dict[str, Set[WebSocket]] = {}
        self._operators: Dict[str, Set[WebSocket]] = {}
        self._socket_visitor: Dict[WebSocket, str] = {}
        self._socket_operator: Dict[WebSocket, str] = {}
        self._operator_status: Dict[str, str] = {}
        self._lock = asyncio.Lock()

    async def add_visitor(self, visitor_id: str, websocket: WebSocket) -> None:
        async with self._lock:
            self._visitors.setdefault(visitor_id, set()).add(websocket)
            self._socket_visitor[websocket] = visitor_id

    async def remove_visitor(self, websocket: WebSocket) -> Optional[str]:
        async with self._lock:
            visitor_id = self._socket_visitor.pop(websocket, None)
            if visitor_id and visitor_id in self._visitors:
                self._visitors[visitor_id].discard(websocket)
                if not self._visitors[visitor_id]:
                    self._visitors.pop(visitor_id, None)
            return visitor_id

    async def add_operator(self, operator_id: str, websocket: WebSocket) -> None:
        async with self._lock:
            self._operators.setdefault(operator_id, set()).add(websocket)
            self._socket_operator[websocket] = operator_id
            self._operator_status[operator_id] = support.OPERATOR_ONLINE

    async def remove_operator(self, websocket: WebSocket) -> Optional[str]:
        async with self._lock:
            operator_id = self._socket_operator.pop(websocket, None)
            if operator_id and operator_id in self._operators:
                self._operators[operator_id].discard(websocket)
                if not self._operators[operator_id]:
                    self._operators.pop(operator_id, None)
                    self._operator_status.pop(operator_id, None)
            return operator_id

    def visitor_online(self, visitor_id: str) -> bool:
        return bool(self._visitors.get(visitor_id))

    def has_operator_sockets(self, operator_id: str) -> bool:
        return bool(self._operators.get(operator_id))

    def operators_online(self) -> int:
        return sum(1 for status in self._operator_status.values() if status == support.OPERATOR_ONLINE)

    def online_operator_ids(self) -> Set[str]:
        return {key for key, status in self._operator_status.items() if status == support.OPERATOR_ONLINE}

    def set_status(self, operator_id: str, status: str) -> None:
        self._operator_status[operator_id] = status

    def status_of(self, operator_id: str) -> str:
        if operator_id not in self._operators:
            return support.OPERATOR_OFFLINE
        return self._operator_status.get(operator_id, support.OPERATOR_ONLINE)

    @staticmethod
    async def send(websocket: WebSocket, payload: Dict[str, Any]) -> None:
        try:
            await websocket.send_json(payload)
        except Exception:  # noqa: BLE001 - ligação já fechada
            pass


    async def send_to_visitor(self, visitor_id: str, payload: Dict[str, Any]) -> None:
        for websocket in list(self._visitors.get(visitor_id) or ()):
            await self.send(websocket, payload)

    async def send_to_operators(self, payload: Dict[str, Any]) -> None:
        for sockets in list(self._operators.values()):
            for websocket in list(sockets):
                await self.send(websocket, payload)

    def presence(self) -> Dict[str, Any]:
        return {
            "type": "presence",
            "operators_online": self.operators_online(),
            "busy": len(self._operators),
        }


hub = SupportHub()


def _public_session(document: Dict[str, Any], *, operator_id: str = "") -> Dict[str, Any]:
    payload = support.public_session(document, online=hub.visitor_online(str(document.get("visitor_id") or "")))
    payload["assigned_to_me"] = bool(operator_id) and payload.get("assigned_operator_id") == operator_id
    return payload


# --------------------------------------------------------------- rotas públicas
@router.get("/config")
def support_config() -> Dict[str, Any]:
    """Configuração do widget + disponibilidade calculada em tempo real."""
    return support.widget_config(hub.operators_online())


@router.get("/widget.js", response_class=PlainTextResponse)
def support_widget_script() -> PlainTextResponse:
    """JavaScript do widget, autocontido (Shadow DOM), servido pela API."""
    if not WIDGET_PATH.is_file():
        raise HTTPException(status_code=404, detail="Widget indisponível.")
    javascript = WIDGET_PATH.read_text(encoding="utf-8")
    return PlainTextResponse(
        javascript,
        media_type="application/javascript; charset=utf-8",
        headers={"Cache-Control": "no-cache, must-revalidate"},
    )


@router.post("/visitors")
def support_bootstrap(
    payload: VisitorBootstrap,
    request: Request,
    current: Annotated[Optional[CurrentSession], Depends(optional_session)] = None,
) -> Dict[str, Any]:
    """Emite um token de visitante e atualiza a ficha (perfil + contexto)."""
    info = _client_info(request)
    visitor_id = support.clean_text(payload.visitor_id, 64)
    if visitor_id and not visitor_id.startswith("v_"):
        visitor_id = ""
    try:
        support.check_rate(f"bootstrap:{info['ip']}", limit=30, window_seconds=60)
    except support.SupportError as error:
        raise _auth_error(error) from error
    if not visitor_id:
        visitor_id = support.new_visitor_id()
    context = {**(payload.context or {}), **info}
    user = current.user.model_dump() if current else None
    try:
        support.touch_visitor(visitor_id, profile=payload.profile, context=context, user=user)
    except support.SupportError as error:
        raise _auth_error(error) from error
    return {
        "visitor_id": visitor_id,
        "token": _visitor_token(visitor_id),
        "config": support.widget_config(hub.operators_online()),
    }


@router.post("/sessions")
def support_start_session(payload: SessionStart, request: Request, visitor_id: VisitorId) -> Dict[str, Any]:
    """Abre (ou retoma) a conversa do visitante."""
    info = _client_info(request)
    try:
        support.check_rate(f"session:{visitor_id}", limit=10, window_seconds=3600)
        context = {**(payload.context or {}), **info}
        document, created = support.create_session(
            visitor_id,
            profile=payload.profile,
            context=context,
            subject=payload.subject,
        )
    except support.SupportError as error:
        raise _auth_error(error) from error
    messages = support.list_messages(document["session_id"], include_internal=False)
    return {
        "session": _public_session(document),
        "messages": messages,
        "created": created,
        "config": support.widget_config(hub.operators_online()),
    }


@router.get("/sessions/{session_id}")
def support_get_session(session_id: str, visitor_id: VisitorId) -> Dict[str, Any]:
    document = _owned_session(session_id, visitor_id)
    return {
        "session": _public_session(document),
        "messages": support.list_messages(session_id, include_internal=False),
        "tickets": support.list_session_tickets(session_id),
    }


@router.post("/sessions/{session_id}/messages")
async def support_send_message(
    session_id: str,
    payload: MessageIn,
    visitor_id: VisitorId,
) -> Dict[str, Any]:
    current_session = _owned_session(session_id, visitor_id)
    try:
        support.check_rate(f"message:{visitor_id}", limit=30, window_seconds=60)
        message = await run_in_threadpool(
            support.add_message,
            session_id,
            author_type=support.AUTHOR_VISITOR,
            author_id=visitor_id,
            author_name=str(current_session.get("visitor_name") or "Visitante"),
            body=payload.body,
            client_id=payload.client_id,
        )
    except support.SupportError as error:
        raise _auth_error(error) from error
    document = support.require_session(session_id)
    await hub.send_to_visitor(visitor_id, {"type": "message.created", "message": message})
    await hub.send_to_operators(
        {
            "type": "message.created",
            "message": message,
            "session": _public_session(document),
        }
    )
    return {"message": message, "session": _public_session(document)}


@router.post("/sessions/{session_id}/context")
async def support_update_context(session_id: str, payload: ContextIn, request: Request, visitor_id: VisitorId) -> Dict[str, Any]:
    _owned_session(session_id, visitor_id)
    info = _client_info(request)
    context = {**(payload.context or {}), **info}
    try:
        document = await run_in_threadpool(support.update_context, session_id, context, payload.profile)
    except support.SupportError as error:
        raise _auth_error(error) from error
    await hub.send_to_operators({"type": "session.updated", "session": _public_session(document)})
    return {"session": _public_session(document)}


@router.post("/sessions/{session_id}/read")
async def support_visitor_read(session_id: str, visitor_id: VisitorId) -> Dict[str, Any]:
    _owned_session(session_id, visitor_id)
    document = await run_in_threadpool(support.mark_read, session_id, "visitor")
    await hub.send_to_operators({"type": "session.updated", "session": _public_session(document)})
    return {"session": _public_session(document)}


@router.post("/sessions/{session_id}/ticket")
async def support_open_ticket(session_id: str, payload: TicketIn, visitor_id: VisitorId) -> Dict[str, Any]:
    document = _owned_session(session_id, visitor_id)
    try:
        ticket = await run_in_threadpool(
            support.create_ticket,
            session_id,
            subject=payload.subject,
            description=payload.description,
            category=payload.category,
            priority=payload.priority,
            requester={
                "name": document.get("visitor_name") or "Visitante",
                "email": document.get("visitor_email") or "",
                "user_id": document.get("user_id") or "",
            },
        )
    except support.SupportError as error:
        raise _auth_error(error) from error
    refreshed = support.require_session(session_id)
    await hub.send_to_visitor(visitor_id, {"type": "ticket.created", "ticket": ticket})
    await hub.send_to_operators(
        {"type": "ticket.created", "ticket": ticket, "session": _public_session(refreshed)}
    )
    return {"ticket": ticket, "session": _public_session(refreshed)}


@router.post("/sessions/{session_id}/forms/{message_id}")
async def support_submit_form(
    session_id: str,
    message_id: str,
    payload: FormResponseIn,
    visitor_id: VisitorId,
) -> Dict[str, Any]:
    """Guarda a resposta do visitante a um formulário enviado pelo operador."""
    document = _owned_session(session_id, visitor_id)
    try:
        support.check_rate(f"form:{visitor_id}", limit=20, window_seconds=60)
        message, response = await run_in_threadpool(
            support.submit_form_response,
            session_id,
            message_id,
            payload.values,
            visitor_id=visitor_id,
            visitor_name=str(document.get("visitor_name") or "Visitante"),
            visitor_email=str(document.get("visitor_email") or ""),
        )
    except support.SupportError as error:
        raise _auth_error(error) from error
    refreshed = support.require_session(session_id)
    await hub.send_to_visitor(
        visitor_id,
        {
            "type": "form.submitted",
            "message": message,
            "response": response,
            "session": support.public_session(refreshed),
        },
    )
    await hub.send_to_operators(
        {
            "type": "form.submitted",
            "message": message,
            "response": response,
            "session": _public_session(refreshed),
        }
    )
    return {"message": message, "response": response, "session": _public_session(refreshed)}


@router.post("/sessions/{session_id}/rate")
def support_rate_session(session_id: str, payload: RatingIn, visitor_id: VisitorId) -> Dict[str, Any]:
    _owned_session(session_id, visitor_id)
    try:
        document = support.rate_session(session_id, payload.rating, payload.comment)
    except support.SupportError as error:
        raise _auth_error(error) from error
    return {"session": _public_session(document)}


@router.post("/sessions/{session_id}/close")
async def support_close_session(session_id: str, visitor_id: VisitorId) -> Dict[str, Any]:
    _owned_session(session_id, visitor_id)
    document = await run_in_threadpool(
        support.close_session,
        session_id,
        actor_type=support.AUTHOR_VISITOR,
        actor_id=visitor_id,
        actor_name="Visitante",
        reason="O visitante fechou a conversa",
    )
    await hub.send_to_visitor(visitor_id, {"type": "session.closed", "session": support.public_session(document)})
    await hub.send_to_operators({"type": "session.closed", "session": _public_session(document)})
    return {"session": _public_session(document)}


# ---------------------------------------------------------------- rotas admin
@admin_router.get("/overview")
def admin_support_overview() -> Dict[str, Any]:
    data = support.overview()
    data["operators_online"] = hub.operators_online()
    for operator in data.get("operators") or []:
        operator["live_status"] = hub.status_of(str(operator.get("id") or ""))
    return data


@admin_router.get("/sessions")
def admin_support_sessions(
    current: AdminSession,
    status: str = Query("", description="waiting | active | closed | open"),
    q: str = Query(""),
    assigned: str = Query(""),
    unread: bool = Query(False),
    from_: int = Query(0, alias="from", ge=0),
    size: int = Query(50, ge=1, le=100),
) -> Dict[str, Any]:
    try:
        result = support.list_sessions(
            status=status,
            q=q,
            assigned=assigned,
            operator_id=current.user.id,
            unread=unread,
            from_=from_,
            size=size,
        )
    except support.SupportError as error:
        raise _auth_error(error) from error
    result["items"] = [_public_session(item, operator_id=current.user.id) for item in result.get("items") or []]
    return result


@admin_router.get("/sessions/{session_id}")
def admin_support_session_detail(session_id: str, current: AdminSession) -> Dict[str, Any]:
    try:
        document = support.require_session(session_id)
    except support.SupportError as error:
        raise _auth_error(error) from error
    account = None
    user_id = str(document.get("user_id") or "")
    if user_id:
        user = auth.get_user_by_id(user_id)
        account = auth.public_user(user) if user else None
    return {
        "session": _public_session(document, operator_id=current.user.id),
        "messages": support.list_messages(session_id, include_internal=True),
        "tickets": support.list_session_tickets(session_id),
        "form_responses": support.list_form_responses(session_id),
        "events": support.list_events(session_id=session_id, size=60)["items"],
        "account": account,
        "visitor": support.get_visitor(str(document.get("visitor_id") or "")),
    }


@admin_router.post("/sessions/{session_id}/claim")
async def admin_support_claim(session_id: str, current: AdminSession) -> Dict[str, Any]:
    operator = _operator_of(current)
    try:
        document = await run_in_threadpool(support.claim_session, session_id, operator["id"], operator["name"])
    except support.SupportError as error:
        raise _auth_error(error) from error
    await hub.send_to_visitor(
        str(document.get("visitor_id") or ""),
        {
            "type": "operator.joined",
            "operator": {"name": operator["name"]},
            "session": support.public_session(document),
        },
    )
    await hub.send_to_operators({"type": "session.updated", "session": _public_session(document, operator_id=operator["id"])})
    return {"session": _public_session(document, operator_id=operator["id"])}


@admin_router.post("/sessions/{session_id}/release")
async def admin_support_release(session_id: str, current: AdminSession) -> Dict[str, Any]:
    operator = _operator_of(current)
    try:
        document = await run_in_threadpool(support.release_session, session_id, operator["id"], operator["name"])
    except support.SupportError as error:
        raise _auth_error(error) from error
    await hub.send_to_operators({"type": "session.updated", "session": _public_session(document)})
    return {"session": _public_session(document)}


@admin_router.post("/sessions/{session_id}/close")
async def admin_support_close(session_id: str, current: AdminSession) -> Dict[str, Any]:
    operator = _operator_of(current)
    try:
        document = await run_in_threadpool(
            support.close_session,
            session_id,
            actor_type=support.AUTHOR_OPERATOR,
            actor_id=operator["id"],
            actor_name=operator["name"],
            reason=f"Conversa fechada por {operator['name']}",
        )
    except support.SupportError as error:
        raise _auth_error(error) from error
    await hub.send_to_visitor(
        str(document.get("visitor_id") or ""),
        {"type": "session.closed", "session": support.public_session(document)},
    )
    await hub.send_to_operators({"type": "session.closed", "session": _public_session(document)})
    return {"session": _public_session(document)}


@admin_router.post("/sessions/{session_id}/read")
def admin_support_read(session_id: str) -> Dict[str, Any]:
    try:
        document = support.mark_read(session_id, "operator")
    except support.SupportError as error:
        raise _auth_error(error) from error
    return {"session": _public_session(document)}


@admin_router.post("/sessions/{session_id}/messages")
async def admin_support_message(session_id: str, payload: AdminMessageIn, current: AdminSession) -> Dict[str, Any]:
    operator = _operator_of(current)
    try:
        document = await run_in_threadpool(support.require_session, session_id)
        if not document.get("assigned_operator_id"):
            document = await run_in_threadpool(support.claim_session, session_id, operator["id"], operator["name"])
        if payload.kind != support.MESSAGE_TEXT:
            message = await run_in_threadpool(
                support.send_rich_message,
                session_id,
                kind=payload.kind,
                payload=payload.payload,
                author_id=operator["id"],
                author_name=operator["name"],
                client_id=payload.client_id,
                internal=payload.internal,
            )
        else:
            message = await run_in_threadpool(
                support.add_message,
                session_id,
                author_type=support.AUTHOR_OPERATOR,
                author_id=operator["id"],
                author_name=operator["name"],
                body=payload.body,
                client_id=payload.client_id,
                internal=payload.internal,
            )
    except support.SupportError as error:
        raise _auth_error(error) from error
    document = await run_in_threadpool(support.require_session, session_id)
    if not payload.internal:
        await hub.send_to_visitor(
            str(document.get("visitor_id") or ""),
            {"type": "message.created", "message": message, "session": support.public_session(document)},
        )
    await hub.send_to_operators(
        {
            "type": "message.created",
            "message": message,
            "session": _public_session(document, operator_id=operator["id"]),
        }
    )
    return {"message": message, "session": _public_session(document, operator_id=operator["id"])}


@admin_router.post("/sessions/{session_id}/ticket")
async def admin_support_create_ticket(session_id: str, payload: TicketIn, current: AdminSession) -> Dict[str, Any]:
    operator = _operator_of(current)
    try:
        document = await run_in_threadpool(support.require_session, session_id)
        ticket = await run_in_threadpool(
            support.create_ticket,
            session_id,
            subject=payload.subject,
            description=payload.description,
            category=payload.category,
            priority=payload.priority,
            requester={
                "name": document.get("visitor_name") or "Visitante",
                "email": document.get("visitor_email") or "",
                "user_id": document.get("user_id") or "",
            },
            operator_id=operator["id"],
            operator_name=operator["name"],
        )
    except support.SupportError as error:
        raise _auth_error(error) from error
    refreshed = await run_in_threadpool(support.require_session, session_id)
    ticket_payload = ticket
    await hub.send_to_visitor(
        str(refreshed.get("visitor_id") or ""),
        {"type": "ticket.created", "ticket": ticket_payload, "session": support.public_session(refreshed)},
    )
    await hub.send_to_operators(
        {"type": "ticket.created", "ticket": ticket_payload, "session": _public_session(refreshed, operator_id=operator["id"])}
    )
    return {"ticket": ticket_payload, "session": _public_session(refreshed, operator_id=operator["id"])}


@admin_router.get("/reports")
def admin_support_reports(q: str = Query(""), limit: int = Query(40, ge=1, le=100)) -> Dict[str, Any]:
    """Relatórios que o operador pode enviar para a conversa.

    Usa a biblioteca pública (pacotes e documentos publicados): o link enviado é
    o download público quando o documento é gratuito, ou a página do catálogo
    quando é pago — nunca uma rota interna do Estúdio.
    """
    try:
        from api import reports_library  # noqa: PLC0415 - evita ciclo no arranque

        items = reports_library.items(include_paid=True)
    except Exception as exc:  # noqa: BLE001
        logger.debug("Apoio: relatórios indisponíveis: %s", exc)
        return {"items": [], "total": 0}
    needle = str(q or "").strip().lower()
    result: List[Dict[str, Any]] = []
    for item in items:
        title = str(item.get("title") or "")
        subtitle = str(item.get("subtitle") or "")
        summary = str(item.get("note") or "") or subtitle
        haystack = " ".join(
            [title, subtitle, summary, str(item.get("area_label") or ""), str(item.get("kind_label") or "")]
        ).lower()
        if needle and needle not in haystack:
            continue
        result.append(
            {
                "report_id": str(item.get("ref") or ""),
                "title": title,
                "subtitle": subtitle,
                "summary": summary,
                "url": str(item.get("download") or item.get("href") or "/reports"),
                "free": bool(item.get("free")),
                "kind": str(item.get("kind") or ""),
                "kind_label": str(item.get("kind_label") or ""),
                "area": str(item.get("area_label") or ""),
                "price": item.get("price") or 0,
            }
        )
        if len(result) >= limit:
            break
    return {"items": result, "total": len(result)}


@admin_router.get("/forms")
def admin_support_form_templates() -> Dict[str, Any]:
    """Modelos de formulário prontos e tipos de campo aceites."""
    return {
        "templates": list(support.FORM_TEMPLATES),
        "field_types": list(support.FORM_FIELD_TYPES),
        "max_fields": support.FORM_MAX_FIELDS,
    }


@admin_router.get("/tickets")
def admin_support_tickets(
    status: str = Query(""),
    q: str = Query(""),
    session_id: str = Query(""),
    from_: int = Query(0, alias="from", ge=0),
    size: int = Query(50, ge=1, le=100),
) -> Dict[str, Any]:
    try:
        return support.list_tickets(status=status, q=q, session_id=session_id, from_=from_, size=size)
    except support.SupportError as error:
        raise _auth_error(error) from error


@admin_router.patch("/tickets/{ticket_id}")
def admin_support_ticket_patch(ticket_id: str, payload: TicketPatch, current: AdminSession) -> Dict[str, Any]:
    operator = _operator_of(current)
    try:
        ticket = support.update_ticket(
            ticket_id,
            status=payload.status,
            priority=payload.priority,
            category=payload.category,
            note=payload.note,
            actor_id=operator["id"],
            actor_name=operator["name"],
        )
    except support.SupportError as error:
        raise _auth_error(error) from error
    return {"ticket": ticket}


@admin_router.get("/events")
def admin_support_events(
    session_id: str = Query(""),
    from_: int = Query(0, alias="from", ge=0),
    size: int = Query(50, ge=1, le=200),
) -> Dict[str, Any]:
    try:
        return support.list_events(session_id=session_id, from_=from_, size=size)
    except support.SupportError as error:
        raise _auth_error(error) from error


@admin_router.get("/operators")
def admin_support_operators() -> Dict[str, Any]:
    operators = support.list_operators()
    for operator in operators:
        operator["live_status"] = hub.status_of(str(operator.get("id") or ""))
    return {
        "items": operators,
        "operators_online": hub.operators_online(),
        "connected": sorted(hub.online_operator_ids()),
    }


@admin_router.post("/operators/me")
def admin_support_operator_status(payload: OperatorStatusIn, current: AdminSession) -> Dict[str, Any]:
    operator = _operator_of(current)
    try:
        document = support.set_operator_status(operator, payload.status)
    except support.SupportError as error:
        raise _auth_error(error) from error
    hub.set_status(operator["id"], payload.status)
    return {"operator": {**document, "live_status": payload.status}}


# ------------------------------------------------------------------- websocket
async def _send_error(websocket: WebSocket, message: str) -> None:
    await hub.send(websocket, {"type": "error", "message": message})


@router.websocket("/ws")
async def support_websocket(
    websocket: WebSocket,
    role: str = Query("visitor"),
    token: str = Query(""),
    session_id: str = Query(""),
) -> None:
    if role == "operator":
        await _operator_socket(websocket, token)
    else:
        await _visitor_socket(websocket, token, session_id)


async def _visitor_socket(websocket: WebSocket, token: str, session_id: str) -> None:
    try:
        visitor_id = _visitor_from_token(token)
    except HTTPException:
        await websocket.close(code=4401, reason="Token de visitante inválido")
        return

    await websocket.accept()
    await hub.add_visitor(visitor_id, websocket)
    document: Optional[Dict[str, Any]] = None
    if session_id:
        try:
            document = support.require_session(session_id)
        except support.SupportError:
            document = None
    if document and str(document.get("visitor_id") or "") == visitor_id:
        await websocket.send_json(
            {
                "type": "ready",
                "visitor_id": visitor_id,
                "session": support.public_session(document, online=True),
                "messages": support.list_messages(session_id, include_internal=False),
            }
        )
        await run_in_threadpool(support.touch_session_presence, session_id)
        await hub.send_to_operators({"type": "session.updated", "session": _public_session(document)})
    else:
        document = None
        await websocket.send_json(
            {
                "type": "ready",
                "visitor_id": visitor_id,
                "session": None,
                "messages": [],
                "config": support.widget_config(hub.operators_online()),
            }
        )

    try:
        while True:
            payload = await websocket.receive_json()
            if not isinstance(payload, dict):
                continue
            kind = str(payload.get("type") or "")
            if kind == "ping":
                await hub.send(websocket, {"type": "pong"})
                continue
            # O widget pode começar uma conversa nova na mesma ligação (por
            # exemplo depois de a anterior ser fechada). Nesse caso o
            # `session_id` do evento passa a ser a fonte de verdade — sem isto
            # a mensagem ia para a sessão antiga e voltava «já está fechada».
            requested_id = str(payload.get("session_id") or session_id or "")
            if requested_id and (
                not document or requested_id != str(document.get("session_id") or "")
            ):
                try:
                    candidate = support.require_session(requested_id)
                    if str(candidate.get("visitor_id") or "") == visitor_id:
                        document = candidate
                except support.SupportError:
                    pass
            if not document:
                await _send_error(websocket, "Abra uma conversa antes de enviar mensagens.")
                continue
            current_session = document
            if kind == "message":
                try:
                    support.check_rate(f"ws-message:{visitor_id}", limit=30, window_seconds=60)
                    message = await run_in_threadpool(
                        support.add_message,
                        current_session["session_id"],
                        author_type=support.AUTHOR_VISITOR,
                        author_id=visitor_id,
                        author_name=str(current_session.get("visitor_name") or "Visitante"),
                        body=str(payload.get("body") or ""),
                        client_id=str(payload.get("client_id") or ""),
                    )
                except support.SupportError as error:
                    await _send_error(websocket, error.message)
                    continue
                updated = support.require_session(current_session["session_id"])
                document = updated
                await hub.send_to_visitor(
                    visitor_id,
                    {"type": "message.created", "message": message, "session": support.public_session(updated, online=True)},
                )
                await hub.send_to_operators(
                    {"type": "message.created", "message": message, "session": _public_session(updated)}
                )
            elif kind == "typing":
                await hub.send_to_operators(
                    {
                        "type": "typing",
                        "session_id": current_session["session_id"],
                        "actor": "visitor",
                        "name": str(current_session.get("visitor_name") or "Visitante"),
                    }
                )
            elif kind == "context":
                try:
                    document = await run_in_threadpool(
                        support.update_context,
                        current_session["session_id"],
                        payload.get("context") or {},
                        payload.get("profile"),
                    )
                except support.SupportError as error:
                    await _send_error(websocket, error.message)
                    continue
                await hub.send_to_operators({"type": "session.updated", "session": _public_session(document)})
            elif kind == "read":
                document = await run_in_threadpool(support.mark_read, current_session["session_id"], "visitor")
                await hub.send_to_operators({"type": "session.updated", "session": _public_session(document)})
            elif kind == "close":
                document = await run_in_threadpool(
                    support.close_session,
                    current_session["session_id"],
                    actor_type=support.AUTHOR_VISITOR,
                    actor_id=visitor_id,
                    actor_name="Visitante",
                    reason="O visitante fechou a conversa",
                )
                await hub.send_to_visitor(
                    visitor_id,
                    {"type": "session.closed", "session": support.public_session(document)},
                )
                await hub.send_to_operators({"type": "session.closed", "session": _public_session(document)})
    except WebSocketDisconnect:
        pass
    except Exception as exc:  # noqa: BLE001 - não deixar cair o processo
        logger.debug("Apoio WS visitante: %s", exc)
    finally:
        removed = await hub.remove_visitor(websocket)
        if removed and document:
            try:
                refreshed = await run_in_threadpool(support.require_session, str(document.get("session_id")))
                await hub.send_to_operators({"type": "session.updated", "session": _public_session(refreshed)})
                await hub.send_to_operators(
                    {"type": "visitor.offline", "session_id": document.get("session_id"), "visitor_id": removed}
                )
            except Exception:  # noqa: BLE001
                pass


async def _operator_socket(websocket: WebSocket, token: str) -> None:
    operator = _operator_from_token(token)
    if not operator:
        await websocket.close(code=4401, reason="Sessão de administração inválida")
        return

    await websocket.accept()
    operator_id = str(operator.get("id") or operator.get("email") or "")
    operator_name = str(operator.get("name") or operator.get("email") or "Operador")
    await hub.add_operator(operator_id, websocket)
    await run_in_threadpool(support.upsert_operator, operator, status=support.OPERATOR_ONLINE)
    await hub.send(
        websocket,
        {
            "type": "ready",
            "operator": {"id": operator_id, "name": operator_name, "email": operator.get("email")},
            "overview": await run_in_threadpool(support.overview),
            "operators_online": hub.operators_online(),
        },
    )
    await hub.send_to_operators(hub.presence())

    try:
        while True:
            payload = await websocket.receive_json()
            if not isinstance(payload, dict):
                continue
            kind = str(payload.get("type") or "")
            if kind == "ping":
                await hub.send(websocket, {"type": "pong"})
                continue
            if kind == "status":
                status = str(payload.get("status") or support.OPERATOR_ONLINE)
                try:
                    await run_in_threadpool(support.set_operator_status, operator, status)
                except support.SupportError as error:
                    await _send_error(websocket, error.message)
                    continue
                hub.set_status(operator_id, status)
                await hub.send_to_operators(hub.presence())
                continue
            session_id = str(payload.get("session_id") or "")
            if not session_id:
                await _send_error(websocket, "Conversa em falta.")
                continue
            try:
                document = support.require_session(session_id)
            except support.SupportError as error:
                await _send_error(websocket, error.message)
                continue

            if kind == "message":
                try:
                    if not document.get("assigned_operator_id"):
                        document = await run_in_threadpool(
                            support.claim_session, session_id, operator_id, operator_name
                        )
                    message_kind = str(payload.get("kind") or support.MESSAGE_TEXT)
                    if message_kind != support.MESSAGE_TEXT:
                        message = await run_in_threadpool(
                            support.send_rich_message,
                            session_id,
                            kind=message_kind,
                            payload=payload.get("payload") if isinstance(payload.get("payload"), dict) else {},
                            author_id=operator_id,
                            author_name=operator_name,
                            client_id=str(payload.get("client_id") or ""),
                            internal=bool(payload.get("internal")),
                        )
                    else:
                        message = await run_in_threadpool(
                            support.add_message,
                            session_id,
                            author_type=support.AUTHOR_OPERATOR,
                            author_id=operator_id,
                            author_name=operator_name,
                            body=str(payload.get("body") or ""),
                            client_id=str(payload.get("client_id") or ""),
                            internal=bool(payload.get("internal")),
                        )
                except support.SupportError as error:
                    await _send_error(websocket, error.message)
                    continue
                updated = support.require_session(session_id)
                if not message.get("internal"):
                    await hub.send_to_visitor(
                        str(updated.get("visitor_id") or ""),
                        {
                            "type": "message.created",
                            "message": message,
                            "session": support.public_session(updated),
                        },
                    )
                await hub.send_to_operators(
                    {
                        "type": "message.created",
                        "message": message,
                        "session": _public_session(updated, operator_id=operator_id),
                    }
                )
            elif kind == "typing":
                await hub.send_to_visitor(
                    str(document.get("visitor_id") or ""),
                    {
                        "type": "typing",
                        "session_id": session_id,
                        "actor": "operator",
                        "name": operator_name,
                    },
                )
            elif kind == "read":
                updated = await run_in_threadpool(support.mark_read, session_id, "operator")
                await hub.send_to_operators(
                    {"type": "session.updated", "session": _public_session(updated, operator_id=operator_id)}
                )
            elif kind == "claim":
                updated = await run_in_threadpool(support.claim_session, session_id, operator_id, operator_name)
                await hub.send_to_visitor(
                    str(updated.get("visitor_id") or ""),
                    {
                        "type": "operator.joined",
                        "operator": {"name": operator_name},
                        "session": support.public_session(updated),
                    },
                )
                await hub.send_to_operators(
                    {"type": "session.updated", "session": _public_session(updated, operator_id=operator_id)}
                )
            elif kind == "release":
                try:
                    updated = await run_in_threadpool(
                        support.release_session, session_id, operator_id, operator_name
                    )
                except support.SupportError as error:
                    await _send_error(websocket, error.message)
                    continue
                await hub.send_to_operators(
                    {"type": "session.updated", "session": _public_session(updated, operator_id=operator_id)}
                )
            elif kind == "close":
                updated = await run_in_threadpool(
                    support.close_session,
                    session_id,
                    actor_type=support.AUTHOR_OPERATOR,
                    actor_id=operator_id,
                    actor_name=operator_name,
                    reason=f"Conversa fechada por {operator_name}",
                )
                await hub.send_to_visitor(
                    str(updated.get("visitor_id") or ""),
                    {"type": "session.closed", "session": support.public_session(updated)},
                )
                await hub.send_to_operators({"type": "session.closed", "session": _public_session(updated)})
    except WebSocketDisconnect:
        pass
    except Exception as exc:  # noqa: BLE001
        logger.debug("Apoio WS operador: %s", exc)
    finally:
        await hub.remove_operator(websocket)
        if not hub.has_operator_sockets(operator_id):
            try:
                await run_in_threadpool(support.set_operator_status, operator, support.OPERATOR_OFFLINE)
            except Exception:  # noqa: BLE001
                pass
        await hub.send_to_operators(hub.presence())
