"""Agenda da recolha RSS, sobre o APScheduler.

Um único *job* (`rss:refresh`) recolhe **todas** as fontes ativas segundo a
expressão cron guardada nas definições (`settings.cron`, 5 campos
`minuto hora dia mês dia-semana`) e o fuso `settings.timezone`. Como no módulo de
recolha de sites, o agendador:

- `start()`      — arranca no *lifespan* da API (idempotente);
- `shutdown()`   — para ao encerrar;
- `reload_jobs()`— aplica as definições atuais (após gravar a agenda);
- `status()`     — estado, próxima execução e resultado da última recolha.

Se o APScheduler não estiver instalado, a recolha **manual** continua a
funcionar e o motivo é explicado na interface.
"""
from __future__ import annotations

import logging
import threading
from datetime import datetime
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

JOB_ID = "rss:refresh"
_lock = threading.RLock()
_scheduler: Optional[Any] = None
_started = False
_error: Optional[str] = None
_last_run_at: Optional[str] = None
_last_result: Optional[Dict[str, Any]] = None


def _load_scheduler_class() -> Any:
    try:
        from apscheduler.schedulers.background import BackgroundScheduler  # type: ignore

        return BackgroundScheduler
    except Exception as exc:  # pragma: no cover - depende do ambiente
        raise RuntimeError('O APScheduler não está instalado (pip install "apscheduler>=3.10").') from exc


def _job_function() -> None:
    """Corpo do job: recolhe todas as fontes ativas e guarda o resultado."""
    global _last_run_at, _last_result
    from api import rss_service as service
    from api import rss_store as store

    try:
        settings = store.settings()
        if not settings.get("auto_fetch", True):
            return
        result = service.refresh_all(actor="agenda")
        _last_result = result
        _last_run_at = datetime.now().astimezone().isoformat()
        logger.info("Recolha RSS agendada: %s feed(s), %s novo(s).", result.get("feeds"), result.get("added"))
    except Exception as exc:
        _last_result = {"error": str(exc)}
        _last_run_at = datetime.now().astimezone().isoformat()
        logger.warning("Recolha RSS agendada falhou: %s", exc)


def _trigger(settings: Dict[str, Any]) -> Optional[Any]:
    cron = str(settings.get("cron") or "").strip()
    if not cron:
        return None
    try:
        from apscheduler.triggers.cron import CronTrigger  # type: ignore
    except Exception:
        return None
    timezone_name = str(settings.get("timezone") or "Europe/Lisbon")
    try:
        return CronTrigger.from_crontab(cron, timezone=timezone_name)
    except Exception as exc:
        logger.warning("Cron do RSS inválido (%s): %s", cron, exc)
        return None


def start() -> Dict[str, Any]:
    """Arranca o agendador (idempotente)."""
    global _scheduler, _started, _error
    with _lock:
        if _started:
            return status()
        try:
            cls = _load_scheduler_class()
        except Exception as exc:
            _error = str(exc)
            logger.warning("Agendador do leitor RSS inativo: %s", exc)
            return status()
        try:
            _scheduler = cls(timezone="UTC")
            _scheduler.start()
            _started = True
            _error = None
        except Exception as exc:
            _error = str(exc)
            _scheduler = None
            _started = False
            logger.warning("Não foi possível arrancar o agendador do leitor RSS: %s", exc)
            return status()
    reload_jobs()
    return status()


def shutdown() -> None:
    """Para o agendador."""
    global _scheduler, _started
    with _lock:
        if _scheduler is not None:
            try:
                _scheduler.shutdown(wait=False)
            except Exception as exc:  # pragma: no cover
                logger.debug("Erro ao parar o agendador do leitor RSS: %s", exc)
        _scheduler = None
        _started = False


def reload_jobs() -> Dict[str, Any]:
    """Sincroniza o job com as definições guardadas."""
    from api import rss_store as store

    with _lock:
        if not _started or _scheduler is None:
            return status()
        settings = store.settings()
        try:
            _scheduler.remove_job(JOB_ID)
        except Exception:
            pass
        if settings.get("auto_fetch", True):
            trigger = _trigger(settings)
            if trigger is not None:
                try:
                    _scheduler.add_job(
                        _job_function,
                        trigger=trigger,
                        id=JOB_ID,
                        replace_existing=True,
                        max_instances=1,
                        coalesce=True,
                        # Uma execução perdida (portátil suspenso) ainda corre uma
                        # vez ao acordar, em vez de ser descartada (o APScheduler
                        # dá 1 segundo de tolerância por omissão).
                        misfire_grace_time=3600,
                    )
                except Exception as exc:  # pragma: no cover
                    logger.warning("Não foi possível agendar a recolha RSS: %s", exc)
    return status()


def run_now(*, force: bool = False) -> Dict[str, Any]:
    """Executa a recolha de todas as fontes já (para a interface)."""
    global _last_run_at, _last_result
    from api import rss_service as service

    result = service.refresh_all(actor="manual", force=force)
    _last_result = result
    _last_run_at = datetime.now().astimezone().isoformat()
    return result


def _next_run_at() -> Optional[str]:
    if not _started or _scheduler is None:
        return None
    try:
        job = _scheduler.get_job(JOB_ID)
    except Exception:
        return None
    if job is None or job.next_run_time is None:
        return None
    return job.next_run_time.astimezone().isoformat()


def status() -> Dict[str, Any]:
    """Estado do agendador e das definições (para a interface e `/rss/schedule`)."""
    from api import rss_store as store

    settings = store.settings()
    trigger = _trigger(settings) if settings.get("auto_fetch", True) else None
    return {
        "running": bool(_started),
        "error": _error,
        "job_id": JOB_ID,
        "scheduled": trigger is not None,
        "cron": settings.get("cron") or "",
        "timezone": settings.get("timezone") or "Europe/Lisbon",
        "auto_fetch": bool(settings.get("auto_fetch", True)),
        "next_run_at": _next_run_at(),
        "last_run_at": _last_run_at,
        "last_result": _last_result,
        "settings": settings,
    }
