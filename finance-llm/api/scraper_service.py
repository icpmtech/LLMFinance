"""Motor de recolha de dados de sites («scraping») do IQ OS.

Este módulo é o equivalente, para a recolha web, do que o `crm_service` é para o
trabalho comercial: guarda as **definições** (as «fontes»), executa-as com o
[motoor Scrapling](https://github.com/D4Vinci/Scrapling), grava o resultado em
JSONL (registo/auditoria) e indexa-o no Elasticsearch (`finance_scraped`) para
pesquisa.

Conceitos
---------
- **Fonte** (`source`): uma definição declarativa — URL, tipo de *fetcher*
  (`http` | `dynamic` | `stealth`), seletor da lista, campos a extrair,
  paginação, agendamento cron e identidade do item. As fontes vivem em
  `data/scraper/sources.json` e são criadas/editadas pela UI.
- **Execução** (`run`): uma recolha concreta de uma fonte. Os itens ficam em
  `data/scraper/runs/<fonte>/<run_id>.jsonl` e os metadados (estado, contagens,
  erros) em `<run_id>.meta.json`.
- **Item**: um registo extraído. O `item_id` (derivado dos `id_fields`) é usado
  como `_id` no Elasticsearch, pelo que repetir uma recolha **atualiza** os itens
  conhecidos em vez de os duplicar.

Tudo neste módulo degrada com elegância: se o Scrapling não estiver instalado, a
leitura/escrita das definições continua a funcionar e as execuções devolvem um
erro explicativo (nunca derrubam a API).
"""
from __future__ import annotations

import hashlib
import json
import logging
import re
import threading
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterator, List, Optional, Tuple
from urllib.parse import urljoin
from urllib.robotparser import RobotFileParser

from api.elasticsearch_client import (
    ROOT,
    delete_scraped_source,
    get_es_client,
    index_scraped_items,
    scraped_status,
    search_scraped,
)

logger = logging.getLogger(__name__)

SCRAPER_DIR = ROOT / "data" / "scraper"
SOURCES_FILE = SCRAPER_DIR / "sources.json"
RUNS_DIR = SCRAPER_DIR / "runs"

SOURCES_VERSION = 1
FETCHERS = ("http", "dynamic", "stealth")
FETCHER_LABELS = {
    "http": "HTTP rápido (sem browser)",
    "dynamic": "Browser dinâmico (JavaScript)",
    "stealth": "Browser stealth (anti-bot)",
}
# Tipos de seletor aceites nas definições.
SELECTOR_KINDS = ("css", "xpath", "text", "regex")
# Presets de cron mostrados na UI (expressão → descrição).
CRON_PRESETS = [
    {"cron": "*/15 * * * *", "label": "A cada 15 minutos"},
    {"cron": "0 * * * *", "label": "De hora a hora"},
    {"cron": "0 */6 * * *", "label": "A cada 6 horas"},
    {"cron": "0 7 * * *", "label": "Todos os dias às 07:00"},
    {"cron": "0 7 * * 1-5", "label": "Dias úteis às 07:00"},
    {"cron": "0 8 * * 1", "label": "Todas as segundas às 08:00"},
    {"cron": "0 6 1 * *", "label": "No dia 1 de cada mês às 06:00"},
]

DEFAULT_OPTIONS: Dict[str, Dict[str, Any]] = {
    "http": {"impersonate": "chrome", "timeout": 30},
    "dynamic": {"headless": True, "network_idle": True, "timeout": 45},
    "stealth": {"headless": True, "solve_cloudflare": False, "network_idle": True, "timeout": 60},
}

DEFAULT_USER_AGENT = "IQOS-Scraper/1.0 (recolha autorizada; contacto: administrador local)"

_DEFAULTS = {
    "fetcher": "http",
    "list": {"selector": "", "type": "css"},
    "fields": [],
    "pagination": {"selector": "", "type": "css", "attr": "href", "max_pages": 1},
    "options": {},
    "schedule": {"cron": "", "timezone": "Europe/Lisbon"},
    "respect_robots": True,
    "tags": [],
    "id_fields": [],
}

_lock = threading.RLock()
_active_runs: Dict[str, str] = {}
_robots_cache: Dict[str, Optional[RobotFileParser]] = {}


# --------------------------------------------------------------------- estado
def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _ensure_dirs() -> None:
    SCRAPER_DIR.mkdir(parents=True, exist_ok=True)
    RUNS_DIR.mkdir(parents=True, exist_ok=True)


