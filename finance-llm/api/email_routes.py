"""Rotas do Email IQ OS (`/email/*`).

A caixa de correio dentro da plataforma: contas Gmail, Outlook/Microsoft 365,
iCloud, Yahoo, Zoho, SAPO ou qualquer servidor IMAP/SMTP; pastas, lista de
mensagens, leitura, sinalizadores, envio e resposta.

Tudo requer sessão — a caixa de correio é pessoal e as contas são guardadas por
utilizador.

- `GET    /email/meta`                              — fornecedores suportados e ajuda
- `GET    /email/stats`                             — panorama das contas do utilizador
- `GET    /email/accounts`                          — contas (sem segredos)
- `POST   /email/accounts`                          — criar/alterar conta
- `POST   /email/accounts/test`                     — testar credenciais sem guardar
- `POST   /email/accounts/{id}/test`                — testar uma conta guardada
- `DELETE /email/accounts/{id}`                     — remover conta
- `GET    /email/accounts/{id}/folders`             — pastas e contagens
- `GET    /email/accounts/{id}/messages`            — lista (pasta, pesquisa, não lidas)
- `GET    /email/accounts/{id}/messages/{uid}`      — mensagem completa
- `POST   /email/accounts/{id}/messages/{uid}/flags`— lida/não lida, destacada
- `POST   /email/accounts/{id}/messages/{uid}/move` — mover para outra pasta
- `DELETE /email/accounts/{id}/messages/{uid}`      — apagar
- `POST   /email/accounts/{id}/send`                — enviar (novo ou resposta)
"""
from __future__ import annotations

import logging
from typing import Annotated, Any, Dict, Optional

from fastapi import APIRouter, Body, Depends, HTTPException, Query

from api import email_service as service
from api.auth_routes import CurrentSession, optional_session

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/email", tags=["email"])

Session = Annotated[Optional[CurrentSession], Depends(optional_session)]


def _owner(session: Optional[CurrentSession]) -> str:
    if not session:
        raise HTTPException(status_code=401, detail="Entrar na plataforma para usar o Email.")
    return session.user.email


def _fail(exc: service.EmailError) -> HTTPException:
    return HTTPException(status_code=exc.status, detail=exc.message)


def _account(owner: str, account_id: str) -> Dict[str, Any]:
    try:
        return service.get_account(owner, account_id)
    except service.EmailError as exc:
        raise _fail(exc)


# ------------------------------------------------------------------ metadados
@router.get("/meta")
def meta() -> Dict[str, Any]:
    """Fornecedores suportados (servidores, portas e ajuda) e o que a app faz."""
    catalog = service.provider_catalog()
    return {
        **catalog,
        "about": {
            "name": "Email",
            "description": (
                "A caixa de correio do IQ OS: ligue o Gmail, o Outlook/Microsoft 365, o iCloud, "
                "o Yahoo, o SAPO ou qualquer servidor IMAP/SMTP e leia, organize e escreva correio "
                "sem sair da plataforma."
            ),
            "capabilities": ["read", "search", "folders", "flags", "move", "delete", "send", "reply", "attachments"],
            "security_modes": list(service.SECURITY_MODES),
        },
    }


@router.get("/stats")
def stats(session: Session = None) -> Dict[str, Any]:
    """Panorama das contas do utilizador: quantas, por fornecedor e último erro."""
    return service.stats(_owner(session))


# --------------------------------------------------------------------- contas
@router.get("/accounts")
def list_accounts(session: Session = None) -> Dict[str, Any]:
    """Contas de email do utilizador (sem a palavra-passe)."""
    return service.list_accounts(_owner(session))


@router.post("/accounts")
def save_account(payload: Dict[str, Any] = Body(...), session: Session = None) -> Dict[str, Any]:
    """Cria ou altera uma conta (`provider`, `email_address`, `password`, servidores opcionais)."""
    try:
        account = service.save_account(_owner(session), payload)
    except service.EmailError as exc:
        raise _fail(exc)
    return {"saved": True, "account": account}


@router.post("/accounts/test")
def test_new_account(payload: Dict[str, Any] = Body(...), session: Session = None) -> Dict[str, Any]:
    """Testa as credenciais de uma conta ainda não guardada."""
    owner = _owner(session)
    account = service.account_from_payload(owner, payload)
    if not account["imap_host"] or not account["smtp_host"]:
        raise HTTPException(status_code=422, detail="Indique os servidores IMAP e SMTP (ou escolha um fornecedor).")
    if not account["password"]:
        raise HTTPException(status_code=422, detail="Indique a palavra-passe (ou palavra-passe de aplicação).")
    try:
        return {"account": {"email_address": account["email_address"], "provider": account["provider"]}, **service.test_account(account)}
    except service.EmailError as exc:
        raise _fail(exc)


