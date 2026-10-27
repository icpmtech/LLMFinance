"""Apoio ao cliente — conversas, tickets e registos.

Substitui o Tawk.to nas páginas públicas (site, loja e SPA). O modelo é o de
qualquer *live chat*: um **visitante** abre uma conversa, a conversa fica em
espera e um **operador** (conta com papel `admin`) assume-a no backoffice.

O que fica guardado, e onde:

- `finance_support_visitors` — ficha acumulada do visitante (perfil, primeira e
  última página, número de conversas);
- `finance_support_sessions` — uma conversa: estado (`waiting`/`active`/`closed`),
  operador atribuído, contadores de não lidos, contexto do browser (página,
  referrer, idioma, fuso, ecrã, IP) e histórico de páginas visitadas;
- `finance_support_messages` — mensagens (visitante, operador, sistema ou nota
  interna), num índice próprio para as conversas crescerem sem reescrever a
  sessão a cada mensagem;
- `finance_support_tickets` — tickets abertos a partir da conversa (ou pelo
  backoffice), com estado, prioridade, categoria e notas;
- `finance_support_events` — registo de tudo o que acontece na conversa
  (aberta, assumida, mensagem, ticket, fecho, avaliação), para auditoria;
- `finance_support_operators` — presença dos operadores (online/ausente/offline).

A entrega em tempo real (WebSocket) vive em `api/support_routes.py`; este módulo
só trata de persistência, para poder ser testado sem sockets.
"""
from __future__ import annotations

import logging
import secrets
import threading
import time
from collections import deque
from datetime import datetime, timedelta, timezone
from typing import Any, Deque, Dict, Iterable, List, Optional, Tuple

from api import events_service as system_events
from api.elasticsearch_client import (
    SUPPORT_EVENTS_INDEX,
    SUPPORT_FORM_RESPONSES_INDEX,
    SUPPORT_MESSAGES_INDEX,
    SUPPORT_OPERATORS_INDEX,
    SUPPORT_SESSIONS_INDEX,
    SUPPORT_TICKETS_INDEX,
    SUPPORT_VISITORS_INDEX,
    get_es_client,
)
from api.es.support_mappings import ensure_support_indices

logger = logging.getLogger(__name__)

# --------------------------------------------------------------- constantes
STATUS_WAITING = "waiting"
STATUS_ACTIVE = "active"
STATUS_CLOSED = "closed"
SESSION_STATUSES = (STATUS_WAITING, STATUS_ACTIVE, STATUS_CLOSED)
STATUS_LABELS = {
    STATUS_WAITING: "À espera",
    STATUS_ACTIVE: "Em curso",
    STATUS_CLOSED: "Fechada",
}

AUTHOR_VISITOR = "visitor"
AUTHOR_OPERATOR = "operator"
AUTHOR_SYSTEM = "system"
AUTHOR_NOTE = "note"

MESSAGE_TEXT = "text"
MESSAGE_LINK = "link"
MESSAGE_REPORT = "report"
MESSAGE_FORM = "form"
MESSAGE_FORM_RESPONSE = "form_response"
MESSAGE_KINDS = (MESSAGE_TEXT, MESSAGE_LINK, MESSAGE_REPORT, MESSAGE_FORM)

FORM_FIELD_TYPES = ("text", "email", "tel", "textarea", "select", "number", "date")
FORM_MAX_FIELDS = 12
FORM_MAX_OPTIONS = 20
FORM_VALUE_MAX_LEN = 2000
LINK_TITLE_MAX_LEN = 160
LINK_DESCRIPTION_MAX_LEN = 1000
REPORT_SUMMARY_MAX_LEN = 1500

#: Modelos de formulário que o operador pode enviar sem construir campos.
FORM_TEMPLATES: Tuple[Dict[str, Any], ...] = (
    {
        "id": "contacto",
        "title": "Dados de contacto",
        "description": "Para falarmos consigo, indique os seus dados.",
        "fields": [
            {"key": "nome", "label": "Nome", "type": "text", "required": True},
            {"key": "email", "label": "Email", "type": "email", "required": True},
            {"key": "telefone", "label": "Telefone", "type": "tel", "required": False},
            {"key": "mensagem", "label": "Como podemos ajudar?", "type": "textarea", "required": True},
        ],
    },
    {
        "id": "empresa",
        "title": "Dados da empresa",
        "description": "Identifique a empresa para prepararmos a resposta.",
        "fields": [
            {"key": "nome", "label": "Nome", "type": "text", "required": True},
            {"key": "email", "label": "Email", "type": "email", "required": True},
            {"key": "empresa", "label": "Empresa", "type": "text", "required": True},
            {"key": "nif", "label": "NIF", "type": "text", "required": False},
            {"key": "funcao", "label": "Função", "type": "text", "required": False},
            {"key": "mensagem", "label": "O que precisa?", "type": "textarea", "required": True},
        ],
    },
    {
        "id": "faturacao",
        "title": "Dados de faturação",
        "description": "Indique os dados para tratarmos da faturação.",
        "fields": [
            {"key": "nome", "label": "Nome", "type": "text", "required": True},
            {"key": "email", "label": "Email", "type": "email", "required": True},
            {"key": "nif", "label": "NIF", "type": "text", "required": True},
            {"key": "referencia", "label": "Referência", "type": "text", "required": False},
            {"key": "descricao", "label": "Descrição", "type": "textarea", "required": True},
        ],
    },
)

TICKET_OPEN = "open"
TICKET_PENDING = "pending"
TICKET_RESOLVED = "resolved"
TICKET_CLOSED = "closed"
TICKET_STATUSES = (TICKET_OPEN, TICKET_PENDING, TICKET_RESOLVED, TICKET_CLOSED)
TICKET_STATUS_LABELS = {
    TICKET_OPEN: "Aberto",
    TICKET_PENDING: "Pendente",
    TICKET_RESOLVED: "Resolvido",
    TICKET_CLOSED: "Fechado",
}
TICKET_PRIORITIES = ("low", "normal", "high", "urgent")
TICKET_PRIORITY_LABELS = {"low": "Baixa", "normal": "Normal", "high": "Alta", "urgent": "Urgente"}

OPERATOR_ONLINE = "online"
OPERATOR_AWAY = "away"
OPERATOR_OFFLINE = "offline"

BODY_MAX_LEN = 4000
SUBJECT_MAX_LEN = 200
DESCRIPTION_MAX_LEN = 8000
NAME_MAX_LEN = 120
EMAIL_MAX_LEN = 160
MESSAGE_PAGE_SIZE = 500

#: Uma conversa aberta é retomada se o visitante voltar dentro deste prazo.
SESSION_REUSE_HOURS = 12

