"""Rotas de autenticação (`/auth/*`).

Fluxo:
- `POST /auth/register` cria a conta e devolve já um token (auto-login).
- `POST /auth/login` valida as credenciais e abre uma sessão. Quando a conta tem
  **verificação em dois passos** (política da administração ou escolha do
  utilizador), devolve um `challenge_id` e envia um código de 6 dígitos por email
  em vez do token.
- `POST /auth/mfa/verify` troca esse código por um token de sessão;
  `POST /auth/mfa/resend` reenvia um código novo (com intervalo mínimo).
- `GET/PUT /auth/mfa` mostram e alteram a preferência da própria conta.
- O browser envia o token em `Authorization: Bearer <token>`; a dependência
  `current_user` valida a assinatura e a sessão no Elasticsearch.
- `POST /auth/logout` revoga a sessão atual (imediato).
- `PATCH /auth/me` e `POST /auth/password` alteram dados reais da conta.
- `GET/DELETE /auth/sessions*` listam e terminam sessões (incluindo as de outros
  dispositivos).
"""
from __future__ import annotations

import logging
from typing import Annotated, Any, Dict, List, Optional, Union

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from pydantic import BaseModel, Field

from api import auth_service as auth
from api import billing_service as billing_service_module
from api import events_service as events
from api import mfa_service as mfa
from api import sidebar_access

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


class MfaVerifyRequest(BaseModel):
    challenge_id: str
    code: str = Field(..., description="Código de 6 dígitos enviado por email")


class MfaResendRequest(BaseModel):
    challenge_id: str


class MfaPreferenceRequest(BaseModel):
    enabled: bool


class IframePagePreference(BaseModel):
    id: str
    title: str
    url: str
    icon: str = "Globe2"
    accent: str = "56,189,248"
    gradient: str = "from-sky-300 via-sky-500 to-sky-700"
    enabled: bool = True
    createdAt: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


class PreferencesPayload(BaseModel):
    theme: Optional[str] = None
    default_view: Optional[str] = None
    dock_position: Optional[str] = None
    sidebar_hidden: Optional[bool] = None
    sidebar_mode: Optional[str] = None
    window_mode: Optional[bool] = None
    reduced_motion: Optional[bool] = None
    email_notifications: Optional[bool] = None
    iframe_pages: Optional[List[IframePagePreference]] = None


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
    trial_expires_at: Optional[str] = None
    approved_at: Optional[str] = None
    pending_approval: bool = False
    subscription: Optional[Dict[str, Any]] = None


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
    ok: bool = True
    error: Optional[str] = None


class MessageResponse(BaseModel):
    ok: bool = True
    message: str = ""


class MfaChallengeResponse(BaseModel):
    """Resposta do login quando a conta tem verificação em dois passos."""

    ok: bool = True
    mfa_required: bool = True
    challenge_id: str
    email: str
    expires_at: Optional[str] = None
    resend_cooldown_seconds: int = mfa.DEFAULT_RESEND_SECONDS
    code_sent: bool = True


class MfaStatusResponse(BaseModel):
    """Estado da verificação em dois passos para a conta autenticada."""

    policy: str
    policy_label: str
    enforced: bool
    user_enabled: bool
    required: bool
    can_change: bool
    email: str
    email_configured: bool
    code_ttl_seconds: int
    max_attempts: int
    resend_cooldown_seconds: int


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


def _require_user_active(user: Dict[str, Any]) -> None:
    """Garante que a conta não está pendente ou com trial expirado."""
    status = user.get("status") or auth.USER_STATUS_ACTIVE
    if status == auth.USER_STATUS_PENDING:
        raise HTTPException(status_code=403, detail="A conta está pendente de aprovação por um administrador.")
    if status != auth.USER_STATUS_ACTIVE:
        raise HTTPException(status_code=403, detail="Esta conta está suspensa.")
    if auth._is_trial_expired(user):
        raise HTTPException(status_code=403, detail="O período de trial de 5 dias expirou. Efetue o pagamento para reativar o acesso.")


