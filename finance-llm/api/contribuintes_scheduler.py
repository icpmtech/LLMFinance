"""Agendamento (cron) da sincronização dos contribuintes, sobre o APScheduler.

O índice `finance_contribuintes` é derivado: para se manter atualizado tem de
ser reconstruído de tempos a tempos a partir de todos os índices da plataforma.
Este módulo mantém um `BackgroundScheduler` com **um** job
(`contribuintes:sync`) cuja expressão cron vive na configuração do módulo
(`data/contribuintes/config.json`, editável na página Contribuintes):

- `start()`       — arranca o agendador (chamado no *lifespan* da API);
- `shutdown()`    — para o agendador (ao encerrar a API);
- `reload_jobs()` — aplica a configuração atual (após guardar o horário);
- `status()`      — estado e próxima execução (para a UI e `/contribuintes/schedule`).

Só arranca se o APScheduler estiver instalado; sem ele, a sincronização manual
continua a funcionar e o motivo é explicado na UI.
"""
from __future__ import annotations

import logging
import threading
from datetime import datetime
from typing import Any, Dict, List, Optional

from api import contribuintes_service as service

logger = logging.getLogger(__name__)

JOB_ID = "contribuintes:sync"
_scheduler: Optional[Any] = None
_started = False
_error: Optional[str] = None
_lock = threading.RLock()


def _load_scheduler_class() -> Any:
    try:
        from apscheduler.schedulers.background import BackgroundScheduler  # type: ignore

        return BackgroundScheduler
    except Exception as exc:  # pragma: no cover - depende do ambiente
        raise RuntimeError(
            'O APScheduler não está instalado (pip install "apscheduler>=3.10").'
        ) from exc


def _job_function() -> None:
    """Corpo do job: reconstrói o índice de contribuintes a partir de todas as fontes."""
    config = service.load_config()
    sources = config.get("sources") or None
    try:
        summary = service.run_sync(sources, page_size=config.get("page_size"), trigger="cron")
        logger.info(
            "Cron de contribuintes: %s contribuintes em %s s (run %s)",
            summary.get("unique"),
            summary.get("duration_s"),
            summary.get("run_id"),
        )
    except Exception as exc:
        logger.warning("Cron de contribuintes falhou: %s", exc)


def _trigger_for(config: Dict[str, Any]) -> Optional[Any]:
    if not config.get("enabled"):
        return None
    cron = str(config.get("cron") or "").strip()
    if not cron:
        return None
    try:
        from apscheduler.triggers.cron import CronTrigger  # type: ignore
    except Exception:
        return None
    timezone_name = str(config.get("timezone") or "Europe/Lisbon")
    try:
        return CronTrigger.from_crontab(cron, timezone=timezone_name)
    except Exception as exc:
        logger.warning("Cron inválido para contribuintes (%s): %s", cron, exc)
        return None


def start() -> Dict[str, Any]:
    """Arranca o agendador em segundo plano (idempotente)."""
    global _scheduler, _started, _error
    with _lock:
        if _started:
            return status()
        try:
            cls = _load_scheduler_class()
        except Exception as exc:
            _error = str(exc)
            logger.warning("Agendador de contribuintes inativo: %s", exc)
            return status()
        try:
            _scheduler = cls(timezone="UTC")
            _scheduler.start()
            _started = True
            _error = None
            logger.info("Agendador de contribuintes arrancou.")
        except Exception as exc:
            _error = str(exc)
            _scheduler = None
            _started = False
            logger.warning("Não foi possível arrancar o agendador de contribuintes: %s", exc)
            return status()
    reload_jobs()
    return status()


def shutdown() -> None:
    """Para o agendador (ao encerrar a API)."""
    global _scheduler, _started
    with _lock:
        if _scheduler is not None:
            try:
                _scheduler.shutdown(wait=False)
            except Exception as exc:
                logger.debug("Erro ao parar o agendador de contribuintes: %s", exc)
        _scheduler = None
        _started = False


def reload_jobs() -> Dict[str, Any]:
    """Sincroniza o job com a configuração guardada."""
    with _lock:
        if not _started or _scheduler is None:
            return status()
        config = service.load_config()
        trigger = _trigger_for(config)
        try:
            _scheduler.remove_job(JOB_ID)
        except Exception:
            pass
        if trigger is None:
            return status()
        try:
            _scheduler.add_job(
                _job_function,
                trigger=trigger,
                id=JOB_ID,
                name="Contribuintes · sincronizar índice",
                replace_existing=True,
                max_instances=1,
                coalesce=True,
                misfire_grace_time=1800,
            )
        except Exception as exc:
            logger.warning("Não foi possível agendar a sincronização de contribuintes: %s", exc)
    return status()


def status() -> Dict[str, Any]:
    """Estado do agendador e próxima execução."""
    with _lock:
        scheduler = _scheduler
        running = bool(_started and scheduler is not None)
        next_run: Optional[str] = None
        if running:
            try:
                job = scheduler.get_job(JOB_ID)
                moment = getattr(job, "next_run_time", None) if job else None
                next_run = moment.isoformat() if isinstance(moment, datetime) else None
            except Exception as exc:
                logger.debug("Falha ao ler o job de contribuintes: %s", exc)
        config = service.load_config()
        enabled = bool(config.get("enabled"))
        jobs: List[Dict[str, Any]] = []
        if running and next_run:
            jobs.append({"id": JOB_ID, "name": "Contribuintes · sincronizar índice", "next_run_time": next_run})
        return {
            "available": running,
            "enabled": enabled,
            "cron": config.get("cron"),
            "timezone": config.get("timezone"),
            "next_run_time": next_run,
            "jobs": jobs,
            "error": _error,
            # Diz se o agendador está a correr mas sem job (configuração desligada).
            "active": bool(running and enabled and next_run),
        }
