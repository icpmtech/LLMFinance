"""Correio da plataforma — gestor das caixas de correio do próprio IQ OS.

A aplicação **Correio da plataforma** (Administração → Correio) é o gestor do
correio da solução, não a caixa pessoal de cada utilizador (essa é a aplicação
`email_service`, com contas Gmail/Outlook/… por pessoa). Aqui trata-se das caixas
do domínio da plataforma: a que envia o email transacional (`no-reply@…`), o
`postmaster@`, o `dmarc@` e as que a administração acrescentar.

Camadas:

- **Caixas** (`finance_mail_accounts`) — servidores IMAP/SMTP e credenciais. A
  palavra-passe **nunca** é devolvida pela API (as respostas trazem apenas
  `has_password`), como manda o módulo de chaves. A caixa do email transacional é
  **derivada** da configuração SMTP da plataforma (`SMTP_*`/`.env`): não guarda
  segredos no índice — só as preferências (pastas, assinatura, ligada/desligada).
- **Arquivo pesquisável** (`finance_mail_messages`) — uma entrada por mensagem
  sincronizada (assunto, participantes, corpo, anexos e fio de conversa). É o
  Elasticsearch que serve a lista, a pesquisa, as contagens e as conversas; o
  IMAP fica para abrir a mensagem inteira e para operar sobre ela.
- **Sincronização** — incremental por pasta (`UID <último+1>:*`), com a primeira
  passagem a trazer as mensagens mais recentes de cada pasta. O estado vive em
  `finance_mail_accounts` (documento `sync::<caixa>`), pelo que reiniciar a API
  não perde o ponto onde ia.
- **Envio** — SMTP com a conta da caixa, corpo em texto e/ou HTML, anexos e
  cabeçalhos de resposta (`In-Reply-To`/`References`); a cópia enviada é
  arquivada na pasta *Sent* por `APPEND` (como o Outlook faz) e entra logo no
  índice, sem esperar pela sincronização seguinte.

A camada IMAP/SMTP é a do webmail (`api/email_service`), reutilizada de
propósito: uma só implementação de ligação, descodificação e envio.

**Degradação graciosa**: sem Elasticsearch a aplicação continua a funcionar —
lista, abre e envia por IMAP direto de uma caixa escolhida; perdem-se a pesquisa
global, as contagens agregadas e as conversas. Cada resposta diz de onde veio
(`source`).
"""
from __future__ import annotations

import logging
import os
import re
import threading
import uuid
from datetime import datetime, timezone
from email import message_from_bytes
from email.message import EmailMessage
from email.utils import formataddr, formatdate, parseaddr, parsedate_to_datetime
from typing import Any, Dict, Iterable, List, Optional, Tuple

from api import email_service
from api import email_signature
from api import service_keys
from api.elasticsearch_client import (
    PLATFORM_MAIL_ACCOUNTS_INDEX,
    PLATFORM_MAIL_MESSAGES_INDEX,
    SETTINGS_INDEX,
    get_es_client,
)

logger = logging.getLogger(__name__)

#: Erro do módulo — o mesmo tipo do webmail, para as rotas terem um só `except`.
MailError = email_service.EmailError

#: Caixa do email transacional (derivada do ambiente, só de leitura).
PLATFORM_ACCOUNT_ID = "plataforma"

KIND_ACCOUNT = "account"
KIND_SYNC = "sync"
KIND_SETTINGS = "platform-mail"
SETTINGS_DOC_ID = "platform-mail"

DEFAULT_SYNC_FOLDERS = ["INBOX", "Sent"]
#: Nomes que o servidor pode dar à pasta de enviados (Dovecot, Outlook, Gmail…).
SENT_ALIASES = ["sent", "sent items", "sent messages", "sent-mail", "elementos enviados", "enviados"]

DEFAULT_IMAP_PORT = 993
DEFAULT_IMAP_SECURITY = "ssl"
DEFAULT_SMTP_PORT = 587
DEFAULT_SMTP_SECURITY = "starttls"

#: Primeira sincronização de uma pasta: as mensagens mais recentes (sincronizar
#: anos de correio na primeira abertura demoraria minutos). `full=True` traz tudo
#: até ao teto.
INITIAL_BATCH = 200
#: Mensagens novas trazidas por pasta em cada passagem incremental.
SYNC_BATCH = 60
#: Teto de segurança de uma sincronização completa, por pasta.
FULL_SYNC_CAP = 2000

MAX_LIMIT = 200
SNIPPET_LIMIT = 240
#: Quanto do corpo entra no índice; o detalhe completo vem sempre do IMAP.
BODY_INDEX_LIMIT = 20_000
#: Acima disto só se arquiva o cabeçalho — uma mensagem de 50 MB não pode parar a
#: sincronização nem inchar o índice.
MAX_MESSAGE_BYTES = 20 * 1024 * 1024

SYNC_LOCK = threading.Lock()
_indices_ready = False


# ---------------------------------------------------------------------------
# Índices
# ---------------------------------------------------------------------------
def accounts_mapping() -> Dict[str, Any]:
    """Mapeamento das caixas de correio e do estado da sincronização."""
    return {
        "properties": {
            "kind": {"type": "keyword"},
            "id": {"type": "keyword"},
            "account": {"type": "keyword"},
            "label": {"type": "text", "fields": {"keyword": {"type": "keyword", "ignore_above": 256}}},
            "email_address": {"type": "keyword"},
            "display_name": {"type": "text"},
            "username": {"type": "keyword"},
            "source": {"type": "keyword"},
            "enabled": {"type": "boolean"},
            "folders": {"type": "keyword"},
            "created_at": {"type": "date"},
            "updated_at": {"type": "date"},
            "updated_by": {"type": "keyword"},
            "last_sync_at": {"type": "date"},
            "last_error": {"type": "text"},
            # Servidores e credenciais não se pesquisam (não interessam a ninguém
            # e não vale a pena indexá-los).
            "imap_host": {"type": "keyword", "index": False},
            "smtp_host": {"type": "keyword", "index": False},
            "state": {"type": "object", "enabled": False},
        }
    }


def messages_mapping() -> Dict[str, Any]:
    """Mapeamento do arquivo de correio (uma entrada por mensagem sincronizada)."""
    address = {
        "properties": {
            "name": {"type": "text"},
            "email": {"type": "keyword"},
        }
    }
    return {
        "properties": {
            "account": {"type": "keyword"},
            "account_label": {"type": "keyword"},
            "mailbox": {"type": "keyword"},
            "folder": {"type": "keyword"},
            "uid": {"type": "keyword"},
            "message_id": {"type": "keyword"},
            "thread_key": {"type": "keyword"},
            "in_reply_to": {"type": "keyword"},
            "references": {"type": "keyword"},
            "subject": {"type": "text", "fields": {"keyword": {"type": "keyword", "ignore_above": 512}}},
            "from_name": {"type": "text"},
            "from_email": {"type": "keyword"},
            "to": address,
            "cc": address,
            "bcc": address,
            "reply_to": address,
            "date": {"type": "date"},
            "internal_date": {"type": "date"},
            "indexed_at": {"type": "date"},
            "synced_at": {"type": "date"},
            "snippet": {"type": "text"},
            "body_text": {"type": "text"},
            # O HTML guarda-se para leitura sem IMAP, mas não se indexa: procurar
            # dentro de marcação só traria ruído aos resultados.
            "body_html": {"type": "text", "index": False},
            "size": {"type": "long"},
            "has_attachments": {"type": "boolean"},
            "attachments_count": {"type": "integer"},
            "attachments": {"type": "object", "enabled": False},
            "unseen": {"type": "boolean"},
            "flagged": {"type": "boolean"},
            "answered": {"type": "boolean"},
            "draft": {"type": "boolean"},
            "flags": {"type": "keyword"},
            "direction": {"type": "keyword"},
        }
    }


def ensure_indices(client: Optional[Any] = None) -> bool:
    """Cria os índices do módulo, se ainda não existirem."""
    cliente = client or get_es_client()
    if not cliente:
        return False
    ok = True
    for indice, mapping in (
        (PLATFORM_MAIL_ACCOUNTS_INDEX, accounts_mapping()),
        (PLATFORM_MAIL_MESSAGES_INDEX, messages_mapping()),
    ):
        try:
            if not cliente.indices.exists(index=indice):
                cliente.indices.create(
                    index=indice,
                    settings={"number_of_shards": 1, "number_of_replicas": 0},
                    mappings=mapping,
                )
        except Exception as exc:  # noqa: BLE001
            logger.warning("Não foi possível garantir o índice %s: %s", indice, exc)
            ok = False
    return ok


def _client() -> Optional[Any]:
    """Cliente Elasticsearch, com os índices do módulo garantidos uma vez."""
    global _indices_ready
    cliente = get_es_client()
    if cliente is not None and not _indices_ready:
        _indices_ready = ensure_indices(cliente)
    return cliente


# ---------------------------------------------------------------------------
# Utilidades
# ---------------------------------------------------------------------------
def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _text(value: Any) -> str:
    return value.strip() if isinstance(value, str) else ""


def _state_doc_id(account_id: str) -> str:
    return f"sync::{account_id}"


def _doc_id(account_id: str, folder: str, uid: str) -> str:
    """Identificador de uma mensagem no índice: `caixa::uid::pasta`."""
    return f"{account_id}::{uid}::{folder}"