def require_module(module_id: str):
    """Dependência que restringe um endpoint ao plano do utilizador."""
    def _check(session: CurrentSession = Depends(require_session)) -> CurrentSession:
        user = auth.get_user_by_id(session.user.id)
        if not user:
            raise HTTPException(status_code=401, detail="Conta não encontrada.")
        if not billing_service_module.can_access_module(user, module_id):
            raise HTTPException(
                status_code=403,
                detail=f"O seu plano não inclui o módulo '{module_id}'. Subscreva ou atualize o plano.",
            )
        return session
    return _check


def session_from_token(token: Optional[str]) -> CurrentSession:
    """Valida um token já extraído (o WebSocket não pode enviar cabeçalhos).

    O browser não deixa definir `Authorization` no handshake de um WebSocket, por
    isso `/llm/modelo/retreinar/ws` recebe o token na query. A validação é a
    mesma de `require_session` — sessão existente, conta ativa e trial válido —
    para o canal aberto não dar mais acesso do que o pedido HTTP equivalente.
    """
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
    _require_user_active(user)
    auth.touch_session(session_id)
    return CurrentSession(
        user=UserResponse(**auth.public_user(user)),
        session_id=session_id,
        token=token,
    )


def require_session(
    authorization: Annotated[Optional[str], Header()] = None,
) -> CurrentSession:
    """Valida o token e a sessão; usado por todos os endpoints protegidos."""
    token = _bearer_token(authorization)
    if not token:
        raise HTTPException(status_code=401, detail="Sessão em falta. Inicie sessão para continuar.")
    return session_from_token(token)


def _client_info(request: Request) -> Dict[str, str]:
    forwarded = request.headers.get("x-forwarded-for") or ""
    ip = (forwarded.split(",")[0].strip() if forwarded else (request.client.host if request.client else "")) or ""
    return {"user_agent": request.headers.get("user-agent") or "", "ip": ip}


def _auth_error(error: auth.AuthError) -> HTTPException:
    return HTTPException(status_code=error.status_code, detail=error.message)


def _mfa_error(error: mfa.MfaError) -> HTTPException:
    headers = {"Retry-After": str(error.retry_after)} if error.retry_after else None
    return HTTPException(status_code=error.status_code, detail=error.message, headers=headers)


def optional_session(
    authorization: Annotated[Optional[str], Header()] = None,
) -> Optional[CurrentSession]:
    """Como `require_session`, mas devolve `None` quando não há sessão válida.

    Usado pelos endpoints de chat (que continuam a funcionar sem autenticação
    para os modelos locais) e para resolver a chave do fornecedor do utilizador.
    """
    if not _bearer_token(authorization):
        return None
    try:
        return require_session(authorization)
    except HTTPException:
        return None


# -------------------------------------------------------------------- rotas
@router.post("/register", response_model=AuthResponse, status_code=201)
def register(payload: RegisterRequest, request: Request):
    """Cria a conta. Se for o primeiro utilizador, inicia sess?o; caso contr?rio,
    fica pendente de aprova??o administrativa."""
    try:
        user = auth.register_user(
            name=payload.name,
            email=payload.email,
            password=payload.password,
            title=payload.title or "",
            organization=payload.organization or "",
        )
        is_first = user.get("role") == "admin"
        if is_first:
            auth.record_login(str(user["id"]))
            session = auth.create_session(user, **_client_info(request))
            refreshed = auth.get_user_by_id(str(user["id"])) or user
            events.log_event(
                "warning",
                "auth",
                f"Primeira conta/admin criada: {auth.public_user(refreshed).get('email')}",
                request=request,
                user_id=str(user["id"]),
                user_email=auth.public_user(refreshed).get("email"),
                data={"role": auth.public_user(refreshed).get("role")},
            )
            return AuthResponse(
                token=session["token"],
                expires_at=session["expires_at"],
                user=UserResponse(**auth.public_user(refreshed)),
            )

        # Contas subsequentes ficam pendentes: n?o iniciam sess?o.
        events.log_event(
            "warning",
            "auth",
            f"Registo pendente de aprova??o: {user.get('email')}",
            request=request,
            data={"email": user.get("email"), "role": user.get("role")},
        )
        return AuthResponse(
            token="",
            expires_at="",
            user=UserResponse(**user),
        )
    except auth.AuthError as error:
        raise _auth_error(error) from error


