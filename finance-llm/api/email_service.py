"""Email IQ OS — caixa de correio ligada ao Gmail, Outlook e a qualquer IMAP/SMTP.

A aplicação Email traz o correio do utilizador para dentro da plataforma: contas
com **presets** para os fornecedores mais comuns (Gmail, Outlook/Microsoft 365,
iCloud, Yahoo, Zoho, SAPO) e a possibilidade de configurar **qualquer servidor**
IMAP/SMTP. Sobre essa ligação a app lê pastas, lista mensagens, abre o corpo de
cada mensagem, marca como lida, destaca, apaga e **envia** correio novo ou uma
resposta.

Camadas:

- **Catálogo de fornecedores** (`PROVIDERS`) — servidores, portas e segurança já
  preenchidos, com a ajuda certa (nas contas Gmail/Microsoft com verificação em
  dois passos é preciso uma *palavra-passe de aplicação*, não a palavra-passe da
  conta).
- **Contas** (`data/email/email.json`) — cada conta pertence a um utilizador da
  plataforma (`owner`); a palavra-passe fica guardada no ficheiro e **nunca** é
  devolvida pela API (as respostas trazem apenas `has_password`).
- **IMAP** (`imaplib`) — pastas, cabeçalhos, corpo, sinalizadores.
- **SMTP** (`smtplib`) — envio com SSL direto ou STARTTLS, anexos e cabeçalhos de
  resposta (`In-Reply-To`/`References`) para as conversas ficarem encadeadas.

Sem dependências novas: tudo assenta na biblioteca padrão do Python.
"""
from __future__ import annotations

import base64
import imaplib
import json
import logging
import mimetypes
import re
import smtplib
import ssl
import threading
import uuid
from datetime import datetime, timezone
from email import message_from_bytes
from email.header import decode_header, make_header
from email.message import EmailMessage
from email.utils import formataddr, formatdate, make_msgid, parsedate_to_datetime
from html import unescape as _unescape_html
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parents[1]
EMAIL_DIR = ROOT / "data" / "email"
EMAIL_PATH = EMAIL_DIR / "email.json"
EMAIL_VERSION = 1

IMAP_TIMEOUT = 25
SMTP_TIMEOUT = 30
MAX_LIMIT = 200
BODY_LIMIT = 400_000
SNIPPET_LIMIT = 240

_lock = threading.Lock()
_cache: Optional[Dict[str, Any]] = None


class EmailError(Exception):
    """Erro do domínio do correio, traduzível para uma resposta HTTP."""

    def __init__(self, message: str, *, status: int = 400) -> None:
        super().__init__(message)
        self.message = message
        self.status = status


# ---------------------------------------------------------------------------
# Catálogo de fornecedores
# ---------------------------------------------------------------------------
PROVIDERS: List[Dict[str, Any]] = [
    {
        "id": "gmail",
        "label": "Gmail / Google Workspace",
        "family": "Google",
        "imap_host": "imap.gmail.com",
        "imap_port": 993,
        "imap_security": "ssl",
        "smtp_host": "smtp.gmail.com",
        "smtp_port": 465,
        "smtp_security": "ssl",
        "help": "Ative a verificação em dois passos e crie uma *palavra-passe de aplicação*; a palavra-passe normal é recusada.",
        "docs_url": "https://support.google.com/accounts/answer/185833",
    },
    {
        "id": "outlook",
        "label": "Outlook / Microsoft 365",
        "family": "Microsoft",
        "imap_host": "outlook.office365.com",
        "imap_port": 993,
        "imap_security": "ssl",
        "smtp_host": "smtp.office365.com",
        "smtp_port": 587,
        "smtp_security": "starttls",
        "help": "Contas com MFA precisam de uma *palavra-passe de aplicação*; o IMAP tem de estar ativo na conta.",
        "docs_url": "https://support.microsoft.com/office/pop-imap-and-smtp-settings-8361e398-8af4-4e97-b147-6c7498c0f3c8",
    },
    {
        "id": "hotmail",
        "label": "Hotmail / Live.com",
        "family": "Microsoft",
        "imap_host": "outlook.office365.com",
        "imap_port": 993,
        "imap_security": "ssl",
        "smtp_host": "smtp.office365.com",
        "smtp_port": 587,
        "smtp_security": "starttls",
        "help": "Mesmas definições do Outlook.com; use uma palavra-passe de aplicação.",
        "docs_url": "https://support.microsoft.com/office/pop-imap-and-smtp-settings-8361e398-8af4-4e97-b147-6c7498c0f3c8",
    },
    {
        "id": "icloud",
        "label": "iCloud Mail",
        "family": "Apple",
        "imap_host": "imap.mail.me.com",
        "imap_port": 993,
        "imap_security": "ssl",
        "smtp_host": "smtp.mail.me.com",
        "smtp_port": 587,
        "smtp_security": "starttls",
        "help": "Crie uma *palavra-passe de app* em appleid.apple.com (Segurança).",
        "docs_url": "https://support.apple.com/pt-pt/HT202304",
    },
    {
        "id": "yahoo",
        "label": "Yahoo Mail",
        "family": "Yahoo",
        "imap_host": "imap.mail.yahoo.com",
        "imap_port": 993,
        "imap_security": "ssl",
        "smtp_host": "smtp.mail.yahoo.com",
        "smtp_port": 465,
        "smtp_security": "ssl",
        "help": "Gere uma *palavra-passe de aplicação* nas definições de segurança da conta.",
        "docs_url": "https://help.yahoo.com/kb/generate-third-party-passwords-sln15241.html",
    },
    {
        "id": "zoho",
        "label": "Zoho Mail",
        "family": "Zoho",
        "imap_host": "imap.zoho.com",
        "imap_port": 993,
        "imap_security": "ssl",
        "smtp_host": "smtp.zoho.com",
        "smtp_port": 465,
        "smtp_security": "ssl",
        "help": "Ative o IMAP na conta e use uma palavra-passe de aplicação se tiver MFA.",
        "docs_url": "https://www.zoho.com/mail/help/imap-access.html",
    },
    {
        "id": "sapo",
        "label": "SAPO Mail",
        "family": "SAPO",
        "imap_host": "imap.sapo.pt",
        "imap_port": 993,
        "imap_security": "ssl",
        "smtp_host": "smtp.sapo.pt",
        "smtp_port": 465,
        "smtp_security": "ssl",
        "help": "Ative o acesso IMAP/SMTP nas definições da caixa de correio.",
        "docs_url": "https://ajuda.sapo.pt/",
    },
    {
        "id": "custom",
        "label": "Outro servidor (IMAP/SMTP)",
        "family": "Genérico",
        "imap_host": "",
        "imap_port": 993,
        "imap_security": "ssl",
        "smtp_host": "",
        "smtp_port": 587,
        "smtp_security": "starttls",
        "help": "Indique os servidores da sua caixa de correio (o servidor de email ou o IT da organização tem estes dados).",
        "docs_url": "",
    },
]

