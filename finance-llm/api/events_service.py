"""Registo de eventos do sistema («event logger»).

Cada evento é uma linha com o momento, o nível, a origem, a mensagem e o
contexto (utilizador, pedido HTTP, duração, dados extra). O registo tem três
destinos complementares, para o visualizador da área de administração funcionar
mesmo com o Elasticsearch em baixo:

1. **Memória** — `deque` circular (últimos 2000 eventos), sempre disponível.
2. **Ficheiro** — `logs/events.jsonl` (uma linha JSON por evento), com rotação
   simples por tamanho; permite consultar o histórico depois de reiniciar.
3. **Elasticsearch** — índice `finance_events` (pesquisável, agregações); só se
   escrevem os eventos relevantes (autenticação/administração e nível ≥ warning)
   para não duplicar o volume de pedidos nem pesar a API.

Nenhuma função deste módulo lança exceções: um problema a registar um evento
nunca pode derrubar o pedido que o originou.
"""
from __future__ import annotations

import json
import logging
import os
import platform
import socket
from collections import deque
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Deque, Dict, Iterable, List, Optional

from api.elasticsearch_client import EVENTS_INDEX, ROOT, ensure_indices, get_es_client

logger = logging.getLogger(__name__)

LEVELS = ("debug", "info", "warning", "error", "critical")
LEVEL_RANK = {level: index for index, level in enumerate(LEVELS)}

# Origens que ficam sempre no Elasticsearch (auditoria de segurança).
ALWAYS_INDEXED_SOURCES = {"auth", "admin"}

LOG_DIR = ROOT / "logs"
EVENTS_FILE = LOG_DIR / "events.jsonl"
MAX_FILE_BYTES = 5 * 1024 * 1024
BUFFER_SIZE = 2000

_buffer: Deque[Dict[str, Any]] = deque(maxlen=BUFFER_SIZE)
_host = socket.gethostname()
_pid = os.getpid()

TEXT_LOG_EXTENSIONS = (".log", ".err", ".out", ".jsonl", ".txt")


# ------------------------------------------------------------------ utilidades
def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(moment: datetime) -> str:
    return moment.replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _client_ip(request: Any) -> str:
    if request is None:
        return ""
    try:
        forwarded = request.headers.get("x-forwarded-for") or ""
        if forwarded:
            return forwarded.split(",")[0].strip()
        return request.client.host if request.client else ""
    except Exception:
        return ""


def _user_agent(request: Any) -> str:
    if request is None:
        return ""
    try:
        return request.headers.get("user-agent") or ""
    except Exception:
        return ""


def _rotate_if_needed() -> None:
    try:
        if EVENTS_FILE.exists() and EVENTS_FILE.stat().st_size > MAX_FILE_BYTES:
            backup = EVENTS_FILE.with_suffix(".jsonl.1")
            backup.unlink(missing_ok=True)
            EVENTS_FILE.rename(backup)
    except Exception:
        pass


def _append_file(document: Dict[str, Any]) -> None:
    try:
        LOG_DIR.mkdir(parents=True, exist_ok=True)
        _rotate_if_needed()
        with open(EVENTS_FILE, "a", encoding="utf-8") as handle:
            handle.write(json.dumps(document, ensure_ascii=False, default=str) + "\n")
    except Exception:
        pass


def _should_index(document: Dict[str, Any]) -> bool:
    if document.get("source") in ALWAYS_INDEXED_SOURCES:
        return True
    return LEVEL_RANK.get(str(document.get("level")), 1) >= LEVEL_RANK["warning"]


def _index(document: Dict[str, Any]) -> None:
    try:
        client = get_es_client()
        if not client:
            return
        ensure_indices(client)
        client.index(index=EVENTS_INDEX, document=document)
    except Exception:
        # Elasticsearch indisponível: o evento continua na memória e no ficheiro.
        pass