#: Configuração do widget, comum ao site, à loja e à SPA.
SUPPORT_CONFIG: Dict[str, Any] = {
    "title": "Apoio ao cliente",
    "greeting": "Olá! Em que podemos ajudar?",
    "away_message": "Deixe a sua mensagem e respondemos assim que possível.",
    "online_message": "Normalmente respondemos em poucos minutos.",
    "placeholder": "Escreva a sua mensagem…",
    "quick_replies": [
        "Tenho uma pergunta",
        "Quero saber mais",
        "Tenho um problema na conta",
    ],
    "ticket_categories": ["Conta", "Faturação", "Dados", "Sugestão", "Outro"],
    "business_hours": "Dias úteis, 9h–19h (Lisboa)",
}

#: Fora deste intervalo (hora local do servidor) a equipa é dada como ausente
#: quando não há operadores ligados.
BUSINESS_START_HOUR = 9
BUSINESS_END_HOUR = 19


class SupportError(Exception):
    """Erro do módulo de apoio com um estado HTTP associado."""

    def __init__(self, message: str, status_code: int = 400, code: str = "support_error"):
        super().__init__(message)
        self.message = message
        self.status_code = status_code
        self.code = code


# --------------------------------------------------------------------- base
_schema_lock = threading.Lock()
_schema_checked_at = 0.0
_SCHEMA_TTL = 300.0


def _client():
    """Cliente Elasticsearch, garantindo (com folga) que os índices existem."""
    global _schema_checked_at
    client = get_es_client()
    if not client:
        raise SupportError("Base de dados do apoio indisponível.", 503, "es_unavailable")
    now = time.monotonic()
    if now - _schema_checked_at > _SCHEMA_TTL:
        with _schema_lock:
            if now - _schema_checked_at > _SCHEMA_TTL:
                try:
                    ensure_support_indices(client)
                except Exception as exc:  # noqa: BLE001 - o índice pode ser criado na escrita
                    logger.debug("Apoio: não foi possível verificar os índices: %s", exc)
                _schema_checked_at = time.monotonic()
    return client


def reset_schema_cache() -> None:
    """Força a verificação dos índices na próxima utilização (testes/recuperação)."""
    global _schema_checked_at
    _schema_checked_at = 0.0


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(value: Optional[datetime] = None) -> str:
    return (value or _now()).isoformat()


def _clean(value: Any, limit: int) -> str:
    text = str(value or "").replace("\x00", "").strip()
    return text[:limit]


def clean_text(value: Any, limit: int) -> str:
    """Texto normalizado e truncado (helper público para as rotas)."""
    return _clean(value, limit)


def _valid_email(value: str) -> bool:
    if not value:
        return True
    local, _, domain = value.partition("@")
    return bool(local and domain and "." in domain and " " not in value)


def _valid_url(value: Any) -> str:
    """Aceita apenas http(s) absoluto ou caminho interno iniciado por `/`."""
    from urllib.parse import urlparse

    text = _clean(value, 2000)
    if not text:
        return ""
    parsed = urlparse(text)
    if parsed.scheme:
        if parsed.scheme not in ("http", "https") or not parsed.netloc:
            return ""
        return text
    if text.startswith("/") and not text.startswith("//"):
        return text
    return ""


def _slug_key(value: Any, fallback: str = "campo") -> str:
    import re
    import unicodedata

    text = unicodedata.normalize("NFKD", str(value or ""))
    text = "".join(char for char in text if not unicodedata.combining(char))
    text = re.sub(r"[^a-zA-Z0-9_]+", "_", text).strip("_").lower()
    return (text or fallback)[:40]


