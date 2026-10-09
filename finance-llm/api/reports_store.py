"""Relatórios a pedido — catálogo, pedidos, pagamentos (MB Way) e entrega.

A plataforma vende **relatórios** (corporativos, financeiros e de concorrência)
que são **produzidos à mão pela equipa de backoffice**: o cliente pede, paga
(por MB Way para o número configurado na administração) e, quando o relatório
fica pronto, o ficheiro é anexado ao pedido e fica disponível para descarregar
na área «Relatórios» com o estado **Gerado**.

Tudo vive num único documento JSON (`data/reports/reports.json`) com escrita
atómica — o ficheiro é a fonte de verdade e pode ser versionado, exatamente como
o CMS e a loja. Os ficheiros gerados ficam em `data/reports/files/<pedido>/`.

Ciclo de vida de um pedido (`status`):

    aguarda_pagamento → pagamento_confirmado → em_producao → gerado → entregue
    (a qualquer momento) cancelado | reembolsado

Os pedidos de valor zero (relatório corporativo, grátis) saltam o pagamento e
entram diretamente em `em_producao`.

O **pagamento** é um documento dentro do pedido (`payment`):

    method: mbway | transferencia | referencia | manual
    status: pendente | aguarda_confirmacao | confirmado | rejeitado | reembolsado

Quando existe uma chave de API do MB Way (`settings.mbway_api_key`, IFTThenPay)
é criado um **pedido de pagamento** para o telemóvel do cliente e o estado do
pagamento é confirmado automaticamente (ou por consulta do estado). Sem chave, o
cliente transfere para o número configurado e carrega em «Já paguei»: o pedido
fica `aguarda_confirmacao` e alguém do backoffice confirma.
"""
from __future__ import annotations

import base64
import copy
import json
import logging
import re
import threading
import time
import unicodedata
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

logger = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parents[1]
REPORTS_DIR = ROOT / "data" / "reports"
REPORTS_PATH = REPORTS_DIR / "reports.json"
FILES_DIR = REPORTS_DIR / "files"
REPORTS_VERSION = 1

REPORT_STATUSES: Tuple[str, ...] = (
    "aguarda_pagamento",
    "pagamento_confirmado",
    "em_producao",
    "gerado",
    "entregue",
    "cancelado",
    "reembolsado",
)
REPORT_LABELS: Dict[str, str] = {
    "aguarda_pagamento": "Aguarda pagamento",
    "pagamento_confirmado": "Pagamento confirmado",
    "em_producao": "Em produção",
    "gerado": "Gerado",
    "entregue": "Entregue",
    "cancelado": "Cancelado",
    "reembolsado": "Reembolsado",
}
REPORT_STYLE: Dict[str, str] = {
    "aguarda_pagamento": "amber",
    "pagamento_confirmado": "sky",
    "em_producao": "violet",
    "gerado": "emerald",
    "entregue": "teal",
    "cancelado": "rose",
    "reembolsado": "zinc",
}
REPORT_HINTS: Dict[str, str] = {
    "aguarda_pagamento": "Falta o pagamento para a equipa começar o relatório.",
    "pagamento_confirmado": "Pagamento recebido; o relatório entra na fila de produção.",
    "em_producao": "A equipa está a produzir o relatório.",
    "gerado": "O relatório está pronto para descarregar.",
    "entregue": "O relatório foi descarregado/entregue ao cliente.",
    "cancelado": "Pedido cancelado.",
    "reembolsado": "Pedido reembolsado.",
}
# Estados seguintes sugeridos em cada passo (o backoffice pode saltar passos).
REPORT_FLOW: Dict[str, List[str]] = {
    "aguarda_pagamento": ["pagamento_confirmado", "em_producao", "cancelado"],
    "pagamento_confirmado": ["em_producao", "cancelado", "reembolsado"],
    "em_producao": ["gerado", "cancelado", "reembolsado"],
    "gerado": ["entregue", "reembolsado"],
    "entregue": ["reembolsado"],
    "cancelado": [],
    "reembolsado": [],
}
# Passos mostrados ao cliente (progresso do pedido).
REPORT_FLOW_STEPS: Tuple[str, ...] = (
    "aguarda_pagamento",
    "pagamento_confirmado",
    "em_producao",
    "gerado",
    "entregue",
)

PAYMENT_STATUSES: Tuple[str, ...] = (
    "pendente",
    "aguarda_confirmacao",
    "confirmado",
    "rejeitado",
    "reembolsado",
)
PAYMENT_LABELS: Dict[str, str] = {
    "pendente": "Pendente",
    "aguarda_confirmacao": "Aguarda confirmação",
    "confirmado": "Confirmado",
    "rejeitado": "Rejeitado",
    "reembolsado": "Reembolsado",
}
PAYMENT_STYLE: Dict[str, str] = {
    "pendente": "amber",
    "aguarda_confirmacao": "sky",
    "confirmado": "emerald",
    "rejeitado": "rose",
    "reembolsado": "zinc",
}

PAYMENT_METHODS: List[Dict[str, str]] = [
    {"id": "mbway", "label": "MB Way", "hint": "Transferência imediata pelo telemóvel"},
    {"id": "transferencia", "label": "Transferência bancária", "hint": "IBAN enviado com o pedido"},
    {"id": "referencia", "label": "Referência Multibanco", "hint": "Pedida ao backoffice"},
    {"id": "manual", "label": "Outro (combinado)", "hint": "Registado à mão pelo backoffice"},
]

MAX_TARGETS = 6
MAX_NOTES = 2000
MAX_FILES_PER_REQUEST = 12
MAX_FILE_BYTES = 25 * 1024 * 1024
MAX_NOTIFICATIONS = 800
MAX_ACTIVITY = 600

SAFE_FILENAME_RE = re.compile(r"[^A-Za-z0-9._-]+")
PT_PHONE_RE = re.compile(r"^(?:351)?(9[1236]\d{7})$")

ALLOWED_FILE_SUFFIXES: Tuple[str, ...] = (
    ".pdf", ".doc", ".docx", ".xls", ".xlsx", ".csv", ".txt", ".md", ".json", ".zip", ".png", ".jpg", ".jpeg",
)