def _example_source() -> Dict[str, Any]:
    """Fonte de exemplo (site público de demonstração) para a UI arrancar cheia."""
    return {
        "id": "quotes-demo",
        "name": "Quotes to Scrape (exemplo)",
        "description": "Exemplo de definição: lista de citações, autor e etiquetas.",
        "url": "https://quotes.toscrape.com/",
        "enabled": False,
        "fetcher": "http",
        "list": {"selector": ".quote", "type": "css"},
        "fields": [
            {"name": "citacao", "label": "Citação", "selector": ".text::text", "type": "css"},
            {"name": "autor", "label": "Autor", "selector": ".author::text", "type": "css"},
            {"name": "etiquetas", "label": "Etiquetas", "selector": ".tag::text", "type": "css", "all": True},
        ],
        "pagination": {"selector": ".next a", "type": "css", "attr": "href", "max_pages": 3},
        "options": {"impersonate": "chrome", "timeout": 30},
        "schedule": {"cron": "0 7 * * *", "timezone": "Europe/Lisbon"},
        "respect_robots": True,
        "tags": ["exemplo", "demonstracao"],
        "id_fields": ["autor", "citacao"],
    }


def _load() -> Dict[str, Any]:
    """Lê o ficheiro de definições (cria-o com a fonte de exemplo na 1.ª vez)."""
    _ensure_dirs()
    if not SOURCES_FILE.exists():
        payload = {"version": SOURCES_VERSION, "sources": [_example_source()]}
        _write(payload)
        return payload
    try:
        data = json.loads(SOURCES_FILE.read_text(encoding="utf-8"))
        if isinstance(data, list):  # tolerar formato antigo
            data = {"version": SOURCES_VERSION, "sources": data}
        data.setdefault("version", SOURCES_VERSION)
        data.setdefault("sources", [])
        return data
    except Exception as exc:
        logger.error("Definições de recolha ilegíveis (%s); a recomeçar vazias.", exc)
        return {"version": SOURCES_VERSION, "sources": []}


def _write(payload: Dict[str, Any]) -> None:
    _ensure_dirs()
    tmp = SOURCES_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(SOURCES_FILE)


