"""Rotas do Correio da plataforma (`/admin/mail/*`).

O gestor do correio da própria solução, exclusivo de contas com o papel `admin`:
as caixas do domínio da plataforma (a que envia o email transacional, o
`postmaster@`, o `dmarc@` e as que a administração acrescentar), a lista e a
leitura das mensagens, a pesquisa sobre o índice, as conversas, o envio com
editor e anexos, e o panorama do que está arquivado.

- `GET    /admin/mail/meta`                        — servidores, pastas e limites
- `GET    /admin/mail/stats`                       — panorama das caixas e do índice
- `GET    /admin/mail/settings`                    — sincronização automática
- `PUT    /admin/mail/settings`                    — alterar essa agenda
- `GET    /admin/mail/accounts`                    — caixas de correio (sem segredos)
- `POST   /admin/mail/accounts`                    — criar/alterar uma caixa
- `POST   /admin/mail/accounts/test`               — testar credenciais sem guardar
- `DELETE /admin/mail/accounts/{account_id}`       — remover uma caixa
- `GET    /admin/mail/accounts/{account_id}/folders` — pastas, contagens e último UID
- `POST   /admin/mail/sync`                        — sincronizar (uma caixa ou todas)
- `GET    /admin/mail/messages`                    — lista/pesquisa (Elasticsearch)
- `GET    /admin/mail/messages/{message_id}`       — mensagem completa (IMAP)
- `POST   /admin/mail/messages/{message_id}/flags` — lida/não lida, destacada
- `POST   /admin/mail/messages/{message_id}/move`  — mover para outra pasta
- `DELETE /admin/mail/messages/{message_id}`       — apagar
- `POST   /admin/mail/send`                        — enviar (novo ou resposta)

Todas as acções ficam registadas como eventos de auditoria (origem `admin`,
`data.module = "mail"`), porque mexer no correio da plataforma é uma operação
sensível.
"""
from __future__ import annotations

import logging
from typing import Annotated, Any, Dict, Optional

from fastapi import APIRouter, Body, HTTPException, Query

from api import events_service as events
from api import platform_mail_service as service
from api.admin_routes import AdminSession

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/admin/mail", tags=["admin", "mail"])


def _fail(exc: service.MailError) -> HTTPException:
    """Erro do domínio do correio → resposta HTTP."""
    return HTTPException(status_code=exc.status, detail=exc.message)


def _audit(session: Any, message: str, **data: Any) -> None:
    """Registo de auditoria das operações sobre o correio (nunca falha)."""
    try:
        events.log_event(
            "info",
            "admin",
            f"Correio: {message}",
            data={"module": "mail", **data},
            user_id=getattr(getattr(session, "user", None), "id", None),
            user_email=getattr(getattr(session, "user", None), "email", None),
        )
    except Exception as error:  # noqa: BLE001 - a auditoria não pode travar a operação
        logger.debug("Evento de auditoria do correio falhou: %s", error)


# ------------------------------------------------------------------ metadados
@router.get("/meta")
def meta(session: AdminSession) -> Dict[str, Any]:
    """O que a aplicação precisa: servidores, pastas a sincronizar e limites."""
    return service.meta()


@router.get("/stats")
def stats(session: AdminSession) -> Dict[str, Any]:
    """Panorama: mensagens por pasta, por ler, destaques, remetentes e por caixa."""
    return service.stats()


@router.get("/settings")
def get_settings(session: AdminSession) -> Dict[str, Any]:
    """Agenda da sincronização automática (intervalo em segundos)."""
    return service.settings()


@router.put("/settings")
def put_settings(session: AdminSession, payload: Dict[str, Any] = Body(...)) -> Dict[str, Any]:
    """Altera a agenda da sincronização automática (`sync_seconds`, `auto_sync`)."""
    try:
        resultado = service.save_settings(payload, utilizador=getattr(session.user, "email", None))
    except service.MailError as exc:
        raise _fail(exc)
    # A agenda nova vale já: o agendador relê o intervalo sem reiniciar a API.
    try:
        from api import platform_mail_scheduler

        platform_mail_scheduler.reload_jobs()
    except Exception as error:  # noqa: BLE001 - sem agendador a sincronização manual continua
        logger.debug("Não foi possível recarregar o agendador do correio: %s", error)
    _audit(session, "agenda da sincronização alterada", settings=resultado.get("settings"))
    return resultado


# --------------------------------------------------------------------- caixas
@router.get("/accounts")
def list_accounts(session: AdminSession) -> Dict[str, Any]:
    """Caixas de correio da plataforma (a palavra-passe nunca sai daqui)."""
    itens = [service.public_account(conta) for conta in service.accounts()]
    return {"total": len(itens), "items": itens}


@router.post("/accounts")
def save_account(session: AdminSession, payload: Dict[str, Any] = Body(...)) -> Dict[str, Any]:
    """Cria ou altera uma caixa (`email_address`, `password`, servidores opcionais)."""
    try:
        resultado = service.save_account(payload, utilizador=getattr(session.user, "email", None))
    except service.MailError as exc:
        raise _fail(exc)
    _audit(session, "caixa de correio guardada", account=resultado["account"].get("id"))
    return resultado


@router.post("/accounts/test")
def test_account(session: AdminSession, payload: Dict[str, Any] = Body(...)) -> Dict[str, Any]:
    """Testa as credenciais de uma caixa (guardada por `id`, ou de um rascunho)."""
    try:
        return service.test_account(payload)
    except service.MailError as exc:
        raise _fail(exc)


