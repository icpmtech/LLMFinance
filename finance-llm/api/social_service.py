"""Serviço de **pesquisa social** do IQ OS (LinkedIn, TikTok, Reddit, Facebook).

Este módulo é o equivalente do `scraper_service`, mas para redes sociais: em vez
de seletores de HTML, guarda **canais** (definições do tipo «a página X do
LinkedIn», «a comunidade Y do Reddit», «a hashtag Z do TikTok») e usa os
coletores de `social_collectors` — que falam as APIs/oEmbed/JSON-LD de cada
plataforma — para trazer publicações normalizadas.

Conceitos
---------
- **Canal** (`channel`): a definição — plataforma, variante (`kind`), alvo
  (`target`), credenciais/proxy (nas `options`), limite, etiquetas, bloco de
  sentimento e agenda cron. Vivem em `data/social/channels.json`.
- **Execução** (`run`): uma recolha. As publicações ficam em
  `data/social/runs/<canal>/<run_id>.jsonl` e os metadados em `<run_id>.meta.json`.
- **Publicação**: o item normalizado. O `item_id`
  (`sha1(plataforma|tipo|alvo|id)`) é o `_id` no índice `finance_social`, pelo que
  repetir a recolha **atualiza** as métricas em vez de duplicar.

Tudo degrada com elegância: uma plataforma que peça credenciais, que bloqueie o
IP ou que esteja em baixo produz um estado explicativo no canal — sem derrubar a
API nem os restantes canais.
"""
from __future__ import annotations

import hashlib
import json
import logging
import platform as platform_module
import re
import sys
import threading
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from api import scraper_sentiment
from api import social_collectors as collectors
from api.elasticsearch_client import (
    ROOT,
    delete_social_channel,
    get_es_client,
    index_social_items,
    search_social,
    social_status,
)
from api.scraper_service import validate_cron

logger = logging.getLogger(__name__)

SOCIAL_DIR = ROOT / "data" / "social"
CHANNELS_FILE = SOCIAL_DIR / "channels.json"
RUNS_DIR = SOCIAL_DIR / "runs"

CHANNELS_VERSION = 1

#: Presets de cron mostrados na UI (expressão → descrição).
CRON_PRESETS = [
    {"cron": "*/30 * * * *", "label": "A cada 30 minutos"},
    {"cron": "0 * * * *", "label": "De hora a hora"},
    {"cron": "0 */6 * * *", "label": "A cada 6 horas"},
    {"cron": "0 8 * * *", "label": "Todos os dias às 08:00"},
    {"cron": "0 8 * * 1-5", "label": "Dias úteis às 08:00"},
    {"cron": "0 9 * * 1", "label": "Todas as segundas às 09:00"},
]

#: Estados possíveis de uma execução (o que a UI mostra).
RUN_STATUSES = ("running", "ok", "empty", "credentials", "blocked", "error")

#: Chaves de `options` que são segredos e nunca saem mascaradas para a UI.
_SECRET_KEY_RE = re.compile(r"(token|secret|password|passwd|api_?key|credentials|session|cookie)", re.I)

#: Sentimento por omissão: léxico local (não gasta tokens de IA e é imediato).
_DEFAULT_SENTIMENT = {
    **scraper_sentiment.DEFAULT_CONFIG,
    "enabled": True,
    "engine": "lexicon",
    "max_items": 40,
    "field": "text",
}

_DEFAULTS: Dict[str, Any] = {
    "platform": "linkedin",
    "kind": "company",
    "target": "",
    "enabled": False,
    "limit": collectors.DEFAULT_LIMIT,
    "options": {},
    "schedule": {"cron": "", "timezone": "Europe/Lisbon"},
    "tags": [],
    "sentiment": dict(_DEFAULT_SENTIMENT),
    "notes": "",
}

_lock = threading.RLock()
_active_runs: Dict[str, str] = {}


# --------------------------------------------------------------------- estado
def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _ensure_dirs() -> None:
    SOCIAL_DIR.mkdir(parents=True, exist_ok=True)
    RUNS_DIR.mkdir(parents=True, exist_ok=True)