# ----------------------------------------------------------------- definições
def normalize_source(payload: Dict[str, Any], existing: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Valida e normaliza uma definição de fonte (aceita patches parciais)."""
    base = dict(existing or {})
    merged: Dict[str, Any] = {**_DEFAULTS, **base, **(payload or {})}

    source_id = str(merged.get("id") or "").strip()
    if not source_id:
        source_id = re.sub(r"[^a-z0-9]+", "-", str(merged.get("name") or "fonte").strip().lower()).strip("-")
        source_id = f"{source_id or 'fonte'}-{uuid.uuid4().hex[:6]}"
    merged["id"] = source_id

    url = str(merged.get("url") or "").strip()
    if not url:
        raise ValueError("A fonte precisa de um URL.")
    if not re.match(r"^https?://", url, re.I):
        url = f"https://{url}"
    merged["url"] = url

    name = str(merged.get("name") or "").strip() or url
    merged["name"] = name
    merged["description"] = str(merged.get("description") or "").strip()

    fetcher = str(merged.get("fetcher") or "http").strip().lower()
    if fetcher not in FETCHERS:
        raise ValueError(f"Fetcher inválido: {fetcher!r} (use um de {', '.join(FETCHERS)}).")
    merged["fetcher"] = fetcher
    merged["enabled"] = bool(merged.get("enabled", False))
    merged["respect_robots"] = bool(merged.get("respect_robots", True))

    merged["list"] = _normalize_selector(merged.get("list"), default_type="css")
    merged["pagination"] = _normalize_pagination(merged.get("pagination"))

    fields: List[Dict[str, Any]] = []
    for raw in merged.get("fields") or []:
        if not isinstance(raw, dict):
            continue
        fname = str(raw.get("name") or "").strip()
        if not fname:
            continue
        selector = str(raw.get("selector") or "").strip()
        fields.append(
            {
                "name": fname,
                "label": str(raw.get("label") or fname).strip(),
                "selector": selector,
                "type": str(raw.get("type") or "css").strip().lower(),
                "attr": (str(raw.get("attr")).strip() or None) if raw.get("attr") else None,
                "all": bool(raw.get("all", False)),
                "join": str(raw.get("join") or " | "),
                "cast": str(raw.get("cast") or "text").strip().lower(),
                "max_length": int(raw.get("max_length") or 5000),
            }
        )
    if not fields:
        raise ValueError("A fonte precisa de pelo menos um campo a extrair.")
    merged["fields"] = fields

    ids = [str(v).strip() for v in (merged.get("id_fields") or []) if str(v).strip()]
    merged["id_fields"] = [f for f in ids if f in {x["name"] for x in fields}]

    merged["tags"] = [str(t).strip() for t in (merged.get("tags") or []) if str(t).strip()]

    options = dict(DEFAULT_OPTIONS.get(fetcher, {}))
    options.update({k: v for k, v in (merged.get("options") or {}).items() if v not in (None, "")})
    merged["options"] = options

    schedule = merged.get("schedule") or {}
    cron = str(schedule.get("cron") or "").strip()
    timezone_name = str(schedule.get("timezone") or "Europe/Lisbon").strip()
    if cron:
        validate_cron(cron)
    merged["schedule"] = {"cron": cron, "timezone": timezone_name}

    for key in ("title_field", "summary_field", "text_field", "tags_field"):
        value = str(merged.get(key) or "").strip()
        merged[key] = value or ""

    merged["created_at"] = base.get("created_at") or _now()
    merged["updated_at"] = _now()
    return merged


def _normalize_selector(raw: Any, default_type: str = "css") -> Dict[str, Any]:
    if isinstance(raw, str):
        raw = {"selector": raw}
    raw = raw if isinstance(raw, dict) else {}
    kind = str(raw.get("type") or default_type).strip().lower()
    if kind not in SELECTOR_KINDS:
        kind = default_type
    return {"selector": str(raw.get("selector") or "").strip(), "type": kind}


def _normalize_pagination(raw: Any) -> Dict[str, Any]:
    if isinstance(raw, str):
        raw = {"selector": raw}
    raw = raw if isinstance(raw, dict) else {}
    base = _normalize_selector(raw, "css")
    return {
        "selector": base["selector"],
        "type": base["type"],
        "attr": str(raw.get("attr") or "href").strip() or "href",
        "max_pages": max(1, min(int(raw.get("max_pages") or 1), 500)),
    }


def validate_cron(expression: str) -> None:
    """Valida uma expressão cron de 5 campos (minuto hora dia mês dia-semana)."""
    parts = str(expression or "").split()
    if len(parts) != 5:
        raise ValueError("Expressão cron inválida: são precisos 5 campos (minuto hora dia mês dia-semana).")
    checks = [
        (parts[0], 0, 59, "minuto"),
        (parts[1], 0, 23, "hora"),
        (parts[2], 1, 31, "dia do mês"),
        (parts[3], 1, 12, "mês"),
        (parts[4], 0, 7, "dia da semana"),
    ]
    for token, low, high, label in checks:
        if token == "*":
            continue
        for chunk in token.split(","):
            step = chunk
            if "/" in chunk:
                step, _, step_value = chunk.partition("/")
                if not step_value.isdigit() or int(step_value) < 1:
                    raise ValueError(f"Passo inválido no campo {label}: {chunk!r}.")
                step = step or "*"
            if step == "*":
                continue
            if "-" in step:
                start, _, end = step.partition("-")
                if not (start.isdigit() and end.isdigit()):
                    raise ValueError(f"Intervalo inválido no campo {label}: {chunk!r}.")
                if not (low <= int(start) <= high and low <= int(end) <= high):
                    raise ValueError(f"Valores fora do intervalo no campo {label}: {chunk!r}.")
                continue
            if not step.isdigit():
                raise ValueError(f"Valor inválido no campo {label}: {chunk!r}.")
            if not (low <= int(step) <= high):
                raise ValueError(f"Valores fora do intervalo no campo {label}: {chunk!r}.")


def list_sources() -> List[Dict[str, Any]]:
    """Lista as fontes, com o estado da última execução agregado."""
    with _lock:
        sources = list(_load().get("sources") or [])
    runs = list_runs(limit=200)
    latest: Dict[str, Dict[str, Any]] = {}
    for run in runs:
        latest.setdefault(run.get("source_id", ""), run)
    active = dict(_active_runs)
    for source in sources:
        run = latest.get(source["id"])
        source["last_run"] = run_summary(run) if run else None
        source["running"] = source["id"] in active
        source["active_run_id"] = active.get(source["id"])
    return sources


def get_source(source_id: str) -> Optional[Dict[str, Any]]:
    for source in list_sources():
        if source.get("id") == source_id:
            return source
    return None


def _notify_scheduler() -> None:
    """Reaplica as definições ao agendador (import tardio evita ciclo de imports)."""
    try:
        from api import scraper_scheduler

        scraper_scheduler.reload_jobs()
    except Exception as exc:
        logger.debug("Agendador não atualizado: %s", exc)


def upsert_source(payload: Dict[str, Any]) -> Dict[str, Any]:
    """Cria ou atualiza uma fonte (o `id` identifica-a)."""
    with _lock:
        data = _load()
        sources: List[Dict[str, Any]] = list(data.get("sources") or [])
        source_id = str(payload.get("id") or "").strip()
        index = next((i for i, s in enumerate(sources) if s.get("id") == source_id), None)
        existing = sources[index] if index is not None else None
        if source_id and existing is None and payload.get("_must_exist"):
            raise KeyError(source_id)
        source = normalize_source(payload, existing)
        if existing is not None:
            sources[index] = source
        else:
            if any(s.get("id") == source["id"] for s in sources):
                source["id"] = f"{source['id']}-{uuid.uuid4().hex[:4]}"
            sources.append(source)
        data["sources"] = sources
        _write(data)
    _notify_scheduler()
    return get_source(source["id"]) or source


def delete_source(source_id: str, *, purge_items: bool = False) -> Dict[str, Any]:
    """Remove uma fonte (e opcionalmente os itens já indexados)."""
    with _lock:
        data = _load()
        sources = [s for s in (data.get("sources") or []) if s.get("id") != source_id]
        if len(sources) == len(data.get("sources") or []):
            raise KeyError(source_id)
        data["sources"] = sources
        _write(data)
    _notify_scheduler()
    result: Dict[str, Any] = {"ok": True, "deleted": source_id}
    if purge_items:
        result["purged"] = delete_scraped_source(source_id)
    return result


# ------------------------------------------------------------------ Scrapling
def _load_scrapling() -> Dict[str, Any]:
    """Importa o Scrapling (tarde) e devolve as classes dos fetchers."""
    try:
        from scrapling.fetchers import (  # type: ignore
            DynamicFetcher,
            DynamicSession,
            Fetcher,
            FetcherSession,
            StealthyFetcher,
            StealthySession,
        )
    except Exception as exc:  # pragma: no cover - depende do ambiente
        raise RuntimeError(
            "O Scrapling não está instalado. Instale com `pip install \"scrapling[fetchers]\"` "
            "e, para browsers, `scrapling install`."
        ) from exc
    return {
        "Fetcher": Fetcher,
        "FetcherSession": FetcherSession,
        "DynamicFetcher": DynamicFetcher,
        "DynamicSession": DynamicSession,
        "StealthyFetcher": StealthyFetcher,
        "StealthySession": StealthySession,
    }


def availability() -> Dict[str, Any]:
    """Diagnóstico do ambiente de recolha (Scrapling, browsers, Elasticsearch)."""
    info: Dict[str, Any] = {"scrapling": False, "fetchers": {}, "elasticsearch": False}
    try:
        classes = _load_scrapling()
        info["scrapling"] = True
        info["fetchers"] = {
            "http": "FetcherSession" in classes,
            "dynamic": "DynamicSession" in classes,
            "stealth": "StealthySession" in classes,
        }
    except Exception as exc:
        info["scrapling_error"] = str(exc)
        info["fetchers"] = {kind: False for kind in FETCHERS}

    try:
        from playwright.sync_api import sync_playwright  # type: ignore  # noqa: F401

        info["playwright"] = True
    except Exception:
        info["playwright"] = False

    client = get_es_client()
    if client:
        status = scraped_status(client)
        info["elasticsearch"] = bool(status.get("available"))
        info["indexed_items"] = status.get("total", 0)
        info["indexed_sources"] = status.get("sources", [])

    scheduler: Dict[str, Any] = {"available": False}
    try:
        from api import scraper_scheduler

        scheduler = scraper_scheduler.status()
    except Exception:
        pass
    info["scheduler"] = scheduler
    return info


def _open_session(kind: str, options: Dict[str, Any]):
    """Abre a sessão Scrapling adequada ao tipo de fetcher (context manager)."""
    classes = _load_scrapling()
    opts = {**DEFAULT_OPTIONS.get(kind, {}), **(options or {})}
    if kind == "http":
        kwargs: Dict[str, Any] = {}
        if opts.get("impersonate"):
            kwargs["impersonate"] = opts["impersonate"]
        if opts.get("http3"):
            kwargs["http3"] = bool(opts["http3"])
        if opts.get("proxy"):
            kwargs["proxy"] = opts["proxy"]
        return classes["FetcherSession"](**kwargs)
    if kind == "dynamic":
        kwargs = {"headless": bool(opts.get("headless", True))}
        if opts.get("network_idle") is not None:
            kwargs["network_idle"] = bool(opts["network_idle"])
        if opts.get("disable_resources") is not None:
            kwargs["disable_resources"] = bool(opts["disable_resources"])
        if opts.get("proxy"):
            kwargs["proxy"] = opts["proxy"]
        return classes["DynamicSession"](**kwargs)
    kwargs = {"headless": bool(opts.get("headless", True))}
    if opts.get("solve_cloudflare") is not None:
        kwargs["solve_cloudflare"] = bool(opts["solve_cloudflare"])
    if opts.get("network_idle") is not None:
        kwargs["network_idle"] = bool(opts["network_idle"])
    if opts.get("proxy"):
        kwargs["proxy"] = opts["proxy"]
    return classes["StealthySession"](**kwargs)


def _session_fetch(session: Any, kind: str, url: str, options: Dict[str, Any]) -> Any:
    """Executa um pedido, uniformizando a API das sessões do Scrapling."""
    timeout = options.get("timeout")
    if kind == "http":
        kwargs: Dict[str, Any] = {"stealthy_headers": True}
        if timeout:
            kwargs["timeout"] = timeout
        return session.get(url, **kwargs)
    kwargs = {}
    if timeout:
        kwargs["timeout"] = timeout * 1000  # os browsers usam milissegundos
    return session.fetch(url, **kwargs)


# -------------------------------------------------------------------- robots
def _robots_for(url: str) -> Optional[RobotFileParser]:
    """Lê (com cache) o robots.txt do domínio, ou `None` se não for possível."""
    try:
        parts = url.split("/")
        origin = "/".join(parts[:3])
    except Exception:
        return None
    if origin in _robots_cache:
        return _robots_cache[origin]
    parser: Optional[RobotFileParser] = None
    try:
        import urllib.request

        request = urllib.request.Request(f"{origin}/robots.txt", headers={"User-Agent": DEFAULT_USER_AGENT})
        with urllib.request.urlopen(request, timeout=6) as response:  # noqa: S310 - URL do utilizador
            parser = RobotFileParser()
            parser.parse(response.read().decode("utf-8", "ignore").splitlines())
    except Exception:
        parser = None  # sem robots.txt legível → não bloqueia
    _robots_cache[origin] = parser
    return parser


def _robots_allows(url: str, user_agent: str) -> bool:
    parser = _robots_for(url)
    if parser is None:
        return True
    try:
        return parser.can_fetch(user_agent or DEFAULT_USER_AGENT, url)
    except Exception:
        return True


# ------------------------------------------------------------------ extração
def _as_list(result: Any) -> List[Any]:
    """Uniformiza o resultado de um seletor do Scrapling numa lista."""
    if result is None:
        return []
    if isinstance(result, str):
        return [result]
    if isinstance(result, (list, tuple, set)):
        return list(result)
    getall = getattr(result, "getall", None)
    if callable(getall):
        try:
            return list(getall())
        except Exception:
            pass
    try:
        return list(result)
    except TypeError:
        return [result]


def _select(node: Any, selector: str, kind: str = "css") -> List[Any]:
    """Corre um seletor (css/xpath/text/regex) sobre um nó do Scrapling."""
    if not selector:
        return []
    try:
        if kind == "xpath":
            return _as_list(node.xpath(selector))
        if kind == "text":
            return _as_list(node.find_by_text(selector))
        if kind == "regex":
            text = _node_text(node)
            return re.findall(selector, text)
        return _as_list(node.css(selector))
    except Exception as exc:
        logger.debug("Seletor %r (%s) falhou: %s", selector, kind, exc)
        return []


def _node_text(node: Any) -> str:
    for attr in ("get_all_text", "text", "get"):
        value = getattr(node, attr, None)
        try:
            if callable(value):
                text = value()
            elif isinstance(value, str):
                text = value
            else:
                continue
        except Exception:
            continue
        if isinstance(text, str) and text:
            return text
    return str(node)


def _cast(value: Any, field: Dict[str, Any]) -> Any:
    """Converte um valor extraído para o tipo declarado no campo."""
    cast = str(field.get("cast") or "text").lower()
    if cast in ("text", "str", "string"):
        return value
    if cast in ("int", "integer"):
        digits = re.sub(r"[^\d\-]", "", str(value))
        try:
            return int(digits) if digits not in ("", "-") else None
        except ValueError:
            return None
    if cast in ("float", "number", "decimal"):
        cleaned = re.sub(r"[^\d\-.,]", "", str(value)).replace(".", "").replace(",", ".")
        try:
            return float(cleaned)
        except ValueError:
            return None
    if cast in ("bool", "boolean"):
        return str(value).strip().lower() in {"1", "true", "sim", "yes", "verdadeiro"}
    if cast == "date":
        match = re.search(r"\d{4}-\d{2}-\d{2}", str(value))
        return match.group(0) if match else None
    return value


def _value_from(node: Any, field: Dict[str, Any]) -> Any:
    """Extrai o valor de um campo de um item da lista."""
    selector = field.get("selector") or ""
    kind = field.get("type") or "css"
    attr = field.get("attr")
    if attr and kind == "css" and "::attr(" not in selector and "::text" not in selector:
        selector = f"{selector}::attr({attr})"
    values = [str(v).strip() for v in _select(node, selector, kind)]
    values = [v for v in values if v != ""]
    max_length = int(field.get("max_length") or 5000)
    values = [v[:max_length] for v in values]

    if field.get("all"):
        casted = [_cast(v, field) for v in values]
        return [v for v in casted if v not in (None, "")]
    if not values:
        return None
    return _cast(values[0], field)


def _item_id(item: Dict[str, Any], source: Dict[str, Any]) -> str:
    """Identidade estável do item (usada como `_id` no Elasticsearch)."""
    keys = list(source.get("id_fields") or [])
    if not keys:
        keys = ["url"] if item.get("url") else [f["name"] for f in source.get("fields", [])]
    parts: List[str] = []
    for key in keys:
        value = item.get(key)
        if isinstance(value, (list, tuple, set)):
            value = " | ".join(str(v) for v in value)
        if value not in (None, ""):
            parts.append(f"{key}={value}")
    if not parts:
        parts.append(json.dumps(item, ensure_ascii=False, sort_keys=True, default=str))
    raw = f"{source['id']}::{ '::'.join(parts) }"
    return f"{source['id']}:{hashlib.sha1(raw.encode('utf-8')).hexdigest()[:24]}"


def _to_document(raw: Dict[str, Any], source: Dict[str, Any], page_url: str) -> Dict[str, Any]:
    """Converte os campos extraídos no documento de recolha (item + índice)."""
    data = {k: v for k, v in raw.items() if v not in (None, "", [])}
    if page_url:
        data.setdefault("url", page_url)

    fields = {f["name"] for f in source.get("fields", [])}

    def pick(explicit: str, candidates: List[str]) -> Any:
        if explicit and explicit in data:
            return data[explicit]
        for name in candidates:
            if name in data and data[name] not in (None, "", []):
                return data[name]
        return None

    title = pick(source.get("title_field") or "", ["title", "titulo", "nome", "name", "assunto"])
    summary = pick(source.get("summary_field") or "", ["summary", "resumo", "description", "descricao", "objeto"])
    text = pick(source.get("text_field") or "", ["text", "texto", "conteudo", "body"])
    # Sem título declarado nem campo com nome previsível, usa-se o primeiro
    # campo textual extraído (é o que o utilizador vê como identificador).
    if not title:
        for name in [f["name"] for f in source.get("fields", [])]:
            value = data.get(name)
            if isinstance(value, str) and value.strip() and name != "url":
                title = value
                break
    if not text:
        parts = []
        for name in [f["name"] for f in source.get("fields", [])]:
            value = data.get(name)
            if isinstance(value, (list, tuple)):
                value = " | ".join(str(v) for v in value)
            if isinstance(value, str) and value and name not in {"url"}:
                parts.append(value)
        text = " · ".join(parts)
    if isinstance(text, (list, tuple)):
        text = " | ".join(str(v) for v in text)

    tags_value = pick(source.get("tags_field") or "", ["tags", "etiquetas", "categorias", "categoria"])
    if tags_value in (None, "", []):
        tags = list(source.get("tags") or [])
    elif isinstance(tags_value, (list, tuple)):
        tags = [str(t) for t in tags_value] + list(source.get("tags") or [])
    else:
        tags = re.split(r"[,;|]", str(tags_value))
        tags = [t.strip() for t in tags if t.strip()] + list(source.get("tags") or [])

    item = {
        "title": str(title or "")[:512],
        "summary": str(summary or "")[:2000],
        "text": str(text or "")[:20000],
        # Se a fonte extrai um campo `url` (o link do próprio item), esse valor
        # manda; só se não existir é que se usa o URL da página listada.
        "url": str(data.get("url") or page_url or ""),
        "tags": sorted({t for t in tags if t}),
        "data": data,
        "scraped_at": _now(),
    }
    item["item_id"] = _item_id({**item, **{k: v for k, v in data.items() if k in fields}}, source)
    return item


def _extract_items(page: Any, source: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Extrai os itens de uma página, conforme a definição da fonte."""
    page_url = str(getattr(page, "url", "") or source.get("url") or "")
    list_selector = (source.get("list") or {}).get("selector") or ""
    list_kind = (source.get("list") or {}).get("type") or "css"
    rows = _select(page, list_selector, list_kind) if list_selector else [page]
    if not rows:
        return []
    items: List[Dict[str, Any]] = []
    for row in rows:
        raw: Dict[str, Any] = {}
        for field in source.get("fields", []):
            value = _value_from(row, field)
            if isinstance(value, list):
                raw[field["name"]] = value
            elif value not in (None, ""):
                raw[field["name"]] = value
        if raw:
            items.append(_to_document(raw, source, page_url))
    return items


def _next_page_url(page: Any, source: Dict[str, Any], current_url: str) -> Optional[str]:
    pagination = source.get("pagination") or {}
    selector = pagination.get("selector") or ""
    if not selector:
        return None
    kind = pagination.get("type") or "css"
    attr = pagination.get("attr") or "href"
    if kind == "css" and "::attr(" not in selector and "::text" not in selector:
        selector = f"{selector}::attr({attr})"
    values = [str(v).strip() for v in _select(page, selector, kind)]
    values = [v for v in values if v]
    if not values:
        return None
    target = urljoin(current_url, values[0])
    if target.rstrip("/") == current_url.rstrip("/"):
        return None
    return target


def _walk_source(source: Dict[str, Any], *, max_pages: Optional[int] = None) -> Iterator[Tuple[int, Any, List[Dict[str, Any]]]]:
    """Percorre as páginas de uma fonte, devolvendo `(n.º página, página, itens)`."""
    options = source.get("options") or {}
    pagination = source.get("pagination") or {}
    pages_limit = min(int(max_pages or pagination.get("max_pages") or 1), 500)
    user_agent = str(options.get("user_agent") or DEFAULT_USER_AGENT)
    url = source["url"]

    with _open_session(source["fetcher"], options) as session:
        for page_number in range(1, pages_limit + 1):
            if source.get("respect_robots", True) and not _robots_allows(url, user_agent):
                logger.warning("Recolha: robots.txt de %s não permite %s", source["id"], url)
                break
            page = _session_fetch(session, source["fetcher"], url, options)
            if page is None:
                break
            yield page_number, page, _extract_items(page, source)
            next_url = _next_page_url(page, source, url)
            if not next_url:
                break
            url = next_url


# -------------------------------------------------------------------- execução
def _run_dir(source_id: str) -> Path:
    path = RUNS_DIR / source_id
    path.mkdir(parents=True, exist_ok=True)
    return path


def _meta_path(run_id: str, source_id: str) -> Path:
    return _run_dir(source_id) / f"{run_id}.meta.json"


def _items_path(run_id: str, source_id: str) -> Path:
    return _run_dir(source_id) / f"{run_id}.jsonl"


def _save_meta(meta: Dict[str, Any]) -> None:
    path = _meta_path(meta["run_id"], meta["source_id"])
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)


