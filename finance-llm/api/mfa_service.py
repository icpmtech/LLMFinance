"""Verificação em dois passos (MFA) com código enviado por email.

O login em duas etapas é **opcional** e gerido pela administração:

* a **política** (`finance_settings`, `id = auth_mfa`) decide quem é desafiado —
  ninguém, apenas administradores ou todas as contas;
* cada conta pode ainda ativar/desativar a verificação para si própria
  (`finance_users.mfa`), exceto quando a política a obriga.

O código de 6 dígitos é gerado no servidor, enviado para o email da conta e
guardado **apenas** como HMAC (`finance_auth_challenges`), com validade, limite
de tentativas e intervalo mínimo entre reenvios. Nada disto vive em memória, pelo
que sobrevive a reinícios e pode ser auditado.
"""
from __future__ import annotations

import hashlib
import hmac
import logging
import secrets
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from api import auth_service
from api import notification_email
from api.elasticsearch_client import (
    AUTH_CHALLENGES_INDEX,
    SETTINGS_INDEX,
    ensure_indices,
    get_es_client,
)

logger = logging.getLogger(__name__)

DOC_ID = "auth_mfa"
DOC_KIND = "auth_mfa"

POLICY_OFF = "off"
POLICY_ADMINS = "admins"
POLICY_ALL = "all"
POLICIES = (POLICY_OFF, POLICY_ADMINS, POLICY_ALL)
POLICY_LABELS: Dict[str, str] = {
    POLICY_OFF: "Desligado (só para quem ativar na própria conta)",
    POLICY_ADMINS: "Apenas administradores",
    POLICY_ALL: "Todas as contas",
}

CODE_DIGITS = 6
DEFAULT_TTL_SECONDS = 600
MIN_TTL_SECONDS = 120
MAX_TTL_SECONDS = 1800
DEFAULT_MAX_ATTEMPTS = 5
MIN_MAX_ATTEMPTS = 3
MAX_MAX_ATTEMPTS = 10
DEFAULT_RESEND_SECONDS = 60
MIN_RESEND_SECONDS = 15
MAX_RESEND_SECONDS = 600

# Travão contra tentativas em série: cada login cria um desafio novo, por isso o
# limite de tentativas de um código sozinho não chegaria.
CHALLENGE_WINDOW_MINUTES = 15
CHALLENGE_LIMIT_PER_WINDOW = 10

# Um segundo login imediato (duplo clique, repetir, recarregar) reutiliza o
# desafio que já está aberto em vez de criar outro: o código que seguiu por email
# continua a valer e o ecrã recebe o mesmo `challenge_id`. Sem isto, o email que o
# utilizador tem à frente deixava de servir assim que o login fosse repetido.
REUSE_WINDOW_SECONDS = 60


class MfaError(Exception):
    """Erro de verificação em dois passos com código HTTP associado."""

    def __init__(self, message: str, status_code: int = 400, code: str = "mfa_error", retry_after: int = 0):
        super().__init__(message)
        self.message = message
        self.status_code = status_code
        self.code = code
        self.retry_after = retry_after


# ------------------------------------------------------------------ infraestrutura
def _client():
    client = get_es_client()
    if not client:
        raise MfaError("Base de dados (Elasticsearch) indisponível.", status_code=503, code="es_unavailable")
    ensure_indices(client)
    return client


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(moment: datetime) -> str:
    return moment.isoformat(timespec="seconds").replace("+00:00", "Z")


def _parse_iso(value: Any) -> Optional[datetime]:
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None


def _clamp_int(value: Any, default: int, low: int, high: int) -> int:
    try:
        number = int(value)
    except (TypeError, ValueError):
        return default
    return max(low, min(high, number))


# ---------------------------------------------------------------------- política
def _default_policy() -> Dict[str, Any]:
    return {
        "policy": POLICY_OFF,
        "code_ttl_seconds": DEFAULT_TTL_SECONDS,
        "max_attempts": DEFAULT_MAX_ATTEMPTS,
        "resend_cooldown_seconds": DEFAULT_RESEND_SECONDS,
        "updated_at": None,
        "updated_by": "",
    }