#: Canais de arranque: cobrem as quatro plataformas e ficam **por ligar**
#: (o utilizador liga o interruptor quando quiser que o cron os recolha).
def _example_channels() -> List[Dict[str, Any]]:
    return [
        {
            "id": "linkedin-microsoft",
            "name": "LinkedIn · Microsoft",
            "description": "Publicações públicas da página da Microsoft no LinkedIn.",
            "platform": "linkedin",
            "kind": "company",
            "target": "microsoft",
            "enabled": False,
            "limit": 25,
            "schedule": {"cron": "0 */6 * * *", "timezone": "Europe/Lisbon"},
            "tags": ["linkedin", "tecnologia"],
        },
        {
            "id": "reddit-investimentos",
            "name": "Reddit · r/investimentos",
            "description": "Publicações em destaque da comunidade r/investimentos.",
            "platform": "reddit",
            "kind": "subreddit",
            "target": "investimentos",
            "enabled": False,
            "limit": 25,
            "schedule": {"cron": "0 */6 * * *", "timezone": "Europe/Lisbon"},
            "tags": ["reddit", "investimentos"],
        },
        {
            "id": "tiktok-edp",
            "name": "TikTok · #edp",
            "description": "Métricas e vídeos em destaque da hashtag #edp.",
            "platform": "tiktok",
            "kind": "hashtag",
            "target": "edp",
            "enabled": False,
            "limit": 25,
            "schedule": {"cron": "0 8 * * *", "timezone": "Europe/Lisbon"},
            "tags": ["tiktok", "energia"],
        },
        {
            "id": "facebook-exemplo",
            "name": "Facebook · página (exemplo)",
            "description": "Publicações de uma página do Facebook (exige token da Graph API).",
            "platform": "facebook",
            "kind": "page",
            "target": "nasa",
            "enabled": False,
            "limit": 25,
            "schedule": {"cron": "0 8 * * *", "timezone": "Europe/Lisbon"},
            "tags": ["facebook"],
        },
    ]


def _load() -> Dict[str, Any]:
    """Lê o ficheiro de canais (cria-o com os exemplos na 1.ª vez)."""
    _ensure_dirs()
    if not CHANNELS_FILE.exists():
        payload = {"version": CHANNELS_VERSION, "channels": _example_channels()}
        _write(payload)
        return payload
    try:
        data = json.loads(CHANNELS_FILE.read_text(encoding="utf-8"))
    except Exception as exc:
        logger.warning("Canais sociais: ficheiro ilegível (%s); a recomeçar.", exc)
        return {"version": CHANNELS_VERSION, "channels": []}
    if isinstance(data, list):
        return {"version": CHANNELS_VERSION, "channels": data}
    if not isinstance(data, dict):
        return {"version": CHANNELS_VERSION, "channels": []}
    data.setdefault("version", CHANNELS_VERSION)
    data.setdefault("channels", [])
    return data


def _write(payload: Dict[str, Any]) -> None:
    _ensure_dirs()
    tmp = CHANNELS_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    tmp.replace(CHANNELS_FILE)


