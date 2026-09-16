"""Rotas de autenticação (`/auth/*`).

Fluxo:
- `POST /auth/register` cria a conta e devolve já um token (auto-login).
- `POST /auth/login` valida as credenciais e abre uma sessão.
- O browser envia o token em `Authorization: Bearer <token>`; a dependência
  `current_user` valida a assinatura e a sessão no Elasticsearch.
- `POST /auth/logout` revoga a sessão atual (imediato).
- `PATCH /auth/me` e `POST /auth/password` alteram dados reais da conta.
- `GET/DELETE /auth/sessions*` listam e terminam sessões (incluindo as de outros
  dispositivos).
"""
from __future__ import annotations

import logging
from typing import Annotated, Any, Dict, List, Optional

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from pydantic import BaseModel, Field

from api import auth_service as auth

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/auth", tags=["auth"])

BEARER_PREFIX = "bearer "


# ------------------------------------------------------------------- modelos
class RegisterRequest(BaseModel):
    name: str = Field(..., description="Nome completo")
    email: str
    password: str
    title: Optional[str] = None
    organization: Optional[str] = None


class LoginRequest(BaseModel):
    email: str
    password: str
    remember: bool = False


class PreferencesPayload(BaseModel):
    theme: Optional[str] = None
    default_view: Optional[str] = None
    dock_position: Optional[str] = None
    sidebar_hidden: Optional[bool] = None
    reduced_motion: Optional[bool] = None
    email_notifications: Optional[bool] = None


class UpdateProfileRequest(BaseModel):
    name: Optional[str] = None
    title: Optional[str] = None
    organization: Optional[str] = None
    phone: Optional[str] = None
    locale: Optional[str] = None
    timezone: Optional[str] = None
    preferences: Optional[PreferencesPayload] = None


class ChangePasswordRequest(BaseModel):
    current_password: str
    new_password: str


class DeleteAccountRequest(BaseModel):
    password: str


class UserResponse(BaseModel):
    id: str
    email: str
    name: str
    initials: str
    role: str
    status: str
    title: str = ""
    organization: str = ""
    phone: str = ""
    locale: str
    timezone: str
    created_at: Optional[str] = None
    updated_at: Optional[str] = None
    last_login_at: Optional[str] = None
    login_count: int = 0
    preferences: Dict[str, Any] = Field(default_factory=dict)
    password_updated_at: Optional[str] = None


class SessionResponse(BaseModel):
    id: str
    created_at: Optional[str] = None
    last_seen_at: Optional[str] = None
    expires_at: Optional[str] = None
    user_agent: str = ""
    ip: str = ""
    current: bool = False


class AuthResponse(BaseModel):
    token: str
    expires_at: str
    user: UserResponse


class MessageResponse(BaseModel):
    ok: bool = True
    message: str = ""


# ------------------------------------------------------------- dependências
def _bearer_token(authorization: Optional[str]) -> Optional[str]:
    if not authorization:
        return None
    value = authorization.strip()
    if value.lower().startswith(BEARER_PREFIX):
        return value[len(BEARER_PREFIX) :].strip() or None
    # Aceita também o token em bruto (clientes simples / testes).
    return value or None


class CurrentSession(BaseModel):
    user: UserResponse
    session_id: str
    token: str


def require_session(
    authorization: Annotated[Optional[str], Header()] = None,
) -> CurrentSession:
    """Valida o token e a sessão; usado por todos os endpoints protegidos."""
    token = _bearer_token(authorization)
    if not token:
        raise HTTPException(status_code=401, detail="Sessão em falta. Inicie sessão para continuar.")
    payload = auth.read_token(token)
    if not payload:
        raise HTTPException(status_code=401, detail="Sessão inválida ou expirada.")
    session_id = str(payload.get("sid"))
    session = auth.get_session(session_id)
    if not session:
        raise HTTPException(status_code=401, detail="Sessão terminada. Inicie sessão novamente.")
    user = auth.get_user_by_id(str(payload.get("sub")))
    if not user:
        raise HTTPException(status_code=401, detail="Conta não encontrada.")
    auth.touch_session(session_id)
    return CurrentSession(
        user=UserResponse(**auth.public_user(user)),
        session_id=session_id,
        token=token,
    )


def _client_info(request: Request) -> Dict[str, str]:
    forwarded = request.headers.get("x-forwarded-for") or ""
    ip = (forwarded.split(",")[0].strip() if forwarded else (request.client.host if request.client else "")) or ""
    return {"user_agent": request.headers.get("user-agent") or "", "ip": ip}


def _auth_error(error: auth.AuthError) -> HTTPException:
    return HTTPException(status_code=error.status_code, detail=error.message)