def _parse_doc_id(value: str) -> Tuple[str, str, str]:
    """Desfaz `caixa::uid::pasta` (a pasta pode conter `::`)."""
    partes = str(value or "").split("::", 2)
    if len(partes) != 3 or not all(partes):
        raise MailError("Identificador de mensagem inválido.", status=400)
    return partes[0], partes[1], partes[2]


def _parse_address(raw: Any) -> Tuple[str, str]:
    """Interpreta `Nome <email@exemplo.pt>` ou apenas `email@exemplo.pt`."""
    nome, endereco = parseaddr(_text(raw))
    if endereco:
        return nome.strip(), endereco.strip()
    return "", _text(raw)


def _first_message_id(value: Optional[str]) -> str:
    """Primeiro identificador `<…>` de um cabeçalho Message-ID/References."""
    achado = re.search(r"<[^>]+>", value or "")
    return (achado.group(0) if achado else _text(value)).strip().lower()


def _thread_key(message_id: str, in_reply_to: str, references: str, subject: str) -> str:
    """Fio da conversa: a raiz das referências; senão o assunto, sem `Re:`/`Fwd:`.

    É o que permite agrupar uma resposta com quem a originou mesmo quando o
    cliente do outro lado não escreve `References`.
    """
    for candidato in re.findall(r"<[^>]+>", references or ""):
        return candidato.strip().lower()
    if in_reply_to:
        return _first_message_id(in_reply_to)
    if message_id:
        return message_id
    base = _subject_key(subject).lower()
    return f"assunto:{base}" if base else ""


def _subject_key(subject: str) -> str:
    """Assunto sem os prefixos de resposta (`Re:`, `Fwd:`, `Re[2]:`…)."""
    return re.sub(r"^(?:(?:re|fw|fwd|enc|res)\s*(\[\d+\])?\s*:\s*)+", "", _text(subject), flags=re.IGNORECASE).strip()


def _imap_defaults() -> Dict[str, Any]:
    """Servidor IMAP das caixas da plataforma.

    Por omissão é o mesmo que envia o correio transacional — é a mesma máquina: o
    Docker Mailserver serve SMTP e IMAP. A administração pode apontar para outro
    host em **Administração → Chaves e integrações**.
    """
    from api import notification_email

    smtp = notification_email._smtp_config()  # noqa: SLF001 - config única da plataforma
    host = _text(service_keys.resolver("mail_imap_host")) or _text(smtp.get("host"))
    port_raw = _text(service_keys.resolver("mail_imap_port")) or str(DEFAULT_IMAP_PORT)
    try:
        port = int(port_raw)
    except ValueError:
        port = DEFAULT_IMAP_PORT
    security = (_text(service_keys.resolver("mail_imap_security")) or DEFAULT_IMAP_SECURITY).lower()
    if security not in {"ssl", "starttls", "plain"}:
        security = DEFAULT_IMAP_SECURITY
    return {"host": host, "port": port, "security": security, "smtp": smtp}


# ---------------------------------------------------------------------------
# Definições do módulo
# ---------------------------------------------------------------------------
def settings() -> Dict[str, Any]:
    """Definições do módulo: sincronização automática e de quanto em quanto tempo."""
    intervalo = 300
    bruto = os.getenv("PLATFORM_MAIL_SYNC_SECONDS")
    if bruto:
        try:
            intervalo = max(0, int(bruto))
        except ValueError:
            pass
    auto = os.getenv("PLATFORM_MAIL_AUTO_SYNC", "1").strip().lower() not in {"0", "false", "no"}
    guardado: Dict[str, Any] = {}
    cliente = _client()
    if cliente is not None:
        try:
            if cliente.exists(index=SETTINGS_INDEX, id=SETTINGS_DOC_ID):
                guardado = cliente.get(index=SETTINGS_INDEX, id=SETTINGS_DOC_ID).get("_source") or {}
        except Exception as exc:  # noqa: BLE001
            logger.warning("Definições do correio da plataforma ilegíveis: %s", exc)
    payload = guardado.get("payload") if isinstance(guardado.get("payload"), dict) else {}
    if payload.get("sync_seconds") is not None:
        try:
            intervalo = max(0, int(payload["sync_seconds"]))
        except (TypeError, ValueError):
            pass
    return {
        "auto_sync": bool(payload.get("auto_sync", auto)),
        "sync_seconds": intervalo,
        "initial_batch": INITIAL_BATCH,
        "sync_batch": SYNC_BATCH,
        "full_sync_cap": FULL_SYNC_CAP,
        "updated_at": guardado.get("updated_at"),
        "updated_by": guardado.get("updated_by"),
    }


def save_settings(patch: Dict[str, Any], *, utilizador: Optional[str] = None) -> Dict[str, Any]:
    """Grava as definições do módulo (0 segundos desliga a sincronização)."""
    atuais = settings()
    novo = {
        "auto_sync": bool(patch.get("auto_sync", atuais["auto_sync"])),
        "sync_seconds": atuais["sync_seconds"],
    }
    if patch.get("sync_seconds") is not None:
        try:
            novo["sync_seconds"] = max(0, int(patch["sync_seconds"]))
        except (TypeError, ValueError):
            raise MailError("O intervalo de sincronização tem de ser um número de segundos.") from None
    cliente = _client()
    if cliente is None:
        raise MailError("Elasticsearch indisponível: não é possível gravar as definições.", status=503)
    documento = {
        "kind": KIND_SETTINGS,
        "id": SETTINGS_DOC_ID,
        "payload": novo,
        "updated_at": _now(),
        "updated_by": utilizador or "administração",
    }
    cliente.index(index=SETTINGS_INDEX, id=SETTINGS_DOC_ID, document=documento, refresh=True)
    return {"saved": True, "settings": settings()}


# ---------------------------------------------------------------------------
# Caixas de correio
# ---------------------------------------------------------------------------
def _platform_overrides() -> Dict[str, Any]:
    """Preferências guardadas da caixa da plataforma (sem credenciais)."""
    cliente = _client()
    if cliente is None:
        return {}
    try:
        if not cliente.exists(index=PLATFORM_MAIL_ACCOUNTS_INDEX, id=PLATFORM_ACCOUNT_ID):
            return {}
        origem = cliente.get(index=PLATFORM_MAIL_ACCOUNTS_INDEX, id=PLATFORM_ACCOUNT_ID).get("_source") or {}
    except Exception:  # noqa: BLE001
        return {}
    permitidos = {"label", "display_name", "signature", "folders", "enabled", "updated_at", "updated_by"}
    return {chave: valor for chave, valor in origem.items() if chave in permitidos}


def _platform_account() -> Optional[Dict[str, Any]]:
    """Caixa do email transacional, derivada da configuração SMTP da plataforma."""
    defaults = _imap_defaults()
    smtp = defaults["smtp"]
    utilizador = _text(smtp.get("user"))
    password = smtp.get("password") or ""
    nome, endereco = _parse_address(smtp.get("from") or utilizador)
    endereco = utilizador or endereco
    if not (defaults["host"] and endereco and password):
        return None
    conta = {
        "id": PLATFORM_ACCOUNT_ID,
        "kind": KIND_ACCOUNT,
        "label": "Correio da plataforma",
        "email_address": endereco,
        "display_name": nome or endereco.split("@")[0],
        "username": utilizador or endereco,
        "password": password,
        "imap_host": defaults["host"],
        "imap_port": defaults["port"],
        "imap_security": defaults["security"],
        "smtp_host": _text(smtp.get("host")) or defaults["host"],
        "smtp_port": int(smtp.get("port") or DEFAULT_SMTP_PORT),
        "smtp_security": _text(smtp.get("security")) or DEFAULT_SMTP_SECURITY,
        "signature": "",
        "folders": list(DEFAULT_SYNC_FOLDERS),
        "enabled": True,
        "source": "env",
        "readonly": True,
        "created_at": None,
        "updated_at": None,
    }
    conta.update(_platform_overrides())
    return conta


