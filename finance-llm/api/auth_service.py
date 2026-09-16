"""Autenticação com Elasticsearch como base de dados.

- Utilizadores: índice `finance_users` (um documento por conta, `_id` = email
  normalizado, o que garante unicidade sem precisar de uma transação).
- Sessões: índice `finance_sessions` (um documento por sessão). O token enviado
  ao browser é assinado (HMAC-SHA256) e transporta apenas o id da sessão; o
  estado real (validade, revogação) vive no Elasticsearch, pelo que terminar
  sessão é imediato e auditável.

Não são necessárias dependências novas: as palavras-passe usam `hashlib.scrypt`
e os tokens são assinados com `hmac` da biblioteca padrão.
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
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from elasticsearch import Elasticsearch

from api.elasticsearch_client import (
    AUTH_SESSIONS_INDEX,
    AUTH_USERS_INDEX,
    ensure_indices,
    get_es_client,
)

logger = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parents[1]
SECRET_FILE = ROOT / "data" / ".auth_secret"

# Parâmetros do scrypt (n=2^14 exige ~16 MB de memória por verificação).
SCRYPT_N = 2**14
SCRYPT_R = 8
SCRYPT_P = 1
SCRYPT_DKLEN = 32
SCRYPT_MAXMEM = 64 * 1024 * 1024

SESSION_TTL_DEFAULT = timedelta(hours=12)
SESSION_TTL_REMEMBER = timedelta(days=30)
EMAIL_MAX_LEN = 254
NAME_MAX_LEN = 120
PASSWORD_MIN_LEN = 8
PASSWORD_MAX_LEN = 200


# --------------------------------------------------------------------- erros
class AuthError(Exception):
    """Erro de autenticação com código HTTP associado."""

    def __init__(self, message: str, status_code: int = 400, code: str = "auth_error"):
        super().__init__(message)
        self.message = message
        self.status_code = status_code
        self.code = code


# ------------------------------------------------------------------- segredo
_secret_cache: Optional[bytes] = None


def _auth_secret() -> bytes:
    """Segredo de assinatura dos tokens (env var ou ficheiro local persistente)."""
    global _secret_cache
    if _secret_cache is not None:
        return _secret_cache

    env = os.getenv("FINANCE_AUTH_SECRET")
    if env and env.strip():
        _secret_cache = env.strip().encode("utf-8")
        return _secret_cache

    try:
        if SECRET_FILE.exists():
            _secret_cache = SECRET_FILE.read_bytes().strip()
            if _secret_cache:
                return _secret_cache
        SECRET_FILE.parent.mkdir(parents=True, exist_ok=True)
        generated = secrets.token_urlsafe(48).encode("utf-8")
        SECRET_FILE.write_bytes(generated)
        try:
            os.chmod(SECRET_FILE, 0o600)
        except OSError:
            pass
        _secret_cache = generated
        return _secret_cache
    except OSError:
        # Sem acesso ao disco: segredo apenas em memória (as sessões caem ao reiniciar).
        _secret_cache = secrets.token_urlsafe(48).encode("utf-8")
        return _secret_cache


def _b64e(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _b64d(text: str) -> bytes:
    padding = "=" * (-len(text) % 4)
    return base64.urlsafe_b64decode(text + padding)


# -------------------------------------------------------------- palavras-passe
def hash_password(password: str) -> Dict[str, str]:
    """Deriva o hash da palavra-passe (scrypt + salt aleatório por conta)."""
    salt = secrets.token_bytes(16)
    digest = hashlib.scrypt(
        password.encode("utf-8"),
        salt=salt,
        n=SCRYPT_N,
        r=SCRYPT_R,
        p=SCRYPT_P,
        dklen=SCRYPT_DKLEN,
        maxmem=SCRYPT_MAXMEM,
    )
    return {
        "algo": f"scrypt:{SCRYPT_N}:{SCRYPT_R}:{SCRYPT_P}",
        "hash": _b64e(digest),
        "salt": _b64e(salt),
        "updated_at": _now_iso(),
    }


def verify_password(password: str, stored: Optional[Dict[str, Any]]) -> bool:
    """Confirma a palavra-passe contra o registo guardado (comparação constante)."""
    if not stored or not stored.get("hash") or not stored.get("salt"):
        return False
    try:
        algo = str(stored.get("algo") or "")
        parts = algo.split(":") if algo.startswith("scrypt:") else []
        n, r, p = (int(parts[1]), int(parts[2]), int(parts[3])) if len(parts) == 4 else (SCRYPT_N, SCRYPT_R, SCRYPT_P)
        digest = hashlib.scrypt(
            password.encode("utf-8"),
            salt=_b64d(str(stored["salt"])),
            n=n,
            r=r,
            p=p,
            dklen=len(_b64d(str(stored["hash"]))),
            maxmem=SCRYPT_MAXMEM,
        )
    except (ValueError, TypeError):
        return False
    return hmac.compare_digest(digest, _b64d(str(stored["hash"])))


def validate_password_strength(password: str) -> Optional[str]:
    """Devolve a mensagem de erro, ou None se a palavra-passe for aceitável."""
    if len(password) < PASSWORD_MIN_LEN:
        return f"A palavra-passe tem de ter pelo menos {PASSWORD_MIN_LEN} caracteres."
    if len(password) > PASSWORD_MAX_LEN:
        return f"A palavra-passe não pode exceder {PASSWORD_MAX_LEN} caracteres."
    if not any(c.isalpha() for c in password):
        return "A palavra-passe tem de incluir pelo menos uma letra."
    if not any(c.isdigit() for c in password):
        return "A palavra-passe tem de incluir pelo menos um dígito."
    return None


# -------------------------------------------------------------------- tokens
def issue_token(session_id: str, user_id: str, ttl: timedelta) -> Tuple[str, str]:
    """Cria um token assinado. Devolve (token, expires_at ISO)."""
    expires_at = datetime.now(timezone.utc) + ttl
    payload = {
        "sid": session_id,
        "sub": user_id,
        "iat": int(time.time()),
        "exp": int(expires_at.timestamp()),
    }
    body = _b64e(json.dumps(payload, separators=(",", ":")).encode("utf-8"))
    signature = hmac.new(_auth_secret(), body.encode("ascii"), hashlib.sha256).digest()
    return f"{body}.{_b64e(signature)}", expires_at.isoformat()


def read_token(token: str) -> Optional[Dict[str, Any]]:
    """Valida a assinatura e a validade temporal. Devolve o payload ou None."""
    if not token or token.count(".") != 1:
        return None
    body, signature = token.split(".", 1)
    expected = hmac.new(_auth_secret(), body.encode("ascii"), hashlib.sha256).digest()
    try:
        provided = _b64d(signature)
    except (ValueError, TypeError):
        return None
    if not hmac.compare_digest(expected, provided):
        return None
    try:
        payload = json.loads(_b64d(body).decode("utf-8"))
    except (ValueError, TypeError, UnicodeDecodeError):
        return None
    if not isinstance(payload, dict) or "sid" not in payload:
        return None
    if int(payload.get("exp") or 0) < int(time.time()):
        return None
    return payload


# ------------------------------------------------------------------ helpers
def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def normalize_email(email: str) -> str:
    return (email or "").strip().lower()


def validate_email(email: str) -> Optional[str]:
    if not email:
        return "Indique o email."
    if len(email) > EMAIL_MAX_LEN:
        return "O email é demasiado longo."
    local, _, domain = email.partition("@")
    if not local or not domain or "." not in domain or " " in email:
        return "O email não parece válido."
    return None


def validate_name(name: str) -> Optional[str]:
    if not name or len(name.strip()) < 2:
        return "Indique o nome (pelo menos 2 caracteres)."
    if len(name) > NAME_MAX_LEN:
        return f"O nome não pode exceder {NAME_MAX_LEN} caracteres."
    return None


def _initials(name: str, email: str) -> str:
    parts = [p for p in (name or "").split() if p]
    if len(parts) >= 2:
        return (parts[0][0] + parts[-1][0]).upper()
    if parts:
        return parts[0][:2].upper()
    return (email or "?")[0].upper()


def _client() -> Elasticsearch:
    client = get_es_client()
    if not client:
        raise AuthError("Base de dados (Elasticsearch) indisponível.", status_code=503, code="es_unavailable")
    ensure_indices(client)
    return client


DEFAULT_PREFERENCES: Dict[str, Any] = {
    "theme": "dark",
    "default_view": "dashboard",
    "dock_position": "bottom",
    "sidebar_hidden": False,
    "reduced_motion": False,
    "email_notifications": False,
}

ALLOWED_PREFERENCES = set(DEFAULT_PREFERENCES)


def public_user(source: Dict[str, Any]) -> Dict[str, Any]:
    """Documento de utilizador tal como sai da API (sem o hash da palavra-passe)."""
    preferences = {**DEFAULT_PREFERENCES, **(source.get("preferences") or {})}
    email = source.get("email") or ""
    name = source.get("name") or ""
    return {
        "id": source.get("id"),
        "email": email,
        "name": name,
        "initials": _initials(name, email),
        "role": source.get("role") or "member",
        "status": source.get("status") or "active",
        "title": source.get("title") or "",
        "organization": source.get("organization") or "",
        "phone": source.get("phone") or "",
        "locale": source.get("locale") or "pt-PT",
        "timezone": source.get("timezone") or "Europe/Lisbon",
        "created_at": source.get("created_at"),
        "updated_at": source.get("updated_at"),
        "last_login_at": source.get("last_login_at"),
        "login_count": int(source.get("login_count") or 0),
        "preferences": preferences,
        "password_updated_at": (source.get("password") or {}).get("updated_at"),
    }


# ------------------------------------------------------------------ contas
def get_user_by_email(email: str, client: Optional[Elasticsearch] = None) -> Optional[Dict[str, Any]]:
    es = client or _client()
    key = normalize_email(email)
    if not key:
        return None
    try:
        resp = es.get(index=AUTH_USERS_INDEX, id=key)
    except Exception:
        return None
    source = dict(resp.get("_source") or {})
    source.setdefault("email", key)
    return source


def get_user_by_id(user_id: str, client: Optional[Elasticsearch] = None) -> Optional[Dict[str, Any]]:
    es = client or _client()
    try:
        resp = es.search(
            index=AUTH_USERS_INDEX,
            body={"query": {"term": {"id": user_id}}, "size": 1},
        )
    except Exception:
        return None
    hits = resp.get("hits", {}).get("hits", [])
    return dict(hits[0]["_source"]) if hits else None


def _count_users(es: Elasticsearch) -> int:
    try:
        return int(es.count(index=AUTH_USERS_INDEX).get("count", 0))
    except Exception:
        return 0


def register_user(
    *,
    name: str,
    email: str,
    password: str,
    title: str = "",
    organization: str = "",
    phone: str = "",
    preferences: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Cria uma conta nova (o primeiro utilizador do sistema fica como admin)."""
    problems = [validate_name(name), validate_email(normalize_email(email)), validate_password_strength(password)]
    for problem in problems:
        if problem:
            raise AuthError(problem, status_code=422, code="invalid_input")

    es = _client()
    key = normalize_email(email)
    now = _now_iso()
    is_first = _count_users(es) == 0
    document = {
        "id": secrets.token_hex(16),
        "email": key,
        "name": name.strip(),
        "title": (title or "").strip()[:120],
        "organization": (organization or "").strip()[:160],
        "phone": (phone or "").strip()[:40],
        "role": "admin" if is_first else "member",
        "status": "active",
        "locale": "pt-PT",
        "timezone": "Europe/Lisbon",
        "preferences": {**DEFAULT_PREFERENCES, **(preferences or {})},
        "password": hash_password(password),
        "created_at": now,
        "updated_at": now,
        "last_login_at": None,
        "login_count": 0,
    }

    try:
        # `create` falha se o email já existir — é a garantia de unicidade.
        es.create(index=AUTH_USERS_INDEX, id=key, document=document, refresh=True)
    except Exception as error:  # noqa: BLE001 - conflito de email ou falha do ES
        if "version_conflict" in str(error) or "already exists" in str(error):
            raise AuthError("Já existe uma conta com este email.", status_code=409, code="email_taken") from error
        logger.exception("Falha ao criar utilizador")
        raise AuthError("Não foi possível criar a conta.", status_code=502, code="es_error") from error

    return public_user(document)