@router.delete("/accounts/{account_id}")
def delete_account(account_id: str, session: AdminSession) -> Dict[str, Any]:
    """Remove uma caixa (o correio no servidor não é tocado)."""
    try:
        resultado = service.delete_account(account_id)
    except service.MailError as exc:
        raise _fail(exc)
    _audit(session, "caixa de correio removida", account=account_id)
    return resultado


@router.get("/accounts/{account_id}/folders")
def folders(account_id: str, session: AdminSession) -> Dict[str, Any]:
    """Pastas da caixa, com as contagens do servidor e do que está indexado."""
    try:
        return service.folders(account_id)
    except service.MailError as exc:
        raise _fail(exc)


# ------------------------------------------------------------------ sincronizar
@router.post("/sync")
def sync(session: AdminSession, payload: Optional[Dict[str, Any]] = Body(None)) -> Dict[str, Any]:
    """Sincroniza as caixas com o índice.

    Sem `account` sincroniza todas as caixas ligadas; `full=true` relê as pastas
    desde o início (útil na primeira vez ou depois de limpar o índice).
    """
    corpo = payload or {}
    try:
        resultado = service.sync(corpo.get("account"), full=bool(corpo.get("full")))
    except service.MailError as exc:
        raise _fail(exc)
    _audit(
        session,
        "sincronização executada",
        account=corpo.get("account") or "todas",
        full=bool(corpo.get("full")),
        indexed=resultado.get("indexed"),
        errors=resultado.get("errors"),
    )
    return resultado


# ------------------------------------------------------------------- mensagens
@router.get("/messages")
def list_messages(
    session: AdminSession,
    account: Optional[str] = Query(None, description="Identificador da caixa"),
    folder: Optional[str] = Query(None, description="Pasta (INBOX, Sent, …)"),
    q: Optional[str] = Query(None, description="Pesquisa por assunto, corpo ou remetente"),
    sender: Optional[str] = Query(None, description="Email exato do remetente"),
    thread: Optional[str] = Query(None, description="Chave da conversa"),
    direction: Optional[str] = Query(None, description="in | out"),
    unseen: Optional[bool] = Query(None, description="Só por ler"),
    flagged: Optional[bool] = Query(None, description="Só destacadas"),
    attachments: Optional[bool] = Query(None, description="Só com anexos"),
    exclude_drafts: bool = Query(True, description="Deixar de fora os rascunhos"),
    date_from: Optional[str] = Query(None, description="Data mínima (ISO)"),
    date_to: Optional[str] = Query(None, description="Data máxima (ISO)"),
    sort: Optional[str] = Query(None, description="date_desc | date_asc | sender | subject | size"),
    limit: int = Query(50, ge=1, le=service.MAX_LIMIT),
    offset: int = Query(0, ge=0),
) -> Dict[str, Any]:
    """Lista/pesquisa o arquivo de correio (Elasticsearch; IMAP se não houver índice)."""
    parametros = {
        "account": account,
        "folder": folder,
        "q": q,
        "sender": sender,
        "thread": thread,
        "direction": direction,
        "unseen": unseen,
        "flagged": flagged,
        "attachments": attachments,
        "exclude_drafts": exclude_drafts,
        "date_from": date_from,
        "date_to": date_to,
        "sort": sort,
        "limit": limit,
        "offset": offset,
    }
    try:
        return service.list_messages(parametros)
    except service.MailError as exc:
        raise _fail(exc)


@router.get("/messages/{message_id:path}")
def get_message(
    message_id: str,
    session: AdminSession,
    mark_read: bool = Query(True, description="Marcar como lida ao abrir"),
) -> Dict[str, Any]:
    """Mensagem completa (texto, HTML e anexos)."""
    try:
        return service.get_message(message_id, mark_read=mark_read)
    except service.MailError as exc:
        raise _fail(exc)


@router.post("/messages/{message_id:path}/flags")
def set_flags(
    message_id: str,
    session: AdminSession,
    payload: Dict[str, Any] = Body(...),
) -> Dict[str, Any]:
    """Muda um sinalizador: `read`, `unread`, `flag` ou `unflag`."""
    action = str((payload or {}).get("action") or "read")
    try:
        return service.set_flags(message_id, action)
    except service.MailError as exc:
        raise _fail(exc)


@router.post("/messages/{message_id:path}/move")
def move_message(
    message_id: str,
    session: AdminSession,
    payload: Dict[str, Any] = Body(...),
) -> Dict[str, Any]:
    """Move a mensagem para outra pasta (`target`)."""
    target = str((payload or {}).get("target") or "").strip()
    if not target:
        raise HTTPException(status_code=422, detail="Indique a pasta de destino.")
    try:
        resultado = service.move_message(message_id, target)
    except service.MailError as exc:
        raise _fail(exc)
    _audit(session, "mensagem movida", message=message_id, to=target)
    return resultado


@router.delete("/messages/{message_id:path}")
def delete_message(message_id: str, session: AdminSession) -> Dict[str, Any]:
    """Apaga a mensagem (na caixa e no índice)."""
    try:
        resultado = service.delete_message(message_id)
    except service.MailError as exc:
        raise _fail(exc)
    _audit(session, "mensagem apagada", message=message_id)
    return resultado


# ----------------------------------------------------------------------- envio
@router.post("/send")
def send(session: AdminSession, payload: Dict[str, Any] = Body(...)) -> Dict[str, Any]:
    """Envia uma mensagem por uma das caixas (assinatura, anexos e encadeamento).

    A cópia enviada fica arquivada na pasta *Sent* da caixa e entra no índice.
    """
    try:
        resultado = service.send(payload)
    except service.MailError as exc:
        raise _fail(exc)
    _audit(
        session,
        "mensagem enviada",
        account=resultado.get("account", {}).get("id"),
        to=resultado.get("to"),
        subject=resultado.get("subject"),
    )
    return resultado