def normalise_rich_payload(kind: str, payload: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """Valida e normaliza o conteúdo de uma mensagem rica (link/relatório/form)."""
    raw = payload if isinstance(payload, dict) else {}
    if kind == MESSAGE_LINK:
        url = _valid_url(raw.get("url"))
        if not url:
            raise SupportError("Indique um endereço http(s) válido.", 400, "invalid_url")
        title = _clean(raw.get("title"), LINK_TITLE_MAX_LEN) or url
        return {
            "url": url,
            "title": title,
            "description": _clean(raw.get("description"), LINK_DESCRIPTION_MAX_LEN),
        }
    if kind == MESSAGE_REPORT:
        url = _valid_url(raw.get("url"))
        title = _clean(raw.get("title"), LINK_TITLE_MAX_LEN)
        if not title:
            raise SupportError("Indique o título do relatório.", 400, "invalid_report")
        if not url:
            raise SupportError("Indique o endereço do relatório.", 400, "invalid_url")
        return {
            "report_id": _clean(raw.get("report_id"), 80),
            "title": title,
            "summary": _clean(raw.get("summary"), REPORT_SUMMARY_MAX_LEN),
            "url": url,
            "free": bool(raw.get("free")),
            "area": _clean(raw.get("area"), 60),
        }
    if kind == MESSAGE_FORM:
        fields: List[Dict[str, Any]] = []
        seen: set = set()
        for index, item in enumerate(raw.get("fields") or []):
            if not isinstance(item, dict) or len(fields) >= FORM_MAX_FIELDS:
                continue
            field_type = _clean(item.get("type"), 20).lower() or "text"
            if field_type not in FORM_FIELD_TYPES:
                field_type = "text"
            label = _clean(item.get("label"), 80)
            if not label:
                continue
            key = _slug_key(item.get("key") or label, f"campo_{index + 1}")
            while key in seen:
                key = f"{key}_{index + 1}"
            seen.add(key)
            options = [
                _clean(option, 80)
                for option in (item.get("options") or [])
                if _clean(option, 80)
            ][:FORM_MAX_OPTIONS]
            fields.append(
                {
                    "key": key,
                    "label": label,
                    "type": field_type,
                    "required": bool(item.get("required")),
                    "placeholder": _clean(item.get("placeholder"), 120),
                    "options": options,
                }
            )
        if not fields:
            raise SupportError("O formulário tem de ter pelo menos um campo.", 400, "invalid_form")
        return {
            "form_id": "f_" + secrets.token_hex(8),
            "title": _clean(raw.get("title"), 120) or "Formulário de apoio",
            "description": _clean(raw.get("description"), 1000),
            "submit_label": _clean(raw.get("submit_label"), 40) or "Enviar",
            "template": _clean(raw.get("template"), 40),
            "fields": fields,
        }
    raise SupportError("Tipo de mensagem inválido.", 400, "invalid_kind")


def validate_form_values(payload: Dict[str, Any], values: Dict[str, Any]) -> Dict[str, str]:
    """Valida as respostas de um formulário e devolve apenas os campos previstos."""
    fields = payload.get("fields") or []
    clean_values: Dict[str, str] = {}
    if not isinstance(values, dict):
        raise SupportError("Resposta inválida.", 400, "invalid_form_response")
    for field in fields:
        key = str(field.get("key") or "")
        raw = values.get(key)
        text = _clean(raw, FORM_VALUE_MAX_LEN)
        if field.get("required") and not text:
            raise SupportError(f"Preencha o campo «{field.get('label')}».", 400, "missing_field")
        if not text:
            continue
        if field.get("type") == "email" and not _valid_email(text):
            raise SupportError(f"O email em «{field.get('label')}» não é válido.", 400, "invalid_email")
        if field.get("type") == "number":
            try:
                float(text.replace(",", "."))
            except ValueError as exc:
                raise SupportError(f"«{field.get('label')}» tem de ser um número.", 400, "invalid_number") from exc
        if field.get("type") == "select":
            options = [str(option) for option in (field.get("options") or [])]
            if options and text not in options:
                raise SupportError(f"Escolha uma opção válida em «{field.get('label')}».", 400, "invalid_option")
        clean_values[key] = text
    return clean_values


def _source(hit: Dict[str, Any]) -> Dict[str, Any]:
    return dict(hit.get("_source") or {})


# --------------------------------------------------------------- rate limit
_rate_lock = threading.Lock()
_rate_buckets: Dict[str, Deque[float]] = {}


def check_rate(key: str, *, limit: int, window_seconds: int) -> None:
    """Limite simples por chave (IP/visitante). Levanta 429 quando excede."""
    moment = time.monotonic()
    with _rate_lock:
        bucket = _rate_buckets.setdefault(key, deque())
        while bucket and moment - bucket[0] > window_seconds:
            bucket.popleft()
        if len(bucket) >= limit:
            raise SupportError("Demasiados pedidos. Aguarde um momento.", 429, "rate_limited")
        bucket.append(moment)


def reset_rate_limits() -> None:
    with _rate_lock:
        _rate_buckets.clear()


# ------------------------------------------------------------------ visitante
def new_visitor_id() -> str:
    return "v_" + secrets.token_hex(12)


def get_visitor(visitor_id: str) -> Optional[Dict[str, Any]]:
    if not visitor_id:
        return None
    try:
        response = _client().get(index=SUPPORT_VISITORS_INDEX, id=visitor_id)
    except Exception:
        return None
    return _source(response)


def _profile_from_user(user: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    if not user:
        return {}
    subscription = user.get("subscription") or {}
    return {
        "name": _clean(user.get("name"), NAME_MAX_LEN),
        "email": _clean(user.get("email"), EMAIL_MAX_LEN),
        "phone": _clean(user.get("phone"), 40),
        "organization": _clean(user.get("organization"), NAME_MAX_LEN),
        "user_id": str(user.get("id") or ""),
        "role": _clean(user.get("role"), 32),
        "account_status": _clean(user.get("status"), 32),
        "plan": _clean(subscription.get("plan_id"), 64),
        "plan_status": _clean(subscription.get("status"), 32),
        "title": _clean(user.get("title"), NAME_MAX_LEN),
        "locale": _clean(user.get("locale"), 16),
        "timezone": _clean(user.get("timezone"), 64),
        "created_at": user.get("created_at"),
        "last_login_at": user.get("last_login_at"),
    }


def touch_visitor(
    visitor_id: str,
    *,
    profile: Optional[Dict[str, Any]] = None,
    context: Optional[Dict[str, Any]] = None,
    user: Optional[Dict[str, Any]] = None,
    new_session: bool = False,
) -> Dict[str, Any]:
    """Cria/atualiza a ficha do visitante e devolve-a."""
    existing = get_visitor(visitor_id) or {}
    merged_profile = {**(existing.get("profile") or {})}
    if user:
        merged_profile.update(_profile_from_user(user))
    for key, value in (profile or {}).items():
        if value not in (None, ""):
            merged_profile[str(key)] = value if not isinstance(value, str) else _clean(value, 512)
    merged_context = {**(existing.get("context") or {}), **(context or {})}
    page = _clean((context or {}).get("url"), 1024)

    document = {
        **existing,
        "visitor_id": visitor_id,
        "user_id": merged_profile.get("user_id") or existing.get("user_id") or "",
        "name": _clean(merged_profile.get("name"), NAME_MAX_LEN),
        "email": _clean(merged_profile.get("email"), EMAIL_MAX_LEN).lower(),
        "phone": _clean(merged_profile.get("phone"), 40),
        "organization": _clean(merged_profile.get("organization"), NAME_MAX_LEN),
        "profile": merged_profile,
        "context": merged_context,
        "first_page": existing.get("first_page") or page,
        "last_page": page or existing.get("last_page") or "",
        "sessions": int(existing.get("sessions") or 0) + (1 if new_session else 0),
        "created_at": existing.get("created_at") or _iso(),
        "updated_at": _iso(),
        "last_seen_at": _iso(),
    }
    try:
        _client().index(index=SUPPORT_VISITORS_INDEX, id=visitor_id, document=document, refresh=True)
    except Exception as exc:  # noqa: BLE001
        raise SupportError("Não foi possível guardar o visitante.", 503, "storage_error") from exc
    return document


# --------------------------------------------------------------------- sessão
def _session_doc(session_id: str) -> Optional[Dict[str, Any]]:
    try:
        response = _client().get(index=SUPPORT_SESSIONS_INDEX, id=session_id)
    except Exception:
        return None
    return _source(response)


def get_session(session_id: str) -> Optional[Dict[str, Any]]:
    return _session_doc(session_id)


def require_session(session_id: str) -> Dict[str, Any]:
    document = _session_doc(session_id)
    if not document:
        raise SupportError("Conversa não encontrada.", 404, "session_not_found")
    return document


def find_open_session(visitor_id: str) -> Optional[Dict[str, Any]]:
    since = _iso(_now() - timedelta(hours=SESSION_REUSE_HOURS))
    body = {
        "query": {
            "bool": {
                "filter": [
                    {"term": {"visitor_id": visitor_id}},
                    {"range": {"created_at": {"gte": since}}},
                ],
                "must_not": [{"term": {"status": STATUS_CLOSED}}],
            }
        },
        "size": 1,
        "sort": [{"created_at": {"order": "desc"}}],
    }
    try:
        response = _client().search(index=SUPPORT_SESSIONS_INDEX, body=body)
    except Exception:
        return None
    hits = response.get("hits", {}).get("hits", [])
    return _source(hits[0]) if hits else None


def create_session(
    visitor_id: str,
    *,
    profile: Optional[Dict[str, Any]] = None,
    context: Optional[Dict[str, Any]] = None,
    user: Optional[Dict[str, Any]] = None,
    subject: str = "",
) -> Tuple[Dict[str, Any], bool]:
    """Abre (ou retoma) a conversa do visitante. Devolve `(sessão, criada)`."""
    existing = find_open_session(visitor_id)
    visitor = touch_visitor(visitor_id, profile=profile, context=context, user=user, new_session=not existing)
    if existing:
        fields = {}
        if profile or user:
            fields["visitor"] = {**(existing.get("visitor") or {}), **(visitor.get("profile") or {})}
            fields["visitor_name"] = _clean(visitor.get("name"), NAME_MAX_LEN) or existing.get("visitor_name") or "Visitante"
            fields["visitor_email"] = visitor.get("email") or existing.get("visitor_email") or ""
        if context:
            fields["context"] = {**(existing.get("context") or {}), **context}
            fields["pages"] = _merge_pages(existing.get("pages") or [], context)
        if fields:
            existing = _patch_session(existing["session_id"], fields) or existing
        return existing, False

    session_id = "s_" + secrets.token_hex(12)
    visitor_profile = visitor.get("profile") or {}
    document = {
        "session_id": session_id,
        "visitor_id": visitor_id,
        "user_id": visitor_profile.get("user_id") or "",
        "status": STATUS_WAITING,
        "subject": _clean(subject, SUBJECT_MAX_LEN),
        "visitor_name": _clean(visitor.get("name") or visitor_profile.get("name"), NAME_MAX_LEN) or "Visitante",
        "visitor_email": _clean(visitor.get("email") or visitor_profile.get("email"), EMAIL_MAX_LEN).lower(),
        "assigned_operator_id": "",
        "assigned_operator_name": "",
        "tags": [],
        "visitor": visitor_profile,
        "context": context or {},
        "pages": _merge_pages([], context or {}),
        "unread_operator": 0,
        "unread_visitor": 0,
        "message_count": 0,
        "rating": None,
        "rating_comment": "",
        "created_at": _iso(),
        "updated_at": _iso(),
        "last_message_at": None,
        "last_visitor_message_at": None,
        "last_operator_message_at": None,
        "last_seen_at": _iso(),
        "closed_at": None,
    }
    try:
        _client().index(index=SUPPORT_SESSIONS_INDEX, id=session_id, document=document, refresh=True)
    except Exception as exc:  # noqa: BLE001
        raise SupportError("Não foi possível abrir a conversa.", 503, "storage_error") from exc
    log_support_event(
        "session.created",
        session_id=session_id,
        actor_type=AUTHOR_VISITOR,
        actor_id=visitor_id,
        actor_name=document["visitor_name"],
        detail=f"Conversa aberta em {_clean((context or {}).get('url'), 300) or 'página desconhecida'}",
        data={"context": context or {}},
    )
    return document, True


def _merge_pages(pages: List[Dict[str, Any]], context: Dict[str, Any]) -> List[Dict[str, Any]]:
    url = _clean(context.get("url"), 1024)
    if not url:
        return list(pages)
    entry = {
        "url": url,
        "title": _clean(context.get("title"), 200),
        "at": _iso(),
    }
    kept = [page for page in pages if page.get("url") != url]
    return ([entry] + kept)[:50]


def _patch_session(session_id: str, fields: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    document = {**fields, "updated_at": _iso()}
    try:
        _client().update(index=SUPPORT_SESSIONS_INDEX, id=session_id, doc=document, refresh=True)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Apoio: falha ao atualizar a conversa %s: %s", session_id, exc)
        return None
    return _session_doc(session_id)


def update_context(session_id: str, context: Dict[str, Any], profile: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    session = require_session(session_id)
    fields: Dict[str, Any] = {
        "context": {**(session.get("context") or {}), **context},
        "pages": _merge_pages(session.get("pages") or [], context),
        "last_seen_at": _iso(),
    }
    if profile:
        visitor = {**(session.get("visitor") or {})}
        for key, value in profile.items():
            if value not in (None, ""):
                visitor[str(key)] = _clean(value, 512) if isinstance(value, str) else value
        fields["visitor"] = visitor
        if visitor.get("name"):
            fields["visitor_name"] = _clean(visitor.get("name"), NAME_MAX_LEN)
        if visitor.get("email"):
            fields["visitor_email"] = _clean(visitor.get("email"), EMAIL_MAX_LEN).lower()
    updated = _patch_session(session_id, fields) or session
    touch_visitor(
        str(session.get("visitor_id") or ""),
        profile=profile,
        context=context,
    )
    return updated


def touch_session_presence(session_id: str) -> None:
    _patch_session(session_id, {"last_seen_at": _iso()})


def public_session(document: Dict[str, Any], *, online: bool = False) -> Dict[str, Any]:
    assigned_id = document.get("assigned_operator_id") or ""
    return {
        "id": document.get("session_id"),
        "visitor_id": document.get("visitor_id"),
        "user_id": document.get("user_id") or "",
        "status": document.get("status") or STATUS_WAITING,
        "subject": document.get("subject") or "",
        "visitor_name": document.get("visitor_name") or "Visitante",
        "visitor_email": document.get("visitor_email") or "",
        "visitor": document.get("visitor") or {},
        "context": document.get("context") or {},
        "pages": document.get("pages") or [],
        "assigned_operator_id": assigned_id,
        "assigned_operator_name": document.get("assigned_operator_name") or "",
        "assigned_to_me": False,
        "tags": document.get("tags") or [],
        "unread_operator": int(document.get("unread_operator") or 0),
        "unread_visitor": int(document.get("unread_visitor") or 0),
        "message_count": int(document.get("message_count") or 0),
        "rating": document.get("rating"),
        "rating_comment": document.get("rating_comment") or "",
        "online": bool(online),
        "created_at": document.get("created_at"),
        "updated_at": document.get("updated_at"),
        "last_message_at": document.get("last_message_at"),
        "last_visitor_message_at": document.get("last_visitor_message_at"),
        "last_seen_at": document.get("last_seen_at"),
        "closed_at": document.get("closed_at"),
    }


def list_sessions(
    *,
    status: str = "",
    q: str = "",
    assigned: str = "",
    operator_id: str = "",
    unread: bool = False,
    from_: int = 0,
    size: int = 50,
) -> Dict[str, Any]:
    filters: List[Dict[str, Any]] = []
    must: List[Dict[str, Any]] = []
    if status in SESSION_STATUSES:
        filters.append({"term": {"status": status}})
    elif status == "open":
        filters.append({"terms": {"status": [STATUS_WAITING, STATUS_ACTIVE]}})
    if assigned == "me" and operator_id:
        filters.append({"term": {"assigned_operator_id": operator_id}})
    elif assigned == "unassigned":
        filters.append({"bool": {"must_not": [{"exists": {"field": "assigned_operator_id"}}]}})
    if unread:
        filters.append({"range": {"unread_operator": {"gt": 0}}})
    text = _clean(q, 200)
    if text:
        must.append(
            {
                "multi_match": {
                    "query": text,
                    "fields": [
                        "visitor_name^3",
                        "visitor_email^3",
                        "subject^2",
                        "context.url",
                        "visitor.organization",
                    ],
                    "type": "best_fields",
                }
            }
        )
    body = {
        "query": {"bool": {"filter": filters, "must": must}},
        "from": max(0, from_),
        "size": max(1, min(size, 100)),
        "sort": [
            {"last_message_at": {"order": "desc", "missing": "_last"}},
            {"created_at": {"order": "desc"}},
        ],
        "track_total_hits": True,
    }
    try:
        response = _client().search(index=SUPPORT_SESSIONS_INDEX, body=body)
    except Exception as exc:  # noqa: BLE001
        raise SupportError("Não foi possível listar as conversas.", 503, "storage_error") from exc
    hits = response.get("hits", {})
    total = hits.get("total", {})
    return {
        "items": [_source(hit) for hit in hits.get("hits", [])],
        "total": int(total.get("value", 0) if isinstance(total, dict) else total or 0),
        "from": from_,
        "size": size,
    }


def claim_session(session_id: str, operator_id: str, operator_name: str) -> Dict[str, Any]:
    session = require_session(session_id)
    if session.get("status") == STATUS_CLOSED:
        raise SupportError("A conversa já está fechada.", 409, "session_closed")
    fields = {
        "assigned_operator_id": operator_id,
        "assigned_operator_name": operator_name,
        "status": STATUS_ACTIVE,
    }
    updated = _patch_session(session_id, fields) or {**session, **fields}
    if session.get("assigned_operator_id") != operator_id:
        log_support_event(
            "session.claimed",
            session_id=session_id,
            actor_type=AUTHOR_OPERATOR,
            actor_id=operator_id,
            actor_name=operator_name,
            detail=f"{operator_name} assumiu a conversa",
        )
    return updated


def release_session(session_id: str, operator_id: str, operator_name: str) -> Dict[str, Any]:
    session = require_session(session_id)
    if (session.get("assigned_operator_id") or "") != operator_id:
        raise SupportError("Só o operador atribuído pode libertar a conversa.", 403, "not_assigned")
    fields = {
        "assigned_operator_id": "",
        "assigned_operator_name": "",
        "status": STATUS_WAITING if session.get("status") != STATUS_CLOSED else STATUS_CLOSED,
    }
    updated = _patch_session(session_id, fields) or {**session, **fields}
    log_support_event(
        "session.released",
        session_id=session_id,
        actor_type=AUTHOR_OPERATOR,
        actor_id=operator_id,
        actor_name=operator_name,
        detail=f"{operator_name} devolveu a conversa à fila",
    )
    return updated


def close_session(session_id: str, *, actor_type: str, actor_id: str, actor_name: str, reason: str = "") -> Dict[str, Any]:
    session = require_session(session_id)
    if session.get("status") == STATUS_CLOSED:
        return session
    fields = {"status": STATUS_CLOSED, "closed_at": _iso(), "unread_operator": 0}
    updated = _patch_session(session_id, fields) or {**session, **fields}
    log_support_event(
        "session.closed",
        session_id=session_id,
        actor_type=actor_type,
        actor_id=actor_id,
        actor_name=actor_name,
        detail=reason or f"Conversa fechada por {actor_name}",
    )
    return updated


def mark_read(session_id: str, side: str) -> Dict[str, Any]:
    session = require_session(session_id)
    field = "unread_visitor" if side == "visitor" else "unread_operator"
    if not int(session.get(field) or 0):
        return session
    return _patch_session(session_id, {field: 0}) or session


def rate_session(session_id: str, rating: int, comment: str = "") -> Dict[str, Any]:
    if rating not in (1, 2, 3, 4, 5):
        raise SupportError("A avaliação tem de ser entre 1 e 5.", 400, "invalid_rating")
    session = require_session(session_id)
    fields = {"rating": rating, "rating_comment": _clean(comment, 1000)}
    updated = _patch_session(session_id, fields) or {**session, **fields}
    log_support_event(
        "session.rated",
        session_id=session_id,
        actor_type=AUTHOR_VISITOR,
        actor_id=str(session.get("visitor_id") or ""),
        actor_name=str(session.get("visitor_name") or "Visitante"),
        detail=f"Avaliação: {rating}/5",
        data={"rating": rating, "comment": comment},
    )
    return updated


# ------------------------------------------------------------------- mensagens
def public_message(document: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "id": document.get("message_id"),
        "session_id": document.get("session_id"),
        "author_type": document.get("author_type") or AUTHOR_SYSTEM,
        "author_id": document.get("author_id") or "",
        "author_name": document.get("author_name") or "",
        "body": document.get("body") or "",
        "kind": document.get("kind") or MESSAGE_TEXT,
        "payload": document.get("payload") or {},
        "form_response": document.get("form_response") or None,
        "client_id": document.get("client_id") or "",
        "internal": bool(document.get("internal")),
        "created_at": document.get("created_at"),
    }


def add_message(
    session_id: str,
    *,
    author_type: str,
    author_id: str = "",
    author_name: str = "",
    body: str,
    client_id: str = "",
    internal: bool = False,
    kind: str = MESSAGE_TEXT,
    payload: Optional[Dict[str, Any]] = None,
    form_response: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    if kind not in MESSAGE_KINDS and kind != MESSAGE_FORM_RESPONSE:
        raise SupportError("Tipo de mensagem inválido.", 400, "invalid_kind")
    text = _clean(body, BODY_MAX_LEN)
    data = payload or {}
    if kind == MESSAGE_TEXT and not text:
        raise SupportError("A mensagem está vazia.", 400, "empty_message")
    if kind != MESSAGE_TEXT and not data:
        raise SupportError("Conteúdo da mensagem em falta.", 400, "empty_payload")
    if not text:
        # Texto de pesquisa/notificação para mensagens ricas (o widget desenha o cartão).
        text = _clean(data.get("title") if isinstance(data, dict) else "", BODY_MAX_LEN)
    session = require_session(session_id)
    if session.get("status") == STATUS_CLOSED:
        raise SupportError("A conversa já está fechada.", 409, "session_closed")

    message_id = "m_" + secrets.token_hex(12)
    document = {
        "message_id": message_id,
        "session_id": session_id,
        "visitor_id": session.get("visitor_id") or "",
        "author_type": author_type,
        "author_id": author_id,
        "author_name": _clean(author_name, NAME_MAX_LEN),
        "body": text,
        "kind": kind,
        "payload": data,
        "form_response": form_response or {},
        "client_id": _clean(client_id, 80),
        "internal": bool(internal),
        "created_at": _iso(),
    }
    try:
        _client().index(
            index=SUPPORT_MESSAGES_INDEX,
            id=message_id,
            document=document,
            refresh="wait_for",
        )
    except Exception as exc:  # noqa: BLE001
        raise SupportError("Não foi possível enviar a mensagem.", 503, "storage_error") from exc

    moment = document["created_at"]
    fields: Dict[str, Any] = {
        "last_message_at": moment,
        "last_seen_at": moment,
    }
    if author_type == AUTHOR_VISITOR:
        fields["unread_operator"] = int(session.get("unread_operator") or 0) + 1
        fields["last_visitor_message_at"] = moment
        fields["message_count"] = int(session.get("message_count") or 0) + 1
        if not session.get("visitor_name") and document["author_name"]:
            fields["visitor_name"] = document["author_name"]
    elif author_type == AUTHOR_OPERATOR:
        if internal:
            fields["last_message_at"] = session.get("last_message_at")
        else:
            fields["unread_visitor"] = int(session.get("unread_visitor") or 0) + 1
            fields["last_operator_message_at"] = moment
            fields["message_count"] = int(session.get("message_count") or 0) + 1
    elif author_type == AUTHOR_SYSTEM:
        fields["message_count"] = int(session.get("message_count") or 0) + 1
    _patch_session(session_id, fields)

    log_support_event(
        f"message.{author_type}",
        session_id=session_id,
        actor_type=author_type,
        actor_id=author_id,
        actor_name=document["author_name"],
        detail=f"{author_type}: {text[:160]}",
    )
    return public_message(document)


def list_messages(session_id: str, *, include_internal: bool = True, size: int = MESSAGE_PAGE_SIZE) -> List[Dict[str, Any]]:
    filters: List[Dict[str, Any]] = [{"term": {"session_id": session_id}}]
    if not include_internal:
        filters.append({"term": {"internal": False}})
    body = {
        "query": {"bool": {"filter": filters}},
        "size": max(1, min(size, 1000)),
        "sort": [{"created_at": {"order": "asc"}}],
    }
    try:
        response = _client().search(index=SUPPORT_MESSAGES_INDEX, body=body)
    except Exception as exc:  # noqa: BLE001
        raise SupportError("Não foi possível carregar as mensagens.", 503, "storage_error") from exc
    return [public_message(_source(hit)) for hit in response.get("hits", {}).get("hits", [])]


def get_message(message_id: str) -> Optional[Dict[str, Any]]:
    try:
        response = _client().get(index=SUPPORT_MESSAGES_INDEX, id=message_id)
    except Exception:
        return None
    return _source(response)


def send_rich_message(
    session_id: str,
    *,
    kind: str,
    payload: Optional[Dict[str, Any]],
    author_id: str,
    author_name: str,
    client_id: str = "",
    internal: bool = False,
) -> Dict[str, Any]:
    """Envia um link, relatório ou formulário para o visitante."""
    if kind not in (MESSAGE_LINK, MESSAGE_REPORT, MESSAGE_FORM):
        raise SupportError("Tipo de mensagem inválido.", 400, "invalid_kind")
    if internal:
        raise SupportError("Uma nota interna não pode ser um cartão.", 400, "invalid_internal")
    data = normalise_rich_payload(kind, payload)
    return add_message(
        session_id,
        author_type=AUTHOR_OPERATOR,
        author_id=author_id,
        author_name=author_name,
        body=str(data.get("title") or ""),
        client_id=client_id,
        internal=False,
        kind=kind,
        payload=data,
    )


def public_form_response(document: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "id": document.get("response_id"),
        "form_id": document.get("form_id") or "",
        "message_id": document.get("message_id") or "",
        "session_id": document.get("session_id") or "",
        "visitor_id": document.get("visitor_id") or "",
        "visitor_name": document.get("visitor_name") or "",
        "visitor_email": document.get("visitor_email") or "",
        "title": document.get("title") or "",
        "values": document.get("values") or {},
        "submitted_at": document.get("submitted_at"),
    }


def submit_form_response(
    session_id: str,
    message_id: str,
    values: Dict[str, Any],
    *,
    visitor_id: str,
    visitor_name: str = "",
    visitor_email: str = "",
) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """Guarda a resposta do visitante a um formulário e marca a mensagem como respondida."""
    message = get_message(message_id)
    if not message or str(message.get("session_id") or "") != session_id:
        raise SupportError("Formulário não encontrado.", 404, "form_not_found")
    if (message.get("kind") or MESSAGE_TEXT) != MESSAGE_FORM:
        raise SupportError("Esta mensagem não é um formulário.", 400, "not_a_form")
    if message.get("form_response"):
        raise SupportError("Este formulário já foi respondido.", 409, "form_already_answered")
    payload = message.get("payload") if isinstance(message.get("payload"), dict) else {}
    clean_values = validate_form_values(payload, values)
    now = _iso()
    response_id = "fr_" + secrets.token_hex(10)
    document = {
        "response_id": response_id,
        "form_id": payload.get("form_id") or "",
        "message_id": message_id,
        "session_id": session_id,
        "visitor_id": visitor_id,
        "visitor_name": _clean(visitor_name, NAME_MAX_LEN),
        "visitor_email": _clean(visitor_email, EMAIL_MAX_LEN).lower(),
        "title": payload.get("title") or "",
        "values": clean_values,
        "submitted_at": now,
        "created_at": now,
    }
    try:
        _client().index(
            index=SUPPORT_FORM_RESPONSES_INDEX,
            id=response_id,
            document=document,
            refresh="wait_for",
        )
    except Exception as exc:  # noqa: BLE001
        raise SupportError("Não foi possível guardar a resposta.", 503, "storage_error") from exc

    form_response = {
        "response_id": response_id,
        "submitted_at": now,
        "values": clean_values,
        "by": _clean(visitor_name, NAME_MAX_LEN),
    }
    try:
        _client().update(
            index=SUPPORT_MESSAGES_INDEX,
            id=message_id,
            doc={"form_response": form_response},
            refresh="wait_for",
        )
    except Exception as exc:  # noqa: BLE001
        raise SupportError("Não foi possível marcar o formulário como respondido.", 503, "storage_error") from exc

    session = require_session(session_id)
    _patch_session(
        session_id,
        {
            "unread_operator": int(session.get("unread_operator") or 0) + 1,
            "last_message_at": now,
            "last_visitor_message_at": now,
            "last_seen_at": now,
        },
    )
    log_support_event(
        "form.submitted",
        session_id=session_id,
        actor_type=AUTHOR_VISITOR,
        actor_id=visitor_id,
        actor_name=visitor_name,
        detail=f"Formulário «{payload.get('title') or ''}» respondido",
        data={"response_id": response_id, "message_id": message_id, "fields": list(clean_values)},
    )
    updated = get_message(message_id)
    return public_message(updated or {**message, "form_response": form_response}), public_form_response(document)


def list_form_responses(session_id: str) -> List[Dict[str, Any]]:
    body = {
        "query": {"term": {"session_id": session_id}},
        "size": 200,
        "sort": [{"submitted_at": {"order": "asc"}}],
    }
    try:
        response = _client().search(index=SUPPORT_FORM_RESPONSES_INDEX, body=body)
    except Exception:
        return []
    return [public_form_response(_source(hit)) for hit in response.get("hits", {}).get("hits", [])]


# -------------------------------------------------------------------- tickets
def public_ticket(document: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "id": document.get("ticket_id"),
        "session_id": document.get("session_id") or "",
        "visitor_id": document.get("visitor_id") or "",
        "subject": document.get("subject") or "",
        "description": document.get("description") or "",
        "status": document.get("status") or TICKET_OPEN,
        "priority": document.get("priority") or "normal",
        "category": document.get("category") or "",
        "requester": document.get("requester") or {},
        "assigned_operator_id": document.get("assigned_operator_id") or "",
        "assigned_operator_name": document.get("assigned_operator_name") or "",
        "notes": document.get("notes") or [],
        "created_at": document.get("created_at"),
        "updated_at": document.get("updated_at"),
        "closed_at": document.get("closed_at"),
    }


def create_ticket(
    session_id: str,
    *,
    subject: str,
    description: str = "",
    category: str = "",
    priority: str = "normal",
    requester: Optional[Dict[str, Any]] = None,
    operator_id: str = "",
    operator_name: str = "",
) -> Dict[str, Any]:
    session = require_session(session_id)
    clean_subject = _clean(subject, SUBJECT_MAX_LEN)
    if len(clean_subject) < 3:
        raise SupportError("Indique um assunto com pelo menos 3 caracteres.", 400, "invalid_subject")
    ticket_id = "t_" + secrets.token_hex(10)
    now = _iso()
    document = {
        "ticket_id": ticket_id,
        "session_id": session_id,
        "visitor_id": session.get("visitor_id") or "",
        "subject": clean_subject,
        "description": _clean(description, DESCRIPTION_MAX_LEN),
        "status": TICKET_OPEN,
        "priority": priority if priority in TICKET_PRIORITIES else "normal",
        "category": _clean(category, 80),
        "requester": requester
        or {
            "name": session.get("visitor_name") or "Visitante",
            "email": session.get("visitor_email") or "",
            "user_id": session.get("user_id") or "",
        },
        "assigned_operator_id": operator_id,
        "assigned_operator_name": operator_name,
        "notes": [],
        "created_at": now,
        "updated_at": now,
        "closed_at": None,
    }
    try:
        _client().index(index=SUPPORT_TICKETS_INDEX, id=ticket_id, document=document, refresh=True)
    except Exception as exc:  # noqa: BLE001
        raise SupportError("Não foi possível abrir o ticket.", 503, "storage_error") from exc

    log_support_event(
        "ticket.created",
        session_id=session_id,
        ticket_id=ticket_id,
        actor_type=AUTHOR_OPERATOR if operator_id else AUTHOR_VISITOR,
        actor_id=operator_id or str(session.get("visitor_id") or ""),
        actor_name=operator_name or str(session.get("visitor_name") or "Visitante"),
        detail=f"Ticket aberto: {clean_subject}",
        data={"category": category, "priority": document["priority"]},
    )
    try:
        add_message(
            session_id,
            author_type=AUTHOR_SYSTEM,
            author_name="Sistema",
            body=f"Ticket #{ticket_id[-6:]} aberto: {clean_subject}",
            internal=False,
        )
    except SupportError:
        pass
    return public_ticket(document)


def get_ticket(ticket_id: str) -> Optional[Dict[str, Any]]:
    try:
        response = _client().get(index=SUPPORT_TICKETS_INDEX, id=ticket_id)
    except Exception:
        return None
    return _source(response)


def list_tickets(
    *,
    status: str = "",
    q: str = "",
    session_id: str = "",
    from_: int = 0,
    size: int = 50,
) -> Dict[str, Any]:
    filters: List[Dict[str, Any]] = []
    must: List[Dict[str, Any]] = []
    if status in TICKET_STATUSES:
        filters.append({"term": {"status": status}})
    elif status == "open":
        filters.append({"terms": {"status": [TICKET_OPEN, TICKET_PENDING]}})
    if session_id:
        filters.append({"term": {"session_id": session_id}})
    text = _clean(q, 200)
    if text:
        must.append(
            {
                "multi_match": {
                    "query": text,
                    "fields": ["subject^3", "description", "requester.name", "requester.email"],
                }
            }
        )
    body = {
        "query": {"bool": {"filter": filters, "must": must}},
        "from": max(0, from_),
        "size": max(1, min(size, 100)),
        "sort": [{"created_at": {"order": "desc"}}],
        "track_total_hits": True,
    }
    try:
        response = _client().search(index=SUPPORT_TICKETS_INDEX, body=body)
    except Exception as exc:  # noqa: BLE001
        raise SupportError("Não foi possível listar os tickets.", 503, "storage_error") from exc
    hits = response.get("hits", {})
    total = hits.get("total", {})
    return {
        "items": [public_ticket(_source(hit)) for hit in hits.get("hits", [])],
        "total": int(total.get("value", 0) if isinstance(total, dict) else total or 0),
        "from": from_,
        "size": size,
    }


def list_session_tickets(session_id: str) -> List[Dict[str, Any]]:
    return list_tickets(session_id=session_id, size=100)["items"]


def update_ticket(
    ticket_id: str,
    *,
    status: Optional[str] = None,
    priority: Optional[str] = None,
    category: Optional[str] = None,
    assigned_operator_id: Optional[str] = None,
    assigned_operator_name: Optional[str] = None,
    note: str = "",
    actor_id: str = "",
    actor_name: str = "",
) -> Dict[str, Any]:
    ticket = get_ticket(ticket_id)
    if not ticket:
        raise SupportError("Ticket não encontrado.", 404, "ticket_not_found")
    fields: Dict[str, Any] = {"updated_at": _iso()}
    if status is not None:
        if status not in TICKET_STATUSES:
            raise SupportError("Estado de ticket inválido.", 400, "invalid_status")
        fields["status"] = status
        fields["closed_at"] = _iso() if status in (TICKET_RESOLVED, TICKET_CLOSED) else None
    if priority is not None:
        if priority not in TICKET_PRIORITIES:
            raise SupportError("Prioridade inválida.", 400, "invalid_priority")
        fields["priority"] = priority
    if category is not None:
        fields["category"] = _clean(category, 80)
    if assigned_operator_id is not None:
        fields["assigned_operator_id"] = assigned_operator_id
        fields["assigned_operator_name"] = _clean(assigned_operator_name, NAME_MAX_LEN)
    if note:
        notes = list(ticket.get("notes") or [])
        notes.append({"at": _iso(), "by_id": actor_id, "by": actor_name, "text": _clean(note, 2000)})
        fields["notes"] = notes[-100:]
    try:
        _client().update(index=SUPPORT_TICKETS_INDEX, id=ticket_id, doc=fields, refresh=True)
    except Exception as exc:  # noqa: BLE001
        raise SupportError("Não foi possível atualizar o ticket.", 503, "storage_error") from exc
    updated = get_ticket(ticket_id) or {**ticket, **fields}
    log_support_event(
        "ticket.updated",
        session_id=str(ticket.get("session_id") or ""),
        ticket_id=ticket_id,
        actor_type=AUTHOR_OPERATOR,
        actor_id=actor_id,
        actor_name=actor_name,
        detail=f"Ticket atualizado ({fields.get('status', ticket.get('status'))})",
        data={key: value for key, value in fields.items() if key != "notes"},
    )
    return public_ticket(updated)


# --------------------------------------------------------------------- eventos
def log_support_event(
    kind: str,
    *,
    session_id: str = "",
    ticket_id: str = "",
    actor_type: str = "",
    actor_id: str = "",
    actor_name: str = "",
    detail: str = "",
    data: Optional[Dict[str, Any]] = None,
) -> None:
    document = {
        "kind": _clean(kind, 64),
        "session_id": session_id,
        "ticket_id": ticket_id,
        "actor_type": actor_type,
        "actor_id": actor_id,
        "actor_name": _clean(actor_name, NAME_MAX_LEN),
        "detail": _clean(detail, 2000),
        "data": data or {},
        "created_at": _iso(),
    }
    try:
        # `refresh` imediato: os registos aparecem logo na consola do operador.
        _client().index(index=SUPPORT_EVENTS_INDEX, document=document, refresh=True)
    except Exception as exc:  # noqa: BLE001 - o registo nunca deve derrubar a conversa
        logger.debug("Apoio: evento não registado (%s): %s", kind, exc)
    if kind in {"session.created", "session.claimed", "session.closed", "ticket.created"}:
        system_events.log_event(
            "info",
            "support",
            f"Apoio: {kind}" + (f" · {detail}" if detail else ""),
            data={"session_id": session_id, "ticket_id": ticket_id, "actor": actor_name},
        )


def public_event(document: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "id": document.get("event_id") or "",
        "kind": document.get("kind") or "",
        "session_id": document.get("session_id") or "",
        "ticket_id": document.get("ticket_id") or "",
        "actor_type": document.get("actor_type") or "",
        "actor_id": document.get("actor_id") or "",
        "actor_name": document.get("actor_name") or "",
        "detail": document.get("detail") or "",
        "data": document.get("data") or {},
        "created_at": document.get("created_at"),
    }


def list_events(
    *,
    session_id: str = "",
    from_: int = 0,
    size: int = 50,
) -> Dict[str, Any]:
    filters: List[Dict[str, Any]] = []
    if session_id:
        filters.append({"term": {"session_id": session_id}})
    body = {
        "query": {"bool": {"filter": filters}},
        "from": max(0, from_),
        "size": max(1, min(size, 200)),
        "sort": [{"created_at": {"order": "desc"}}],
        "track_total_hits": True,
    }
    try:
        response = _client().search(index=SUPPORT_EVENTS_INDEX, body=body)
    except Exception as exc:  # noqa: BLE001
        raise SupportError("Não foi possível carregar os registos.", 503, "storage_error") from exc
    hits = response.get("hits", {})
    total = hits.get("total", {})
    return {
        "items": [public_event({**_source(hit), "event_id": hit.get("_id")}) for hit in hits.get("hits", [])],
        "total": int(total.get("value", 0) if isinstance(total, dict) else total or 0),
        "from": from_,
        "size": size,
    }


# ------------------------------------------------------------------ operadores
def upsert_operator(
    operator: Dict[str, Any],
    *,
    status: str = OPERATOR_ONLINE,
) -> Dict[str, Any]:
    operator_id = str(operator.get("id") or operator.get("email") or "")
    if not operator_id:
        raise SupportError("Operador inválido.", 400, "invalid_operator")
    document = {
        "operator_id": operator_id,
        "name": _clean(operator.get("name"), NAME_MAX_LEN),
        "email": _clean(operator.get("email"), EMAIL_MAX_LEN).lower(),
        "status": status,
        "last_seen_at": _iso(),
        "updated_at": _iso(),
    }
    try:
        _client().index(index=SUPPORT_OPERATORS_INDEX, id=operator_id, document=document, refresh=True)
    except Exception as exc:  # noqa: BLE001
        logger.debug("Apoio: operador não guardado (%s): %s", operator_id, exc)
    return document


def set_operator_status(operator: Dict[str, Any], status: str) -> Dict[str, Any]:
    if status not in (OPERATOR_ONLINE, OPERATOR_AWAY, OPERATOR_OFFLINE):
        raise SupportError("Estado de operador inválido.", 400, "invalid_status")
    return upsert_operator(operator, status=status)


def list_operators() -> List[Dict[str, Any]]:
    body = {
        "query": {"match_all": {}},
        "size": 100,
        "sort": [{"last_seen_at": {"order": "desc"}}],
    }
    try:
        response = _client().search(index=SUPPORT_OPERATORS_INDEX, body=body)
    except Exception:
        return []
    return [
        {
            "id": _source(hit).get("operator_id"),
            "name": _source(hit).get("name"),
            "email": _source(hit).get("email"),
            "status": _source(hit).get("status"),
            "last_seen_at": _source(hit).get("last_seen_at"),
        }
        for hit in response.get("hits", {}).get("hits", [])
    ]


# --------------------------------------------------------------------- resumo
def _count(index: str, query: Optional[Dict[str, Any]] = None) -> int:
    try:
        response = _client().count(index=index, query=query or {"match_all": {}})
    except Exception:
        return 0
    return int(response.get("count") or 0)


def overview() -> Dict[str, Any]:
    now = _now()
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    waiting = _count(SUPPORT_SESSIONS_INDEX, {"term": {"status": STATUS_WAITING}})
    active = _count(SUPPORT_SESSIONS_INDEX, {"term": {"status": STATUS_ACTIVE}})
    closed = _count(SUPPORT_SESSIONS_INDEX, {"term": {"status": STATUS_CLOSED}})
    tickets_open = _count(SUPPORT_TICKETS_INDEX, {"terms": {"status": [TICKET_OPEN, TICKET_PENDING]}})
    today = _count(SUPPORT_SESSIONS_INDEX, {"range": {"created_at": {"gte": _iso(today_start)}}})
    unread = _count(SUPPORT_SESSIONS_INDEX, {"range": {"unread_operator": {"gt": 0}}})
    oldest_waiting = None
    try:
        response = _client().search(
            index=SUPPORT_SESSIONS_INDEX,
            body={
                "query": {"term": {"status": STATUS_WAITING}},
                "size": 1,
                "sort": [{"created_at": {"order": "asc"}}],
                "_source": ["session_id", "created_at", "visitor_name"],
            },
        )
        hits = response.get("hits", {}).get("hits", [])
        if hits:
            source = _source(hits[0])
            oldest_waiting = {
                "id": source.get("session_id"),
                "visitor_name": source.get("visitor_name"),
                "created_at": source.get("created_at"),
            }
    except Exception:
        oldest_waiting = None
    return {
        "waiting": waiting,
        "active": active,
        "closed": closed,
        "open": waiting + active,
        "unread": unread,
        "tickets_open": tickets_open,
        "today": today,
        "oldest_waiting": oldest_waiting,
        "operators": list_operators(),
        "events": list_events(size=8)["items"],
    }


def is_business_hours(moment: Optional[datetime] = None) -> bool:
    local = (moment or _now()).astimezone()
    return local.weekday() < 5 and BUSINESS_START_HOUR <= local.hour < BUSINESS_END_HOUR


def widget_config(operators_online: int) -> Dict[str, Any]:
    available = operators_online > 0 or is_business_hours()
    return {
        **SUPPORT_CONFIG,
        "available": available,
        "operators_online": operators_online,
        "outside_hours": not available,
        "session_reuse_hours": SESSION_REUSE_HOURS,
        "limits": {"message": BODY_MAX_LEN, "subject": SUBJECT_MAX_LEN, "description": DESCRIPTION_MAX_LEN},
    }


def clean_client_id(value: Any) -> str:
    return _clean(value, 80)


def iter_statuses() -> Iterable[str]:
    return SESSION_STATUSES