def authenticate(email: str, password: str) -> Dict[str, Any]:
    """Valida as credenciais e devolve a conta (com o hash, para uso interno)."""
    user = get_user_by_email(email)
    if not user or not verify_password(password, user.get("password")):
        raise AuthError("Email ou palavra-passe incorretos.", status_code=401, code="invalid_credentials")
    if (user.get("status") or "active") != "active":
        raise AuthError("Esta conta está suspensa.", status_code=403, code="suspended")
    return user


def update_user(user_id: str, patch: Dict[str, Any], *, client: Optional[Elasticsearch] = None) -> Dict[str, Any]:
    """Aplica alterações ao perfil do utilizador (substitui apenas o que vem no patch)."""
    es = client or _client()
    user = get_user_by_id(user_id, es)
    if not user:
        raise AuthError("Conta não encontrada.", status_code=404, code="not_found")

    key = normalize_email(user.get("email") or "")
    allowed = {"name", "title", "organization", "phone", "locale", "timezone"}
    document: Dict[str, Any] = {"updated_at": _now_iso()}

    for field in allowed:
        if field not in patch:
            continue
        value = patch[field]
        if value is None:
            continue
        text = str(value).strip()
        if field == "name":
            problem = validate_name(text)
            if problem:
                raise AuthError(problem, status_code=422, code="invalid_input")
        document[field] = text[:160]
    if "name" in document:
        document["initials"] = _initials(document["name"], key)

    preferences = patch.get("preferences")
    if isinstance(preferences, dict):
        merged = {**(user.get("preferences") or {})}
        for field, value in preferences.items():
            if field in ALLOWED_PREFERENCES:
                merged[field] = value
        document["preferences"] = merged

    try:
        es.update(index=AUTH_USERS_INDEX, id=key, doc=document, refresh=True)
    except Exception as error:  # noqa: BLE001
        logger.exception("Falha ao atualizar utilizador")
        raise AuthError("Não foi possível guardar as alterações.", status_code=502, code="es_error") from error

    updated = {**user, **document}
    return public_user(updated)