def _stored_accounts() -> List[Dict[str, Any]]:
    """Caixas gravadas no índice (documentos `kind = account`)."""
    cliente = _client()
    if cliente is None:
        return []
    try:
        resposta = cliente.search(
            index=PLATFORM_MAIL_ACCOUNTS_INDEX,
            body={"query": {"term": {"kind": KIND_ACCOUNT}}, "size": 200},
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("Caixas do correio da plataforma ilegíveis: %s", exc)
        return []
    itens: List[Dict[str, Any]] = []
    for hit in resposta.get("hits", {}).get("hits", []):
        origem = hit.get("_source") or {}
        if origem.get("id") and origem.get("id") != PLATFORM_ACCOUNT_ID:
            itens.append(origem)
    return itens


def accounts() -> List[Dict[str, Any]]:
    """Todas as caixas: a da plataforma primeiro, depois as gravadas."""
    itens: List[Dict[str, Any]] = []
    plataforma = _platform_account()
    if plataforma:
        itens.append(plataforma)
    itens.extend(_stored_accounts())
    estados = _sync_states()
    for conta in itens:
        estado = estados.get(conta["id"]) or {}
        conta["last_sync_at"] = estado.get("last_sync_at") or conta.get("last_sync_at")
        conta["last_error"] = estado.get("last_error") or conta.get("last_error")
    return itens


def public_account(account: Dict[str, Any]) -> Dict[str, Any]:
    """Versão segura de uma caixa: sem palavra-passe, mas com `has_password`."""
    publico = {chave: valor for chave, valor in account.items() if chave != "password"}
    publico["has_password"] = bool(account.get("password"))
    return publico


def get_account(account_id: str) -> Dict[str, Any]:
    """Caixa completa (com segredo), por identificador."""
    alvo = _text(account_id) or PLATFORM_ACCOUNT_ID
    for conta in accounts():
        if conta["id"] == alvo:
            return conta
    raise MailError("Caixa de correio não encontrada.", status=404)


def platform_account() -> Optional[Dict[str, Any]]:
    """Caixa do email transacional, se a plataforma estiver configurada para enviar."""
    return _platform_account()


def _normalize_account(payload: Dict[str, Any], existente: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Valida e completa uma caixa a gravar (servidores herdados da plataforma)."""
    atual = dict(existente or {})
    defaults = _imap_defaults()
    smtp = defaults["smtp"]

    def escolher(campo: str, *alternativas: Any) -> Any:
        """Valor do pedido → valor guardado → alternativa da plataforma."""
        for candidato in (payload.get(campo), atual.get(campo), *alternativas):
            if isinstance(candidato, str):
                if candidato.strip():
                    return candidato.strip()
            elif candidato not in (None, ""):
                return candidato
        return None

    endereco = _text(escolher("email_address"))
    if not endereco or "@" not in endereco:
        raise MailError("Indique o endereço de email da caixa.")
    password = escolher("password")
    if not password:
        raise MailError("Indique a palavra-passe da caixa (a mesma que o servidor usa no IMAP).")

    seguranca_imap = (_text(escolher("imap_security", defaults["security"])) or DEFAULT_IMAP_SECURITY).lower()
    if seguranca_imap not in {"ssl", "starttls", "plain"}:
        raise MailError("A segurança do IMAP tem de ser «ssl», «starttls» ou «plain».")
    seguranca_smtp = (_text(escolher("smtp_security", smtp.get("security"))) or DEFAULT_SMTP_SECURITY).lower()
    if seguranca_smtp not in {"ssl", "starttls", "plain"}:
        raise MailError("A segurança do SMTP tem de ser «ssl», «starttls» ou «plain».")

    pastas = escolher("folders") or list(DEFAULT_SYNC_FOLDERS)
    if isinstance(pastas, str):
        pastas = [parte.strip() for parte in pastas.split(",") if parte.strip()]
    if not isinstance(pastas, list) or not pastas:
        pastas = list(DEFAULT_SYNC_FOLDERS)

    return {
        "id": atual.get("id") or uuid.uuid4().hex[:12],
        "kind": KIND_ACCOUNT,
        "label": _text(escolher("label")) or endereco,
        "email_address": endereco,
        "display_name": _text(escolher("display_name")) or _text(escolher("label")) or endereco,
        "username": _text(escolher("username")) or endereco,
        "password": password,
        "imap_host": _text(escolher("imap_host", defaults["host"])),
        "imap_port": int(escolher("imap_port", defaults["port"]) or DEFAULT_IMAP_PORT),
        "imap_security": seguranca_imap,
        "smtp_host": _text(escolher("smtp_host", smtp.get("host"), defaults["host"])),
        "smtp_port": int(escolher("smtp_port", smtp.get("port")) or DEFAULT_SMTP_PORT),
        "smtp_security": seguranca_smtp,
        "signature": _text(payload.get("signature") if payload.get("signature") is not None else atual.get("signature")),
        "folders": [str(pasta) for pasta in pastas],
        "enabled": bool(payload.get("enabled", atual.get("enabled", True))),
        "source": atual.get("source") or "store",
        "created_at": atual.get("created_at") or _now(),
        "updated_at": _now(),
    }


def save_account(payload: Dict[str, Any], *, utilizador: Optional[str] = None) -> Dict[str, Any]:
    """Cria ou altera uma caixa de correio."""
    account_id = _text(payload.get("id"))
    if account_id == PLATFORM_ACCOUNT_ID:
        atual = _platform_account()
        if not atual:
            raise MailError(
                "A caixa da plataforma aparece quando o SMTP estiver configurado "
                "(Administração → Chaves e integrações).",
                status=409,
            )
        # Sem credenciais no índice: da caixa da plataforma só se guardam as
        # preferências (a palavra-passe continua a vir do SMTP).
        preferencias: Dict[str, Any] = {
            "id": PLATFORM_ACCOUNT_ID,
            "kind": KIND_ACCOUNT,
            "source": "env",
            "updated_at": _now(),
            "updated_by": utilizador or "administração",
        }
        for campo in ("label", "display_name", "signature"):
            if payload.get(campo) is not None:
                preferencias[campo] = _text(payload[campo])
        if payload.get("folders") is not None:
            pastas = payload["folders"]
            if isinstance(pastas, str):
                pastas = [parte.strip() for parte in pastas.split(",") if parte.strip()]
            preferencias["folders"] = [str(pasta) for pasta in pastas] or list(DEFAULT_SYNC_FOLDERS)
        if payload.get("enabled") is not None:
            preferencias["enabled"] = bool(payload["enabled"])
        if len(preferencias) <= 5:
            raise MailError("Nada para alterar na caixa da plataforma.")
        guardada = _store_account(preferencias, created_by=utilizador)
        return {"saved": True, "account": public_account({**atual, **guardada, "password": atual["password"]})}

    existente: Optional[Dict[str, Any]] = None
    if account_id:
        existente = next((conta for conta in _stored_accounts() if conta["id"] == account_id), None)
        if existente is None:
            raise MailError("Caixa de correio não encontrada.", status=404)
    normalizada = _normalize_account(payload, existente)
    guardada = _store_account(normalizada, created_by=utilizador)
    return {"saved": True, "account": public_account(guardada)}


def _store_account(account: Dict[str, Any], *, created_by: Optional[str] = None) -> Dict[str, Any]:
    cliente = _client()
    if cliente is None:
        raise MailError("Elasticsearch indisponível: não é possível guardar a caixa de correio.", status=503)
    documento = {**account, "updated_by": created_by or "administração"}
    cliente.index(index=PLATFORM_MAIL_ACCOUNTS_INDEX, id=account["id"], document=documento, refresh=True)
    return documento


def delete_account(account_id: str) -> Dict[str, Any]:
    """Remove uma caixa gravada (a da plataforma não se apaga, desliga-se)."""
    alvo = _text(account_id)
    if alvo == PLATFORM_ACCOUNT_ID:
        raise MailError(
            "A caixa da plataforma é derivada do SMTP e não se apaga: desligue-a ou mude as pastas.",
            status=409,
        )
    get_account(alvo)
    cliente = _client()
    if cliente is None:
        raise MailError("Elasticsearch indisponível.", status=503)
    cliente.delete(index=PLATFORM_MAIL_ACCOUNTS_INDEX, id=alvo, refresh=True)
    cliente.delete_by_query(
        index=PLATFORM_MAIL_ACCOUNTS_INDEX,
        body={"query": {"term": {"id": _state_doc_id(alvo)}}},
        refresh=True,
    )
    return {"deleted": True, "id": alvo}


def test_account(payload: Dict[str, Any]) -> Dict[str, Any]:
    """Valida as credenciais de uma caixa (gravada) ou de um rascunho (a criar)."""
    account_id = _text(payload.get("id"))
    existente: Optional[Dict[str, Any]] = None
    if account_id:
        existente = next((conta for conta in accounts() if conta["id"] == account_id), None)
        if existente is None:
            raise MailError("Caixa de correio não encontrada.", status=404)
        if not payload.get("password") and not payload.get("imap_host"):
            conta = existente
        else:
            conta = _normalize_account({**payload, "folder": None}, existente)
    else:
        conta = _normalize_account(payload)
    resultado = email_service.test_account(conta)
    resultado["account"] = public_account(conta)
    if resultado.get("imap"):
        resultado["unread_inbox"] = _inbox_unseen(conta)
    return resultado


def _inbox_unseen(account: Dict[str, Any]) -> Optional[int]:
    """Mensagens por ler na caixa de entrada (uma consulta rápida ao servidor)."""
    conn = None
    try:
        conn = email_service._imap_connect(account)  # noqa: SLF001
        status, data = conn.status("INBOX", "(UNSEEN)")  # noqa: SLF001
        if status != "OK" or not data or not data[0]:
            return None
        texto = data[0].decode("utf-8", "replace") if isinstance(data[0], bytes) else str(data[0])
        achado = re.search(r"UNSEEN\s+(\d+)", texto)
        return int(achado.group(1)) if achado else None
    except Exception:  # noqa: BLE001
        return None
    finally:
        email_service._imap_close(conn)  # noqa: SLF001


# ---------------------------------------------------------------------------
# Estado da sincronização
# ---------------------------------------------------------------------------
def _sync_states() -> Dict[str, Dict[str, Any]]:
    cliente = _client()
    if cliente is None:
        return {}
    try:
        resposta = cliente.search(
            index=PLATFORM_MAIL_ACCOUNTS_INDEX,
            body={"query": {"term": {"kind": KIND_SYNC}}, "size": 200},
        )
    except Exception:  # noqa: BLE001
        return {}
    estados: Dict[str, Dict[str, Any]] = {}
    for hit in resposta.get("hits", {}).get("hits", []):
        origem = hit.get("_source") or {}
        if origem.get("account"):
            estados[origem["account"]] = origem
    return estados


def sync_state(account_id: str) -> Dict[str, Any]:
    """Estado da sincronização de uma caixa (pastas e último UID visto).

    O mapa das pastas vive no campo `state` do documento — o campo `folders` está
    mapeado como `keyword` (é a lista de pastas a sincronizar de uma caixa) e não
    aceita objetos.
    """
    documento = _sync_states().get(account_id) or {}
    pastas = documento.get("state")
    return {
        "account": account_id,
        "folders": pastas if isinstance(pastas, dict) else {},
        "last_sync_at": documento.get("last_sync_at"),
        "last_error": documento.get("last_error"),
    }


def _save_sync_state(account_id: str, *, folders: Dict[str, Any], error: Optional[str] = None) -> None:
    cliente = _client()
    if cliente is None:
        return
    documento = {
        "kind": KIND_SYNC,
        "id": _state_doc_id(account_id),
        "account": account_id,
        "state": folders,
        "last_sync_at": _now(),
        "last_error": error,
    }
    try:
        cliente.index(index=PLATFORM_MAIL_ACCOUNTS_INDEX, id=documento["id"], document=documento, refresh=False)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Não foi possível guardar o estado de sincronização de %s: %s", account_id, exc)


# ---------------------------------------------------------------------------
# Pastas
# ---------------------------------------------------------------------------
def _folder_alias(name: str) -> List[str]:
    """Nomes equivalentes de uma pasta (o mesmo conceito em cada servidor)."""
    base = _text(name).lower()
    if base in {"inbox", "caixa de entrada"}:
        return ["inbox", "caixa de entrada"]
    if base in {"sent", *SENT_ALIASES}:
        return ["sent", *SENT_ALIASES]
    if base in {"drafts", "rascunhos"}:
        return ["drafts", "rascunhos"]
    if base in {"junk", "junk e-mail", "spam", "lixo"}:
        return ["junk", "junk e-mail", "spam", "lixo"]
    if base in {"trash", "lixeira", "eliminados"}:
        return ["trash", "lixeira", "eliminados"]
    return [base]


def _resolve_folder(available: Iterable[Dict[str, Any]], wanted: str) -> Optional[str]:
    """Descobre o nome real de uma pasta (Sent vs Sent Items vs Enviados…)."""
    alias = _folder_alias(wanted)
    candidatos = [item for item in available if item.get("selectable", True)]
    for item in candidatos:
        if _text(item.get("name")).lower() in alias:
            return item["name"]
    for item in candidatos:
        if item.get("sent") and "sent" in alias:
            return item["name"]
    return None


def _list_folders(conn: Any) -> List[Dict[str, Any]]:
    """Pastas da caixa a partir de uma ligação já aberta."""
    status, data = conn.list()
    if status != "OK":
        return []
    pastas: List[Dict[str, Any]] = []
    for entry in data or []:
        if not isinstance(entry, bytes):
            continue
        pasta = email_service._folder_from_listing(entry.decode("utf-8", "replace"))  # noqa: SLF001
        if pasta:
            pastas.append(pasta)
    return pastas


def folders(account_id: Optional[str] = None) -> Dict[str, Any]:
    """Pastas de uma caixa, com contagens do servidor e do que está indexado."""
    conta = get_account(account_id or PLATFORM_ACCOUNT_ID)
    conn = None
    try:
        conn = email_service._imap_connect(conta)  # noqa: SLF001
        itens = _list_folders(conn)
        for item in itens:
            if not item.get("selectable", True):
                continue
            try:
                status, data = conn.status(email_service._utf7_encode(item["name"]), "(MESSAGES UNSEEN)")  # noqa: SLF001
                if status != "OK" or not data or not data[0]:
                    continue
                texto = data[0].decode("utf-8", "replace") if isinstance(data[0], bytes) else str(data[0])
                mensagens = re.search(r"MESSAGES\s+(\d+)", texto)
                por_ler = re.search(r"UNSEEN\s+(\d+)", texto)
                if mensagens:
                    item["messages"] = int(mensagens.group(1))
                if por_ler:
                    item["unseen"] = int(por_ler.group(1))
                item["inbox"] = _text(item.get("name")).lower() in {"inbox", "caixa de entrada"}
            except Exception:  # noqa: BLE001
                continue
    except MailError:
        raise
    except Exception as exc:  # noqa: BLE001
        raise MailError(f"Não foi possível ler as pastas: {exc}", status=502) from exc
    finally:
        email_service._imap_close(conn)  # noqa: SLF001
    estado = sync_state(conta["id"]).get("folders") or {}
    contagens = _indexed_counts(conta["id"])
    for item in itens:
        item["indexed"] = contagens.get(item["name"], 0)
        item["synced_at"] = (estado.get(item["name"]) or {}).get("synced_at")
    return {
        "account": public_account(conta),
        "items": itens,
        "total": len(itens),
        "sync_folders": conta.get("folders") or DEFAULT_SYNC_FOLDERS,
        "state": estado,
    }


def _indexed_counts(account_id: str) -> Dict[str, int]:
    cliente = _client()
    if cliente is None:
        return {}
    try:
        resposta = cliente.search(
            index=PLATFORM_MAIL_MESSAGES_INDEX,
            body={
                "size": 0,
                "query": {"term": {"account": account_id}},
                "aggs": {"pastas": {"terms": {"field": "folder", "size": 40}}},
            },
        )
        return {
            balde["key"]: balde["doc_count"]
            for balde in resposta.get("aggregations", {}).get("pastas", {}).get("buckets", [])
        }
    except Exception:  # noqa: BLE001
        return {}


# ---------------------------------------------------------------------------
# Mensagens: leitura do servidor
# ---------------------------------------------------------------------------
def _attachment_parts(message: Any) -> List[Tuple[str, str, bytes]]:
    """Anexos de uma mensagem: `(nome, tipo de conteúdo, conteúdo)`.

    Uma só implementação da deteção de anexos — é ela que decide a ordem com que
    aparecem na lista, pelo que o índice da lista é o índice do descarregamento.
    """
    anexos: List[Tuple[str, str, bytes]] = []
    for part in message.walk():
        if part.is_multipart():
            continue
        disposition = (part.get_content_disposition() or "").lower()
        filename = part.get_filename()
        if disposition != "attachment" and not (filename and disposition != "inline"):
            continue
        anexos.append(
            (
                email_service._decode_header(filename) or "anexo",  # noqa: SLF001
                part.get_content_type(),
                part.get_payload(decode=True) or b"",
            )
        )
    return anexos


def _extract_bodies(message: Any) -> Tuple[str, str, List[Dict[str, Any]]]:
    """Corpo em texto, corpo HTML e metadados dos anexos de uma mensagem."""
    textos: List[str] = []
    htmls: List[str] = []
    for part in message.walk():
        if part.is_multipart():
            continue
        disposition = (part.get_content_disposition() or "").lower()
        filename = part.get_filename()
        if disposition == "attachment" or (filename and disposition != "inline"):
            continue
        if part.get_content_maintype() != "text":
            continue
        texto = email_service._decode_payload(part)  # noqa: SLF001
        if part.get_content_subtype() == "html":
            htmls.append(texto)
        else:
            textos.append(texto)
    texto_final = "\n".join(parte for parte in textos if parte.strip()).strip()
    html_final = "\n".join(parte for parte in htmls if parte.strip()).strip()
    if not texto_final and html_final:
        texto_final = email_service._html_to_text(html_final)  # noqa: SLF001
    anexos = [
        {"filename": nome, "content_type": tipo, "size": len(conteudo)}
        for nome, tipo, conteudo in _attachment_parts(message)
    ]
    return texto_final, html_final, anexos


def _direction(account: Dict[str, Any], folder: str, from_email: str) -> str:
    """Entrada ou saída: pela pasta (enviados) ou por quem assina."""
    if _text(folder).lower() in _folder_alias("Sent"):
        return "out"
    if from_email and from_email.lower() == _text(account.get("email_address")).lower():
        return "out"
    return "in"


def _internal_date(meta: bytes) -> Optional[str]:
    """Data de receção segundo o servidor (`INTERNALDATE`), em ISO."""
    achado = re.search(rb'INTERNALDATE "([^"]+)"', meta or b"")
    if not achado:
        return None
    try:
        momento = parsedate_to_datetime(achado.group(1).decode("ascii", "replace"))
        return momento.astimezone(timezone.utc).isoformat()
    except (TypeError, ValueError, IndexError):
        return None


def message_document(
    account: Dict[str, Any],
    folder: str,
    uid: str,
    raw: bytes,
    flags: bytes,
    internal_date: Optional[str] = None,
) -> Dict[str, Any]:
    """Constrói o documento do índice a partir da mensagem crua (RFC 822)."""
    message = message_from_bytes(raw)
    texto, html, anexos = _extract_bodies(message)
    from_name, from_email = _parse_address(message.get("From"))
    message_id = _first_message_id(message.get("Message-ID"))
    in_reply_to = _first_message_id(message.get("In-Reply-To"))
    references = " ".join(achado.lower() for achado in re.findall(r"<[^>]+>", message.get("References") or ""))
    assunto = email_service._decode_header(message.get("Subject"))  # noqa: SLF001
    data = internal_date
    if message.get("Date"):
        try:
            data = parsedate_to_datetime(message.get("Date")).astimezone(timezone.utc).isoformat()
        except (TypeError, ValueError, IndexError):
            pass
    flags_text = flags.decode("ascii", "replace") if isinstance(flags, bytes) else str(flags or "")
    upper = flags_text.upper()
    return {
        "account": account["id"],
        "account_label": account.get("label") or account["id"],
        "mailbox": account.get("email_address") or "",
        "folder": folder,
        "uid": str(uid),
        "message_id": message_id,
        "thread_key": _thread_key(message_id, in_reply_to, references, assunto),
        "in_reply_to": in_reply_to,
        "references": references,
        "subject": assunto or "(sem assunto)",
        "from_name": from_name,
        "from_email": from_email,
        "to": email_service._address_list(message.get("To")),  # noqa: SLF001
        "cc": email_service._address_list(message.get("Cc")),  # noqa: SLF001
        "bcc": email_service._address_list(message.get("Bcc")),  # noqa: SLF001
        "reply_to": email_service._address_list(message.get("Reply-To")),  # noqa: SLF001
        "date": data,
        "internal_date": internal_date,
        "indexed_at": _now(),
        "synced_at": _now(),
        "snippet": email_service._snippet(texto, SNIPPET_LIMIT),  # noqa: SLF001
        "body_text": texto[:BODY_INDEX_LIMIT],
        "body_html": html[:BODY_INDEX_LIMIT] if html else "",
        "size": len(raw),
        "has_attachments": bool(anexos),
        "attachments_count": len(anexos),
        "attachments": anexos,
        "unseen": "\\SEEN" not in upper,
        "flagged": "\\FLAGGED" in upper,
        "answered": "\\ANSWERED" in upper,
        "draft": "\\DRAFT" in upper,
        "flags": [item for item in flags_text.split() if item.startswith("\\")],
        "direction": _direction(account, folder, from_email),
    }


def _fetch_message(conn: Any, uid: str) -> Optional[Tuple[bytes, bytes, Optional[str]]]:
    """(mensagem crua, sinalizadores, data interna) de um UID."""
    status, data = conn.uid("fetch", uid, "(FLAGS INTERNALDATE RFC822)")
    if status != "OK":
        return None
    for entry in data or []:
        if isinstance(entry, tuple) and len(entry) > 1 and isinstance(entry[1], bytes):
            meta = entry[0] if isinstance(entry[0], bytes) else b""
            flags = b""
            achado = re.search(rb"FLAGS \(([^)]*)\)", meta)
            if achado:
                flags = achado.group(1)
            return entry[1], flags, _internal_date(meta)
    return None


def _index_document(documento: Dict[str, Any], *, refresh: bool = False) -> bool:
    cliente = _client()
    if cliente is None:
        return False
    doc_id = _doc_id(documento["account"], documento["folder"], documento["uid"])
    try:
        cliente.index(index=PLATFORM_MAIL_MESSAGES_INDEX, id=doc_id, document=documento, refresh=refresh)
        return True
    except Exception as exc:  # noqa: BLE001
        logger.warning("Não foi possível indexar a mensagem %s: %s", doc_id, exc)
        return False


# ---------------------------------------------------------------------------
# Sincronização
# ---------------------------------------------------------------------------
def sync(account_id: Optional[str] = None, *, full: bool = False) -> Dict[str, Any]:
    """Sincroniza o correio das caixas para o índice.

    Sem `account_id` sincroniza todas as caixas ligadas. `full=True` relê as
    pastas desde o início (até `FULL_SYNC_CAP`) em vez de pedir só o que é novo.
    """
    if not SYNC_LOCK.acquire(blocking=False):
        raise MailError("Já está uma sincronização a decorrer. Tente daqui a pouco.", status=409)
    try:
        contas = [conta for conta in accounts() if conta.get("enabled", True)]
        if account_id:
            contas = [conta for conta in contas if conta["id"] == account_id]
            if not contas:
                raise MailError("Caixa de correio não encontrada ou desligada.", status=404)
        resultado: Dict[str, Any] = {"started_at": _now(), "indexed": 0, "accounts": [], "errors": []}
        for conta in contas:
            entrada = _sync_account(conta, full=full)
            resultado["accounts"].append(entrada)
            resultado["indexed"] += entrada["indexed"]
            if entrada.get("error"):
                resultado["errors"].append(f"{entrada.get('label') or entrada['id']}: {entrada['error']}")
        resultado["finished_at"] = _now()
        return resultado
    finally:
        SYNC_LOCK.release()


def _sync_account(account: Dict[str, Any], *, full: bool = False) -> Dict[str, Any]:
    """Sincroniza as pastas de uma caixa; devolve as contagens por pasta."""
    entrada: Dict[str, Any] = {
        "id": account["id"],
        "label": account.get("label") or account["id"],
        "email_address": account.get("email_address"),
        "folders": [],
        "indexed": 0,
        "error": None,
    }
    estado = sync_state(account["id"])
    pastas_estado: Dict[str, Any] = dict(estado.get("folders") or {})
    conn = None
    try:
        conn = email_service._imap_connect(account)  # noqa: SLF001
        disponiveis = _list_folders(conn)
        for desejada in account.get("folders") or DEFAULT_SYNC_FOLDERS:
            nome = _resolve_folder(disponiveis, desejada)
            if not nome:
                entrada["folders"].append(
                    {"folder": desejada, "indexed": 0, "error": "A pasta não existe nesta caixa."}
                )
                continue
            resultado = _sync_folder(account, conn, nome, pastas_estado, full=full)
            entrada["folders"].append(resultado)
            entrada["indexed"] += resultado.get("indexed", 0)
        _save_sync_state(account["id"], folders=pastas_estado)
    except MailError as exc:
        entrada["error"] = exc.message
        _save_sync_state(account["id"], folders=pastas_estado, error=exc.message)
    except Exception as exc:  # noqa: BLE001
        entrada["error"] = str(exc) or exc.__class__.__name__
        _save_sync_state(account["id"], folders=pastas_estado, error=entrada["error"])
    finally:
        email_service._imap_close(conn)  # noqa: SLF001
    return entrada


def _sync_folder(
    account: Dict[str, Any],
    conn: Any,
    folder: str,
    pastas_estado: Dict[str, Any],
    *,
    full: bool = False,
) -> Dict[str, Any]:
    """Traz as mensagens novas de uma pasta para o índice."""
    resultado: Dict[str, Any] = {"folder": folder, "indexed": 0, "total": None, "last_uid": None, "full": full, "error": None}
    registo = dict(pastas_estado.get(folder) or {})
    ultimo = 0 if full else int(registo.get("last_uid") or 0)
    try:
        resultado["total"] = email_service._select(conn, folder)  # noqa: SLF001
        criterio = "ALL" if (full or not ultimo) else f"UID {ultimo + 1}:*"
        status, data = conn.uid("search", None, criterio)
        if status != "OK":
            raise MailError(f"O servidor não permitiu procurar em «{folder}».", status=502)
        uids = [item.decode("ascii") for item in (data[0] or b"").split() if item]
        if not uids:
            _save_folder_state(pastas_estado, folder, resultado, registo, indexed=0)
            return resultado
        teto = FULL_SYNC_CAP if full else (INITIAL_BATCH if not ultimo else SYNC_BATCH)
        # Sem estado: as mais recentes primeiro (é o que faz falta ao abrir a
        # aplicação). Com estado: da mais antiga para a mais nova, para o marcador
        # `last_uid` avançar sem deixar buracos.
        janela = uids[:teto] if (full or ultimo) else list(reversed(uids))[:teto]
        for uid in janela:
            obtido = _fetch_message(conn, uid)
            if not obtido:
                continue
            if len(obtido[0]) > MAX_MESSAGE_BYTES:
                logger.info("Mensagem %s/%s excede %s bytes: ignorada.", folder, uid, MAX_MESSAGE_BYTES)
                continue
            documento = message_document(account, folder, uid, obtido[0], obtido[1], obtido[2])
            if _index_document(documento):
                resultado["indexed"] += 1
        resultado["last_uid"] = str(max(max(int(uid) for uid in uids), int(registo.get("last_uid") or 0)))
        if full:
            _prune_folder(account["id"], folder, uids)
        _save_folder_state(pastas_estado, folder, resultado, registo, indexed=resultado["indexed"])
    except MailError as exc:
        resultado["error"] = exc.message
        pastas_estado[folder] = {**registo, "folder": folder, "error": exc.message}
    except Exception as exc:  # noqa: BLE001
        resultado["error"] = str(exc) or exc.__class__.__name__
        pastas_estado[folder] = {**registo, "folder": folder, "error": resultado["error"]}
    return resultado


def _save_folder_state(
    pastas_estado: Dict[str, Any],
    folder: str,
    resultado: Dict[str, Any],
    registo: Dict[str, Any],
    *,
    indexed: int,
) -> None:
    """Guarda o ponto onde a pasta ficou (e o que já se indexou)."""
    pastas_estado[folder] = {
        "folder": folder,
        "last_uid": resultado.get("last_uid") or registo.get("last_uid"),
        "total": resultado.get("total"),
        "indexed_total": int(registo.get("indexed_total") or 0) + int(indexed or 0),
        "synced_at": _now(),
        "error": None,
    }


def _prune_folder(account_id: str, folder: str, uids: List[str]) -> None:
    """Tira do índice o que já não existe na pasta (só em sincronização completa)."""
    cliente = _client()
    if cliente is None or not uids or len(uids) > FULL_SYNC_CAP:
        return
    try:
        cliente.delete_by_query(
            index=PLATFORM_MAIL_MESSAGES_INDEX,
            body={
                "query": {
                    "bool": {
                        "filter": [{"term": {"account": account_id}}, {"term": {"folder": folder}}],
                        "must_not": [{"terms": {"uid": uids}}],
                    }
                }
            },
            refresh=True,
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("Não foi possível limpar o índice da pasta %s/%s: %s", account_id, folder, exc)


# ---------------------------------------------------------------------------
# Mensagens: lista e leitura
# ---------------------------------------------------------------------------
def _build_query(params: Dict[str, Any]) -> Dict[str, Any]:
    """Consulta do Elasticsearch a partir dos filtros da aplicação."""
    filtros: List[Dict[str, Any]] = []
    must_not: List[Dict[str, Any]] = []
    for campo, valor in (
        ("account", params.get("account")),
        ("folder", params.get("folder")),
        ("direction", params.get("direction")),
        ("thread_key", params.get("thread")),
        ("from_email", params.get("sender")),
    ):
        if valor:
            filtros.append({"term": {campo: valor}})
    if params.get("unseen") is True:
        filtros.append({"term": {"unseen": True}})
    if params.get("flagged") is True:
        filtros.append({"term": {"flagged": True}})
    if params.get("attachments") is True:
        filtros.append({"term": {"has_attachments": True}})
    if params.get("exclude_drafts"):
        must_not.append({"term": {"draft": True}})
    if params.get("date_from") or params.get("date_to"):
        intervalo: Dict[str, Any] = {}
        if params.get("date_from"):
            intervalo["gte"] = params["date_from"]
        if params.get("date_to"):
            intervalo["lte"] = params["date_to"]
        filtros.append({"range": {"date": intervalo}})
    consulta = _text(params.get("q"))
    if consulta:
        filtros.append(
            {
                # `operator: and` evita que «fatura maio» devolva tudo o que tenha
                # «maio»; é o que se espera de uma caixa de correio.
                "multi_match": {
                    "query": consulta,
                    "fields": ["subject^3", "snippet^2", "body_text", "from_name", "from_email"],
                    "type": "best_fields",
                    "operator": "and",
                }
            }
        )
    return {"bool": {"filter": filtros, "must_not": must_not}}


def _order(params: Dict[str, Any]) -> List[Dict[str, Any]]:
    escolha = _text(params.get("sort")) or "date_desc"
    if escolha == "date_asc":
        return [{"date": {"order": "asc"}}, {"uid": {"order": "asc"}}]
    if escolha == "sender":
        return [{"from_email": {"order": "asc"}}, {"date": {"order": "desc"}}]
    if escolha == "subject":
        return [{"subject.keyword": {"order": "asc"}}, {"date": {"order": "desc"}}]
    if escolha == "size":
        return [{"size": {"order": "desc"}}]
    return [{"date": {"order": "desc"}}, {"uid": {"order": "desc"}}]


def list_messages(params: Dict[str, Any]) -> Dict[str, Any]:
    """Lista as mensagens do arquivo, com as contagens que a interface mostra.

    Sem Elasticsearch cai para o IMAP de uma caixa concreta — mais lento e sem
    pesquisa global, mas a aplicação continua a funcionar.
    """
    limite = max(1, min(int(params.get("limit") or 50), MAX_LIMIT))
    deslocamento = max(0, int(params.get("offset") or 0))
    cliente = _client()
    if cliente is None:
        return _list_messages_via_imap(params, limite, deslocamento)
    corpo = {
        "query": _build_query(params),
        "sort": _order(params),
        "from": deslocamento,
        "size": limite,
        "track_total_hits": True,
        "aggs": {
            "contas": {"terms": {"field": "account", "size": 20}},
            "pastas": {"terms": {"field": "folder", "size": 30}},
            "por_ler": {"filter": {"term": {"unseen": True}}},
            "destacadas": {"filter": {"term": {"flagged": True}}},
            "com_anexos": {"filter": {"term": {"has_attachments": True}}},
            "remetentes": {"terms": {"field": "from_email", "size": 12}},
        },
    }
    try:
        resposta = cliente.search(index=PLATFORM_MAIL_MESSAGES_INDEX, body=corpo)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Pesquisa no correio da plataforma falhou (%s); a usar IMAP.", exc)
        return _list_messages_via_imap(params, limite, deslocamento)
    hits = resposta.get("hits", {})
    total = _total(hits)
    itens = [_summarize(hit) for hit in hits.get("hits", [])]
    aggs = resposta.get("aggregations", {})
    return {
        "source": "elasticsearch",
        "total": total,
        "limit": limite,
        "offset": deslocamento,
        "has_more": deslocamento + len(itens) < total,
        "items": itens,
        "facets": {
            "accounts": _buckets(aggs.get("contas")),
            "folders": _buckets(aggs.get("pastas")),
            "unseen": aggs.get("por_ler", {}).get("doc_count", 0),
            "flagged": aggs.get("destacadas", {}).get("doc_count", 0),
            "with_attachments": aggs.get("com_anexos", {}).get("doc_count", 0),
            "senders": _buckets(aggs.get("remetentes")),
        },
    }


def _total(hits: Dict[str, Any]) -> int:
    total = hits.get("total")
    if isinstance(total, dict):
        return int(total.get("value") or 0)
    return int(total or 0)


def _buckets(agg: Optional[Dict[str, Any]]) -> List[Dict[str, Any]]:
    return [{"key": balde.get("key"), "count": balde.get("doc_count")} for balde in (agg or {}).get("buckets", [])]


def _summarize(hit: Dict[str, Any]) -> Dict[str, Any]:
    origem = hit.get("_source") or {}
    return {
        "id": hit.get("_id"),
        "account": origem.get("account"),
        "account_label": origem.get("account_label"),
        "mailbox": origem.get("mailbox"),
        "folder": origem.get("folder"),
        "uid": origem.get("uid"),
        "subject": origem.get("subject"),
        "from": {"name": origem.get("from_name") or "", "email": origem.get("from_email") or ""},
        "to": origem.get("to") or [],
        "cc": origem.get("cc") or [],
        "date": origem.get("date") or origem.get("internal_date"),
        "snippet": origem.get("snippet") or "",
        "unseen": bool(origem.get("unseen")),
        "flagged": bool(origem.get("flagged")),
        "answered": bool(origem.get("answered")),
        "draft": bool(origem.get("draft")),
        "has_attachments": bool(origem.get("has_attachments")),
        "attachments_count": origem.get("attachments_count") or 0,
        "size": origem.get("size"),
        "thread_key": origem.get("thread_key"),
        "message_id": origem.get("message_id"),
        "direction": origem.get("direction"),
    }


def _list_messages_via_imap(params: Dict[str, Any], limite: int, deslocamento: int) -> Dict[str, Any]:
    """Plano B: lista ao vivo de uma caixa (sem índice)."""
    account_id = _text(params.get("account"))
    if not account_id:
        raise MailError(
            "O Elasticsearch está indisponível: escolha uma caixa de correio para ver as mensagens.",
            status=503,
        )
    conta = get_account(account_id)
    resultado = email_service.list_messages(
        conta,
        folder=_text(params.get("folder")) or "INBOX",
        limit=limite,
        offset=deslocamento,
        query=_text(params.get("q")) or None,
        unread=bool(params.get("unseen")),
        flagged=bool(params.get("flagged")),
    )
    itens = []
    for item in resultado.get("items", []):
        primeiro = (item.get("from") or [{}])[0] if item.get("from") else {}
        itens.append(
            {
                "id": _doc_id(conta["id"], item["folder"], item["uid"]),
                "account": conta["id"],
                "account_label": conta.get("label"),
                "mailbox": conta.get("email_address"),
                "folder": item["folder"],
                "uid": item["uid"],
                "subject": item["subject"],
                "from": {"name": primeiro.get("name", ""), "email": primeiro.get("email", "")},
                "to": item.get("to") or [],
                "cc": item.get("cc") or [],
                "date": item.get("date"),
                "snippet": item.get("preview") or "",
                "unseen": bool(item.get("unread")),
                "flagged": bool(item.get("flagged")),
                "answered": bool(item.get("answered")),
                "draft": False,
                "has_attachments": None,
                "attachments_count": 0,
                "size": item.get("size"),
                "thread_key": None,
                "message_id": item.get("message_id"),
                "direction": _direction(conta, item["folder"], primeiro.get("email", "")),
            }
        )
    return {
        "source": "imap",
        "total": resultado.get("total", len(itens)),
        "limit": limite,
        "offset": deslocamento,
        "has_more": bool(resultado.get("has_more")),
        "items": itens,
        "facets": {"accounts": [], "folders": [], "unseen": None, "flagged": None, "with_attachments": None, "senders": []},
        "account": public_account(conta),
    }


def get_message(doc_id: str, *, mark_read: bool = True) -> Dict[str, Any]:
    """Mensagem completa: corpo, HTML e anexos.

    Lê sempre do IMAP (é a fonte de verdade e traz os anexos); se a caixa não
    responder, devolve a cópia do arquivo e diz que está desatualizada.
    """
    account_id, uid, folder = _parse_doc_id(doc_id)
    conta = get_account(account_id)
    try:
        resultado = email_service.get_message(conta, uid, folder=folder, mark_read=mark_read)
    except MailError as exc:
        arquivada = _archived_message(doc_id)
        if arquivada is None:
            raise
        return {
            "message": arquivada,
            "account": public_account(conta),
            "source": "elasticsearch",
            "stale": True,
            "warning": exc.message,
        }
    if mark_read:
        _update_index(doc_id, {"unseen": False})
    return {"message": resultado["message"], "account": public_account(conta), "source": "imap", "stale": False}


def _archived_message(doc_id: str) -> Optional[Dict[str, Any]]:
    """Mensagem tal como ficou no índice (usada quando o IMAP não responde)."""
    cliente = _client()
    if cliente is None:
        return None
    try:
        if not cliente.exists(index=PLATFORM_MAIL_MESSAGES_INDEX, id=doc_id):
            return None
        origem = cliente.get(index=PLATFORM_MAIL_MESSAGES_INDEX, id=doc_id).get("_source") or {}
    except Exception:  # noqa: BLE001
        return None
    return {
        "uid": origem.get("uid"),
        "folder": origem.get("folder"),
        "subject": origem.get("subject"),
        "from": [{"name": origem.get("from_name") or "", "email": origem.get("from_email") or ""}],
        "to": origem.get("to") or [],
        "cc": origem.get("cc") or [],
        "reply_to": origem.get("reply_to") or [],
        "date": origem.get("date"),
        "message_id": origem.get("message_id"),
        "in_reply_to": origem.get("in_reply_to"),
        "references": origem.get("references"),
        "body_text": origem.get("body_text") or "",
        "body_html": origem.get("body_html") or "",
        "attachments": origem.get("attachments") or [],
        "unread": bool(origem.get("unseen")),
        "flagged": bool(origem.get("flagged")),
        "answered": bool(origem.get("answered")),
        "draft": bool(origem.get("draft")),
    }


def _update_index(doc_id: str, patch: Dict[str, Any]) -> bool:
    cliente = _client()
    if cliente is None:
        return False
    try:
        cliente.update(index=PLATFORM_MAIL_MESSAGES_INDEX, id=doc_id, doc=patch, refresh=True)
        return True
    except Exception as exc:  # noqa: BLE001
        logger.warning("Não foi possível atualizar %s no índice: %s", doc_id, exc)
        return False


def attachment(doc_id: str, index: int) -> Tuple[str, str, bytes]:
    """Conteúdo de um anexo, por ordem de aparecimento na mensagem.

    Os anexos ficam no servidor (o índice só guarda o nome, o tipo e o tamanho),
    por isso o conteúdo é lido da mensagem sempre que é pedido.
    """
    account_id, uid, folder = _parse_doc_id(doc_id)
    conta = get_account(account_id)
    conn = None
    try:
        conn = email_service._imap_connect(conta)  # noqa: SLF001
        status, _ = conn.select(email_service._utf7_encode(folder), readonly=True)  # noqa: SLF001
        if status != "OK":
            raise MailError(f"Não foi possível abrir a pasta «{folder}».", status=404)
        obtido = _fetch_message(conn, uid)
        if not obtido:
            raise MailError("Mensagem não encontrada.", status=404)
        anexos = _attachment_parts(message_from_bytes(obtido[0]))
        if index < 0 or index >= len(anexos):
            raise MailError("Anexo não encontrado.", status=404)
        return anexos[index]
    except MailError:
        raise
    except Exception as exc:  # noqa: BLE001
        raise MailError(f"Não foi possível ler o anexo: {exc}", status=502) from exc
    finally:
        email_service._imap_close(conn)  # noqa: SLF001


def set_flags(doc_id: str, action: str) -> Dict[str, Any]:
    """Marca uma mensagem como lida/não lida ou destacada (IMAP + índice)."""
    account_id, uid, folder = _parse_doc_id(doc_id)
    conta = get_account(account_id)
    resultado = email_service.set_message_flags(conta, uid, folder=folder, action=action)
    patch: Dict[str, Any] = {}
    if action == "read":
        patch["unseen"] = False
    elif action == "unread":
        patch["unseen"] = True
    elif action == "flag":
        patch["flagged"] = True
    elif action == "unflag":
        patch["flagged"] = False
    return {**resultado, "id": doc_id, "indexed": bool(patch) and _update_index(doc_id, patch)}


def move_message(doc_id: str, target: str) -> Dict[str, Any]:
    """Move uma mensagem para outra pasta e reindexa-a no destino."""
    account_id, uid, folder = _parse_doc_id(doc_id)
    conta = get_account(account_id)
    arquivada = _archived_message(doc_id)
    resultado = email_service.move_message(conta, uid, folder=folder, target=target)
    _delete_index_doc(doc_id)
    novo = None
    if arquivada and arquivada.get("message_id"):
        # O UID no destino é outro e o IMAP não o devolve no `COPY`: procura-se
        # pelo Message-ID para a mensagem aparecer já na pasta nova.
        novo = _index_by_message_id(conta, target, arquivada["message_id"])
    return {**resultado, "id": doc_id, "reindexed_as": novo}


def delete_message(doc_id: str) -> Dict[str, Any]:
    """Apaga uma mensagem na caixa e tira-a do índice."""
    account_id, uid, folder = _parse_doc_id(doc_id)
    conta = get_account(account_id)
    resultado = email_service.delete_message(conta, uid, folder=folder)
    return {**resultado, "id": doc_id, "removed_from_index": _delete_index_doc(doc_id)}


def _delete_index_doc(doc_id: str) -> bool:
    cliente = _client()
    if cliente is None:
        return False
    try:
        cliente.delete(index=PLATFORM_MAIL_MESSAGES_INDEX, id=doc_id, refresh=True)
        return True
    except Exception:  # noqa: BLE001
        return False


def _index_by_message_id(account: Dict[str, Any], folder: str, message_id: str) -> Optional[str]:
    """Indexa uma mensagem pelo seu Message-ID (usado depois de mover)."""
    conn = None
    try:
        conn = email_service._imap_connect(account)  # noqa: SLF001
        status, _ = conn.select(email_service._utf7_encode(folder), readonly=True)  # noqa: SLF001
        if status != "OK":
            return None
        status, data = conn.uid("search", None, f'HEADER Message-ID "{message_id}"')
        if status != "OK" or not data or not data[0]:
            return None
        uid = data[0].split()[-1].decode("ascii")
        obtido = _fetch_message(conn, uid)
        if not obtido:
            return None
        documento = message_document(account, folder, uid, obtido[0], obtido[1], obtido[2])
        return _doc_id(account["id"], folder, uid) if _index_document(documento, refresh=True) else None
    except Exception:  # noqa: BLE001
        return None
    finally:
        email_service._imap_close(conn)  # noqa: SLF001


# ---------------------------------------------------------------------------
# Envio
# ---------------------------------------------------------------------------
def send(payload: Dict[str, Any]) -> Dict[str, Any]:
    """Envia uma mensagem por SMTP e arquiva a cópia em *Sent*."""
    conta = get_account(_text(payload.get("account")) or PLATFORM_ACCOUNT_ID)
    destinatarios = _addresses(payload.get("to"))
    if not destinatarios:
        raise MailError("Indique pelo menos um destinatário.")
    cc = _addresses(payload.get("cc"))
    bcc = _addresses(payload.get("bcc"))
    texto = _text(payload.get("body_text") or payload.get("body"))
    html = _text(payload.get("body_html"))
    if not texto and not html:
        raise MailError("Escreva o corpo da mensagem.")

    mensagem = build_message(conta, payload, destinatarios, cc, texto, html)
    conn = None
    try:
        conn = email_service._smtp_connect(conta)  # noqa: SLF001
        conn.send_message(
            mensagem,
            from_addr=conta.get("email_address") or conta.get("username"),
            to_addrs=destinatarios + cc + bcc,
        )
    except MailError:
        raise
    except Exception as exc:  # noqa: BLE001
        raise MailError(f"O envio falhou: {exc}", status=502) from exc
    finally:
        if conn is not None:
            try:
                conn.quit()
            except Exception:  # noqa: BLE001
                pass

    copia = _append_to_sent(conta, mensagem)
    return {
        "sent": True,
        "account": public_account(conta),
        "message_id": mensagem["Message-ID"],
        "subject": mensagem["Subject"],
        "to": destinatarios,
        "cc": cc,
        "bcc": bcc,
        "appended_to_sent": bool(copia.get("uid")),
        "sent_folder": copia.get("folder"),
        "indexed": bool(copia.get("uid")) and _index_sent(conta, copia),
        "warning": copia.get("warning"),
    }


def _addresses(value: Any) -> List[str]:
    """Lista de destinatários a partir de lista ou de texto separado por `,`/`;`."""
    if isinstance(value, list):
        itens = [str(item).strip() for item in value]
    else:
        itens = [parte.strip() for parte in re.split(r"[;,]", str(value or ""))]
    return [item for item in itens if "@" in item]


def build_message(
    account: Dict[str, Any],
    payload: Dict[str, Any],
    destinatarios: List[str],
    cc: List[str],
    texto: str,
    html: str,
) -> EmailMessage:
    """Compõe a mensagem: texto, HTML, assinatura, anexos e encadeamento."""
    mensagem = EmailMessage()
    nome = account.get("display_name") or account.get("label") or ""
    endereco = account.get("email_address") or account.get("username") or ""
    mensagem["From"] = formataddr((nome, endereco))
    mensagem["To"] = ", ".join(destinatarios)
    if cc:
        mensagem["Cc"] = ", ".join(cc)
    mensagem["Subject"] = _text(payload.get("subject")) or "(sem assunto)"
    mensagem["Date"] = formatdate(localtime=True)
    mensagem["Message-ID"] = email_service.make_message_id(endereco)
    if payload.get("in_reply_to"):
        mensagem["In-Reply-To"] = str(payload["in_reply_to"])
    referencias = _text(payload.get("references")) or _text(payload.get("in_reply_to"))
    if referencias:
        mensagem["References"] = referencias

    assinatura = _text(account.get("signature"))
    if payload.get("include_signature", True):
        if assinatura and "<" in assinatura and ">" in assinatura:
            # Assinatura com marcação: entra tal e qual no HTML, e em texto
            # simples no corpo alternativo (quem lê em texto não perde o que lá
            # está escrito nem vê as etiquetas).
            html_assinatura = assinatura
            texto_assinatura = email_service._html_to_text(assinatura)  # noqa: SLF001
        elif assinatura:
            html_assinatura = f'<pre style="font-family:inherit">{assinatura}</pre>'
            texto_assinatura = assinatura
        else:
            # Sem assinatura própria, a caixa usa a **assinatura de marca** da
            # plataforma (logótipo, marca e ligação), a mesma dos emails
            # transacionais.
            html_assinatura = email_signature.html_block()
            texto_assinatura = email_signature.text_block()
        texto = f"{texto.rstrip()}\n\n{texto_assinatura}"
        if html:
            html = f"{html}<br>{html_assinatura}"

    if html:
        mensagem.set_content(texto or email_service._html_to_text(html))  # noqa: SLF001
        mensagem.add_alternative(html, subtype="html")
    else:
        mensagem.set_content(texto)

    for item in payload.get("attachments") or []:
        if not isinstance(item, dict):
            continue
        nome_anexo, conteudo, content_type = email_service._attachment_payload(item)  # noqa: SLF001
        maintype, _, subtype = content_type.partition("/")
        mensagem.add_attachment(
            conteudo,
            maintype=maintype or "application",
            subtype=subtype or "octet-stream",
            filename=nome_anexo,
        )
    return mensagem


def _append_to_sent(account: Dict[str, Any], mensagem: EmailMessage) -> Dict[str, Any]:
    """Arquiva a cópia enviada na pasta *Sent* (o passo que o Outlook faz)."""
    conn = None
    try:
        conn = email_service._imap_connect(account)  # noqa: SLF001
        destino = _resolve_folder(_list_folders(conn), "Sent")
        if not destino:
            return {"uid": None, "folder": None, "warning": "A caixa não tem pasta «Sent»: a cópia não ficou arquivada."}
        status, _ = conn.append(email_service._utf7_encode(destino), "(\\Seen)", None, mensagem.as_bytes())  # noqa: SLF001
        if status != "OK":
            return {"uid": None, "folder": destino, "warning": "O servidor recusou arquivar a cópia enviada."}
        return {"uid": _last_uid(conn, destino), "folder": destino, "warning": None}
    except Exception as exc:  # noqa: BLE001
        return {"uid": None, "folder": None, "warning": f"A cópia enviada não foi arquivada: {exc}"}
    finally:
        email_service._imap_close(conn)  # noqa: SLF001


def _last_uid(conn: Any, folder: str) -> Optional[str]:
    try:
        status, _ = conn.select(email_service._utf7_encode(folder), readonly=True)  # noqa: SLF001
        if status != "OK":
            return None
        status, data = conn.uid("search", None, "ALL")
        if status != "OK" or not data or not data[0]:
            return None
        return data[0].split()[-1].decode("ascii")
    except Exception:  # noqa: BLE001
        return None


def _index_sent(account: Dict[str, Any], copia: Dict[str, Any]) -> bool:
    """Põe a mensagem enviada no índice (aparece sem esperar pela sincronização)."""
    conn = None
    try:
        conn = email_service._imap_connect(account)  # noqa: SLF001
        status, _ = conn.select(email_service._utf7_encode(copia["folder"]), readonly=True)  # noqa: SLF001
        if status != "OK":
            return False
        obtido = _fetch_message(conn, copia["uid"])
        if not obtido:
            return False
        documento = message_document(account, copia["folder"], copia["uid"], obtido[0], obtido[1], obtido[2])
        return _index_document(documento, refresh=True)
    except Exception:  # noqa: BLE001
        return False
    finally:
        email_service._imap_close(conn)  # noqa: SLF001


# ---------------------------------------------------------------------------
# Panorama e descoberta
# ---------------------------------------------------------------------------
def stats() -> Dict[str, Any]:
    """Panorama do correio da plataforma: índice, contagens e estado por caixa."""
    cliente = _client()
    contas = accounts()
    estados = _sync_states()
    panorama: Dict[str, Any] = {
        "es_available": cliente is not None,
        "accounts": len(contas),
        "enabled_accounts": len([conta for conta in contas if conta.get("enabled", True)]),
        "settings": settings(),
        "mailboxes": [
            {
                "id": conta["id"],
                "label": conta.get("label"),
                "email_address": conta.get("email_address"),
                "source": conta.get("source"),
                "enabled": bool(conta.get("enabled", True)),
                "folders": conta.get("folders") or DEFAULT_SYNC_FOLDERS,
                "last_sync_at": (estados.get(conta["id"]) or {}).get("last_sync_at") or conta.get("last_sync_at"),
                "last_error": (estados.get(conta["id"]) or {}).get("last_error"),
            }
            for conta in contas
        ],
        "index": {"name": PLATFORM_MAIL_MESSAGES_INDEX, "documents": 0, "size": "—"},
        "totals": {"messages": 0, "unseen": 0, "flagged": 0, "with_attachments": 0, "threads": 0},
        "folders": [],
        "senders": [],
        "daily": [],
        "latest": None,
    }
    if cliente is None:
        return panorama
    try:
        if cliente.indices.exists(index=PLATFORM_MAIL_MESSAGES_INDEX):
            panorama["index"]["documents"] = int(cliente.count(index=PLATFORM_MAIL_MESSAGES_INDEX).get("count", 0))
            detalhes = cliente.indices.stats(index=PLATFORM_MAIL_MESSAGES_INDEX, metric="store")
            bytes_ = detalhes.get("_all", {}).get("total", {}).get("store", {}).get("size_in_bytes")
            if isinstance(bytes_, (int, float)):
                panorama["index"]["size"] = f"{bytes_ / (1024 * 1024):.1f} MB"
        resposta = cliente.search(
            index=PLATFORM_MAIL_MESSAGES_INDEX,
            body={
                "size": 1,
                "sort": [{"date": {"order": "desc"}}],
                "track_total_hits": True,
                "aggs": {
                    "pastas": {"terms": {"field": "folder", "size": 30}},
                    "remetentes": {"terms": {"field": "from_email", "size": 12}},
                    "por_ler": {"filter": {"term": {"unseen": True}}},
                    "destacadas": {"filter": {"term": {"flagged": True}}},
                    "com_anexos": {"filter": {"term": {"has_attachments": True}}},
                    "fios": {"cardinality": {"field": "thread_key"}},
                    "dias": {"date_histogram": {"field": "date", "calendar_interval": "day", "min_doc_count": 1}},
                },
            },
        )
        hits = resposta.get("hits", {})
        aggs = resposta.get("aggregations", {})
        panorama["totals"] = {
            "messages": _total(hits),
            "unseen": aggs.get("por_ler", {}).get("doc_count", 0),
            "flagged": aggs.get("destacadas", {}).get("doc_count", 0),
            "with_attachments": aggs.get("com_anexos", {}).get("doc_count", 0),
            "threads": aggs.get("fios", {}).get("value", 0),
        }
        panorama["folders"] = _buckets(aggs.get("pastas"))
        panorama["senders"] = _buckets(aggs.get("remetentes"))
        panorama["daily"] = [
            {"date": balde.get("key_as_string"), "count": balde.get("doc_count")}
            for balde in aggs.get("dias", {}).get("buckets", [])[-30:]
        ]
        achados = hits.get("hits", [])
        panorama["latest"] = _summarize(achados[0]) if achados else None
    except Exception as exc:  # noqa: BLE001
        panorama["error"] = str(exc)
    return panorama


def meta() -> Dict[str, Any]:
    """O que a aplicação precisa para se desenhar: servidores, pastas e limites."""
    defaults = _imap_defaults()
    cliente = _client()
    documentos = 0
    if cliente is not None:
        try:
            if cliente.indices.exists(index=PLATFORM_MAIL_MESSAGES_INDEX):
                documentos = int(cliente.count(index=PLATFORM_MAIL_MESSAGES_INDEX).get("count", 0))
        except Exception:  # noqa: BLE001
            documentos = 0
    return {
        "defaults": {
            "imap_host": defaults["host"],
            "imap_port": defaults["port"],
            "imap_security": defaults["security"],
            "smtp_host": defaults["smtp"].get("host"),
            "smtp_port": defaults["smtp"].get("port"),
            "smtp_security": defaults["smtp"].get("security"),
            "sync_folders": DEFAULT_SYNC_FOLDERS,
        },
        "platform_account_configured": _platform_account() is not None,
        "accounts": len(accounts()),
        # A assinatura de marca vem daqui para a aplicação mostrar, ao compor, o
        # que vai mesmo sair: quem a junta ao corpo é o servidor (uma só cópia,
        # ver `api/email_signature.py`), e a caixa pode ter a sua.
        "signature": {"text": email_signature.text_block(), "html": email_signature.html_block()},
        "es": {"available": cliente is not None, "index": PLATFORM_MAIL_MESSAGES_INDEX, "documents": documentos},
        "limits": {
            "initial_batch": INITIAL_BATCH,
            "sync_batch": SYNC_BATCH,
            "full_sync_cap": FULL_SYNC_CAP,
            "max_limit": MAX_LIMIT,
            "max_message_bytes": MAX_MESSAGE_BYTES,
        },
        "settings": settings(),
        "help": [
            "As caixas vivem no servidor de correio da plataforma (Docker Mailserver).",
            "Uma caixa nova cria-se no servidor (deploy/kamatera → mailserver) e liga-se aqui.",
            "A sincronização só lê: pastas, sinalizadores, envio e movimentos passam pelo IMAP/SMTP.",
        ],
    }