def _clean_policy(payload: Dict[str, Any], *, updated_at: Optional[str], updated_by: str) -> Dict[str, Any]:
    policy = str((payload or {}).get("policy") or POLICY_OFF).strip().lower()
    if policy not in POLICIES:
        policy = POLICY_OFF
    return {
        "policy": policy,
        "code_ttl_seconds": _clamp_int(
            (payload or {}).get("code_ttl_seconds"), DEFAULT_TTL_SECONDS, MIN_TTL_SECONDS, MAX_TTL_SECONDS
        ),
        "max_attempts": _clamp_int(
            (payload or {}).get("max_attempts"), DEFAULT_MAX_ATTEMPTS, MIN_MAX_ATTEMPTS, MAX_MAX_ATTEMPTS
        ),
        "resend_cooldown_seconds": _clamp_int(
            (payload or {}).get("resend_cooldown_seconds"),
            DEFAULT_RESEND_SECONDS,
            MIN_RESEND_SECONDS,
            MAX_RESEND_SECONDS,
        ),
        "updated_at": updated_at,
        "updated_by": updated_by or "",
    }


def policy() -> Dict[str, Any]:
    """Política efetiva (por omissão, desligada)."""
    try:
        client = _client()
        if not client.exists(index=SETTINGS_INDEX, id=DOC_ID):
            return _default_policy()
        source = client.get(index=SETTINGS_INDEX, id=DOC_ID).get("_source") or {}
    except MfaError:
        raise
    except Exception as error:  # noqa: BLE001 - definição ilegível não pode trancar o login
        logger.warning("Política de MFA ilegível: %s", error)
        return _default_policy()
    return _clean_policy(
        source.get("payload") or {},
        updated_at=source.get("updated_at"),
        updated_by=str(source.get("updated_by") or ""),
    )


def save_policy(payload: Dict[str, Any], *, actor_email: str = "") -> Dict[str, Any]:
    """Grava a política (gerida na administração) e devolve o estado resultante."""
    policy_value = str((payload or {}).get("policy") or POLICY_OFF).strip().lower()
    if policy_value not in POLICIES:
        raise MfaError(
            f"Política inválida (use {', '.join(POLICIES)}).", status_code=422, code="invalid_input"
        )
    document = _clean_policy(payload, updated_at=_iso(_now()), updated_by=actor_email)
    client = _client()
    try:
        client.index(
            index=SETTINGS_INDEX,
            id=DOC_ID,
            document={
                "kind": DOC_KIND,
                "id": DOC_ID,
                "payload": {
                    "policy": document["policy"],
                    "code_ttl_seconds": document["code_ttl_seconds"],
                    "max_attempts": document["max_attempts"],
                    "resend_cooldown_seconds": document["resend_cooldown_seconds"],
                },
                "updated_at": document["updated_at"],
                "updated_by": actor_email,
            },
            refresh=True,
        )
    except Exception as error:  # noqa: BLE001
        logger.exception("Falha ao gravar a política de MFA")
        raise MfaError("Não foi possível guardar a política de MFA.", status_code=502, code="es_error") from error
    return document


def email_configured() -> bool:
    """Se o envio de códigos está operacional (SMTP configurado)."""
    try:
        return notification_email.is_configured()
    except Exception:  # noqa: BLE001 - configuração ilegível não deve rebentar a página
        return False


def overview() -> Dict[str, Any]:
    """Estado completo para o backoffice (política + avisos + catálogo)."""
    try:
        current = policy()
        error = None
    except MfaError as caught:
        current = _default_policy()
        error = caught.message
    configured = email_configured()
    warning = None
    if current["policy"] != POLICY_OFF and not configured:
        warning = (
            "O envio de email não está configurado: com a verificação em dois passos ativa, "
            "ninguém consegue concluir o login. Configure o SMTP em «Chaves» antes de ativar."
        )
    return {
        **current,
        "label": POLICY_LABELS.get(current["policy"], current["policy"]),
        "policies": [{"value": value, "label": POLICY_LABELS[value]} for value in POLICIES],
        "email_configured": configured,
        "warning": warning,
        "error": error,
        "limits": {
            "code_ttl_seconds": [MIN_TTL_SECONDS, MAX_TTL_SECONDS],
            "max_attempts": [MIN_MAX_ATTEMPTS, MAX_MAX_ATTEMPTS],
            "resend_cooldown_seconds": [MIN_RESEND_SECONDS, MAX_RESEND_SECONDS],
        },
    }