@router.post("/accounts/{account_id}/test")
def test_account(account_id: str, session: Session = None) -> Dict[str, Any]:
    """Testa a ligação IMAP e SMTP de uma conta guardada."""
    try:
        return service.test_account(_account(_owner(session), account_id))
    except service.EmailError as exc:
        raise _fail(exc)


@router.delete("/accounts/{account_id}")
def delete_account(account_id: str, session: Session = None) -> Dict[str, Any]:
    """Remove uma conta de email (o correio no servidor não é tocado)."""
    try:
        return service.delete_account(_owner(session), account_id)
    except service.EmailError as exc:
        raise _fail(exc)


# --------------------------------------------------------------------- pastas
@router.get("/accounts/{account_id}/folders")
def list_folders(account_id: str, session: Session = None) -> Dict[str, Any]:
    """Pastas da caixa de correio, com mensagens e não lidas por pasta."""
    try:
        return service.list_folders(_account(_owner(session), account_id))
    except service.EmailError as exc:
        raise _fail(exc)


# ------------------------------------------------------------------ mensagens
@router.get("/accounts/{account_id}/messages")
def list_messages(
    account_id: str,
    folder: str = Query("INBOX"),
    limit: int = Query(40, ge=1, le=200),
    offset: int = Query(0, ge=0),
    q: Optional[str] = Query(None, description="Pesquisa no assunto e no remetente."),
    unread: bool = Query(False, description="Apenas não lidas."),
    flagged: bool = Query(False, description="Apenas destacadas."),
    session: Session = None,
) -> Dict[str, Any]:
    """Mensagens de uma pasta, mais recentes primeiro."""
    try:
        return service.list_messages(
            _account(_owner(session), account_id),
            folder=folder,
            limit=limit,
            offset=offset,
            query=q,
            unread=unread,
            flagged=flagged,
        )
    except service.EmailError as exc:
        raise _fail(exc)


@router.get("/accounts/{account_id}/messages/{uid}")
def get_message(
    account_id: str,
    uid: str,
    folder: str = Query("INBOX"),
    mark_read: bool = Query(True, description="Marcar como lida ao abrir."),
    session: Session = None,
) -> Dict[str, Any]:
    """Mensagem completa: corpo em texto e HTML, anexos e cabeçalhos."""
    try:
        return service.get_message(_account(_owner(session), account_id), uid, folder=folder, mark_read=mark_read)
    except service.EmailError as exc:
        raise _fail(exc)


@router.post("/accounts/{account_id}/messages/{uid}/flags")
def set_flags(
    account_id: str,
    uid: str,
    payload: Dict[str, Any] = Body(...),
    session: Session = None,
) -> Dict[str, Any]:
    """Muda sinalizadores: `{"action": "read|unread|flag|unflag", "folder": "INBOX"}`."""
    action = str(payload.get("action") or "").strip().lower()
    if action not in service.FLAG_ACTIONS:
        raise HTTPException(status_code=422, detail=f"Ação desconhecida: {action}.")
    try:
        return service.set_message_flags(
            _account(_owner(session), account_id),
            uid,
            folder=str(payload.get("folder") or "INBOX"),
            action=action,
        )
    except service.EmailError as exc:
        raise _fail(exc)


@router.post("/accounts/{account_id}/messages/{uid}/move")
def move_message(
    account_id: str,
    uid: str,
    payload: Dict[str, Any] = Body(...),
    session: Session = None,
) -> Dict[str, Any]:
    """Move a mensagem para outra pasta: `{"target": "Archive", "folder": "INBOX"}`."""
    target = str(payload.get("target") or "").strip()
    if not target:
        raise HTTPException(status_code=422, detail="Indique a pasta de destino.")
    try:
        return service.move_message(
            _account(_owner(session), account_id),
            uid,
            folder=str(payload.get("folder") or "INBOX"),
            target=target,
        )
    except service.EmailError as exc:
        raise _fail(exc)


@router.delete("/accounts/{account_id}/messages/{uid}")
def delete_message(
    account_id: str,
    uid: str,
    folder: str = Query("INBOX"),
    session: Session = None,
) -> Dict[str, Any]:
    """Apaga a mensagem (marca como apagada e limpa a pasta)."""
    try:
        return service.delete_message(_account(_owner(session), account_id), uid, folder=folder)
    except service.EmailError as exc:
        raise _fail(exc)


# ------------------------------------------------------------------- envio
@router.post("/accounts/{account_id}/send")
def send_message(
    account_id: str,
    payload: Dict[str, Any] = Body(...),
    session: Session = None,
) -> Dict[str, Any]:
    """Envia correio: `to`, `cc`, `bcc`, `subject`, `body_text`, `body_html`, `attachments`."""
    try:
        return service.send_message(_account(_owner(session), account_id), payload)
    except service.EmailError as exc:
        raise _fail(exc)