def run_summary(meta: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """Resumo de uma execução (para listagens e para o painel)."""
    if not meta:
        return None
    return {
        "run_id": meta.get("run_id"),
        "source_id": meta.get("source_id"),
        "source_name": meta.get("source_name"),
        "status": meta.get("status"),
        "trigger": meta.get("trigger"),
        "started_at": meta.get("started_at"),
        "finished_at": meta.get("finished_at"),
        "duration_ms": meta.get("duration_ms"),
        "items_count": meta.get("items_count", 0),
        "indexed_count": meta.get("indexed_count", 0),
        "error_count": meta.get("error_count", 0),
        "pages": meta.get("pages", 0),
    }


def start_run(source_id: str, *, trigger: str = "manual") -> Dict[str, Any]:
    """Arranca uma execução em segundo plano e devolve logo o `run_id`."""
    source = get_source(source_id)
    if not source:
        raise KeyError(source_id)
    with _lock:
        if source_id in _active_runs:
            return {
                "run_id": _active_runs[source_id],
                "status": "running",
                "already_running": True,
            }
    run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S") + "-" + uuid.uuid4().hex[:6]
    meta = {
        "run_id": run_id,
        "source_id": source["id"],
        "source_name": source["name"],
        "url": source["url"],
        "fetcher": source["fetcher"],
        "trigger": trigger,
        "status": "running",
        "started_at": _now(),
        "finished_at": None,
        "duration_ms": None,
        "items_count": 0,
        "indexed_count": 0,
        "error_count": 0,
        "pages": 0,
        "errors": [],
    }
    _save_meta(meta)
    _items_path(run_id, source["id"]).touch()
    with _lock:
        _active_runs[source["id"]] = run_id
    thread = threading.Thread(
        target=_execute_run, args=(source, meta), name=f"scraper-{source['id']}", daemon=True
    )
    thread.start()
    return {"run_id": run_id, "status": "running", "source_id": source["id"]}


def execute_run_sync(source_id: str, *, trigger: str = "manual") -> Dict[str, Any]:
    """Executa uma recolha de forma síncrona (usado pelos testes e pelo cron)."""
    source = get_source(source_id)
    if not source:
        raise KeyError(source_id)
    with _lock:
        if source_id in _active_runs:
            return {"run_id": _active_runs[source_id], "status": "running", "already_running": True}
    run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S") + "-" + uuid.uuid4().hex[:6]
    meta = {
        "run_id": run_id,
        "source_id": source["id"],
        "source_name": source["name"],
        "url": source["url"],
        "fetcher": source["fetcher"],
        "trigger": trigger,
        "status": "running",
        "started_at": _now(),
        "finished_at": None,
        "duration_ms": None,
        "items_count": 0,
        "indexed_count": 0,
        "error_count": 0,
        "pages": 0,
        "errors": [],
    }
    _save_meta(meta)
    _items_path(run_id, source["id"]).touch()
    with _lock:
        _active_runs[source["id"]] = run_id
    try:
        return _execute_run(source, meta)
    finally:
        with _lock:
            _active_runs.pop(source["id"], None)


def _execute_run(source: Dict[str, Any], meta: Dict[str, Any]) -> Dict[str, Any]:
    started = time.perf_counter()
    errors: List[str] = []
    items: List[Dict[str, Any]] = []
    pages = 0
    try:
        for page_number, _page, page_items in _walk_source(source):
            pages = page_number
            for item in page_items:
                items.append(item)
                with _items_path(meta["run_id"], source["id"]).open("a", encoding="utf-8") as handle:
                    handle.write(json.dumps(item, ensure_ascii=False) + "\n")
    except Exception as exc:
        errors.append(f"{type(exc).__name__}: {exc}")
        logger.warning("Recolha de %s falhou: %s", source["id"], exc)
    finally:
        try:
            with _lock:
                _active_runs.pop(source["id"], None)
        except Exception:
            pass

    indexed = {"indexed_count": 0, "error_count": 0}
    if items:
        try:
            indexed = index_scraped_items(
                source_id=source["id"],
                source_name=source["name"],
                run_id=meta["run_id"],
                items=items,
                trigger=meta.get("trigger") or "manual",
            )
            if indexed.get("error"):
                errors.append(str(indexed["error"]))
        except Exception as exc:
            errors.append(f"Indexação falhou: {exc}")

    finished = _now()
    meta.update(
        {
            "status": "failed" if errors and not items else "completed",
            "finished_at": finished,
            "duration_ms": int((time.perf_counter() - started) * 1000),
            "items_count": len(items),
            "indexed_count": int(indexed.get("indexed_count") or 0),
            "error_count": int(indexed.get("error_count") or 0) + (1 if indexed.get("error") else 0),
            "pages": pages,
            "errors": errors[:10],
        }
    )
    _save_meta(meta)
    logger.info(
        "Recolha %s (%s): %s itens, %s indexados, %s páginas em %s ms",
        source["id"],
        meta["run_id"],
        meta["items_count"],
        meta["indexed_count"],
        meta["pages"],
        meta["duration_ms"],
    )
    return meta


def preview_source(payload: Dict[str, Any], *, limit: int = 5, max_pages: int = 1) -> Dict[str, Any]:
    """Testa uma definição (mesmo sem a guardar) e devolve uma amostra de itens."""
    source = normalize_source(payload, payload if payload.get("id") else None)
    items: List[Dict[str, Any]] = []
    pages = 0
    try:
        for page_number, page, page_items in _walk_source(source, max_pages=max_pages):
            pages = page_number
            items.extend(page_items)
            if len(items) >= limit:
                break
    except Exception as exc:
        return {
            "ok": False,
            "error": f"{type(exc).__name__}: {exc}",
            "pages": pages,
            "items": items[:limit],
            "total": len(items),
        }
    return {
        "ok": True,
        "pages": pages,
        "total": len(items),
        "items": items[: max(1, min(limit, 50))],
        "fields": [f["name"] for f in source["fields"]],
    }


# --------------------------------------------------------------- histórico
def list_runs(source_id: Optional[str] = None, *, limit: int = 50) -> List[Dict[str, Any]]:
    """Lista as execuções conhecidas (mais recentes primeiro)."""
    _ensure_dirs()
    runs: List[Dict[str, Any]] = []
    pattern = f"{source_id}/*.meta.json" if source_id else "*/*.meta.json"
    for path in RUNS_DIR.glob(pattern):
        try:
            meta = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            continue
        runs.append(meta)
    runs.sort(key=lambda m: str(m.get("started_at") or ""), reverse=True)
    return runs[: max(1, min(limit, 500))]


def get_run(run_id: str, source_id: Optional[str] = None) -> Optional[Dict[str, Any]]:
    for meta in list_runs(source_id, limit=500):
        if meta.get("run_id") == run_id:
            meta = dict(meta)
            meta["running"] = meta.get("source_id") in _active_runs and _active_runs.get(meta["source_id"]) == run_id
            return meta
    return None


def read_run_items(run_id: str, source_id: str, *, limit: int = 100, offset: int = 0) -> Dict[str, Any]:
    """Lê os itens gravados em JSONL para uma execução."""
    path = _items_path(run_id, source_id)
    if not path.exists():
        return {"run_id": run_id, "total": 0, "items": []}
    items: List[Dict[str, Any]] = []
    total = 0
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            total += 1
            if total <= offset:
                continue
            if len(items) >= limit:
                continue
            try:
                items.append(json.loads(line))
            except Exception:
                continue
    return {"run_id": run_id, "total": total, "items": items, "offset": offset}


def search_items(**kwargs: Any) -> Dict[str, Any]:
    """Pesquisa itens recolhidos no Elasticsearch (ver `elasticsearch_client`)."""
    return search_scraped(**kwargs)


def stats() -> Dict[str, Any]:
    """Resumo do módulo para a UI (fontes, execuções e volumetria)."""
    sources = list_sources()
    runs = list_runs(limit=200)
    completed = [r for r in runs if r.get("status") == "completed"]
    by_source: Dict[str, int] = {}
    for run in runs:
        by_source[run.get("source_id", "")] = by_source.get(run.get("source_id", ""), 0) + int(
            run.get("items_count") or 0
        )
    return {
        "sources_total": len(sources),
        "sources_enabled": len([s for s in sources if s.get("enabled")]),
        "runs_total": len(runs),
        "runs_completed": len(completed),
        "items_scraped": sum(int(r.get("items_count") or 0) for r in runs),
        "items_indexed": sum(int(r.get("indexed_count") or 0) for r in runs),
        "items_by_source": by_source,
        "last_run": run_summary(runs[0]) if runs else None,
        "active_runs": dict(_active_runs),
    }