def _open_session(user: Dict[str, Any], remember: bool, request: Request, *, method: str = "password") -> AuthResponse:
    """Cria a sessão, regista o login e devolve o token (fluxo comum)."""
    ttl = auth.SESSION_TTL_REMEMBER if remember else auth.SESSION_TTL_DEFAULT
    user_id = str(user.get("id") or user.get("email") or "")
    session = auth.create_session(user, ttl=ttl, **_client_info(request))
    auth.record_login(user_id)
    refreshed = auth.get_user_by_id(user_id) or user
    events.log_event(
        "warning",
        "auth",
        f"Início de sessão: {auth.public_user(refreshed).get('email')}",
        request=request,
        user_id=user_id,
        user_email=auth.public_user(refreshed).get("email"),
        data={"remember": bool(remember), "session_id": session.get("session_id"), "verified_by": method},
    )
    return AuthResponse(
        token=session["token"],
        expires_at=session["expires_at"],
        user=UserResponse(**auth.public_user(refreshed)),
    )


@router.post("/login", response_model=Union[AuthResponse, MfaChallengeResponse])
def login(payload: LoginRequest, request: Request):
    """Valida as credenciais e abre uma sessão.

    Quando a conta exige verificação em dois passos (política da administração ou
    escolha do utilizador), a resposta **não** traz token: devolve o
    `challenge_id` e o código segue por email para `POST /auth/mfa/verify`.
    """
    try:
        user = auth.authenticate(payload.email, payload.password)
    except auth.AuthError as error:
        events.log_event(
            "warning",
            "auth",
            f"Início de sessão falhado: {payload.email} ({error.message})",
            request=request,
            data={"email": payload.email, "code": getattr(error, "code", None)},
        )
        raise _auth_error(error) from error

    if mfa.required_for(user):
        info = _client_info(request)
        try:
            challenge = mfa.create_challenge(
                user,
                ip=info["ip"],
                user_agent=info["user_agent"],
                remember=payload.remember,
            )
        except mfa.MfaError as error:
            events.log_event(
                "error",
                "auth",
                f"Verificação em dois passos indisponível: {payload.email} ({error.message})",
                request=request,
                data={"email": payload.email, "code": error.code},
            )
            raise _mfa_error(error) from error
        events.log_event(
            "warning",
            "auth",
            f"Verificação em dois passos pedida: {payload.email}",
            request=request,
            data={"email": payload.email, "challenge_id": challenge["challenge_id"]},
        )
        return MfaChallengeResponse(**challenge)

    return _open_session(user, payload.remember, request)


@router.post("/mfa/verify", response_model=AuthResponse)
def verify_mfa(payload: MfaVerifyRequest, request: Request):
    """Troca o código recebido por email por um token de sessão."""
    try:
        challenge = mfa.verify(payload.challenge_id, payload.code)
    except mfa.MfaError as error:
        events.log_event(
            "warning",
            "auth",
            f"Código de verificação recusado ({error.code})",
            request=request,
            data={"challenge_id": payload.challenge_id, "code": error.code},
        )
        raise _mfa_error(error) from error

    user = auth.get_user_by_id(str(challenge.get("user_id") or ""))
    if not user:
        raise HTTPException(status_code=401, detail="Conta não encontrada.")
    try:
        _require_user_active(user)
    except HTTPException as error:
        events.log_event(
            "warning",
            "auth",
            f"Verificação em dois passos recusada: {user.get('email')} ({error.detail})",
            request=request,
            data={"email": user.get("email")},
        )
        raise
    return _open_session(user, bool(challenge.get("remember")), request, method="email_code")