def set_password(user_id: str, new_password: str, *, client: Optional[Elasticsearch] = None) -> None:
    es = client or _client()
    problem = validate_password_strength(new_password)
    if problem:
        raise AuthError(problem, status_code=422, code="invalid_input")
    user = get_user_by_id(user_id, es)
    if not user:
        raise AuthError("Conta não encontrada.", status_code=404, code="not_found")
    key = normalize_email(user.get("email") or "")
    try:
        es.update(
            index=AUTH_USERS_INDEX,
            id=key,
            doc={"password": hash_password(new_password), "updated_at": _now_iso()},
            refresh=True,
        )
    except Exception as error:  # noqa: BLE001
        raise AuthError("Não foi possível alterar a palavra-passe.", status_code=502, code="es_error") from error


def change_password(user_id: str, current_password: str, new_password: str) -> None:
    """Altera a palavra-passe depois de confirmar a atual."""
    user = get_user_by_id(user_id)
    if not user:
        raise AuthError("Conta não encontrada.", status_code=404, code="not_found")
    if not verify_password(current_password, user.get("password")):
        raise AuthError("A palavra-passe atual não está correta.", status_code=401, code="invalid_credentials")
    if current_password == new_password:
        raise AuthError("A nova palavra-passe tem de ser diferente da atual.", status_code=422, code="invalid_input")
    set_password(user_id, new_password)