# -------------------------------------------------------------------- escrita
def log_event(
    level: str,
    source: str,
    message: str,
    *,
    data: Optional[Dict[str, Any]] = None,
    user_id: Optional[str] = None,
    user_email: Optional[str] = None,
    request: Any = None,
    method: Optional[str] = None,
    path: Optional[str] = None,
    status: Optional[int] = None,
    duration_ms: Optional[float] = None,
) -> Dict[str, Any]:
    """Regista um evento e devolve o documento criado (nunca lança)."""
    normalized = (level or "info").lower()
    if normalized not in LEVEL_RANK:
        normalized = "info"

    document: Dict[str, Any] = {
        "timestamp": _iso(_now()),
        "level": normalized,
        "source": (source or "app").strip().lower() or "app",
        "message": str(message or "").strip()[:4000],
        "host": _host,
        "pid": _pid,
    }
    if data:
        document["data"] = json.loads(json.dumps(data, ensure_ascii=False, default=str)) if not isinstance(data, dict) else data
    if user_id:
        document["user_id"] = str(user_id)
    if user_email:
        document["user_email"] = str(user_email)
    if request is not None:
        document["ip"] = _client_ip(request)
        document["user_agent"] = _user_agent(request)[:512]
        document["path"] = document.get("path") or getattr(request, "url", None) and request.url.path
        document["method"] = document.get("method") or getattr(request, "method", None)
    if method:
        document["method"] = method
    if path:
        document["path"] = path
    if status is not None:
        document["status"] = int(status)
    if duration_ms is not None:
        document["duration_ms"] = round(float(duration_ms), 1)

    _buffer.append(document)
    _append_file(document)
    if _should_index(document):
        _index(document)
    return document


def log_request(
    request: Any,
    *,
    status: int,
    duration_ms: float,
    user_id: Optional[str] = None,
    user_email: Optional[str] = None,
) -> None:
    """Regista um pedido HTTP, com o nível derivado do código de resposta."""
    if status >= 500:
        level = "error"
    elif status >= 400:
        level = "warning"
    elif status >= 300:
        level = "info"
    else:
        level = "debug"

    path = getattr(getattr(request, "url", None), "path", "") or ""
    log_event(
        level,
        "api",
        f"{request.method} {path} → {status}",
        request=request,
        method=request.method,
        path=path,
        status=status,
        duration_ms=duration_ms,
        user_id=user_id,
        user_email=user_email,
    )


# -------------------------------------------------------------------- leitura
def _buffer_search(
    *,
    level: Optional[str],
    source: Optional[str],
    user: Optional[str],
    q: Optional[str],
    since: Optional[str],
    from_: int,
    size: int,
) -> List[Dict[str, Any]]:
    items = list(reversed(_buffer))
    return _apply_filters(items, level=level, source=source, user=user, q=q, since=since)[from_ : from_ + size]


def _apply_filters(
    items: Iterable[Dict[str, Any]],
    *,
    level: Optional[str],
    source: Optional[str],
    user: Optional[str],
    q: Optional[str],
    since: Optional[str],
) -> List[Dict[str, Any]]:
    levels = {value.strip().lower() for value in (level or "").split(",") if value.strip()}
    needle = (q or "").strip().lower()
    user_needle = (user or "").strip().lower()
    result: List[Dict[str, Any]] = []
    for item in items:
        if levels and str(item.get("level")) not in levels:
            continue
        if source and str(item.get("source")) != source:
            continue
        if since and str(item.get("timestamp", "")) < since:
            continue
        if user_needle:
            haystack = f"{item.get('user_email', '')} {item.get('user_id', '')}".lower()
            if user_needle not in haystack:
                continue
        if needle:
            haystack = " ".join(
                [
                    str(item.get("message", "")),
                    str(item.get("path", "")),
                    str(item.get("source", "")),
                    json.dumps(item.get("data", {}), ensure_ascii=False, default=str) if item.get("data") else "",
                ]
            ).lower()
            if needle not in haystack:
                continue
        result.append(item)
    return result


def search_events(
    *,
    level: Optional[str] = None,
    source: Optional[str] = None,
    user: Optional[str] = None,
    q: Optional[str] = None,
    since: Optional[str] = None,
    until: Optional[str] = None,
    from_: int = 0,
    size: int = 50,
    backend: str = "auto",
) -> Dict[str, Any]:
    """Procura eventos.

    `backend`:
    - `memory` (predefinido em tempo real) — só o buffer em memória, que tem
      **todos** os eventos recentes (inclui os pedidos HTTP de nível `debug`/
      `info`, que não são escritos no Elasticsearch);
    - `elasticsearch` — arquivo completo (só lá estão autenticação/administração e
      nível ≥ `warning`), com recurso à memória se o serviço estiver em baixo;
    - `auto` — Elasticsearch quando o filtro só pede níveis que são arquivados
      (`warning`, `error`, `critical`) e a memória no resto dos casos.
    """
    size = max(1, min(int(size or 50), 500))
    wanted_levels = {value.strip().lower() for value in (level or "").split(",") if value.strip()}
    archived_levels = {"warning", "error", "critical"}

    use_es = backend == "elasticsearch"
    if backend == "auto":
        use_es = bool(wanted_levels) and wanted_levels.issubset(archived_levels)

    if use_es:
        result = _search_elasticsearch(
            level=level,
            source=source,
            user=user,
            q=q,
            since=since,
            until=until,
            from_=from_,
            size=size,
        )
        if result is not None:
            return result

    items = _buffer_search(level=level, source=source, user=user, q=q, since=since, from_=max(0, int(from_ or 0)), size=size)
    total = len(_apply_filters(list(reversed(_buffer)), level=level, source=source, user=user, q=q, since=since))
    return {
        "items": items,
        "total": total,
        "from": max(0, int(from_ or 0)),
        "size": size,
        "backend": "memoria",
        "capacity": BUFFER_SIZE,
    }