# --------------------------------------------------------------------------
# Catálogo por omissão (os pacotes anunciados na plataforma)
# --------------------------------------------------------------------------
DEFAULT_CATALOGUE: List[Dict[str, Any]] = [
    {
        "id": "corporativo",
        "code": "CORP",
        "title": "Relatório Corporativo",
        "subtitle": "Dados estruturais da empresa",
        "note": "Informação atualizada diariamente",
        "price": 0.0,
        "list_price": 7.0,
        "badge": "",
        "max_targets": 1,
        "delivery_days": 1,
        "active": True,
        "features": [
            "Eventos",
            "Marcas",
            "Ações em Tribunal e Insolvência",
            "Estado de Atividade",
            "Dívida Fiscal",
            "Subsidiárias e Participações",
            "Empresas Relacionadas",
            "Contratos Públicos",
        ],
    },
    {
        "id": "financeiro-resumido",
        "code": "FIN-R",
        "title": "Relatório Financeiro Resumido",
        "subtitle": "Saúde Financeira",
        "note": "Informações dos últimos 3 anos *",
        "price": 18.0,
        "list_price": 0.0,
        "badge": "",
        "max_targets": 1,
        "delivery_days": 2,
        "active": True,
        "features": [
            "Dados estruturais da empresa",
            "Saúde Financeira (Indicadores)",
            "Volume de Vendas / Faturação",
            "Lucros Resultados",
            "Custos",
            "Volume Importações / Exportações",
            "Nº Colaboradores",
            "Remunerações do Pessoal",
        ],
    },
    {
        "id": "financeiro-detalhado",
        "code": "FIN-D",
        "title": "Relatório Financeiro Detalhado",
        "subtitle": "Informações Contabilísticas",
        "note": "Informações dos últimos 3 anos *",
        "price": 24.0,
        "list_price": 0.0,
        "badge": "RECOMENDADO",
        "max_targets": 1,
        "delivery_days": 2,
        "active": True,
        "features": [
            "Relatório Corporativo e Relatório Financeiro Resumido",
            "Demonstração de Resultados",
            "Balanço",
            "Anexo ao Balanço",
            "Fluxos de Caixa",
            "Rácios de Gestão",
            "Informação por Estabelecimento",
        ],
    },
    {
        "id": "concorrencia",
        "code": "CONC",
        "title": "Relatório Concorrência",
        "subtitle": "Compare até 6 empresas",
        "note": "Evolução dos 3 últimos anos p/ empresa",
        "price": 130.0,
        "list_price": 0.0,
        "badge": "",
        "max_targets": 6,
        "delivery_days": 5,
        "active": True,
        "features": [
            "Todos os relatórios anteriores",
            "Informação do balanço últimos 3 anos",
            "Rating Rácius",
            "Setores de Atividade",
            "Quota do Mercado",
            "Receitas/Despesas/Lucros ou Prejuízos",
            "Volume Importações/Exportações",
            "Nº Colaboradores e seus Gastos",
            "Cerca de 50 Rácios em Comparação",
        ],
    },
]

DEFAULT_SETTINGS: Dict[str, Any] = {
    # Número MB Way de destino (configurável pela administração).
    "mbway_number": "919520386",
    "mbway_holder": "",
    "mbway_enabled": True,
    # Integração automática (IFTThenPay). Sem chave, o pagamento é confirmado à mão.
    "mbway_provider": "ifthenpay",
    "mbway_api_key": "",
    "mbway_api_url": "https://mbway.ifthenpay.com/ifthenpaymbw.ashx",
    "iban": "",
    "payment_instructions": (
        "Faça a transferência MB Way para o número indicado e, no MB Way, escreva a "
        "referência do pedido nas observações. Depois carregue em «Já paguei»."
    ),
    "vat_rate": 23.0,
    "default_delivery_days": 2,
    "auto_confirm_mbway_api": True,
    # Contas com acesso ao backoffice de relatórios (além dos administradores).
    "backoffice_users": [],
    # Emails extra avisados de cada pedido novo.
    "notify_extra_emails": [],
    "updated_at": "",
    "updated_by": "",
}

_lock = threading.RLock()
_cache: Optional[Dict[str, Any]] = None
_cache_mtime: Optional[int] = None


# --------------------------------------------------------------------------
# Utilitários
# --------------------------------------------------------------------------
def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _new_id(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:10]}"


def _text(value: Any, limit: int = 0) -> str:
    result = str(value or "").strip()
    if limit and len(result) > limit:
        result = result[:limit].rstrip()
    return result


def money(value: Any) -> float:
    try:
        amount = float(str(value).replace("€", "").replace(" ", "").replace(",", "."))
    except (TypeError, ValueError):
        return 0.0
    return round(amount + 1e-9, 2)


def _bool(value: Any, default: bool = False) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "true", "sim", "yes", "on", "ativo"}


def _email(value: Any) -> str:
    return _text(value, 254).lower()


def normalise_phone(value: Any) -> str:
    """Devolve o telemóvel no formato `9XXXXXXXX` (ou string vazia)."""
    digits = re.sub(r"\D+", "", str(value or ""))
    if digits.startswith("00"):
        digits = digits[2:]
    match = PT_PHONE_RE.match(digits)
    if match:
        return match.group(1)
    return ""


def safe_filename(name: str, fallback: str = "relatorio") -> str:
    base = Path(_text(name) or fallback).name
    cleaned = SAFE_FILENAME_RE.sub("_", base).strip("._")
    return cleaned[:120] or fallback


def slug(value: Any, fallback: str = "relatorio") -> str:
    text = unicodedata.normalize("NFKD", str(value or ""))
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    text = re.sub(r"[^a-zA-Z0-9]+", "-", text).strip("-").lower()
    return text or fallback


def _type_label(value: str) -> str:
    return REPORT_LABELS.get(value, value or "—")


# --------------------------------------------------------------------------
# Persistência
# --------------------------------------------------------------------------
def _empty_store() -> Dict[str, Any]:
    return {
        "version": REPORTS_VERSION,
        "settings": copy.deepcopy(DEFAULT_SETTINGS),
        "catalogue": copy.deepcopy(DEFAULT_CATALOGUE),
        "requests": [],
        "notifications": [],
        "activity": [],
        "updated_at": _now(),
    }