def record_login(user_id: str) -> None:
    """Regista a data/count do último início de sessão."""
    es = _client()
    user = get_user_by_id(user_id, es)
    if not user:
        return
    key = normalize_email(user.get("email") or "")
    try:
        es.update(
            index=AUTH_USERS_INDEX,
            id=key,
            doc={
                "last_login_at": _now_iso(),
                "login_count": int(user.get("login_count") or 0) + 1,
                "updated_at": _now_iso(),
            },
            refresh=True,
        )
    except Exception:  # noqa: BLE001 - não vale a pena falhar o login por isto
        logger.warning("Não foi possível registar o último login de %s", user_id)


def delete_account(user_id: str) -> None:
    """Apaga a conta e todas as suas sessões."""
    es = _client()
    user = get_user_by_id(user_id, es)
    if not user:
        raise AuthError("Conta não encontrada.", status_code=404, code="not_found")
    key = normalize_email(user.get("email") or "")
    try:
        es.delete(index=AUTH_USERS_INDEX, id=key, refresh=True)
    except Exception as error:  # noqa: BLE001
        raise AuthError("Não foi possível apagar a conta.", status_code=502, code="es_error") from error
    revoke_all_sessions(user_id, client=es)


def list_users(limit: int = 200) -> List[Dict[str, Any]]:
    """Lista contas (para administração)."""
    es = _client()
    try:
        resp = es.search(
            index=AUTH_USERS_INDEX,
            body={"query": {"match_all": {}}, "size": max(1, min(limit, 500)), "sort": [{"created_at": "desc"}]},
        )
    except Exception:
        return []
    return [public_user(hit["_source"]) for hit in resp.get("hits", {}).get("hits", [])]


# ------------------------------------------------------------------ sessões
def create_session(
    user: Dict[str, Any],
    *,
    ttl: timedelta = SESSION_TTL_DEFAULT,
    user_agent: str = "",
    ip: str = "",
) -> Dict[str, Any]:
    """Abre uma sessão e devolve o token assinado + os dados da sessão."""
    es = _client()
    session_id = secrets.token_hex(24)
    token, expires_at = issue_token(session_id, str(user.get("id")), ttl)
    document = {
        "session_id": session_id,
        "user_id": user.get("id"),
        "email": user.get("email"),
        "created_at": _now_iso(),
        "last_seen_at": _now_iso(),
        "expires_at": expires_at,
        "revoked": False,
        "revoked_at": None,
        "user_agent": (user_agent or "")[:300],
        "ip": (ip or "")[:64],
    }
    try:
        es.index(index=AUTH_SESSIONS_INDEX, id=session_id, document=document, refresh=True)
    except Exception as error:  # noqa: BLE001
        raise AuthError("Não foi possível iniciar a sessão.", status_code=502, code="es_error") from error
    return {"token": token, "expires_at": expires_at, "session": _public_session(document, session_id)}