@router.post("/mfa/resend", response_model=MfaChallengeResponse)
def resend_mfa(payload: MfaResendRequest, request: Request):
    """Reenvia um código novo para o mesmo desafio (respeitando o intervalo mínimo)."""
    try:
        challenge = mfa.resend(payload.challenge_id, ip=_client_info(request)["ip"])
    except mfa.MfaError as error:
        raise _mfa_error(error) from error
    events.log_event(
        "warning",
        "auth",
        f"Código de verificação reenviado: {challenge.get('email')}",
        request=request,
        data={"challenge_id": payload.challenge_id},
    )
    return MfaChallengeResponse(**challenge)


@router.get("/mfa", response_model=MfaStatusResponse)
def mfa_status(session: Annotated[CurrentSession, Depends(require_session)]):
    """Estado da verificação em dois passos para a conta autenticada."""
    user = auth.get_user_by_id(session.user.id) or {}
    try:
        return MfaStatusResponse(**mfa.status_for(user))
    except mfa.MfaError as error:
        raise _mfa_error(error) from error


@router.put("/mfa", response_model=MfaStatusResponse)
def update_mfa(payload: MfaPreferenceRequest, session: Annotated[CurrentSession, Depends(require_session)]):
    """Ativa/desativa a verificação em dois passos para a própria conta.

    Quando a política da administração a obriga, não é possível desligar (409).
    """
    user = auth.get_user_by_id(session.user.id) or {}
    try:
        enforced = mfa.is_enforced(user)
    except mfa.MfaError as error:
        raise _mfa_error(error) from error
    if enforced and not payload.enabled:
        raise HTTPException(
            status_code=409,
            detail="A verificação em dois passos é obrigatória para esta conta por decisão do administrador.",
        )
    try:
        updated = auth.set_mfa_enabled(session.user.id, payload.enabled, actor=session.user.email)
    except auth.AuthError as error:
        raise _auth_error(error) from error

    events.log_event(
        "warning",
        "auth",
        f"Verificação em dois passos {'ativada' if payload.enabled else 'desativada'}: {session.user.email}",
        user_id=session.user.id,
        user_email=session.user.email,
        data={"enabled": bool(payload.enabled), "enforced": enforced},
    )
    return MfaStatusResponse(**mfa.status_for(updated))


@router.post("/logout", response_model=MessageResponse)
def logout(session: Annotated[CurrentSession, Depends(require_session)]):
    """Termina a sessão atual."""
    auth.revoke_session(session.session_id)
    events.log_event(
        "warning",
        "auth",
        f"Fim de sessão: {session.user.email}",
        user_id=session.user.id,
        user_email=session.user.email,
        data={"session_id": session.session_id},
    )
    return MessageResponse(message="Sessão terminada.")


@router.get("/me", response_model=UserResponse)
def me(session: Annotated[CurrentSession, Depends(require_session)]):
    """Dados da conta autenticada (usados para revalidar a sessão ao abrir a app)."""
    return session.user


@router.get("/sidebar-access")
def sidebar_access_for_me(session: Annotated[CurrentSession, Depends(require_session)]) -> Dict[str, Any]:
    """Módulos da solução que **não** devem aparecer na barra lateral deste utilizador.

    O resultado junta o papel da plataforma (`admin`/`member`) com o perfil de CRM
    atribuído ao utilizador; a matriz é gerida na página de administração.
    """
    try:
        return sidebar_access.effective(session.user)
    except Exception as error:  # pragma: no cover - nunca deve impedir o arranque da app
        logger.debug("acesso à barra lateral indisponível: %s", error)
        return {"hidden": [], "platform_role": getattr(session.user, "role", "") or "member", "profile": "", "profile_label": "", "protected": list(sidebar_access.PROTECTED)}


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
    events.log_event(
        "warning",
        "auth",
        f"Palavra-passe alterada: {session.user.email} ({revoked} sessão(ões) terminada(s))",
        user_id=session.user.id,
        user_email=session.user.email,
        data={"revoked_sessions": revoked},
    )
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
    events.log_event(
        "warning",
        "auth",
        f"Outras sessões terminadas: {session.user.email} ({count})",
        user_id=session.user.id,
        user_email=session.user.email,
    )
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
    events.log_event(
        "warning",
        "auth",
        f"Conta apagada pelo próprio: {session.user.email}",
        user_id=session.user.id,
        user_email=session.user.email,
    )
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