# ------------------------------------------------------------------ definições
def _slug(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", (value or "").strip().lower()).strip("-")


def _is_secret(key: str) -> bool:
    return bool(_SECRET_KEY_RE.search(key or ""))


def _mask_options(options: Dict[str, Any]) -> Dict[str, Any]:
    """Opções prontas para a UI: os segredos passam a «definido»/«não definido»."""
    masked: Dict[str, Any] = {}
    for key, value in (options or {}).items():
        if _is_secret(key):
            masked[key] = "••••••" if value else ""
        else:
            masked[key] = value
    return masked


def credentials_state(channel: Dict[str, Any]) -> Dict[str, Any]:
    """Diz se o canal tem as credenciais que a sua variante exige."""
    platform = str(channel.get("platform") or "")
    kind = str(channel.get("kind") or "")
    options = channel.get("options") or {}
    definition = (collectors.PLATFORMS.get(platform) or {}).get("kinds", {}).get(kind) or {}
    needs = bool(definition.get("credentials"))
    names = collectors.credential_names(platform)
    provided = [name for name in names if options.get(name)]
    if not needs:
        return {"required": False, "ok": True, "provided": provided, "missing": []}
    # Basta uma das formas de credencial; se nenhuma vier nas opções, o coletor
    # ainda pode encontrá-la no ambiente — só o estado «não definido» é claro.
    ok = bool(provided)
    return {
        "required": True,
        "ok": ok,
        "provided": provided,
        "missing": [] if ok else list(names),
        "hint": (collectors.PLATFORMS.get(platform) or {}).get("credential_hint", ""),
    }


def normalize_channel(payload: Dict[str, Any], existing: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Valida e normaliza um canal (aceita alterações parciais)."""
    base = dict(existing or {})
    merged: Dict[str, Any] = {**_DEFAULTS, **base, **(payload or {})}

    platform = str(merged.get("platform") or "").strip().lower()
    kind = str(merged.get("kind") or "").strip().lower()
    target = str(merged.get("target") or "").strip()
    try:
        collectors.validate_channel_definition(platform, kind, target)
    except collectors.CollectorError as exc:
        raise ValueError(str(exc)) from exc
    merged["platform"] = platform
    merged["kind"] = kind
    merged["target"] = target

    channel_id = str(merged.get("id") or "").strip()
    if not channel_id:
        stem = _slug(f"{platform}-{kind}-{target}")[:40]
        channel_id = f"{stem or platform}-{uuid.uuid4().hex[:6]}"
    merged["id"] = channel_id

    label = (collectors.PLATFORMS.get(platform) or {}).get("label", platform)
    merged["name"] = str(merged.get("name") or "").strip() or f"{label} · {target}"
    merged["description"] = str(merged.get("description") or "").strip()
    merged["notes"] = str(merged.get("notes") or "").strip()
    merged["enabled"] = bool(merged.get("enabled", False))

    try:
        merged["limit"] = max(1, min(int(merged.get("limit") or collectors.DEFAULT_LIMIT), collectors.MAX_LIMIT))
    except (TypeError, ValueError):
        merged["limit"] = collectors.DEFAULT_LIMIT

    options = {k: v for k, v in (merged.get("options") or {}).items() if v not in (None, "")}
    merged["options"] = options

    merged["tags"] = [str(t).strip() for t in (merged.get("tags") or []) if str(t).strip()]

    schedule = merged.get("schedule") or {}
    cron = str(schedule.get("cron") or "").strip()
    timezone_name = str(schedule.get("timezone") or "Europe/Lisbon").strip()
    if cron:
        validate_cron(cron)
    merged["schedule"] = {"cron": cron, "timezone": timezone_name}

    merged["sentiment"] = scraper_sentiment.normalize_config(merged.get("sentiment"))

    merged["created_at"] = base.get("created_at") or _now()
    merged["updated_at"] = _now()
    return merged


def channel_public(channel: Dict[str, Any], *, with_credentials: bool = False) -> Dict[str, Any]:
    """Canal pronto para a API: segredos mascarados e estado das credenciais."""
    public = dict(channel)
    options = dict(public.get("options") or {})
    public["options"] = _mask_options(options) if not with_credentials else options
    credentials = credentials_state(channel)
    public["credentials"] = credentials
    public["requires_credentials"] = credentials["required"]
    definition = (collectors.PLATFORMS.get(channel.get("platform")) or {}).get("kinds", {}).get(channel.get("kind")) or {}
    public["kind_label"] = definition.get("label", channel.get("kind"))
    public["platform_label"] = (collectors.PLATFORMS.get(channel.get("platform")) or {}).get(
        "label", channel.get("platform")
    )
    public["kind_notes"] = definition.get("notes", "")
    return public


def list_channels(*, include_disabled: bool = True) -> List[Dict[str, Any]]:
    channels = _load().get("channels") or []
    if not include_disabled:
        channels = [c for c in channels if c.get("enabled")]
    return [channel_public(channel) for channel in channels]


def get_channel(channel_id: str, *, raw: bool = False) -> Optional[Dict[str, Any]]:
    for channel in _load().get("channels") or []:
        if channel.get("id") == channel_id:
            return channel if raw else channel_public(channel)
    return None


def _must_exist(channel_id: str) -> Dict[str, Any]:
    channel = get_channel(channel_id, raw=True)
    if not channel:
        raise KeyError(channel_id)
    return channel


def _notify_scheduler() -> None:
    """Reaplica os canais ao agendador (import tardio, para não haver ciclo)."""
    try:
        from api import social_scheduler

        social_scheduler.reload_jobs()
    except Exception as exc:  # pragma: no cover - só em ambientes sem APScheduler
        logger.debug("Agendador social não recarregado: %s", exc)


def upsert_channel(payload: Dict[str, Any]) -> Dict[str, Any]:
    """Cria ou atualiza um canal, preservando histórico/identidade."""
    with _lock:
        store = _load()
        channels: List[Dict[str, Any]] = store.get("channels") or []
        channel_id = str(payload.get("id") or "").strip()
        index = next((i for i, c in enumerate(channels) if c.get("id") == channel_id), None)
        existing = channels[index] if index is not None else None
        if channel_id and existing is None and payload.get("_must_exist"):
            raise KeyError(channel_id)
        channel = normalize_channel(payload, existing)
        if existing is not None:
            channels[index] = channel
        else:
            if any(c.get("id") == channel["id"] for c in channels):
                channel["id"] = f"{channel['id']}-{uuid.uuid4().hex[:4]}"
            channels.append(channel)
        store["channels"] = channels
        _write(store)
    _notify_scheduler()
    return get_channel(channel["id"]) or channel_public(channel)


def delete_channel(channel_id: str, *, purge_items: bool = False) -> Dict[str, Any]:
    """Apaga um canal (e, se pedido, as suas publicações do índice)."""
    with _lock:
        store = _load()
        channels: List[Dict[str, Any]] = store.get("channels") or []
        remaining = [c for c in channels if c.get("id") != channel_id]
        if len(remaining) == len(channels):
            raise KeyError(channel_id)
        store["channels"] = remaining
        _write(store)
    purged = delete_social_channel(channel_id) if purge_items else {}
    _notify_scheduler()
    return {"id": channel_id, "deleted": True, "purged": purged}


# ------------------------------------------------------------------ ambiente
def availability() -> Dict[str, Any]:
    """Diagnóstico do ambiente desta recolha (HTTP, Scrapling/browsers, ES, cron)."""
    info: Dict[str, Any] = {
        "python": sys.executable,
        "python_version": platform_module.python_version(),
        "http_client": None,
        "scrapling": False,
        "browsers": False,
        "elasticsearch": False,
        "indexed_items": 0,
        "platforms": collectors.platform_catalog(),
    }
    try:
        import httpx

        info["http_client"] = getattr(httpx, "__version__", "instalado")
    except Exception as exc:  # pragma: no cover
        info["http_client_error"] = str(exc)

    try:
        from api import scraper_service

        scraper_info = scraper_service.availability()
        info["scrapling"] = bool(scraper_info.get("scrapling"))
        info["browsers"] = bool(scraper_info.get("browsers"))
        info["scrapling_version"] = scraper_info.get("scrapling_version")
    except Exception as exc:
        info["scrapling_error"] = str(exc)

    client = get_es_client()
    if client:
        status = social_status(client)
        info["elasticsearch"] = bool(status.get("available"))
        info["indexed_items"] = status.get("total", 0)
        info["indexed_platforms"] = status.get("platforms", [])
        info["indexed_channels"] = status.get("channels", [])

    scheduler: Dict[str, Any] = {"available": False}
    try:
        from api import social_scheduler

        scheduler = social_scheduler.status()
    except Exception:
        pass
    info["scheduler"] = scheduler
    proxy = collectors._proxy_for({})  # noqa: SLF001 - diagnóstico explícito
    info["proxy_configured"] = bool(proxy)
    return info


# ------------------------------------------------------------------ execução
def _run_dir(channel_id: str) -> Path:
    path = RUNS_DIR / channel_id
    path.mkdir(parents=True, exist_ok=True)
    return path


def _meta_path(run_id: str, channel_id: str) -> Path:
    return _run_dir(channel_id) / f"{run_id}.meta.json"


def _items_path(run_id: str, channel_id: str) -> Path:
    return _run_dir(channel_id) / f"{run_id}.jsonl"


def _save_meta(meta: Dict[str, Any]) -> None:
    path = _meta_path(meta["run_id"], meta["channel_id"])
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(meta, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    tmp.replace(path)


def run_summary(meta: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """Metadados de uma execução prontos para a UI (com o canal identificado)."""
    if not meta:
        return None
    counters = sorted(
        [
            {"key": "likes", "count": int(meta.get("likes") or 0)},
            {"key": "comments", "count": int(meta.get("comments") or 0)},
            {"key": "views", "count": int(meta.get("views") or 0)},
            {"key": "shares", "count": int(meta.get("shares") or 0)},
        ],
        key=lambda row: row["count"],
        reverse=True,
    )
    return {
        **meta,
        "source_id": meta.get("channel_id"),
        "source_name": meta.get("channel_name"),
        "items": int(meta.get("items_count") or 0),
        "counters": [row for row in counters if row["count"]],
    }


def _new_meta(channel: Dict[str, Any], run_id: str, trigger: str, status: str = "running") -> Dict[str, Any]:
    return {
        "run_id": run_id,
        "channel_id": channel["id"],
        "channel_name": channel.get("name") or channel["id"],
        "platform": channel.get("platform"),
        "kind": channel.get("kind"),
        "target": channel.get("target"),
        "trigger": trigger,
        "status": status,
        "started_at": _now(),
        "finished_at": None,
        "items_count": 0,
        "indexed_count": 0,
        "index_error": None,
        "notes": [],
        "error": None,
        "hint": None,
        "sentiment_count": 0,
        "likes": 0,
        "comments": 0,
        "views": 0,
        "shares": 0,
        "seconds": None,
        "user_id": None,
    }


def _aggregate_metrics(items: List[Dict[str, Any]]) -> Dict[str, int]:
    totals = {"likes": 0, "comments": 0, "views": 0, "shares": 0}
    for item in items:
        metrics = item.get("metrics") or {}
        for key in totals:
            try:
                totals[key] += int(metrics.get(key) or 0)
            except (TypeError, ValueError):
                continue
    return totals


def _execute_run(channel: Dict[str, Any], meta: Dict[str, Any], user_id: Optional[str] = None) -> Dict[str, Any]:
    """Corre um canal: recolhe, classifica o sentimento, grava e indexa."""
    started = time.time()
    meta["status"] = "running"
    if user_id:
        meta["user_id"] = user_id
    _save_meta(meta)

    try:
        result = collectors.collect(channel, limit=int(channel.get("limit") or collectors.DEFAULT_LIMIT))
    except collectors.CollectorError as exc:
        meta["status"] = exc.status if exc.status in RUN_STATUSES else "error"
        meta["error"] = str(exc)
        meta["hint"] = exc.hint or None
        meta["finished_at"] = _now()
        meta["seconds"] = round(time.time() - started, 2)
        _save_meta(meta)
        logger.warning("Recolha social %s: %s (%s)", channel["id"], exc, exc.status)
        return meta
    except Exception as exc:  # pragma: no cover - rede/parsing inesperado
        logger.exception("Recolha social %s falhou", channel["id"])
        meta["status"] = "error"
        meta["error"] = f"{type(exc).__name__}: {exc}"
        meta["finished_at"] = _now()
        meta["seconds"] = round(time.time() - started, 2)
        _save_meta(meta)
        return meta

    items: List[Dict[str, Any]] = result.get("items") or []

    # Sentimento (léxico local por omissão; IA quando o canal o pedir).
    try:
        counters = scraper_sentiment.analyze_items(items, channel.get("sentiment") or {}, user_id=user_id)
    except Exception as exc:
        logger.debug("Sentimento dos itens sociais falhou: %s", exc)
        counters = {}
    for key, value in (counters or {}).items():
        if value:
            meta[key] = value

    run_id = meta["run_id"]
    items_path = _items_path(run_id, channel["id"])
    with items_path.open("w", encoding="utf-8") as handle:
        for item in items:
            payload = {**item, "run_id": run_id}
            handle.write(json.dumps(payload, ensure_ascii=False, default=str) + "\n")

    indexing = index_social_items(channel, items, trigger=str(meta.get("trigger") or "manual"))
    meta["indexed_count"] = int(indexing.get("indexed_count") or 0)
    meta["index_error"] = indexing.get("error")

    meta.update(_aggregate_metrics(items))
    meta["items_count"] = len(items)
    meta["notes"] = list(result.get("notes") or [])
    if result.get("organization"):
        meta["organization"] = result["organization"]
    meta["status"] = "ok" if items else "empty"
    meta["finished_at"] = _now()
    meta["seconds"] = round(time.time() - started, 2)
    _save_meta(meta)
    logger.info(
        "Recolha social %s: %s itens (%s indexados) em %.1fs",
        channel["id"],
        len(items),
        meta["indexed_count"],
        meta["seconds"],
    )
    return meta


def execute_run_sync(
    channel_id: str, *, trigger: str = "manual", user_id: Optional[str] = None
) -> Dict[str, Any]:
    """Executa um canal e espera pelo resultado (usado pelo cron e pela UI)."""
    channel = _must_exist(channel_id)
    run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S") + "-" + uuid.uuid4().hex[:6]
    meta = _new_meta(channel, run_id, trigger)
    with _lock:
        _active_runs[channel_id] = run_id
    try:
        return _execute_run(channel, meta, user_id=user_id)
    finally:
        with _lock:
            _active_runs.pop(channel_id, None)


def start_run(channel_id: str, *, trigger: str = "manual", user_id: Optional[str] = None) -> Dict[str, Any]:
    """Lança a recolha em segundo plano e devolve já os metadados da execução.

    A UI pede o estado por `GET /social/runs/{run_id}` enquanto a recolha corre.
    """
    channel = _must_exist(channel_id)
    with _lock:
        if channel_id in _active_runs:
            return {"already_running": True, "run_id": _active_runs[channel_id], "status": "running"}
        run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S") + "-" + uuid.uuid4().hex[:6]
        meta = _new_meta(channel, run_id, trigger, status="running")
        _save_meta(meta)
        _active_runs[channel_id] = run_id

        def _worker() -> None:
            try:
                _execute_run(channel, meta, user_id=user_id)
            finally:
                with _lock:
                    _active_runs.pop(channel_id, None)

    thread = threading.Thread(target=_worker, name=f"social-{channel_id}", daemon=True)
    thread.start()
    return {"started": True, "run_id": run_id, "status": "running", "meta": run_summary(meta)}


def preview_channel(payload: Dict[str, Any], *, limit: int = 5) -> Dict[str, Any]:
    """Testa uma definição **sem guardar**: recolhe uma amostra e devolve-a."""
    try:
        channel = normalize_channel(payload)
    except ValueError as exc:
        return {"ok": False, "status": "definition", "error": str(exc), "items": [], "notes": []}

    if get_channel(channel["id"], raw=True):
        channel["id"] = f"{channel['id']}-preview"

    started = time.time()
    try:
        result = collectors.collect(channel, limit=max(1, min(int(limit), collectors.MAX_LIMIT)))
    except collectors.CollectorError as exc:
        return {
            "ok": False,
            "status": exc.status,
            "error": str(exc),
            "hint": exc.hint,
            "items": [],
            "notes": [],
            "seconds": round(time.time() - started, 2),
            "channel": channel_public(channel),
        }
    except Exception as exc:
        return {
            "ok": False,
            "status": "error",
            "error": f"{type(exc).__name__}: {exc}",
            "items": [],
            "notes": [],
            "seconds": round(time.time() - started, 2),
            "channel": channel_public(channel),
        }

    items = result.get("items") or []
    try:
        scraper_sentiment.analyze_items(items, channel.get("sentiment") or {})
    except Exception as exc:
        logger.debug("Sentimento da amostra social falhou: %s", exc)
    return {
        "ok": True,
        "status": "ok" if items else "empty",
        "items": items,
        "notes": result.get("notes") or [],
        "organization": result.get("organization") or {},
        "count": len(items),
        "seconds": round(time.time() - started, 2),
        "channel": channel_public(channel),
    }


def list_runs(channel_id: Optional[str] = None, *, limit: int = 50) -> List[Dict[str, Any]]:
    """Histórico de execuções (mais recentes primeiro)."""
    metas: List[Dict[str, Any]] = []
    directories = [_run_dir(channel_id)] if channel_id else [path for path in RUNS_DIR.glob("*") if path.is_dir()]
    for directory in directories:
        for path in directory.glob("*.meta.json"):
            try:
                metas.append(json.loads(path.read_text(encoding="utf-8")))
            except Exception:
                continue
    metas.sort(key=lambda m: str(m.get("started_at") or ""), reverse=True)
    return [summary for summary in (run_summary(meta) for meta in metas[: max(1, limit)]) if summary]


def get_run(run_id: str, channel_id: Optional[str] = None) -> Optional[Dict[str, Any]]:
    directories = [_run_dir(channel_id)] if channel_id else [path for path in RUNS_DIR.glob("*") if path.is_dir()]
    for directory in directories:
        path = directory / f"{run_id}.meta.json"
        if path.exists():
            try:
                return run_summary(json.loads(path.read_text(encoding="utf-8")))
            except Exception:
                return None
    return None


def read_run_items(run_id: str, channel_id: str, *, limit: int = 100, offset: int = 0) -> Dict[str, Any]:
    """Lê as publicações gravadas de uma execução (do JSONL)."""
    path = _items_path(run_id, channel_id)
    if not path.exists():
        raise KeyError(run_id)
    items: List[Dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as handle:
        for index, line in enumerate(handle):
            if index < offset:
                continue
            if len(items) >= limit:
                break
            line = line.strip()
            if not line:
                continue
            try:
                items.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    meta = get_run(run_id, channel_id) or {}
    return {"run_id": run_id, "items": items, "count": len(items), "total": int(meta.get("items_count") or 0)}


# ------------------------------------------------------------------ pesquisa
def search_items(**kwargs: Any) -> Dict[str, Any]:
    """Pesquisa publicações sociais no índice (delega no cliente ES)."""
    return search_social(**kwargs)


def stats() -> Dict[str, Any]:
    """Resumo do módulo para o painel: canais, execuções e volumetria."""
    channels = _load().get("channels") or []
    runs = list_runs(limit=500)
    by_status: Dict[str, int] = {}
    by_platform: Dict[str, int] = {}
    for run in runs:
        by_status[run.get("status") or "?"] = by_status.get(run.get("status") or "?", 0) + 1
    for channel in channels:
        platform = channel.get("platform") or "?"
        by_platform[platform] = by_platform.get(platform, 0) + 1
    client = get_es_client()
    indexed = social_status(client) if client else {"total": 0, "platforms": []}
    return {
        "channels": len(channels),
        "channels_enabled": sum(1 for c in channels if c.get("enabled")),
        "channels_by_platform": [{"key": k, "count": v} for k, v in sorted(by_platform.items())],
        "runs": len(runs),
        "runs_by_status": [{"key": k, "count": v} for k, v in sorted(by_status.items())],
        "last_run": runs[0] if runs else None,
        "indexed": indexed,
        "cron_presets": CRON_PRESETS,
    }


def templates() -> List[Dict[str, Any]]:
    """Canais prontos a criar (galeria da UI), por plataforma."""
    return [
        {
            "id": "linkedin-empresa",
            "name": "LinkedIn · página de empresa",
            "platform": "linkedin",
            "kind": "company",
            "target": "microsoft",
            "description": "Publicações públicas da página de uma empresa no LinkedIn (sem credenciais).",
            "requires_credentials": False,
            "cron": "0 */6 * * *",
            "tags": ["linkedin"],
        },
        {
            "id": "reddit-comunidade",
            "name": "Reddit · comunidade",
            "platform": "reddit",
            "kind": "subreddit",
            "target": "investimentos",
            "description": "Publicações em destaque de um subreddit (sem credenciais).",
            "requires_credentials": False,
            "cron": "0 */6 * * *",
            "tags": ["reddit"],
        },
        {
            "id": "reddit-pesquisa",
            "name": "Reddit · pesquisa por palavra-chave",
            "platform": "reddit",
            "kind": "search",
            "target": "EDP",
            "description": "Pesquisa no Reddit por termo (exige client_id/client_secret da API OAuth).",
            "requires_credentials": True,
            "cron": "0 */6 * * *",
            "tags": ["reddit", "pesquisa"],
        },
        {
            "id": "tiktok-hashtag",
            "name": "TikTok · hashtag",
            "platform": "tiktok",
            "kind": "hashtag",
            "target": "edp",
            "description": "Métricas da hashtag e vídeos em destaque (sem credenciais).",
            "requires_credentials": False,
            "cron": "0 8 * * *",
            "tags": ["tiktok"],
        },
        {
            "id": "tiktok-video",
            "name": "TikTok · vídeo",
            "platform": "tiktok",
            "kind": "video",
            "target": "https://www.tiktok.com/@tiktok/video/6718335390845095173",
            "description": "Metadados de um vídeo concreto pelo oembed oficial (sem credenciais).",
            "requires_credentials": False,
            "cron": "",
            "tags": ["tiktok", "video"],
        },
        {
            "id": "facebook-pagina",
            "name": "Facebook · página",
            "platform": "facebook",
            "kind": "page",
            "target": "nasa",
            "description": "Publicações de uma página do Facebook (exige token da Graph API).",
            "requires_credentials": True,
            "cron": "0 8 * * *",
            "tags": ["facebook"],
        },
    ]


def channel_from_template(template_id: str, overrides: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Definição de canal pronta a guardar, a partir de um template da galeria."""
    entry = next((t for t in templates() if t["id"] == template_id), None)
    if not entry:
        raise KeyError(template_id)
    payload: Dict[str, Any] = {
        "platform": entry["platform"],
        "kind": entry["kind"],
        "target": entry["target"],
        "name": entry["name"],
        "description": entry["description"],
        "tags": list(entry.get("tags") or []),
        "schedule": {"cron": entry.get("cron") or "", "timezone": "Europe/Lisbon"},
    }
    overrides = dict(overrides or {})
    overrides.pop("id", None)
    for key, value in overrides.items():
        if isinstance(value, dict) and isinstance(payload.get(key), dict):
            merged = dict(payload[key])
            merged.update({k: v for k, v in value.items() if v not in (None, "")})
            payload[key] = merged
        elif value not in (None, ""):
            payload[key] = value
    channel = normalize_channel(payload)
    channel["template_id"] = template_id
    return channel_public(channel)


def fingerprint(channel: Dict[str, Any]) -> str:
    """Impressão digital da definição (para saber quando o cron deve ser reaplicado)."""
    relevant = {k: channel.get(k) for k in ("platform", "kind", "target", "limit", "enabled")}
    return hashlib.sha1(json.dumps(relevant, sort_keys=True, default=str).encode("utf-8")).hexdigest()[:16]