PROVIDERS_BY_ID: Dict[str, Dict[str, Any]] = {entry["id"]: entry for entry in PROVIDERS}

SECURITY_MODES = ("ssl", "starttls", "plain")


def provider_catalog() -> Dict[str, Any]:
    """Catálogo de fornecedores suportados (para o formulário de nova conta)."""
    return {"total": len(PROVIDERS), "items": PROVIDERS}


# ---------------------------------------------------------------------------
# Armazenamento das contas
# ---------------------------------------------------------------------------
def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _empty_store() -> Dict[str, Any]:
    return {"version": EMAIL_VERSION, "accounts": [], "updated_at": _now()}


def _read_store() -> Dict[str, Any]:
    if not EMAIL_PATH.exists():
        return _empty_store()
    try:
        raw = json.loads(EMAIL_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        logger.warning("Ficheiro de email ilegível (%s); a recomeçar.", exc)
        return _empty_store()
    if not isinstance(raw, dict):
        return _empty_store()
    store = _empty_store()
    accounts = raw.get("accounts")
    if isinstance(accounts, list):
        store["accounts"] = [item for item in accounts if isinstance(item, dict)]
    return store


def _write_store(store: Dict[str, Any]) -> None:
    global _cache
    store["version"] = EMAIL_VERSION
    store["updated_at"] = _now()
    EMAIL_DIR.mkdir(parents=True, exist_ok=True)
    tmp = EMAIL_PATH.with_suffix(".json.tmp")
    payload = json.dumps(store, ensure_ascii=False, indent=2, default=str)
    tmp.write_text(payload, encoding="utf-8")
    tmp.replace(EMAIL_PATH)
    _cache = store


def _store() -> Dict[str, Any]:
    global _cache
    if _cache is None:
        _cache = _read_store()
    return _cache


def _normalize_key(value: Optional[str]) -> str:
    return (value or "").strip().lower()


def _public_account(account: Dict[str, Any]) -> Dict[str, Any]:
    """Versão segura de uma conta: sem a palavra-passe, mas com `has_password`."""
    public = {key: value for key, value in account.items() if key != "password"}
    public["has_password"] = bool(account.get("password"))
    public["provider_label"] = (PROVIDERS_BY_ID.get(account.get("provider") or "custom") or {}).get("label")
    return public


def _find(account_id: str, owner: str) -> Dict[str, Any]:
    for account in _store()["accounts"]:
        if account.get("id") == account_id and _normalize_key(account.get("owner")) == _normalize_key(owner):
            return account
    raise EmailError("Conta de email não encontrada.", status=404)


def get_account(owner: str, account_id: str) -> Dict[str, Any]:
    """Conta completa (com o segredo) de um utilizador; `EmailError(404)` se não existir."""
    return _find(account_id, owner)


def list_accounts(owner: str) -> Dict[str, Any]:
    """Contas do utilizador (sem segredos), marcando a conta por omissão."""
    items = [
        _public_account(account)
        for account in _store()["accounts"]
        if _normalize_key(account.get("owner")) == _normalize_key(owner)
    ]
    items.sort(key=lambda item: (not item.get("is_default"), item.get("email_address") or ""))
    return {
        "total": len(items),
        "items": items,
        "default_id": next((item["id"] for item in items if item.get("is_default")), items[0]["id"] if items else None),
    }


def save_account(owner: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    """Cria ou altera uma conta de email (a palavra-passe só muda se vier preenchida)."""
    email_address = (payload.get("email_address") or "").strip()
    if not email_address or "@" not in email_address:
        raise EmailError("Indique um endereço de email válido.")

    provider_id = (payload.get("provider") or "custom").strip() or "custom"
    preset = PROVIDERS_BY_ID.get(provider_id) or PROVIDERS_BY_ID["custom"]
    account_id = (payload.get("id") or "").strip() or uuid.uuid4().hex[:12]

    imap_host = (payload.get("imap_host") or preset.get("imap_host") or "").strip()
    smtp_host = (payload.get("smtp_host") or preset.get("smtp_host") or "").strip()
    if not imap_host or not smtp_host:
        raise EmailError("Indique os servidores IMAP e SMTP (ou escolha um fornecedor da lista).")

    imap_security = (payload.get("imap_security") or preset.get("imap_security") or "ssl").lower()
    smtp_security = (payload.get("smtp_security") or preset.get("smtp_security") or "starttls").lower()
    for mode in (imap_security, smtp_security):
        if mode not in SECURITY_MODES:
            raise EmailError(f"Modo de segurança desconhecido: {mode}.")

    existing: Optional[Dict[str, Any]] = None
    for account in _store()["accounts"]:
        if account.get("id") == account_id and _normalize_key(account.get("owner")) == _normalize_key(owner):
            existing = account
            break

    password = payload.get("password")
    if password is None or password == "":
        password = existing.get("password") if existing else ""
    if not password:
        raise EmailError("Indique a palavra-passe (ou a palavra-passe de aplicação) da conta.")

    record: Dict[str, Any] = {
        "id": account_id,
        "owner": owner,
        "label": (payload.get("label") or email_address).strip(),
        "email_address": email_address,
        "display_name": (payload.get("display_name") or "").strip(),
        "provider": provider_id,
        "username": (payload.get("username") or email_address).strip(),
        "password": str(password),
        "imap_host": imap_host,
        "imap_port": int(payload.get("imap_port") or preset.get("imap_port") or 993),
        "imap_security": imap_security,
        "smtp_host": smtp_host,
        "smtp_port": int(payload.get("smtp_port") or preset.get("smtp_port") or 587),
        "smtp_security": smtp_security,
        "signature": payload.get("signature") or (existing or {}).get("signature") or "",
        "color": payload.get("color") or (existing or {}).get("color") or "teal",
        "created_at": (existing or {}).get("created_at") or _now(),
        "updated_at": _now(),
        "last_sync_at": (existing or {}).get("last_sync_at"),
        "last_error": None,
    }

    store = _store()
    if payload.get("is_default"):
        for account in store["accounts"]:
            if _normalize_key(account.get("owner")) == _normalize_key(owner):
                account["is_default"] = False
    record["is_default"] = bool(payload.get("is_default")) or not any(
        _normalize_key(account.get("owner")) == _normalize_key(owner) for account in store["accounts"]
    )

    with _lock:
        store["accounts"] = [account for account in store["accounts"] if account.get("id") != account_id]
        store["accounts"].append(record)
        _write_store(store)

    return _public_account(record)


def delete_account(owner: str, account_id: str) -> Dict[str, Any]:
    """Remove uma conta de email do utilizador."""
    store = _store()
    before = len(store["accounts"])
    with _lock:
        store["accounts"] = [
            account
            for account in store["accounts"]
            if not (account.get("id") == account_id and _normalize_key(account.get("owner")) == _normalize_key(owner))
        ]
        removed = before - len(store["accounts"])
        if removed:
            _write_store(store)
    if not removed:
        raise EmailError("Conta de email não encontrada.", status=404)
    return {"deleted": True, "id": account_id}


def _touch(account_id: str, *, error: Optional[str] = None) -> None:
    """Regista a última sincronização (ou o último erro) de uma conta."""
    store = _store()
    for account in store["accounts"]:
        if account.get("id") == account_id:
            account["last_sync_at"] = _now()
            account["last_error"] = error
            with _lock:
                _write_store(store)
            return


# ---------------------------------------------------------------------------
# IMAP
# ---------------------------------------------------------------------------
def _imap_connect(account: Dict[str, Any]) -> imaplib.IMAP4:
    host = account.get("imap_host") or ""
    port = int(account.get("imap_port") or 993)
    security = (account.get("imap_security") or "ssl").lower()
    if security == "starttls":
        try:
            conn: imaplib.IMAP4 = imaplib.IMAP4(host, port, timeout=IMAP_TIMEOUT)
        except Exception as exc:
            raise EmailError(f"Não foi possível ligar a {host}:{port} ({exc}).", status=502)
        try:
            conn.starttls(ssl.create_default_context())
        except Exception as exc:
            raise EmailError(f"O servidor {host} recusou STARTTLS ({exc}).", status=502)
    else:
        try:
            conn = imaplib.IMAP4_SSL(host, port, timeout=IMAP_TIMEOUT)
        except Exception as exc:
            raise EmailError(f"Não foi possível ligar a {host}:{port} ({exc}).", status=502)

    try:
        conn.login(account.get("username") or account.get("email_address") or "", account.get("password") or "")
    except Exception as exc:
        try:
            conn.logout()
        except Exception:
            pass
        raise EmailError(
            "O servidor recusou o utilizador ou a palavra-passe. Em Gmail/Outlook/ iCloud é preciso uma palavra-passe de aplicação.",
            status=401,
        ) from exc
    return conn


def _imap_close(conn: Optional[imaplib.IMAP4]) -> None:
    if conn is None:
        return
    try:
        conn.logout()
    except Exception:
        pass


def _utf7_encode(text: str) -> str:
    """Codifica um nome de pasta em *modified UTF-7* (o que o IMAP usa)."""
    result: List[str] = []
    buffer: List[str] = []

    def flush() -> None:
        if not buffer:
            return
        encoded = base64.b64encode("".join(buffer).encode("utf-16-be")).decode("ascii").rstrip("=")
        result.append("&" + encoded.replace("/", ",") + "-")
        buffer.clear()

    for char in text:
        code = ord(char)
        if 0x20 <= code <= 0x7E:
            flush()
            result.append("&-" if char == "&" else char)
        else:
            buffer.append(char)
    flush()
    return "".join(result)


def _utf7_decode(text: str) -> str:
    """Decodifica um nome de pasta em *modified UTF-7*."""
    result: List[str] = []
    index = 0
    while index < len(text):
        char = text[index]
        if char != "&":
            result.append(char)
            index += 1
            continue
        end = text.find("-", index)
        if end == -1:
            result.append(char)
            index += 1
            continue
        chunk = text[index + 1 : end]
        if not chunk:
            result.append("&")
        else:
            padding = "=" * (-len(chunk) % 4)
            try:
                result.append(base64.b64decode(chunk.replace(",", "/") + padding).decode("utf-16-be"))
            except Exception:
                result.append(chunk)
        index = end + 1
    return "".join(result)


def _folder_from_listing(line: str) -> Optional[Dict[str, Any]]:
    match = re.match(r"\((?P<flags>[^)]*)\)\s+(?P<delim>\"[^\"]*\"|NIL)\s+(?P<name>.+)$", line.strip())
    if not match:
        return None
    delimiter = match.group("delim")
    delimiter = delimiter[1:-1] if delimiter.startswith('"') else "/"
    name = match.group("name").strip().strip('"')
    if not name:
        return None
    decoded = _utf7_decode(name)
    label = decoded.split(delimiter)[-1] if delimiter else decoded
    flags = match.group("flags").lower()
    return {
        # O `id` é o nome **legível**: é o que a aplicação devolve e recebe, e o
        # serviço volta a codificá-lo em *modified UTF-7* antes de falar com o
        # servidor (entrar numa pasta, mover, consultar contagens).
        "id": decoded,
        "raw": name,
        "name": decoded,
        "label": label or decoded,
        "delimiter": delimiter,
        "selectable": "\\noselect" not in flags,
        "sent": "\\sent" in flags,
        "drafts": "\\drafts" in flags,
        "trash": "\\trash" in flags,
        "junk": "\\junk" in flags,
        "archive": "\\archive" in flags or "archive" in decoded.lower(),
    }


def _imap_error(account_id: str, exc: Exception) -> EmailError:
    message = str(exc) or exc.__class__.__name__
    _touch(account_id, error=message)
    return EmailError(f"A caixa de correio respondeu com um erro: {message}", status=502)


def list_folders(account: Dict[str, Any]) -> Dict[str, Any]:
    """Pastas da caixa de correio, com o número de mensagens por pasta."""
    conn: Optional[imaplib.IMAP4] = None
    try:
        conn = _imap_connect(account)
        status, data = conn.list()
        if status != "OK":
            raise EmailError("O servidor não devolveu a lista de pastas.", status=502)
        folders: List[Dict[str, Any]] = []
        for raw in data or []:
            line = raw.decode("utf-8", "replace") if isinstance(raw, bytes) else str(raw)
            folder = _folder_from_listing(line)
            if not folder:
                continue
            if folder["selectable"]:
                try:
                    _, info = conn.status(_utf7_encode(folder["id"]), "(MESSAGES UNSEEN)")
                    blob = b" ".join(part for part in (info or []) if isinstance(part, bytes))
                    messages = re.search(rb"MESSAGES\s+(\d+)", blob)
                    unseen = re.search(rb"UNSEEN\s+(\d+)", blob)
                    folder["messages"] = int(messages.group(1)) if messages else 0
                    folder["unseen"] = int(unseen.group(1)) if unseen else 0
                except Exception:
                    folder["messages"] = None
                    folder["unseen"] = None
            folders.append(folder)

        order = {"inbox": 0, "sent": 1, "drafts": 2, "archive": 3, "junk": 4, "trash": 5}

        def rank(folder: Dict[str, Any]) -> Tuple[int, str]:
            name = (folder["name"] or "").upper()
            if name == "INBOX":
                return (0, "")
            for key, position in order.items():
                if folder.get(key):
                    return (position, name)
            return (9, name)

        folders.sort(key=rank)
        _touch(account["id"])
        return {"total": len(folders), "items": folders, "account": _public_account(account)}
    except EmailError:
        raise
    except Exception as exc:  # noqa: BLE001 - ligação de rede: devolver erro legível
        raise _imap_error(account["id"], exc)
    finally:
        _imap_close(conn)


def _decode_header(value: Optional[str]) -> str:
    if not value:
        return ""
    try:
        return str(make_header(decode_header(value)))
    except Exception:
        return str(value).strip()


def _decode_payload(part) -> str:
    payload = part.get_payload(decode=True)
    if payload is None:
        raw = part.get_payload()
        return raw if isinstance(raw, str) else ""
    charset = part.get_content_charset() or "utf-8"
    try:
        return payload.decode(charset, errors="replace")
    except (LookupError, UnicodeDecodeError):
        return payload.decode("utf-8", errors="replace")


_TAG_RE = re.compile(r"<[^>]+>")
_SCRIPT_RE = re.compile(r"<(script|style)[^>]*>.*?</\1>", re.S | re.I)


def _html_to_text(html: str) -> str:
    text = _SCRIPT_RE.sub(" ", html)
    text = re.sub(r"<br\s*/?>|</p>|</div>|</tr>", "\n", text, flags=re.I)
    text = _TAG_RE.sub(" ", text)
    text = _unescape_html(text)
    return re.sub(r"[ \t]+", " ", text).strip()


def _snippet(text: str, limit: int = SNIPPET_LIMIT) -> str:
    flat = re.sub(r"\s+", " ", text or "").strip()
    return flat[:limit]


def _address_list(value: Optional[str]) -> List[Dict[str, str]]:
    if not value:
        return []
    items: List[Dict[str, str]] = []
    for part in re.split(r",(?![^\"]*\")", value):
        decoded = _decode_header(part)
        match = re.match(r"\s*(?P<name>.*?)\s*<(?P<email>[^>]+)>\s*$", decoded)
        if match:
            items.append({"name": match.group("name").strip().strip('"'), "email": match.group("email").strip()})
        elif decoded.strip():
            items.append({"name": "", "email": decoded.strip()})
    return items


def _iso_date(value: Optional[str]) -> Optional[str]:
    if not value:
        return None
    try:
        parsed = parsedate_to_datetime(value)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc).isoformat()
    except Exception:
        return None


IMAP_SEARCH_CHARSETS = (None, "UTF-8")


def _search_uids(conn: imaplib.IMAP4, *, query: Optional[str], unread: bool, flagged: bool) -> List[str]:
    criteria: List[str] = []
    if unread:
        criteria.append("UNSEEN")
    if flagged:
        criteria.append("FLAGGED")
    if query:
        escaped = query.replace("\\", "\\\\").replace('"', '\\"')
        criteria.append(f'(OR SUBJECT "{escaped}" FROM "{escaped}")')
    expression = f"({' '.join(criteria)})" if criteria else "ALL"

    last_error: Optional[Exception] = None
    for charset in IMAP_SEARCH_CHARSETS:
        try:
            args = (charset, expression) if charset else (expression,)
            status, data = conn.uid("search", *args)
            if status != "OK":
                continue
            blob = b" ".join(part for part in (data or []) if isinstance(part, bytes))
            return [token.decode("ascii", "ignore") for token in blob.split() if token.strip()]
        except Exception as exc:  # noqa: BLE001 - alguns servidores recusam charsets
            last_error = exc
            continue
    if last_error:
        raise last_error
    return []


def _select(conn: imaplib.IMAP4, folder: str) -> int:
    status, data = conn.select(_utf7_encode(folder or "INBOX"), readonly=True)
    if status != "OK":
        raise EmailError(f"Não foi possível abrir a pasta «{folder}».", status=404)
    blob = b" ".join(part for part in (data or []) if isinstance(part, bytes))
    match = re.search(rb"(\d+)", blob)
    return int(match.group(1)) if match else 0


def list_messages(
    account: Dict[str, Any],
    *,
    folder: str = "INBOX",
    limit: int = 40,
    offset: int = 0,
    query: Optional[str] = None,
    unread: bool = False,
    flagged: bool = False,
) -> Dict[str, Any]:
    """Lista as mensagens de uma pasta (mais recentes primeiro), com pré-visualização."""
    limit = max(1, min(int(limit or 40), MAX_LIMIT))
    conn: Optional[imaplib.IMAP4] = None
    try:
        conn = _imap_connect(account)
        total_in_folder = _select(conn, folder)
        uids = _search_uids(conn, query=query, unread=unread, flagged=flagged)
        total = len(uids)
        window = list(reversed(uids))[offset : offset + limit]
        items: List[Dict[str, Any]] = []
        if window:
            chunk = b",".join(uid.encode("ascii") for uid in window)
            status, data = conn.uid(
                "fetch",
                chunk,
                "(FLAGS RFC822.SIZE BODY.PEEK[HEADER.FIELDS (FROM TO CC REPLY-TO SUBJECT DATE MESSAGE-ID)])",
            )
            if status != "OK":
                raise EmailError("O servidor não devolveu as mensagens pedidas.", status=502)
            order: Dict[str, Dict[str, Any]] = {}
            for entry in data or []:
                if not isinstance(entry, tuple) or len(entry) < 2:
                    continue
                meta = entry[0] if isinstance(entry[0], bytes) else b""
                raw = entry[1] if isinstance(entry[1], bytes) else b""
                uid_match = re.search(rb"UID\s+(\d+)", meta)
                if not uid_match:
                    continue
                uid = uid_match.group(1).decode("ascii")
                message = message_from_bytes(raw)
                flags_blob = meta.upper()
                order[uid] = {
                    "uid": uid,
                    "folder": folder,
                    "subject": _decode_header(message.get("Subject")) or "(sem assunto)",
                    "from": _address_list(message.get("From")),
                    "to": _address_list(message.get("To")),
                    "cc": _address_list(message.get("Cc")),
                    "date": _iso_date(message.get("Date")),
                    "message_id": (message.get("Message-ID") or "").strip(),
                    "size": int(re.search(rb"RFC822\.SIZE\s+(\d+)", meta).group(1)) if re.search(rb"RFC822\.SIZE\s+(\d+)", meta) else None,
                    "unread": b"\\SEEN" not in flags_blob,
                    "flagged": b"\\FLAGGED" in flags_blob,
                    "answered": b"\\ANSWERED" in flags_blob,
                    "has_attachments": None,
                }
            for uid in window:
                item = order.get(uid)
                if item:
                    items.append(item)

            # Pré-visualização: um excerto do corpo de cada mensagem da página.
            for item in items:
                try:
                    body_status, body_data = conn.uid("fetch", item["uid"], "(BODY.PEEK[TEXT]<0.2048>)")
                    if body_status != "OK":
                        continue
                    blob = b""
                    for entry in body_data or []:
                        if isinstance(entry, tuple) and len(entry) > 1 and isinstance(entry[1], bytes):
                            blob = entry[1]
                            break
                    text = blob.decode("utf-8", "replace")
                    if re.search(r"<[a-z][\s>]", text, re.I):
                        text = _html_to_text(text)
                    elif "=" in text and re.search(r"=[0-9A-F]{2}", text):
                        text = re.sub(r"=\r?\n", "", text)  # quoted-printable simples
                        try:
                            import quopri

                            text = quopri.decodestring(text.encode("latin-1", "replace")).decode("utf-8", "replace")
                        except Exception:
                            pass
                    item["preview"] = _snippet(text)
                except Exception:
                    item["preview"] = ""
        _touch(account["id"])
        return {
            "folder": folder,
            "total": total,
            "folder_total": total_in_folder,
            "offset": offset,
            "limit": limit,
            "has_more": offset + len(items) < total,
            "items": items,
        }
    except EmailError:
        raise
    except Exception as exc:  # noqa: BLE001
        raise _imap_error(account["id"], exc)
    finally:
        _imap_close(conn)


def get_message(account: Dict[str, Any], uid: str, *, folder: str = "INBOX", mark_read: bool = True) -> Dict[str, Any]:
    """Mensagem completa: cabeçalhos, texto, HTML, anexos e sinalizadores."""
    conn: Optional[imaplib.IMAP4] = None
    try:
        conn = _imap_connect(account)
        status, _ = conn.select(_utf7_encode(folder or "INBOX"), readonly=False)
        if status != "OK":
            raise EmailError(f"Não foi possível abrir a pasta «{folder}».", status=404)
        status, data = conn.uid("fetch", uid, "(FLAGS RFC822)")
        if status != "OK":
            raise EmailError("Mensagem não encontrada.", status=404)

        meta = b""
        raw = b""
        for entry in data or []:
            if isinstance(entry, tuple) and len(entry) > 1:
                meta = entry[0] if isinstance(entry[0], bytes) else b""
                raw = entry[1] if isinstance(entry[1], bytes) else b""
                break
        if not raw:
            raise EmailError("Mensagem não encontrada.", status=404)

        message = message_from_bytes(raw)
        text_parts: List[str] = []
        html_parts: List[str] = []
        attachments: List[Dict[str, Any]] = []
        for part in message.walk():
            if part.is_multipart():
                continue
            content_type = part.get_content_type()
            disposition = (part.get("Content-Disposition") or "").lower()
            filename = _decode_header(part.get_filename())
            if "attachment" in disposition or (filename and content_type not in ("text/plain", "text/html")):
                payload = part.get_payload(decode=True) or b""
                attachments.append(
                    {
                        "filename": filename or "anexo",
                        "content_type": content_type,
                        "size": len(payload),
                        "inline": "inline" in disposition,
                    }
                )
                continue
            if content_type == "text/plain":
                text_parts.append(_decode_payload(part))
            elif content_type == "text/html":
                html_parts.append(_decode_payload(part))

        body_text = "\n".join(part for part in text_parts if part.strip())
        body_html = "\n".join(part for part in html_parts if part.strip())
        if not body_text and body_html:
            body_text = _html_to_text(body_html)

        flags_blob = meta.upper()
        folder_flags = {
            "unread": b"\\SEEN" not in flags_blob,
            "flagged": b"\\FLAGGED" in flags_blob,
            "answered": b"\\ANSWERED" in flags_blob,
            "draft": b"\\DRAFT" in flags_blob,
        }
        if mark_read and folder_flags["unread"]:
            try:
                conn.uid("store", uid, "+FLAGS", "(\\Seen)")
                folder_flags["unread"] = False
            except Exception:
                pass

        _touch(account["id"])
        return {
            "message": {
                "uid": uid,
                "folder": folder,
                "subject": _decode_header(message.get("Subject")) or "(sem assunto)",
                "from": _address_list(message.get("From")),
                "to": _address_list(message.get("To")),
                "cc": _address_list(message.get("Cc")),
                "reply_to": _address_list(message.get("Reply-To")),
                "date": _iso_date(message.get("Date")),
                "message_id": (message.get("Message-ID") or "").strip(),
                "in_reply_to": (message.get("In-Reply-To") or "").strip(),
                "references": (message.get("References") or "").strip(),
                "body_text": body_text[:BODY_LIMIT],
                "body_html": body_html[:BODY_LIMIT],
                "attachments": attachments,
                **folder_flags,
            },
            "account": _public_account(account),
        }
    except EmailError:
        raise
    except Exception as exc:  # noqa: BLE001
        raise _imap_error(account["id"], exc)
    finally:
        _imap_close(conn)


FLAG_ACTIONS = {
    "read": ("+FLAGS", "(\\Seen)"),
    "unread": ("-FLAGS", "(\\Seen)"),
    "flag": ("+FLAGS", "(\\Flagged)"),
    "unflag": ("-FLAGS", "(\\Flagged)"),
}


def set_message_flags(account: Dict[str, Any], uid: str, *, folder: str = "INBOX", action: str = "read") -> Dict[str, Any]:
    """Muda um sinalizador: lida/não lida, destacada/não destacada."""
    if action not in FLAG_ACTIONS:
        raise EmailError(f"Ação desconhecida: {action}.")
    operation, flags = FLAG_ACTIONS[action]
    conn: Optional[imaplib.IMAP4] = None
    try:
        conn = _imap_connect(account)
        status, _ = conn.select(_utf7_encode(folder or "INBOX"), readonly=False)
        if status != "OK":
            raise EmailError(f"Não foi possível abrir a pasta «{folder}».", status=404)
        status, _ = conn.uid("store", uid, operation, flags)
        if status != "OK":
            raise EmailError("O servidor recusou a alteração do sinalizador.", status=502)
        _touch(account["id"])
        return {"updated": True, "uid": uid, "action": action}
    except EmailError:
        raise
    except Exception as exc:  # noqa: BLE001
        raise _imap_error(account["id"], exc)
    finally:
        _imap_close(conn)


def move_message(
    account: Dict[str, Any], uid: str, *, folder: str = "INBOX", target: str = "Archive"
) -> Dict[str, Any]:
    """Move uma mensagem para outra pasta (copia e apaga, universalmente suportado)."""
    if not target:
        raise EmailError("Indique a pasta de destino.")
    conn: Optional[imaplib.IMAP4] = None
    try:
        conn = _imap_connect(account)
        status, _ = conn.select(_utf7_encode(folder or "INBOX"), readonly=False)
        if status != "OK":
            raise EmailError(f"Não foi possível abrir a pasta «{folder}».", status=404)
        status, _ = conn.uid("copy", uid, _utf7_encode(target))
        if status != "OK":
            raise EmailError(f"Não foi possível copiar para «{target}».", status=502)
        conn.uid("store", uid, "+FLAGS", "(\\Deleted)")
        try:
            conn.expunge()
        except Exception:
            pass
        _touch(account["id"])
        return {"moved": True, "uid": uid, "from": folder, "to": target}
    except EmailError:
        raise
    except Exception as exc:  # noqa: BLE001
        raise _imap_error(account["id"], exc)
    finally:
        _imap_close(conn)


def delete_message(account: Dict[str, Any], uid: str, *, folder: str = "INBOX") -> Dict[str, Any]:
    """Apaga uma mensagem (marca como apagada e limpa a pasta)."""
    conn: Optional[imaplib.IMAP4] = None
    try:
        conn = _imap_connect(account)
        status, _ = conn.select(_utf7_encode(folder or "INBOX"), readonly=False)
        if status != "OK":
            raise EmailError(f"Não foi possível abrir a pasta «{folder}».", status=404)
        status, _ = conn.uid("store", uid, "+FLAGS", "(\\Deleted)")
        if status != "OK":
            raise EmailError("O servidor recusou apagar a mensagem.", status=502)
        try:
            conn.expunge()
        except Exception:
            pass
        _touch(account["id"])
        return {"deleted": True, "uid": uid, "folder": folder}
    except EmailError:
        raise
    except Exception as exc:  # noqa: BLE001
        raise _imap_error(account["id"], exc)
    finally:
        _imap_close(conn)


# ---------------------------------------------------------------------------
# SMTP
# ---------------------------------------------------------------------------
def _smtp_connect(account: Dict[str, Any]) -> smtplib.SMTP:
    host = account.get("smtp_host") or ""
    port = int(account.get("smtp_port") or 587)
    security = (account.get("smtp_security") or "starttls").lower()
    if security == "ssl":
        try:
            conn: smtplib.SMTP = smtplib.SMTP_SSL(host, port, timeout=SMTP_TIMEOUT, context=ssl.create_default_context())
        except Exception as exc:
            raise EmailError(f"Não foi possível ligar a {host}:{port} ({exc}).", status=502)
    else:
        try:
            conn = smtplib.SMTP(host, port, timeout=SMTP_TIMEOUT)
        except Exception as exc:
            raise EmailError(f"Não foi possível ligar a {host}:{port} ({exc}).", status=502)
        if security == "starttls":
            try:
                conn.starttls(context=ssl.create_default_context())
                conn.ehlo()
            except Exception as exc:
                raise EmailError(f"O servidor {host} recusou STARTTLS ({exc}).", status=502)
    try:
        conn.login(account.get("username") or account.get("email_address") or "", account.get("password") or "")
    except Exception as exc:
        try:
            conn.quit()
        except Exception:
            pass
        raise EmailError(
            "O servidor de envio recusou o utilizador ou a palavra-passe. Confirme a palavra-passe de aplicação.",
            status=401,
        ) from exc
    return conn


def _attachment_payload(item: Dict[str, Any]) -> Tuple[str, bytes, str]:
    filename = (item.get("filename") or "anexo").strip()
    content_type = item.get("content_type") or mimetypes.guess_type(filename)[0] or "application/octet-stream"
    data = item.get("data") or ""
    if isinstance(data, str):
        if "," in data and data.strip().startswith("data:"):
            data = data.split(",", 1)[1]
        try:
            payload = base64.b64decode(data)
        except Exception as exc:
            raise EmailError(f"O anexo «{filename}» não está em base64 válido.") from exc
    else:
        payload = bytes(data)
    return filename, payload, content_type


def send_message(account: Dict[str, Any], payload: Dict[str, Any]) -> Dict[str, Any]:
    """Envia uma mensagem (nova ou resposta) com texto, HTML opcional e anexos."""
    to = payload.get("to")
    recipients = to if isinstance(to, list) else [part for part in re.split(r"[;,]", str(to or "")) if part.strip()]
    recipients = [str(item).strip() for item in recipients if str(item).strip()]
    if not recipients:
        raise EmailError("Indique pelo menos um destinatário.")

    body_text = payload.get("body_text") or payload.get("body") or ""
    if not body_text.strip() and not payload.get("body_html"):
        raise EmailError("Escreva o corpo da mensagem.")

    message = EmailMessage()
    message["Subject"] = payload.get("subject") or "(sem assunto)"
    display_name = account.get("display_name") or account.get("label") or ""
    message["From"] = formataddr((display_name, account.get("email_address") or account.get("username") or ""))
    message["To"] = ", ".join(recipients)
    cc = payload.get("cc")
    cc_list = cc if isinstance(cc, list) else [part for part in re.split(r"[;,]", str(cc or "")) if part.strip()]
    if cc_list:
        message["Cc"] = ", ".join(str(item).strip() for item in cc_list)
    bcc = payload.get("bcc")
    bcc_list = bcc if isinstance(bcc, list) else [part for part in re.split(r"[;,]", str(bcc or "")) if part.strip()]
    message["Date"] = formatdate(localtime=True)
    message["Message-ID"] = make_msgid()
    if payload.get("in_reply_to"):
        message["In-Reply-To"] = str(payload["in_reply_to"])
    if payload.get("references"):
        message["References"] = str(payload["references"])
    elif payload.get("in_reply_to"):
        message["References"] = str(payload["in_reply_to"])

    signature = (account.get("signature") or "").strip()
    if signature and payload.get("include_signature", True):
        body_text = f"{body_text.rstrip()}\n\n{signature}\n"

    body_html = payload.get("body_html")
    if body_html:
        html_body = str(body_html)
        if signature and payload.get("include_signature", True):
            html_body = f"{html_body}<br><br><pre style=\"font-family:inherit\">{signature}</pre>"
        message.set_content(body_text or _html_to_text(html_body))
        message.add_alternative(html_body, subtype="html")
    else:
        message.set_content(body_text)

    for item in payload.get("attachments") or []:
        if not isinstance(item, dict):
            continue
        filename, content, content_type = _attachment_payload(item)
        maintype, _, subtype = content_type.partition("/")
        message.add_attachment(content, maintype=maintype or "application", subtype=subtype or "octet-stream", filename=filename)

    conn: Optional[smtplib.SMTP] = None
    try:
        conn = _smtp_connect(account)
        conn.send_message(message, from_addr=account.get("email_address") or account.get("username"), to_addrs=recipients + [str(item).strip() for item in cc_list] + [str(item).strip() for item in bcc_list])
        _touch(account["id"])
        return {"sent": True, "message_id": message["Message-ID"], "to": recipients, "cc": [str(item).strip() for item in cc_list]}
    except EmailError:
        raise
    except Exception as exc:  # noqa: BLE001
        message_text = str(exc) or exc.__class__.__name__
        _touch(account["id"], error=message_text)
        raise EmailError(f"O envio falhou: {message_text}", status=502)
    finally:
        if conn is not None:
            try:
                conn.quit()
            except Exception:
                pass


# ---------------------------------------------------------------------------
# Teste de ligação
# ---------------------------------------------------------------------------
def test_account(account: Dict[str, Any]) -> Dict[str, Any]:
    """Valida as credenciais e devolve o que a conta permite fazer."""
    result: Dict[str, Any] = {"imap": False, "smtp": False, "folders": 0, "capabilities": []}
    conn: Optional[imaplib.IMAP4] = None
    try:
        conn = _imap_connect(account)
        result["imap"] = True
        try:
            status, data = conn.list()
            result["folders"] = len(data or []) if status == "OK" else 0
        except Exception:
            pass
        try:
            capabilities = conn.capabilities or ()
            result["capabilities"] = sorted(str(item) for item in capabilities)
        except Exception:
            pass
        try:
            conn.select("INBOX", readonly=True)
            result["inbox_ok"] = True
        except Exception:
            result["inbox_ok"] = False
    finally:
        _imap_close(conn)

    smtp_conn: Optional[smtplib.SMTP] = None
    try:
        smtp_conn = _smtp_connect(account)
        result["smtp"] = True
    except EmailError as exc:
        result["smtp_error"] = exc.message
    finally:
        if smtp_conn is not None:
            try:
                smtp_conn.quit()
            except Exception:
                pass

    _touch(account["id"], error=None if (result["imap"] and result["smtp"]) else "Teste de ligação incompleto")
    return result


def account_from_payload(owner: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    """Constrói uma conta temporária (ainda não guardada) para teste direto."""
    provider_id = (payload.get("provider") or "custom").strip() or "custom"
    preset = PROVIDERS_BY_ID.get(provider_id) or PROVIDERS_BY_ID["custom"]
    return {
        "id": "test",
        "owner": owner,
        "email_address": (payload.get("email_address") or "").strip(),
        "display_name": payload.get("display_name") or "",
        "label": payload.get("label") or payload.get("email_address"),
        "provider": provider_id,
        "username": (payload.get("username") or payload.get("email_address") or "").strip(),
        "password": payload.get("password") or "",
        "imap_host": (payload.get("imap_host") or preset.get("imap_host") or "").strip(),
        "imap_port": int(payload.get("imap_port") or preset.get("imap_port") or 993),
        "imap_security": (payload.get("imap_security") or preset.get("imap_security") or "ssl").lower(),
        "smtp_host": (payload.get("smtp_host") or preset.get("smtp_host") or "").strip(),
        "smtp_port": int(payload.get("smtp_port") or preset.get("smtp_port") or 587),
        "smtp_security": (payload.get("smtp_security") or preset.get("smtp_security") or "starttls").lower(),
        "signature": payload.get("signature") or "",
    }


def stats(owner: str) -> Dict[str, Any]:
    """Panorama do Email para o utilizador: contas, fornecedores e último erro."""
    accounts = [
        account
        for account in _store()["accounts"]
        if _normalize_key(account.get("owner")) == _normalize_key(owner)
    ]
    by_provider: Dict[str, int] = {}
    for account in accounts:
        key = account.get("provider") or "custom"
        by_provider[key] = by_provider.get(key, 0) + 1
    return {
        "accounts": len(accounts),
        "default_id": next((account["id"] for account in accounts if account.get("is_default")), None),
        "by_provider": [
            {
                "value": key,
                "label": (PROVIDERS_BY_ID.get(key) or {}).get("label", key),
                "count": value,
            }
            for key, value in sorted(by_provider.items(), key=lambda item: -item[1])
        ],
        "last_sync_at": max((account.get("last_sync_at") or "" for account in accounts), default=None),
        "errors": [
            {"id": account["id"], "email_address": account.get("email_address"), "error": account.get("last_error")}
            for account in accounts
            if account.get("last_error")
        ],
    }