def _read_store() -> Dict[str, Any]:
    if not REPORTS_PATH.exists():
        return _empty_store()
    try:
        raw = json.loads(REPORTS_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        logger.warning("Ficheiro de relatórios ilegível (%s); a recomeçar.", exc)
        return _empty_store()
    if not isinstance(raw, dict):
        return _empty_store()
    store = _empty_store()
    for entity in ("requests", "notifications", "activity"):
        value = raw.get(entity)
        if isinstance(value, list):
            store[entity] = [item for item in value if isinstance(item, dict)]
    settings = raw.get("settings")
    if isinstance(settings, dict):
        store["settings"].update({key: value for key, value in settings.items() if value is not None})
    catalogue = raw.get("catalogue")
    if isinstance(catalogue, list) and catalogue:
        store["catalogue"] = [item for item in catalogue if isinstance(item, dict)]
    return store


def _write_store(store: Dict[str, Any]) -> None:
    global _cache, _cache_mtime
    store["version"] = REPORTS_VERSION
    store["updated_at"] = _now()
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(store, ensure_ascii=False, indent=2, default=str)
    tmp = REPORTS_PATH.with_suffix(".json.tmp")
    tmp.write_text(payload, encoding="utf-8")
    # No Windows o antivírus/indexador pode segurar o ficheiro recém-criado.
    last: Optional[OSError] = None
    for attempt in range(5):
        try:
            tmp.replace(REPORTS_PATH)
            break
        except PermissionError as exc:  # pragma: no cover - depende do sistema
            last = exc
            time.sleep(0.08 * (attempt + 1))
    else:  # pragma: no cover - depende do sistema
        raise last if last else OSError(f"Não foi possível gravar {REPORTS_PATH}.")
    _cache = store
    _cache_mtime = _file_mtime()


def _file_mtime() -> Optional[int]:
    try:
        return REPORTS_PATH.stat().st_mtime_ns
    except OSError:
        return None


def load() -> Dict[str, Any]:
    """Documento de relatórios (recarrega se o ficheiro mudou fora do processo)."""
    global _cache, _cache_mtime
    stamp = _file_mtime()
    if _cache is not None and stamp != _cache_mtime:
        _cache = None
    if _cache is None:
        _cache = _read_store()
        if not REPORTS_PATH.exists():
            _write_store(_cache)
        else:
            _cache_mtime = _file_mtime()
    return _cache


def _log(store: Dict[str, Any], action: str, *, request: Optional[Dict[str, Any]] = None, actor: str = "", detail: str = "") -> None:
    store["activity"].insert(
        0,
        {
            "id": _new_id("act"),
            "action": action,
            "entity": "requests",
            "entity_id": (request or {}).get("id", ""),
            "reference": (request or {}).get("reference", ""),
            "actor": actor,
            "detail": detail[:400],
            "at": _now(),
        },
    )
    del store["activity"][MAX_ACTIVITY:]


# --------------------------------------------------------------------------
# Configuração e catálogo
# --------------------------------------------------------------------------
def settings() -> Dict[str, Any]:
    return copy.deepcopy(load()["settings"])


def public_settings() -> Dict[str, Any]:
    """Só o que o cliente pode ver (nunca a chave de API)."""
    data = load()["settings"]
    return {
        "mbway_number": data.get("mbway_number", ""),
        "mbway_holder": data.get("mbway_holder", ""),
        "mbway_enabled": _bool(data.get("mbway_enabled"), True),
        "mbway_api": bool(_text(data.get("mbway_api_key"))),
        "iban": data.get("iban", ""),
        "payment_instructions": data.get("payment_instructions", ""),
        "vat_rate": money(data.get("vat_rate")) or 0.0,
        "methods": PAYMENT_METHODS,
    }


def save_settings(patch: Dict[str, Any], actor: str = "") -> Dict[str, Any]:
    with _lock:
        store = load()
        data = store["settings"]
        if "mbway_number" in patch:
            raw = _text(patch.get("mbway_number"))
            phone = normalise_phone(raw) if raw else ""
            if raw and not phone:
                raise ValueError("O número MB Way tem de ser um telemóvel português (9 dígitos).")
            data["mbway_number"] = phone or raw
        for key in ("mbway_holder", "iban", "payment_instructions", "mbway_api_url"):
            if key in patch:
                data[key] = _text(patch.get(key), 400)
        if "mbway_provider" in patch:
            provider = _text(patch.get("mbway_provider"), 40).lower() or "ifthenpay"
            if provider not in {"ifthenpay", "manual"}:
                raise ValueError("Fornecedor MB Way inválido.")
            data["mbway_provider"] = provider
        if "mbway_api_key" in patch:
            data["mbway_api_key"] = _text(patch.get("mbway_api_key"), 200)
        for key in ("mbway_enabled", "auto_confirm_mbway_api"):
            if key in patch:
                data[key] = _bool(patch.get(key), False)
        for key in ("vat_rate", "default_delivery_days"):
            if key in patch:
                try:
                    data[key] = money(patch.get(key))
                except (TypeError, ValueError):
                    pass
        if "backoffice_users" in patch:
            data["backoffice_users"] = _emails(patch.get("backoffice_users"))
        if "notify_extra_emails" in patch:
            data["notify_extra_emails"] = _emails(patch.get("notify_extra_emails"))
        data["updated_at"] = _now()
        data["updated_by"] = actor
        _log(store, "settings.saved", actor=actor, detail="Configuração de relatórios atualizada")
        _write_store(store)
    return settings()


def _emails(value: Any) -> List[str]:
    if isinstance(value, str):
        items: Sequence[Any] = re.split(r"[,\s;]+", value)
    elif isinstance(value, (list, tuple, set)):
        items = list(value)
    else:
        items = []
    seen: List[str] = []
    for item in items:
        email = _email(item)
        if email and "@" in email and email not in seen:
            seen.append(email)
    return seen


def catalogue(only_active: bool = False) -> List[Dict[str, Any]]:
    items = [copy.deepcopy(item) for item in load()["catalogue"]]
    if only_active:
        items = [item for item in items if _bool(item.get("active"), True)]
    items.sort(key=lambda item: (money(item.get("price")), item.get("title", "")))
    return items


def package(package_id: str) -> Optional[Dict[str, Any]]:
    key = _text(package_id).lower()
    for item in load()["catalogue"]:
        if str(item.get("id", "")).lower() == key or str(item.get("code", "")).lower() == key:
            return copy.deepcopy(item)
    return None


def save_package(payload: Dict[str, Any], actor: str = "") -> Dict[str, Any]:
    with _lock:
        store = load()
        items = store["catalogue"]
        package_id = _text(payload.get("id")).lower()
        existing = next((item for item in items if str(item.get("id", "")).lower() == package_id), None)
        if existing is None:
            package_id = slug(payload.get("id") or payload.get("title"), "pacote")
            existing = next((item for item in items if str(item.get("id")) == package_id), None)
        if existing is None:
            if len(items) >= 40:
                raise ValueError("Demasiados pacotes no catálogo.")
            existing = {
                "id": package_id,
                "code": _text(payload.get("code") or package_id[:6]).upper(),
                "title": "",
                "subtitle": "",
                "note": "",
                "price": 0.0,
                "list_price": 0.0,
                "badge": "",
                "max_targets": 1,
                "delivery_days": money(load()["settings"].get("default_delivery_days")) or 2,
                "active": True,
                "features": [],
            }
            items.append(existing)
        for key, limit in (("title", 120), ("subtitle", 160), ("note", 200), ("badge", 24), ("code", 12)):
            if key in payload:
                existing[key] = _text(payload.get(key), limit)
        if not _text(existing.get("title")):
            raise ValueError("O pacote precisa de um título.")
        if "price" in payload:
            existing["price"] = money(payload.get("price"))
        if "list_price" in payload:
            existing["list_price"] = money(payload.get("list_price"))
        if "delivery_days" in payload:
            try:
                existing["delivery_days"] = max(0, int(float(payload.get("delivery_days") or 0)))
            except (TypeError, ValueError):
                pass
        if "max_targets" in payload:
            try:
                existing["max_targets"] = min(MAX_TARGETS, max(1, int(float(payload.get("max_targets") or 1))))
            except (TypeError, ValueError):
                pass
        if "active" in payload:
            existing["active"] = _bool(payload.get("active"), True)
        if "features" in payload:
            raw = payload.get("features")
            if isinstance(raw, str):
                raw = [line.strip() for line in raw.splitlines()]
            features = [_text(item, 200) for item in (raw or []) if _text(item, 200)]
            existing["features"] = features[:30]
        _log(store, "catalogue.saved", actor=actor, detail=f"Pacote «{existing.get('title')}» atualizado")
        _write_store(store)
    return copy.deepcopy(existing)


def delete_package(package_id: str, actor: str = "") -> bool:
    with _lock:
        store = load()
        before = len(store["catalogue"])
        store["catalogue"] = [item for item in store["catalogue"] if str(item.get("id")) != str(package_id)]
        if len(store["catalogue"]) == before:
            return False
        _log(store, "catalogue.deleted", actor=actor, detail=f"Pacote {package_id} removido")
        _write_store(store)
    return True


# --------------------------------------------------------------------------
# Acessos
# --------------------------------------------------------------------------
def backoffice_users() -> List[str]:
    return list(load()["settings"].get("backoffice_users") or [])


def is_backoffice(email: str, role: str = "member") -> bool:
    if (role or "member") == "admin":
        return True
    return _email(email) in backoffice_users()


def backoffice_recipients(extra_admins: Sequence[str] = ()) -> List[str]:
    """Emails que devem ser avisados de pedidos novos (sem duplicados)."""
    emails = list(backoffice_users())
    for item in load()["settings"].get("notify_extra_emails") or []:
        email = _email(item)
        if email and email not in emails:
            emails.append(email)
    for item in extra_admins:
        email = _email(item)
        if email and email not in emails:
            emails.append(email)
    return emails


# --------------------------------------------------------------------------
# Notificações
# --------------------------------------------------------------------------
def notify(store: Dict[str, Any], emails: Sequence[str], title: str, body: str, *, kind: str = "sistema", request: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
    created: List[Dict[str, Any]] = []
    for email in emails:
        target = _email(email)
        if not target:
            continue
        item = {
            "id": _new_id("ntf"),
            "user_email": target,
            "title": _text(title, 160),
            "body": _text(body, 600),
            "kind": kind,
            "request_id": (request or {}).get("id", ""),
            "request_reference": (request or {}).get("reference", ""),
            "read": False,
            "created_at": _now(),
        }
        store["notifications"].insert(0, item)
        created.append(item)
    del store["notifications"][MAX_NOTIFICATIONS:]
    return created


def notifications_for(email: str, limit: int = 40) -> List[Dict[str, Any]]:
    target = _email(email)
    items = [item for item in load()["notifications"] if _email(item.get("user_email")) == target]
    return [copy.deepcopy(item) for item in items[: max(1, limit)]]


def unread_count(email: str) -> int:
    target = _email(email)
    return sum(1 for item in load()["notifications"] if _email(item.get("user_email")) == target and not item.get("read"))


def mark_read(email: str, ids: Optional[Sequence[str]] = None) -> int:
    target = _email(email)
    with _lock:
        store = load()
        wanted = {str(item) for item in (ids or [])}
        changed = 0
        for item in store["notifications"]:
            if _email(item.get("user_email")) != target or item.get("read"):
                continue
            if wanted and str(item.get("id")) not in wanted:
                continue
            item["read"] = True
            item["read_at"] = _now()
            changed += 1
        if changed:
            _write_store(store)
    return changed


# --------------------------------------------------------------------------
# Pedidos
# --------------------------------------------------------------------------
def _next_reference(store: Dict[str, Any]) -> str:
    year = datetime.now(timezone.utc).year
    prefix = f"REL-{year}-"
    highest = 0
    for item in store["requests"]:
        ref = str(item.get("reference", ""))
        if ref.startswith(prefix):
            try:
                highest = max(highest, int(ref[len(prefix) :]))
            except ValueError:
                continue
    return f"{prefix}{highest + 1:04d}"


def _normalise_targets(raw: Any, limit: int) -> List[Dict[str, str]]:
    items: Sequence[Any]
    if isinstance(raw, str):
        items = [line.strip() for line in raw.splitlines() if line.strip()]
    elif isinstance(raw, (list, tuple)):
        items = list(raw)
    else:
        items = []
    targets: List[Dict[str, str]] = []
    for item in items:
        if isinstance(item, dict):
            name = _text(item.get("name") or item.get("empresa") or item.get("label"), 200)
            nif = re.sub(r"\D+", "", str(item.get("nif") or item.get("nipc") or ""))
        else:
            name = _text(item, 200)
            nif = ""
        if not name and not nif:
            continue
        targets.append({"name": name, "nif": nif[:9]})
    if not targets:
        raise ValueError("Indique a empresa (ou empresas) do relatório.")
    if len(targets) > limit:
        raise ValueError(f"Este relatório permite no máximo {limit} empresa(s).")
    return targets


def target_label(target: Any) -> str:
    """«Nome (NIF)» de um alvo, para listas e exportações."""
    if not isinstance(target, dict):
        return _text(target, 200)
    name = _text(target.get("name"), 200)
    nif = _text(target.get("nif"), 20)
    if name and nif:
        return f"{name} ({nif})"
    return name or nif


def totals(price: Any, vat_rate: Any, prices_include_tax: bool = True) -> Dict[str, float]:
    gross = money(price)
    rate = money(vat_rate)
    if prices_include_tax:
        net = round(gross / (1 + rate / 100), 2) if rate else gross
        vat = round(gross - net, 2)
    else:
        net = gross
        vat = round(gross * rate / 100, 2)
        gross = round(net + vat, 2)
    return {"subtotal": net, "vat": vat, "total": gross}


def request_view(doc: Dict[str, Any], *, include_internal: bool = False) -> Dict[str, Any]:
    """Vista do pedido com etiquetas, totais e (opcionalmente) notas internas."""
    data = copy.deepcopy(doc)
    status = str(data.get("status") or "aguarda_pagamento")
    payment = data.get("payment") or {}
    payment_status = str(payment.get("status") or "pendente")
    view: Dict[str, Any] = {
        "id": data.get("id"),
        "reference": data.get("reference"),
        "status": status,
        "status_label": REPORT_LABELS.get(status, status),
        "status_style": REPORT_STYLE.get(status, "zinc"),
        "status_hint": REPORT_HINTS.get(status, ""),
        "next_statuses": [
            {"id": item, "label": REPORT_LABELS.get(item, item), "style": REPORT_STYLE.get(item, "zinc")}
            for item in REPORT_FLOW.get(status, [])
        ],
        "flow": [
            {
                "id": step,
                "label": REPORT_LABELS.get(step, step),
                "done": REPORT_FLOW_STEPS.index(step) <= REPORT_FLOW_STEPS.index(status)
                if status in REPORT_FLOW_STEPS
                else False,
            }
            for step in REPORT_FLOW_STEPS
        ],
        "package_id": data.get("package_id"),
        "package_title": data.get("package_title"),
        "package_subtitle": data.get("package_subtitle"),
        "targets": data.get("targets") or [],
        "targets_label": ", ".join(target_label(item) for item in (data.get("targets") or [])),
        "notes": data.get("notes") or "",
        "requester": data.get("requester") or {},
        "assigned_to": data.get("assigned_to") or "",
        "amounts": data.get("amounts") or totals(0, 0),
        "payment": {
            "method": payment.get("method") or "",
            "method_label": next(
                (item["label"] for item in PAYMENT_METHODS if item["id"] == payment.get("method")),
                payment.get("method") or "—",
            ),
            "status": payment_status,
            "status_label": PAYMENT_LABELS.get(payment_status, payment_status),
            "status_style": PAYMENT_STYLE.get(payment_status, "zinc"),
            "mbway_phone": payment.get("mbway_phone") or "",
            "mbway_number": payment.get("mbway_number") or "",
            "mbway_reference": payment.get("mbway_reference") or "",
            "requested_at": payment.get("requested_at") or "",
            "paid_at": payment.get("paid_at") or "",
            "confirmed_by": payment.get("confirmed_by") or "",
            "note": payment.get("note") or "",
            "automatic": bool(payment.get("automatic")),
        },
        "files": [
            {
                "id": item.get("id"),
                "name": item.get("name"),
                "size": item.get("size", 0),
                "mime": item.get("mime", ""),
                "uploaded_at": item.get("uploaded_at"),
                "uploaded_by": item.get("uploaded_by"),
            }
            for item in (data.get("files") or [])
        ],
        "created_at": data.get("created_at"),
        "updated_at": data.get("updated_at"),
        "payment_instructions": data.get("payment_instructions") or "",
        "internal_note": (data.get("internal_note") or "") if include_internal else "",
        "history": [
            item
            for item in (data.get("history") or [])
            if include_internal or item.get("visibility", "public") == "public"
        ],
    }
    return view


def _history(store: Dict[str, Any], doc: Dict[str, Any], actor: str, message: str, *, visibility: str = "public", to_status: str = "", kind: str = "nota") -> None:
    doc.setdefault("history", []).insert(
        0,
        {
            "id": _new_id("hst"),
            "at": _now(),
            "by": actor,
            "kind": kind,
            "message": message,
            "from_status": doc.get("status", ""),
            "to_status": to_status,
            "visibility": visibility,
        },
    )
    del doc["history"][120:]


def create_request(requester: Dict[str, Any], payload: Dict[str, Any]) -> Dict[str, Any]:
    """Cria um pedido de relatório para o utilizador autenticado."""
    with _lock:
        store = load()
        item = package(payload.get("package_id"))
        if not item or not _bool(item.get("active"), True):
            raise ValueError("Relatório indisponível. Escolha outro do catálogo.")
        limit = int(item.get("max_targets") or 1)
        targets = _normalise_targets(payload.get("targets") or payload.get("target"), limit)
        notes = _text(payload.get("notes"), MAX_NOTES)
        settings_data = store["settings"]
        amounts = totals(item.get("price"), settings_data.get("vat_rate"))
        free = amounts["total"] <= 0
        phone = normalise_phone(payload.get("mbway_phone"))
        if payload.get("mbway_phone") and not phone:
            raise ValueError("O número MB Way indicado não parece um telemóvel português.")
        email = _email(requester.get("email"))
        if not email:
            raise ValueError("Sessão sem email; volte a entrar.")
        reference = _next_reference(store)
        request = {
            "id": _new_id("rep"),
            "reference": reference,
            "status": "em_producao" if free else "aguarda_pagamento",
            "package_id": item.get("id"),
            "package_title": item.get("title"),
            "package_subtitle": item.get("subtitle"),
            "package_features": item.get("features") or [],
            "delivery_days": int(item.get("delivery_days") or settings_data.get("default_delivery_days") or 2),
            "targets": targets,
            "notes": notes,
            "requester": {
                "email": email,
                "name": _text(requester.get("name"), 120),
            },
            "amounts": amounts,
            "payment": {
                "method": "manual" if free else "",
                "status": "confirmado" if free else "pendente",
                "mbway_phone": phone,
                "mbway_number": "" if free else str(settings_data.get("mbway_number") or ""),
                "mbway_reference": "" if free else reference.rsplit("-", 1)[-1],
                "requested_at": "" if free else _now(),
                "paid_at": _now() if free else "",
                "confirmed_by": "sistema (grátis)" if free else "",
                "note": "",
                "automatic": False,
            },
            "payment_instructions": "" if free else str(settings_data.get("payment_instructions") or ""),
            "files": [],
            "history": [],
            "assigned_to": "",
            "internal_note": "",
            "created_at": _now(),
            "updated_at": _now(),
        }
        store["requests"].insert(0, request)
        _history(store, request, email, f"Pedido criado ({item.get('title')}).", kind="criado")
        _log(store, "request.created", request=request, actor=email, detail=request["reference"])
        recipients = backoffice_recipients(payload.get("_admins") or [])
        notify(
            store,
            recipients,
            f"Novo pedido de relatório {request['reference']}",
            f"{requester.get('name') or email} pediu «{item.get('title')}» para {request_view(request)['targets_label']}.",
            kind="pedido",
            request=request,
        )
        _write_store(store)
        return request_view(request, include_internal=True)


def request_reference_hint(store: Dict[str, Any]) -> str:
    """Referência curta que o cliente escreve no MB Way (usa o próximo número)."""
    return _next_reference(store).rsplit("-", 1)[-1]


def requests_for(email: str, *, limit: int = 200) -> List[Dict[str, Any]]:
    target = _email(email)
    items = [item for item in load()["requests"] if _email((item.get("requester") or {}).get("email")) == target]
    items.sort(key=lambda item: item.get("created_at", ""), reverse=True)
    return [request_view(item) for item in items[:limit]]


def all_requests(*, status: str = "", query: str = "", assigned_to: str = "", only_backoffice: bool = False, limit: int = 300) -> List[Dict[str, Any]]:
    status = _text(status).lower()
    needle = _text(query).lower()
    items = list(load()["requests"])
    if status:
        items = [item for item in items if str(item.get("status")) == status]
    if only_backoffice and assigned_to:
        items = [item for item in items if _email(item.get("assigned_to")) == _email(assigned_to)]
    if needle:
        def matches(item: Dict[str, Any]) -> bool:
            blob = " ".join(
                [
                    str(item.get("reference", "")),
                    str(item.get("package_title", "")),
                    str((item.get("requester") or {}).get("email", "")),
                    str((item.get("requester") or {}).get("name", "")),
                    " ".join(str(t.get("name", "")) for t in (item.get("targets") or [])),
                    " ".join(str(t.get("nif", "")) for t in (item.get("targets") or [])),
                    str(item.get("notes", "")),
                ]
            ).lower()
            return needle in blob

        items = [item for item in items if matches(item)]
    items.sort(key=lambda item: item.get("created_at", ""), reverse=True)
    return [request_view(item, include_internal=True) for item in items[:limit]]


def get_request(request_id: str) -> Optional[Dict[str, Any]]:
    for item in load()["requests"]:
        if str(item.get("id")) == str(request_id) or str(item.get("reference")) == str(request_id):
            return item
    return None


def get_request_view(request_id: str, *, include_internal: bool = False) -> Optional[Dict[str, Any]]:
    doc = get_request(request_id)
    return request_view(doc, include_internal=include_internal) if doc else None


def stats() -> Dict[str, Any]:
    items = load()["requests"]
    counters = {status: 0 for status in REPORT_STATUSES}
    for item in items:
        status = str(item.get("status") or "aguarda_pagamento")
        counters[status] = counters.get(status, 0) + 1
    revenue = 0.0
    for item in items:
        if str(item.get("status")) in {"cancelado"}:
            continue
        payment = item.get("payment") or {}
        if str(payment.get("status")) == "confirmado":
            revenue += money((item.get("amounts") or {}).get("total"))
    return {
        "total": len(items),
        "by_status": counters,
        "labels": REPORT_LABELS,
        "revenue": round(revenue, 2),
        "pending_payment": counters.get("aguarda_pagamento", 0),
        "awaiting_confirm": sum(
            1 for item in items if str((item.get("payment") or {}).get("status")) == "aguarda_confirmacao"
        ),
        "open": sum(
            1
            for item in items
            if str(item.get("status")) in {"aguarda_pagamento", "pagamento_confirmado", "em_producao"}
        ),
    }


# --------------------------------------------------------------------------
# Pagamentos
# --------------------------------------------------------------------------
def declare_payment(request_id: str, user: Dict[str, Any], payload: Dict[str, Any], *, admins: Sequence[str] = ()) -> Dict[str, Any]:
    """O cliente indica que pagou (ou pede o pedido de pagamento MB Way)."""
    email = _email(user.get("email"))
    with _lock:
        store = load()
        doc = get_request(request_id)
        if doc is None:
            raise ValueError("Pedido não encontrado.")
        if _email((doc.get("requester") or {}).get("email")) != email:
            raise ValueError("Este pedido não é seu.")
        if str(doc.get("status")) in {"cancelado", "reembolsado"}:
            raise ValueError("O pedido já não aceita pagamentos.")
        payment = doc.setdefault("payment", {})
        if str(payment.get("status")) == "confirmado":
            raise ValueError("Este pedido já está pago.")
        method = _text(payload.get("method") or "mbway", 20).lower()
        if method not in {item["id"] for item in PAYMENT_METHODS}:
            method = "mbway"
        phone = normalise_phone(payload.get("mbway_phone")) or _text(payment.get("mbway_phone"))
        if method == "mbway" and payload.get("mbway_phone") and not phone:
            raise ValueError("O número MB Way indicado não parece um telemóvel português.")
        payment["method"] = method
        if phone:
            payment["mbway_phone"] = phone
        note = _text(payload.get("note"), 400)
        if note:
            payment["note"] = note
        if str(store["settings"].get("mbway_number")):
            payment["mbway_number"] = str(store["settings"].get("mbway_number"))
        already_declared = str(payment.get("status")) == "aguarda_confirmacao"
        payment["status"] = "aguarda_confirmacao"
        payment["declared_at"] = _now()
        doc["updated_at"] = _now()
        _history(
            store,
            doc,
            email,
            f"Cliente indicou pagamento por {next((m['label'] for m in PAYMENT_METHODS if m['id'] == method), method)}" + ("." if not already_declared else " (reforço)."),
            kind="pagamento",
        )
        _log(store, "payment.declared", request=doc, actor=email, detail=note)
        notify(
            store,
            backoffice_recipients(admins),
            f"Pagamento a confirmar — {doc.get('reference')}",
            f"{user.get('name') or email} diz ter pago {money((doc.get('amounts') or {}).get('total')):.2f} € "
            f"({next((m['label'] for m in PAYMENT_METHODS if m['id'] == method), method)}"
            + (f", telemóvel {phone}" if phone else "")
            + ").",
            kind="pagamento",
            request=doc,
        )
        _write_store(store)
        return request_view(doc, include_internal=True)


def set_payment_result(
    request_id: str,
    actor: str,
    action: str,
    *,
    note: str = "",
    amount: Any = None,
    automatic: bool = False,
) -> Dict[str, Any]:
    """Confirma ou rejeita o pagamento (backoffice) e avança o estado do pedido."""
    action = _text(action).lower()
    if action not in {"confirm", "reject"}:
        raise ValueError("Ação de pagamento inválida.")
    with _lock:
        store = load()
        doc = get_request(request_id)
        if doc is None:
            raise ValueError("Pedido não encontrado.")
        payment = doc.setdefault("payment", {})
        if action == "confirm":
            payment["status"] = "confirmado"
            payment["paid_at"] = _now()
            payment["confirmed_by"] = actor
            payment["automatic"] = bool(automatic)
            if amount is not None and str(amount) != "":
                payment["amount_received"] = money(amount)
            if note:
                payment["note"] = _text(note, 400)
            if str(doc.get("status")) == "aguarda_pagamento":
                doc["status"] = "pagamento_confirmado"
                _history(store, doc, actor, "Pagamento confirmado; o pedido entra na fila.", to_status="pagamento_confirmado", kind="pagamento")
            else:
                _history(store, doc, actor, "Pagamento confirmado.", kind="pagamento")
            notify(
                store,
                [_email((doc.get("requester") or {}).get("email"))],
                f"Pagamento confirmado — {doc.get('reference')}",
                "Recebemos o seu pagamento. O relatório vai entrar em produção.",
                kind="pagamento",
                request=doc,
            )
            _log(store, "payment.confirmed", request=doc, actor=actor)
        else:
            payment["status"] = "rejeitado"
            payment["confirmed_by"] = actor
            if note:
                payment["note"] = _text(note, 400)
            _history(store, doc, actor, note or "Pagamento rejeitado.", kind="pagamento")
            notify(
                store,
                [_email((doc.get("requester") or {}).get("email"))],
                f"Pagamento por confirmar — {doc.get('reference')}",
                note or "Não conseguimos identificar o seu pagamento. Fale com o apoio.",
                kind="pagamento",
                request=doc,
            )
            _log(store, "payment.rejected", request=doc, actor=actor, detail=note)
        doc["updated_at"] = _now()
        _write_store(store)
        return request_view(doc, include_internal=True)


def record_mbway_request(request_id: str, provider_request_id: str, provider_status: str = "") -> Optional[Dict[str, Any]]:
    """Guarda o id do pedido de pagamento criado na API do MB Way.

    É esse id que permite consultar o estado mais tarde
    (`GET /reports/requests/{id}/payment/status`) sem o cliente repetir o pedido.
    """
    with _lock:
        store = load()
        doc = get_request(request_id)
        if doc is None:
            return None
        payment = doc.setdefault("payment", {})
        payment["provider_request_id"] = _text(provider_request_id, 80)
        payment["provider_status"] = _text(provider_status, 40)
        payment["provider_status_at"] = _now()
        payment["automatic"] = True
        doc["updated_at"] = _now()
        _history(
            store,
            doc,
            "mbway",
            "Pedido de pagamento MB Way enviado para o telemóvel do cliente.",
            kind="pagamento",
        )
        _write_store(store)
        return request_view(doc, include_internal=True)


def register_automatic_payment(request_id: str, *, reference: str = "", amount: Any = None) -> Optional[Dict[str, Any]]:
    """Confirma um pagamento vindo da API do MB Way (sem intervenção humana)."""
    try:
        return set_payment_result(
            request_id,
            "mbway",
            "confirm",
            note="Pagamento confirmado automaticamente pela API MB Way"
            + (f" (referência {reference})." if reference else "."),
            amount=amount,
            automatic=True,
        )
    except ValueError:
        return None


def set_status(request_id: str, actor: str, status: str, *, note: str = "", assigned_to: Optional[str] = None, internal: bool = False) -> Dict[str, Any]:
    status = _text(status).lower()
    if status not in REPORT_STATUSES:
        raise ValueError("Estado inválido.")
    with _lock:
        store = load()
        doc = get_request(request_id)
        if doc is None:
            raise ValueError("Pedido não encontrado.")
        current = str(doc.get("status"))
        if status == current and not note and assigned_to is None:
            return request_view(doc, include_internal=True)
        if current in {"cancelado", "reembolsado"} and status != current:
            raise ValueError("Um pedido cancelado/reembolsado não volta atrás.")
        doc["status"] = status
        doc["updated_at"] = _now()
        if assigned_to is not None:
            doc["assigned_to"] = _email(assigned_to)
        if internal and note:
            doc["internal_note"] = _text(note, 2000)
        _history(
            store,
            doc,
            actor,
            note or f"Estado alterado para {REPORT_LABELS.get(status, status)}.",
            visibility="internal" if internal else "public",
            to_status=status,
            kind="estado",
        )
        _log(store, "request.status", request=doc, actor=actor, detail=f"{current} → {status}")
        if status in {"gerado", "entregue", "cancelado", "reembolsado", "em_producao"} and status != current:
            messages = {
                "em_producao": ("Relatório em produção", "A equipa começou a produzir o seu relatório."),
                "gerado": ("Relatório pronto", "O seu relatório já está disponível para descarregar na área Relatórios."),
                "entregue": ("Relatório entregue", "Marcámos o seu relatório como entregue."),
                "cancelado": ("Pedido cancelado", note or "O seu pedido foi cancelado."),
                "reembolsado": ("Pedido reembolsado", note or "O seu pedido foi reembolsado."),
            }
            title, body = messages.get(status, (f"Pedido {doc.get('reference')}", ""))
            notify(store, [_email((doc.get("requester") or {}).get("email"))], f"{title} — {doc.get('reference')}", body, kind=status, request=doc)
        _write_store(store)
        return request_view(doc, include_internal=True)


def cancel(request_id: str, user: Dict[str, Any], note: str = "") -> Dict[str, Any]:
    email = _email(user.get("email"))
    with _lock:
        doc = get_request(request_id)
        if doc is None:
            raise ValueError("Pedido não encontrado.")
        if _email((doc.get("requester") or {}).get("email")) != email:
            raise ValueError("Este pedido não é seu.")
        if str(doc.get("status")) not in {"aguarda_pagamento", "pagamento_confirmado"}:
            raise ValueError("Só é possível cancelar antes de o relatório entrar em produção.")
        return set_status(request_id, email, "cancelado", note=note or "Cancelado pelo cliente.")


def attach_note(request_id: str, actor: str, message: str, *, internal: bool = False) -> Dict[str, Any]:
    message = _text(message, MAX_NOTES)
    if not message:
        raise ValueError("Escreva a nota.")
    with _lock:
        store = load()
        doc = get_request(request_id)
        if doc is None:
            raise ValueError("Pedido não encontrado.")
        doc["updated_at"] = _now()
        _history(store, doc, actor, message, visibility="internal" if internal else "public", kind="nota")
        if internal:
            # O campo «nota interna» é o que o backoffice vê/editano topo da ficha
            # (o histórico guarda todas as notas, esta é a que fica em destaque).
            doc["internal_note"] = message
        _log(store, "request.note", request=doc, actor=actor, detail=message[:200])
        _write_store(store)
        return request_view(doc, include_internal=True)


# --------------------------------------------------------------------------
# Ficheiros (relatórios gerados)
# --------------------------------------------------------------------------
def request_dir(request_id: str) -> Path:
    return FILES_DIR / str(request_id)


def add_file(request_id: str, actor: str, *, name: str, data: bytes, mime: str = "", mark_generated: bool = True) -> Dict[str, Any]:
    safe = safe_filename(name)
    suffix = Path(safe).suffix.lower()
    if suffix and suffix not in ALLOWED_FILE_SUFFIXES:
        raise ValueError(f"Extensão não permitida ({suffix}).")
    if not data:
        raise ValueError("O ficheiro está vazio.")
    if len(data) > MAX_FILE_BYTES:
        raise ValueError("O ficheiro excede 25 MB.")
    with _lock:
        store = load()
        doc = get_request(request_id)
        if doc is None:
            raise ValueError("Pedido não encontrado.")
        files = doc.setdefault("files", [])
        if len(files) >= MAX_FILES_PER_REQUEST:
            raise ValueError("Demasiados ficheiros neste pedido.")
        file_id = _new_id("fl")
        target_dir = request_dir(request_id)
        target_dir.mkdir(parents=True, exist_ok=True)
        target = target_dir / f"{file_id}-{safe}"
        target.write_bytes(data)
        item = {
            "id": file_id,
            "name": safe,
            "stored_name": target.name,
            "size": len(data),
            "mime": _text(mime, 120) or "application/octet-stream",
            "uploaded_at": _now(),
            "uploaded_by": actor,
        }
        files.append(item)
        doc["updated_at"] = _now()
        _history(store, doc, actor, f"Ficheiro «{safe}» anexado ao pedido.", kind="ficheiro")
        previous = str(doc.get("status"))
        if mark_generated and previous not in {"gerado", "entregue"}:
            doc["status"] = "gerado"
            _history(store, doc, actor, "Relatório gerado e disponibilizado ao cliente.", to_status="gerado", kind="estado")
            notify(
                store,
                [_email((doc.get("requester") or {}).get("email"))],
                f"Relatório pronto — {doc.get('reference')}",
                f"«{doc.get('package_title')}» já está disponível para descarregar na área Relatórios.",
                kind="gerado",
                request=doc,
            )
        _log(store, "request.file", request=doc, actor=actor, detail=safe)
        _write_store(store)
        return request_view(doc, include_internal=True)


def add_file_base64(request_id: str, actor: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    """Variante JSON (base64) usada quando o cliente não pode enviar multipart."""
    raw = str(payload.get("data") or "")
    if "," in raw[:200] and raw.strip().startswith("data:"):
        raw = raw.split(",", 1)[1]
    try:
        blob = base64.b64decode(raw, validate=False)
    except Exception as exc:  # noqa: BLE001 - entrada do utilizador
        raise ValueError("Ficheiro inválido (base64).") from exc
    return add_file(
        request_id,
        actor,
        name=_text(payload.get("name"), 200) or "relatorio.pdf",
        data=blob,
        mime=_text(payload.get("mime"), 120),
        mark_generated=_bool(payload.get("mark_generated"), True),
    )


def file_of(request_id: str, file_id: str) -> Optional[Tuple[Path, Dict[str, Any]]]:
    doc = get_request(request_id)
    if doc is None:
        return None
    for item in doc.get("files") or []:
        if str(item.get("id")) == str(file_id):
            path = request_dir(str(doc.get("id"))) / str(item.get("stored_name") or item.get("name"))
            if path.exists():
                return path, item
            return None
    return None


def remove_file(request_id: str, file_id: str, actor: str = "") -> bool:
    with _lock:
        store = load()
        doc = get_request(request_id)
        if doc is None:
            return False
        files = doc.get("files") or []
        target = next((item for item in files if str(item.get("id")) == str(file_id)), None)
        if target is None:
            return False
        doc["files"] = [item for item in files if str(item.get("id")) != str(file_id)]
        path = request_dir(str(doc.get("id"))) / str(target.get("stored_name") or target.get("name"))
        try:
            if path.exists():
                path.unlink()
        except OSError:  # pragma: no cover - depende do sistema
            logger.warning("Não foi possível apagar %s", path)
        doc["updated_at"] = _now()
        _history(store, doc, actor, f"Ficheiro «{target.get('name')}» removido.", kind="ficheiro")
        _write_store(store)
    return True


def activity(limit: int = 40) -> List[Dict[str, Any]]:
    return [copy.deepcopy(item) for item in load()["activity"][: max(1, limit)]]


def csv_rows(status: str = "") -> List[List[str]]:
    """Exportação simples (backoffice) dos pedidos."""
    rows = [["Referência", "Estado", "Pacote", "Alvos", "Total", "Pagamento", "Cliente", "Email", "Criado em"]]
    for item in all_requests(status=status, limit=5000):
        rows.append(
            [
                str(item.get("reference", "")),
                str(item.get("status_label", "")),
                str(item.get("package_title", "")),
                str(item.get("targets_label", "")),
                f"{money((item.get('amounts') or {}).get('total')):.2f}".replace(".", ","),
                str((item.get("payment") or {}).get("status_label", "")),
                str((item.get("requester") or {}).get("name", "")),
                str((item.get("requester") or {}).get("email", "")),
                str(item.get("created_at", "")),
            ]
        )
    return rows


def reset_for_tests() -> None:
    """Só para testes: esquece o documento em memória."""
    global _cache, _cache_mtime
    _cache = None
    _cache_mtime = None