# ---------------------------------------------------------------- quem é desafiado
def user_enabled(user: Optional[Dict[str, Any]]) -> bool:
    """Preferência guardada na conta.

    Aceita o documento cru do Elasticsearch (`mfa: {enabled: …}`) e o retrato
    público devolvido pela API (`mfa_enabled`), para o mesmo cálculo servir na
    rota de login e nas definições da conta.
    """
    data = user or {}
    stored = data.get("mfa")
    if isinstance(stored, dict):
        return bool(stored.get("enabled"))
    return bool(data.get("mfa_enabled"))


def is_enforced(user: Optional[Dict[str, Any]], settings: Optional[Dict[str, Any]] = None) -> bool:
    """True quando a política obriga esta conta a usar MFA (ignora a preferência)."""
    if not user:
        return False
    current = settings or policy()
    if current["policy"] == POLICY_ALL:
        return True
    if current["policy"] == POLICY_ADMINS:
        return str(user.get("role") or "member") == auth_service.ROLE_ADMIN
    return False


def required_for(user: Optional[Dict[str, Any]], settings: Optional[Dict[str, Any]] = None) -> bool:
    """Se o login desta conta tem de passar pelo código de verificação."""
    if not user:
        return False
    return user_enabled(user) or is_enforced(user, settings)