def _public_session(source: Dict[str, Any], session_id: str) -> Dict[str, Any]:
    return {
        "id": session_id,
        "created_at": source.get("created_at"),
        "last_seen_at": source.get("last_seen_at"),
        "expires_at": source.get("expires_at"),
        "user_agent": source.get("user_agent") or "",
        "ip": source.get("ip") or "",
    }


def get_session(session_id: str, client: Optional[Elasticsearch] = None) -> Optional[Dict[str, Any]]:
    es = client or _client()
    try:
        resp = es.get(index=AUTH_SESSIONS_INDEX, id=session_id)
    except Exception:
        return None
    source = dict(resp.get("_source") or {})
    if source.get("revoked"):
        return None
    expires_at = source.get("expires_at")
    if expires_at:
        try:
            if datetime.fromisoformat(str(expires_at).replace("Z", "+00:00")) <= datetime.now(timezone.utc):
                return None
        except ValueError:
            pass
    source["session_id"] = session_id
    return source


def touch_session(session_id: str) -> None:
    """Atualiza `last_seen_at` (sem bloquear o pedido)."""
    es = get_es_client()
    if not es:
        return
    try:
        es.update(
            index=AUTH_SESSIONS_INDEX,
            id=session_id,
            doc={"last_seen_at": _now_iso()},
        )
    except Exception:  # noqa: BLE001
        pass


def revoke_session(session_id: str, *, client: Optional[Elasticsearch] = None) -> bool:
    """Termina uma sessão (logout)."""
    es = client or _client()
    try:
        es.update(
            index=AUTH_SESSIONS_INDEX,
            id=session_id,
            doc={"revoked": True, "revoked_at": _now_iso()},
            refresh=True,
        )
        return True
    except Exception:
        return False


def revoke_all_sessions(user_id: str, *, keep: Optional[str] = None, client: Optional[Elasticsearch] = None) -> int:
    """Termina todas as sessões de um utilizador (opcionalmente mantendo uma)."""
    es = client or _client()
    try:
        resp = es.search(
            index=AUTH_SESSIONS_INDEX,
            body={"query": {"bool": {"filter": [{"term": {"user_id": user_id}}, {"term": {"revoked": False}}]}}, "size": 500},
        )
    except Exception:
        return 0
    count = 0
    for hit in resp.get("hits", {}).get("hits", []):
        if keep and hit["_id"] == keep:
            continue
        try:
            es.update(index=AUTH_SESSIONS_INDEX, id=hit["_id"], doc={"revoked": True, "revoked_at": _now_iso()})
            count += 1
        except Exception:  # noqa: BLE001
            continue
    return count


def list_sessions(user_id: str, *, client: Optional[Elasticsearch] = None) -> List[Dict[str, Any]]:
    """Sessões ativas do utilizador (mais recentes primeiro)."""
    es = client or _client()
    try:
        resp = es.search(
            index=AUTH_SESSIONS_INDEX,
            body={
                "query": {
                    "bool": {
                        "filter": [
                            {"term": {"user_id": user_id}},
                            {"term": {"revoked": False}},
                            {"range": {"expires_at": {"gt": _now_iso()}}},
                        ]
                    }
                },
                "size": 100,
                "sort": [{"created_at": {"order": "desc"}}],
            },
        )
    except Exception:
        return []
    return [_public_session(hit["_source"], hit["_id"]) for hit in resp.get("hits", {}).get("hits", [])]


def stats() -> Dict[str, Any]:
    """Números do índice de contas e sessões (para o painel de administração)."""
    es = _client()
    try:
        users = int(es.count(index=AUTH_USERS_INDEX).get("count", 0))
        sessions = int(
            es.count(
                index=AUTH_SESSIONS_INDEX,
                body={
                    "query": {
                        "bool": {"filter": [{"term": {"revoked": False}}, {"range": {"expires_at": {"gt": _now_iso()}}}]}
                    }
                },
            ).get("count", 0)
        )
    except Exception:
        raise AuthError("Não foi possível ler as estatísticas.", status_code=502, code="es_error")
    return {"users": users, "active_sessions": sessions}
