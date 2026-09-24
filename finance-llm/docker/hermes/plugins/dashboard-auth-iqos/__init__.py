"""Provider de autenticação do dashboard do Hermes Agent que usa as **contas do IQ OS**.

O dashboard do Hermes tem um *auth gate* próprio, obrigatório quando está ligado a um
endereço não-loopback. Em vez de um par fixo de credenciais
(`HERMES_DASHBOARD_BASIC_AUTH_USERNAME`/`_PASSWORD`), este plugin regista um
`DashboardAuthProvider` com `supports_password = True`: o formulário
**«Sign in with Username & Password»** passa a aceitar **as mesmas contas da
plataforma** — as credenciais são validadas em `POST /auth/login` da API do IQ OS
(e ficam na sessão auditada do IQ OS, como em qualquer outro início de sessão).

Instalação (já feita no `docker-compose.yml` do IQ OS):

    services:
      hermes-agent:
        volumes:
          - ./docker/hermes/plugins/dashboard-auth-iqos:/opt/data/plugins/dashboard-auth-iqos:ro
        environment:
          - IQOS_API_URL=http://backend:8000

Variáveis de ambiente
---------------------
``IQOS_API_URL``
    Base da API do IQ OS **vista de dentro do container** (`http://backend:8000` no
    compose). Sem ela o plugin não registra nada.
``HERMES_DASHBOARD_IQOS_SECRET``
    Chave HMAC das sessões do dashboard. Se ficar vazia, é gerada uma por processo e
    as sessões não sobrevivem a um reinício do container.

Notas de segurança
------------------
* As palavras-passe **nunca** são guardadas: cada login é validado na API do IQ OS
  (scrypt do lado de lá) e só a identidade (id/email/nome) é assinada na sessão.
* O `401` do IQ OS é traduzido em `InvalidCredentialsError`, que o dashboard
  responde com um `401` genérico (sem permitir enumerar contas).
* A API do IQ OS serve de *backing store*: se estiver em baixo devolvemos
  `ProviderError` (HTTP 503), em vez de aceitar ou recusar logins às cegas.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import logging
import os
import secrets
import time
import urllib.error
import urllib.request
from typing import Any, Dict, Optional

from hermes_cli.dashboard_auth import (
    DashboardAuthProvider,
    InvalidCredentialsError,
    ProviderError,
    RefreshExpiredError,
    Session,
)

logger = logging.getLogger(__name__)
_TAG = "dashboard-auth-iqos"

# O middleware renova a sessão sozinho através do refresh token, por isso o TTL do
# access token controla a frequência do refresh, não a duração do login.
_ACCESS_TTL_SECONDS = 12 * 60 * 60
_REFRESH_TTL_SECONDS = 30 * 24 * 60 * 60
_LOGIN_TIMEOUT_SECONDS = 20.0

_NO_OAUTH = (
    "IQOSAuthProvider é um provider de palavra-passe; não há fluxo OAuth. "
    "O formulário de /login publica em /auth/password-login."
)


# --------------------------------------------------------------------------- tokens
def _b64(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _unb64(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def _sign(payload: Dict[str, Any], secret: bytes) -> str:
    raw = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
    return f"{_b64(raw)}.{_b64(hmac.new(secret, raw, hashlib.sha256).digest())}"


def _unsign(token: str, secret: bytes, kind: str) -> Optional[Dict[str, Any]]:
    """Verifica assinatura + validade. Devolve `None` para qualquer token inválido."""
    try:
        raw_b64, signature_b64 = token.split(".", 1)
        raw, signature = _unb64(raw_b64), _unb64(signature_b64)
    except Exception:
        return None
    if not hmac.compare_digest(signature, hmac.new(secret, raw, hashlib.sha256).digest()):
        return None
    try:
        payload = json.loads(raw)
    except Exception:
        return None
    if payload.get("kind") != kind or int(payload.get("exp", 0)) <= int(time.time()):
        return None
    return payload


# --------------------------------------------------------------------------- provider
class IQOSAuthProvider(DashboardAuthProvider):
    """Login por email + palavra-passe validado na API do IQ OS."""

    name = "iqos"
    display_name = "IQ OS"
    supports_password = True

    def __init__(self, *, api_url: str, secret: bytes, timeout: float = _LOGIN_TIMEOUT_SECONDS) -> None:
        if not api_url:
            raise ValueError("api_url must be non-empty")
        if len(secret) < 16:
            raise ValueError("secret must be at least 16 bytes")
        self._api_url = api_url.rstrip("/")
        self._secret = secret
        self._timeout = float(timeout)

    # ---- OAuth: não aplicável (provider só de palavra-passe) ---------------
    def start_login(self, *, redirect_uri: str):
        raise NotImplementedError(_NO_OAUTH)

    def complete_login(self, *, code: str, state: str, code_verifier: str, redirect_uri: str):
        raise NotImplementedError(_NO_OAUTH)

    # ---- login com credenciais do IQ OS -----------------------------------
    def complete_password_login(self, *, username: str, password: str) -> Session:
        return self._mint_session(self._authenticate(username, password))

    def _authenticate(self, username: str, password: str) -> Dict[str, str]:
        """Valida as credenciais em `POST {IQOS_API_URL}/auth/login`."""
        body = json.dumps({"email": username.strip(), "password": password}).encode("utf-8")
        request = urllib.request.Request(
            f"{self._api_url}/auth/login",
            data=body,
            headers={"Content-Type": "application/json", "Accept": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=self._timeout) as response:
                data = json.loads(response.read().decode("utf-8") or "{}")
        except urllib.error.HTTPError as error:
            if error.code in (400, 401, 403):
                logger.info("%s: credenciais recusadas pelo IQ OS (HTTP %s)", _TAG, error.code)
                raise InvalidCredentialsError("email ou palavra-passe inválidos") from error
            raise ProviderError(f"o IQ OS respondeu HTTP {error.code} no login") from error
        except Exception as error:  # rede, DNS, timeout
            raise ProviderError(
                f"não foi possível contactar o IQ OS em {self._api_url}/auth/login: {error}"
            ) from error

        user = data.get("user") or {}
        email = str(user.get("email") or username.strip())
        return {
            "user_id": str(user.get("id") or email or username.strip()),
            "email": email,
            "display_name": str(user.get("name") or email),
            "org_id": str(user.get("organization") or ""),
        }

    # ---- sessão (tokens HMAC stateless, como o provider `basic`) -----------
    def verify_session(self, *, access_token: str) -> Optional[Session]:
        payload = _unsign(access_token, self._secret, "access")
        if payload is None:
            return None
        return self._session(payload, int(payload["exp"]), access_token, "")

    def refresh_session(self, *, refresh_token: str) -> Session:
        payload = _unsign(refresh_token, self._secret, "refresh")
        if payload is None:
            raise RefreshExpiredError("refresh token inválido ou expirado")
        now = int(time.time())
        access_exp = now + _ACCESS_TTL_SECONDS
        return self._session(
            payload,
            access_exp,
            _sign({**payload, "kind": "access", "exp": access_exp}, self._secret),
            refresh_token,
        )

    def revoke_session(self, *, refresh_token: str) -> None:
        # Tokens stateless: nada a revogar do lado do servidor (a sessão do IQ OS
        # em si é revogável na plataforma). Não pode levantar exceção.
        return None

    def _mint_session(self, identity: Dict[str, str]) -> Session:
        now = int(time.time())
        base = {
            "sub": identity["user_id"],
            "email": identity["email"],
            "name": identity["display_name"],
            "org": identity["org_id"],
        }
        access_exp = now + _ACCESS_TTL_SECONDS
        return self._session(
            base,
            access_exp,
            _sign({**base, "kind": "access", "exp": access_exp}, self._secret),
            _sign({**base, "kind": "refresh", "exp": now + _REFRESH_TTL_SECONDS}, self._secret),
        )

    def _session(self, payload: Dict[str, Any], exp: int, access_token: str, refresh_token: str) -> Session:
        email = str(payload.get("email") or "")
        return Session(
            user_id=str(payload.get("sub") or ""),
            email=email,
            display_name=str(payload.get("name") or email or payload.get("sub") or ""),
            org_id=str(payload.get("org") or ""),
            provider=self.name,
            expires_at=exp,
            access_token=access_token,
            refresh_token=refresh_token,
        )


# --------------------------------------------------------------------------- registo
def _api_url() -> str:
    return (os.getenv("IQOS_API_URL") or "").strip()


def _secret() -> bytes:
    raw = (os.getenv("HERMES_DASHBOARD_IQOS_SECRET") or "").strip()
    if raw:
        return raw.encode("utf-8")
    logger.info(
        "%s: HERMES_DASHBOARD_IQOS_SECRET vazia — a gerar uma chave por processo "
        "(as sessões do dashboard não sobrevivem a um reinício do container).",
        _TAG,
    )
    return secrets.token_bytes(32)


def register(ctx) -> None:
    """Registo do provider no arranque do dashboard."""
    api_url = _api_url()
    if not api_url:
        logger.warning("%s: IQOS_API_URL não definida — provider não registado.", _TAG)
        return
    ctx.register_dashboard_auth_provider(IQOSAuthProvider(api_url=api_url, secret=_secret()))
    logger.info("%s: provider registado; o login é validado em %s/auth/login.", _TAG, api_url)