def _search_elasticsearch(
    *,
    level: Optional[str],
    source: Optional[str],
    user: Optional[str],
    q: Optional[str],
    since: Optional[str],
    until: Optional[str],
    from_: int,
    size: int,
) -> Optional[Dict[str, Any]]:
    """Pesquisa no índice de eventos; devolve `None` se o Elasticsearch falhar."""
    client = get_es_client()
    if not client:
        return None
    try:
        filters: List[Dict[str, Any]] = []
        levels = [value.strip().lower() for value in (level or "").split(",") if value.strip()]
        if levels:
            filters.append({"terms": {"level": levels}})
        if source:
            filters.append({"term": {"source": source}})
        if since or until:
            window: Dict[str, Any] = {}
            if since:
                window["gte"] = since
            if until:
                window["lte"] = until
            filters.append({"range": {"timestamp": window}})
        must: List[Dict[str, Any]] = []
        if q:
            must.append(
                {
                    "multi_match": {
                        "query": q,
                        "fields": ["message^2", "path", "source"],
                        "type": "best_fields",
                    }
                }
            )
        if user:
            must.append(
                {
                    "bool": {
                        "should": [
                            {"term": {"user_email": user}},
                            {"wildcard": {"user_email": f"*{user.lower()}*"}},
                        ],
                        "minimum_should_match": 1,
                    }
                }
            )
        query: Dict[str, Any] = {"bool": {}}
        if filters:
            query["bool"]["filter"] = filters
        if must:
            query["bool"]["must"] = must
        if not query["bool"]:
            query = {"match_all": {}}

        response = client.search(
            index=EVENTS_INDEX,
            body={
                "query": query,
                "sort": [{"timestamp": {"order": "desc"}}],
                "from": max(0, int(from_ or 0)),
                "size": size,
                "track_total_hits": True,
            },
        )
        hits = response.get("hits", {})
        items = []
        for hit in hits.get("hits", []):
            document = dict(hit.get("_source") or {})
            document.setdefault("id", hit.get("_id"))
            items.append(document)
        return {
            "items": items,
            "total": int(hits.get("total", {}).get("value", len(items))),
            "from": max(0, int(from_ or 0)),
            "size": size,
            "backend": "elasticsearch",
        }
    except Exception as error:
        logger.debug("Pesquisa de eventos falhou no Elasticsearch: %s", error)
        return None