# -------------------------------------------------------------------- rotas
@router.post("/register", response_model=AuthResponse, status_code=201)
def register(payload: RegisterRequest, request: Request):
    """Cria a conta e inicia sessão automaticamente."""
    try:
        user = auth.register_user(
            name=payload.name,
            email=payload.email,
            password=payload.password,
            title=payload.title or "",
            organization=payload.organization or "",
        )
        auth.record_login(str(user["id"]))
        session = auth.create_session(user, **_client_info(request))
        refreshed = auth.get_user_by_id(str(user["id"])) or user
        return AuthResponse(
            token=session["token"],
            expires_at=session["expires_at"],
            user=UserResponse(**auth.public_user(refreshed)),
        )
    except auth.AuthError as error:
        raise _auth_error(error) from error


@router.post("/login", response_model=AuthResponse)
def login(payload: LoginRequest, request: Request):
    """Valida as credenciais e abre uma sessão."""
    try:
        user = auth.authenticate(payload.email, payload.password)
        ttl = auth.SESSION_TTL_REMEMBER if payload.remember else auth.SESSION_TTL_DEFAULT
        session = auth.create_session(user, ttl=ttl, **_client_info(request))
        auth.record_login(str(user["id"]))
        refreshed = auth.get_user_by_id(str(user["id"])) or user
        return AuthResponse(
            token=session["token"],
            expires_at=session["expires_at"],
            user=UserResponse(**auth.public_user(refreshed)),
        )
    except auth.AuthError as error:
        raise _auth_error(error) from error


@router.post("/logout", response_model=MessageResponse)
def logout(session: Annotated[CurrentSession, Depends(require_session)]):
    """Termina a sessão atual."""
    auth.revoke_session(session.session_id)
    return MessageResponse(message="Sessão terminada.")


@router.get("/me", response_model=UserResponse)
def me(session: Annotated[CurrentSession, Depends(require_session)]):
    """Dados da conta autenticada (usados para revalidar a sessão ao abrir a app)."""
    return session.user


@router.patch("/me", response_model=UserResponse)
def update_me(payload: UpdateProfileRequest, session: Annotated[CurrentSession, Depends(require_session)]):
    """Atualiza o perfil e as preferências (gravados no Elasticsearch)."""
    patch = payload.model_dump(exclude_unset=True)
    preferences = patch.pop("preferences", None)
    if preferences is not None:
        patch["preferences"] = {k: v for k, v in preferences.items() if v is not None}
    try:
        return UserResponse(**auth.update_user(session.user.id, patch))
    except auth.AuthError as error:
        raise _auth_error(error) from error
@router.post("/password", response_model=MessageResponse)
def change_password(payload: ChangePasswordRequest, session: Annotated[CurrentSession, Depends(require_session)]):
    """Altera a palavra-passe e termina as outras sessões."""
    try:
        auth.change_password(session.user.id, payload.current_password, payload.new_password)
    except auth.AuthError as error:
        raise _auth_error(error) from error
    revoked = auth.revoke_all_sessions(session.user.id, keep=session.session_id)
    return MessageResponse(message=f"Palavra-passe atualizada. {revoked} sessão(ões) terminada(s) por segurança.")


@router.get("/sessions", response_model=List[SessionResponse])
def sessions(session: Annotated[CurrentSession, Depends(require_session)]):
    """Lista as sessões ativas da conta."""
    return [
        SessionResponse(**{**item, "current": item["id"] == session.session_id})
        for item in auth.list_sessions(session.user.id)
    ]


@router.delete("/sessions/{session_id}", response_model=MessageResponse)
def revoke_session(session_id: str, session: Annotated[CurrentSession, Depends(require_session)]):
    """Termina uma sessão concreta (por exemplo, noutro dispositivo)."""
    if session_id == session.session_id:
        raise HTTPException(status_code=400, detail="Para esta sessão use «Terminar sessão».")
    if not auth.revoke_session(session_id):
        raise HTTPException(status_code=404, detail="Sessão não encontrada.")
    return MessageResponse(message="Sessão terminada.")


@router.delete("/sessions", response_model=MessageResponse)
def revoke_other_sessions(session: Annotated[CurrentSession, Depends(require_session)]):
    """Termina todas as sessões da conta exceto a atual."""
    count = auth.revoke_all_sessions(session.user.id, keep=session.session_id)
    return MessageResponse(message=f"{count} sessão(ões) terminada(s).")


@router.delete("/me", response_model=MessageResponse)
def delete_me(payload: DeleteAccountRequest, session: Annotated[CurrentSession, Depends(require_session)]):
    """Apaga a conta (confirmação pela palavra-passe)."""
    try:
        user = auth.authenticate(session.user.email, payload.password)
    except auth.AuthError as error:
        raise _auth_error(error) from error
    try:
        auth.delete_account(str(user["id"]))
    except auth.AuthError as error:
        raise _auth_error(error) from error
    return MessageResponse(message="Conta apagada.")


@router.get("/stats")
def stats(session: Annotated[CurrentSession, Depends(require_session)]):
    """Números do sistema de contas (apenas para administradores)."""
    if session.user.role != "admin":
        raise HTTPException(status_code=403, detail="Apenas administradores podem ver estas estatísticas.")
    try:
        data = auth.stats()
    except auth.AuthError as error:
        raise _auth_error(error) from error
    return {**data, "users_list": auth.list_users(limit=50) if data["users"] <= 50 else []}