def status_for(user: Dict[str, Any], settings: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Estado apresentado ao utilizador autenticado (definições da conta)."""
    current = settings or policy()
    enforced = is_enforced(user, current)
    return {
        "policy": current["policy"],
        "policy_label": POLICY_LABELS.get(current["policy"], current["policy"]),
        "enforced": enforced,
        "user_enabled": user_enabled(user),
        "required": enforced or user_enabled(user),
        "can_change": not enforced,
        "email": user.get("email") or "",
        "email_configured": email_configured(),
        "code_ttl_seconds": current["code_ttl_seconds"],
        "max_attempts": current["max_attempts"],
        "resend_cooldown_seconds": current["resend_cooldown_seconds"],
    }


# --------------------------------------------------------------------- desafios
def mask_email(email: str) -> str:
    """`ana.ribeiro@empresa.pt` → `an***@empresa.pt` (para mostrar no ecrã)."""
    value = (email or "").strip()
    if "@" not in value:
        return value
    user, _, domain = value.partition("@")
    visible = user[:2] if len(user) > 2 else user[:1]
    return f"{visible}***@{domain}"


def _new_code() -> str:
    return f"{secrets.randbelow(10 ** CODE_DIGITS):0{CODE_DIGITS}d}"


def _code_hash(challenge_id: str, code: str) -> str:
    """HMAC do código: o valor em claro nunca chega ao índice."""
    message = f"{challenge_id}:{code}".encode("utf-8")
    return hmac.new(auth_service.signing_secret(), message, hashlib.sha256).hexdigest()


def _recent_challenges(user_id: str, client) -> int:
    """Quantos desafios esta conta pediu na janela recente (travão anti-força-bruta)."""
    since = _iso(_now() - timedelta(minutes=CHALLENGE_WINDOW_MINUTES))
    try:
        response = client.search(
            index=AUTH_CHALLENGES_INDEX,
            body={
                "size": 0,
                "query": {
                    "bool": {
                        "filter": [
                            {"term": {"user_id": user_id}},
                            {"range": {"created_at": {"gte": since}}},
                        ],
                        # Os códigos que já foram usados com sucesso não contam:
                        # o travão é para tentativas falhadas, não para quem entra
                        # várias vezes de forma legítima.
                        "must_not": [{"term": {"verified": True}}],
                    }
                },
            },
        )
        hits = response.get("hits", {}).get("total", 0)
        if isinstance(hits, dict):
            hits = hits.get("value", 0)
        return int(hits or 0)
    except Exception as error:  # noqa: BLE001 - não travar o login por causa da contagem
        logger.debug("MFA: contagem de desafios recentes falhou: %s", error)
        return 0


def _age_seconds(value: Any) -> Optional[float]:
    created = _parse_iso(value)
    if not created:
        return None
    try:
        return (_now() - created).total_seconds()
    except TypeError:
        return None


def _open_challenge(user_id: str, client) -> Optional[Dict[str, Any]]:
    """Desafio aberto (não usado e ainda válido) mais recente da conta."""
    try:
        response = client.search(
            index=AUTH_CHALLENGES_INDEX,
            body={
                "size": 1,
                "query": {"bool": {"filter": [{"term": {"user_id": user_id}}, {"term": {"used": False}}]}},
                "sort": [{"created_at": {"order": "desc"}}],
            },
        )
    except Exception as error:  # noqa: BLE001 - sem leitura, cria-se um desafio novo
        logger.debug("MFA: não foi possível ler o desafio aberto: %s", error)
        return None
    hits = response.get("hits", {}).get("hits", [])
    if not hits:
        return None
    document = dict(hits[0].get("_source") or {})
    document["challenge_id"] = hits[0].get("_id") or document.get("challenge_id")
    expires = _parse_iso(document.get("expires_at"))
    if not expires or expires <= _now():
        return None
    return document


def _retire_open_challenges(user_id: str, client) -> None:
    """Um código novo anula os anteriores da mesma conta.

    Ficam marcados como usados (e não apagados): a marca impede a reutilização e
    o documento continua a contar para o travão de pedidos em série.
    """
    now = _iso(_now())
    try:
        response = client.search(
            index=AUTH_CHALLENGES_INDEX,
            body={
                "size": 50,
                "query": {"bool": {"filter": [{"term": {"user_id": user_id}}, {"term": {"used": False}}]}},
            },
        )
        for hit in response.get("hits", {}).get("hits", []):
            client.update(
                index=AUTH_CHALLENGES_INDEX,
                id=hit["_id"],
                doc={"used": True, "used_at": now},
                refresh=False,
            )
    except Exception as error:  # noqa: BLE001 - limpeza best-effort
        logger.debug("MFA: não foi possível anular os desafios anteriores: %s", error)


def _purge_old_challenges(user_id: str, client) -> None:
    """Apaga desafios antigos da conta (o histórico não serve para nada depois)."""
    cutoff = _iso(_now() - timedelta(days=1))
    try:
        client.delete_by_query(
            index=AUTH_CHALLENGES_INDEX,
            body={
                "query": {
                    "bool": {
                        "filter": [
                            {"term": {"user_id": user_id}},
                            {"range": {"created_at": {"lt": cutoff}}},
                        ]
                    }
                }
            },
            refresh=False,
            conflicts="proceed",
        )
    except Exception as error:  # noqa: BLE001 - best-effort
        logger.debug("MFA: não foi possível limpar desafios antigos: %s", error)


def create_challenge(
    user: Dict[str, Any],
    *,
    ip: str = "",
    user_agent: str = "",
    remember: bool = False,
) -> Dict[str, Any]:
    """Gera o código, envia-o por email e devolve o desafio criado."""
    settings = policy()
    email = str(user.get("email") or "")
    if not email:
        raise MfaError("A conta não tem email associado.", status_code=422, code="missing_email")

    client = _client()
    user_key = str(user.get("id") or email)

    # Login repetido há instantes: devolve o mesmo desafio (o código já enviado
    # continua válido e não se gera outro email).
    existing = _open_challenge(user_key, client)
    if existing:
        age = _age_seconds(existing.get("created_at"))
        if age is not None and age < REUSE_WINDOW_SECONDS:
            if bool(existing.get("remember")) != bool(remember):
                try:
                    client.update(
                        index=AUTH_CHALLENGES_INDEX,
                        id=existing["challenge_id"],
                        doc={"remember": bool(remember)},
                        refresh=False,
                    )
                except Exception as error:  # noqa: BLE001 - não impede o login
                    logger.debug("MFA: não foi possível atualizar o desafio: %s", error)
            return _public_challenge({**existing, "remember": bool(remember)}, settings, code_sent=False)

    if _recent_challenges(user_key, client) >= CHALLENGE_LIMIT_PER_WINDOW:
        raise MfaError(
            "Demasiados códigos pedidos em pouco tempo. Aguarde alguns minutos e tente novamente.",
            status_code=429,
            code="mfa_throttled",
            retry_after=CHALLENGE_WINDOW_MINUTES * 60,
        )
    challenge_id = secrets.token_hex(24)
    code = _new_code()
    now = _now()
    expires = now + timedelta(seconds=settings["code_ttl_seconds"])
    document = {
        "challenge_id": challenge_id,
        "user_id": user_key,
        "email": email,
        "code_hash": _code_hash(challenge_id, code),
        "created_at": _iso(now),
        "last_sent_at": _iso(now),
        "expires_at": _iso(expires),
        "attempts": 0,
        "max_attempts": settings["max_attempts"],
        "sends": 1,
        "used": False,
        "used_at": None,
        "remember": bool(remember),
        "user_agent": (user_agent or "")[:300],
        "ip": (ip or "")[:64],
    }

    _retire_open_challenges(user_key, client)
    _purge_old_challenges(user_key, client)
    try:
        client.index(index=AUTH_CHALLENGES_INDEX, id=challenge_id, document=document, refresh=True)
    except Exception as error:  # noqa: BLE001
        logger.exception("MFA: falha ao criar o desafio")
        raise MfaError("Não foi possível iniciar a verificação em dois passos.", status_code=502, code="es_error") from error

    delivery = _deliver(user, code, settings, ip)
    if not delivery.get("ok"):
        _mark_used(challenge_id, client)
        message = (
            "O envio de códigos por email não está configurado. Peça ao administrador para configurar o SMTP."
            if not delivery.get("configured", True)
            else "Não foi possível enviar o código de verificação. Tente novamente."
        )
        raise MfaError(message, status_code=503 if not delivery.get("configured", True) else 502, code="email_failed")

    return _public_challenge(document, settings)


def _deliver(user: Dict[str, Any], code: str, settings: Dict[str, Any], ip: str) -> Dict[str, Any]:
    return notification_email.send_login_code_email(
        to=str(user.get("email") or ""),
        name=str(user.get("name") or user.get("email") or ""),
        code=code,
        ttl_minutes=max(1, round(settings["code_ttl_seconds"] / 60)),
        ip=ip,
    )


def _public_challenge(
    document: Dict[str, Any], settings: Dict[str, Any], *, code_sent: bool = True
) -> Dict[str, Any]:
    return {
        "mfa_required": True,
        "challenge_id": document["challenge_id"],
        "email": mask_email(str(document.get("email") or "")),
        "expires_at": document.get("expires_at"),
        "resend_cooldown_seconds": settings["resend_cooldown_seconds"],
        "code_sent": bool(code_sent),
    }


def _fetch(challenge_id: str, client) -> Dict[str, Any]:
    if not challenge_id or not str(challenge_id).strip():
        raise MfaError("Desafio de verificação em falta.", status_code=422, code="invalid_input")
    try:
        source = client.get(index=AUTH_CHALLENGES_INDEX, id=str(challenge_id).strip()).get("_source") or {}
    except Exception as error:  # noqa: BLE001 - inexistente = inválido
        raise MfaError("Código inválido ou expirado. Inicie sessão novamente.", status_code=401, code="mfa_invalid") from error
    source["challenge_id"] = str(challenge_id).strip()
    return source


def _mark_used(challenge_id: str, client, *, verified: bool = False) -> None:
    try:
        client.update(
            index=AUTH_CHALLENGES_INDEX,
            id=challenge_id,
            doc={"used": True, "used_at": _iso(_now()), "verified": bool(verified)},
            refresh=True,
        )
    except Exception as error:  # noqa: BLE001 - best-effort
        logger.debug("MFA: não foi possível marcar o desafio como usado: %s", error)


def _ensure_open(document: Dict[str, Any], client) -> None:
    """Recusa desafios já usados ou expirados (marcando-os como usados)."""
    if document.get("used"):
        raise MfaError("Este código já foi utilizado. Inicie sessão novamente.", status_code=401, code="mfa_used")
    expires = _parse_iso(document.get("expires_at"))
    if not expires or expires <= _now():
        _mark_used(document["challenge_id"], client)
        raise MfaError("O código expirou. Inicie sessão novamente.", status_code=401, code="mfa_expired")


def verify(challenge_id: str, code: str) -> Dict[str, Any]:
    """Valida o código e devolve o desafio consumido (com `user_id`)."""
    normalized = "".join(ch for ch in str(code or "") if ch.isdigit())
    if len(normalized) != CODE_DIGITS:
        raise MfaError(f"Introduza os {CODE_DIGITS} dígitos do código.", status_code=422, code="invalid_input")

    client = _client()
    document = _fetch(challenge_id, client)
    _ensure_open(document, client)

    max_attempts = _clamp_int(document.get("max_attempts"), DEFAULT_MAX_ATTEMPTS, MIN_MAX_ATTEMPTS, MAX_MAX_ATTEMPTS)
    attempts = int(document.get("attempts") or 0)
    if attempts >= max_attempts:
        _mark_used(document["challenge_id"], client)
        raise MfaError(
            "Demasiadas tentativas. Inicie sessão novamente para receber um código novo.",
            status_code=401,
            code="mfa_locked",
        )

    expected = str(document.get("code_hash") or "")
    if not hmac.compare_digest(expected, _code_hash(document["challenge_id"], normalized)):
        remaining = max_attempts - (attempts + 1)
        try:
            client.update(
                index=AUTH_CHALLENGES_INDEX,
                id=document["challenge_id"],
                doc={"attempts": attempts + 1},
                refresh=True,
            )
        except Exception as error:  # noqa: BLE001 - não esconder o erro de código
            logger.debug("MFA: não foi possível registar a tentativa: %s", error)
        if remaining <= 0:
            _mark_used(document["challenge_id"], client)
            raise MfaError(
                "Demasiadas tentativas. Inicie sessão novamente para receber um código novo.",
                status_code=401,
                code="mfa_locked",
            )
        raise MfaError(
            f"Código incorreto. Restam {remaining} tentativa{'s' if remaining != 1 else ''}. "
            "Se recebeu mais do que um email, use o código do mais recente.",
            status_code=401,
            code="mfa_invalid",
        )

    _mark_used(document["challenge_id"], client, verified=True)
    return document


def resend(challenge_id: str, *, ip: str = "") -> Dict[str, Any]:
    """Envia um código novo para o mesmo desafio (com intervalo mínimo)."""
    client = _client()
    document = _fetch(challenge_id, client)
    _ensure_open(document, client)

    settings = policy()
    last_sent = _parse_iso(document.get("last_sent_at")) or _parse_iso(document.get("created_at"))
    if last_sent:
        elapsed = (_now() - last_sent).total_seconds()
        cooldown = settings["resend_cooldown_seconds"]
        if elapsed < cooldown:
            wait = int(cooldown - elapsed) + 1
            raise MfaError(
                f"Aguarde {wait} segundo{'s' if wait != 1 else ''} antes de pedir outro código.",
                status_code=429,
                code="mfa_cooldown",
                retry_after=wait,
            )

    code = _new_code()
    now = _now()
    expires = now + timedelta(seconds=settings["code_ttl_seconds"])
    update = {
        "code_hash": _code_hash(document["challenge_id"], code),
        "last_sent_at": _iso(now),
        "expires_at": _iso(expires),
        "attempts": 0,
        "max_attempts": settings["max_attempts"],
        "sends": int(document.get("sends") or 1) + 1,
    }
    try:
        client.update(index=AUTH_CHALLENGES_INDEX, id=document["challenge_id"], doc=update, refresh=True)
    except Exception as error:  # noqa: BLE001
        logger.exception("MFA: falha ao renovar o desafio")
        raise MfaError("Não foi possível gerar um código novo.", status_code=502, code="es_error") from error

    delivery = _deliver(
        {"email": document.get("email"), "name": document.get("email")},
        code,
        settings,
        ip or str(document.get("ip") or ""),
    )
    if not delivery.get("ok"):
        message = (
            "O envio de códigos por email não está configurado. Peça ao administrador para configurar o SMTP."
            if not delivery.get("configured", True)
            else "Não foi possível enviar o código de verificação. Tente novamente."
        )
        raise MfaError(message, status_code=503 if not delivery.get("configured", True) else 502, code="email_failed")

    return _public_challenge({**document, **update}, settings)


def pending_for_user(user_id: str) -> List[Dict[str, Any]]:
    """Desafios ainda válidos de uma conta (apoio à administração/auditoria)."""
    client = get_es_client()
    if not client:
        return []
    try:
        response = client.search(
            index=AUTH_CHALLENGES_INDEX,
            body={
                "query": {"bool": {"filter": [{"term": {"user_id": str(user_id)}}, {"term": {"used": False}}]}},
                "size": 20,
                "sort": [{"created_at": "desc"}],
            },
        )
    except Exception:  # noqa: BLE001
        return []
    return [dict(hit.get("_source") or {}) for hit in response.get("hits", {}).get("hits", [])]