def event_stats(hours: int = 24) -> Dict[str, Any]:
    """Contagens por nível/origem nas últimas `hours` horas (ES ou memória)."""
    hours = max(1, min(int(hours or 24), 24 * 30))
    since = _iso(_now() - timedelta(hours=hours))
    client = get_es_client()
    if client:
        try:
            response = client.search(
                index=EVENTS_INDEX,
                body={
                    "size": 0,
                    "query": {"range": {"timestamp": {"gte": since}}},
                    "aggs": {
                        "by_level": {"terms": {"field": "level", "size": 10}},
                        "by_source": {"terms": {"field": "source", "size": 20}},
                        "by_hour": {
                            "date_histogram": {
                                "field": "timestamp",
                                "calendar_interval": "hour",
                                "min_doc_count": 1,
                                "format": "yyyy-MM-dd'T'HH:00",
                            }
                        },
                        "top_paths": {"terms": {"field": "path", "size": 10}},
                    },
                },
            )
            aggs = response.get("aggregations", {})
            return {
                "hours": hours,
                "total": int(response.get("hits", {}).get("total", {}).get("value", 0)),
                "by_level": [{"key": b["key"], "count": b["doc_count"]} for b in aggs.get("by_level", {}).get("buckets", [])],
                "by_source": [{"key": b["key"], "count": b["doc_count"]} for b in aggs.get("by_source", {}).get("buckets", [])],
                "by_hour": [
                    {"key": b.get("key_as_string") or str(b.get("key")), "count": b["doc_count"]}
                    for b in aggs.get("by_hour", {}).get("buckets", [])
                ],
                "top_paths": [{"key": b["key"], "count": b["doc_count"]} for b in aggs.get("top_paths", {}).get("buckets", [])],
                "backend": "elasticsearch",
            }
        except Exception as error:
            logger.debug("Estatísticas de eventos falharam no Elasticsearch: %s", error)

    items = _apply_filters(list(reversed(_buffer)), level=None, source=None, user=None, q=None, since=since)
    by_level: Dict[str, int] = {}
    by_source: Dict[str, int] = {}
    by_hour: Dict[str, int] = {}
    top_paths: Dict[str, int] = {}
    for item in items:
        by_level[str(item.get("level"))] = by_level.get(str(item.get("level")), 0) + 1
        by_source[str(item.get("source"))] = by_source.get(str(item.get("source")), 0) + 1
        hour = str(item.get("timestamp", ""))[:13] + ":00"
        by_hour[hour] = by_hour.get(hour, 0) + 1
        if item.get("path"):
            top_paths[str(item["path"])] = top_paths.get(str(item["path"]), 0) + 1
    return {
        "hours": hours,
        "total": len(items),
        "by_level": [{"key": k, "count": v} for k, v in sorted(by_level.items(), key=lambda kv: -kv[1])],
        "by_source": [{"key": k, "count": v} for k, v in sorted(by_source.items(), key=lambda kv: -kv[1])],
        "by_hour": [{"key": k, "count": v} for k, v in sorted(by_hour.items())],
        "top_paths": [{"key": k, "count": v} for k, v in sorted(top_paths.items(), key=lambda kv: -kv[1])[:10]],
        "backend": "memoria",
    }


# ------------------------------------------------------------- ficheiros de log
def list_log_files() -> List[Dict[str, Any]]:
    """Ficheiros de log disponíveis (nome, tamanho e data de modificação)."""
    files: List[Dict[str, Any]] = []
    try:
        LOG_DIR.mkdir(parents=True, exist_ok=True)
        for path in sorted(LOG_DIR.iterdir()):
            if not path.is_file() or path.suffix.lower() not in TEXT_LOG_EXTENSIONS:
                continue
            stat = path.stat()
            files.append(
                {
                    "name": path.name,
                    "size": stat.st_size,
                    "modified_at": _iso(datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc)),
                }
            )
    except Exception as error:
        logger.debug("Não foi possível listar %s: %s", LOG_DIR, error)
    return files


def tail_log_file(name: str, lines: int = 200) -> Dict[str, Any]:
    """Últimas `lines` linhas de um ficheiro de `logs/` (nome validado)."""
    safe = Path(name or "").name
    if not safe or safe != name:
        return {"error": "Nome de ficheiro inválido."}
    path = LOG_DIR / safe
    if not path.exists() or not path.is_file():
        return {"error": "Ficheiro não encontrado."}
    if path.suffix.lower() not in TEXT_LOG_EXTENSIONS:
        return {"error": "Tipo de ficheiro não suportado."}

    lines = max(1, min(int(lines or 200), 5000))
    try:
        content = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except Exception as error:
        return {"error": f"Não foi possível ler o ficheiro: {error}"}

    return {
        "name": safe,
        "size": path.stat().st_size,
        "total_lines": len(content),
        "lines": content[-lines:],
        "truncated": len(content) > lines,
    }


# ------------------------------------------------------------------- ambiente
def system_info() -> Dict[str, Any]:
    """Informação do processo/ambiente para a página de administração."""
    return {
        "python": platform.python_version(),
        "platform": f"{platform.system()} {platform.release()}",
        "host": _host,
        "pid": _pid,
        "cwd": str(Path.cwd()),
        "root": str(ROOT),
        "buffer_size": len(_buffer),
        "buffer_capacity": BUFFER_SIZE,
        "events_file": str(EVENTS_FILE),
        "started_at": _started_at,
        "uptime_seconds": round((datetime.now(timezone.utc) - datetime.fromisoformat(_started_at)).total_seconds(), 1),
    }


_started_at = _iso(_now())
