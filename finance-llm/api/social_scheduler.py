"""Agendamento (cron) das recolhas sociais, sobre o APScheduler.

Cada canal do `social_service` pode declarar uma expressão cron de 5 campos
(`minuto hora dia mês dia-semana`) e um fuso horário. Este módulo mantém um
`BackgroundScheduler` com um *job* por canal (`social:<id>`), sincronizado com as
definições guardadas:

- `start()`       — arranca o agendador (chamado no *lifespan* da API);
- `shutdown()`    — para o agendador (ao encerrar a API);
- `reload_jobs()` — aplica as definições atuais (após criar/editar/apagar um canal);
- `status()`      — estado e próximas execuções (para a UI e para `/social/status`).

Só arranca se o APScheduler estiver instalado; sem ele, as recolhas manuais
continuam a funcionar e o erro é explicado na UI.
"""
from __future__ import annotations

import logging
import threading
from datetime import datetime
from typing import Any, Dict, List, Optional

from api import social_service as social

logger = logging.getLogger(__name__)

JOB_PREFIX = "social:"
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


def _job_function(channel_id: str) -> None:
    """Corpo do job: executa a recolha do canal e registra o resultado."""
    try:
        result = social.execute_run_sync(channel_id, trigger="cron")
        logger.info("Cron social %s: %s (%s itens)", channel_id, result.get("status"), result.get("items_count"))
    except KeyError:
        logger.warning("Cron social: canal %s já não existe; o job será removido.", channel_id)
    except Exception as exc:
        logger.warning("Cron social %s falhou: %s", channel_id, exc)


def _trigger_for(channel: Dict[str, Any]) -> Optional[Any]:
    schedule = channel.get("schedule") or {}
    cron = str(schedule.get("cron") or "").strip()
    if not cron:
        return None
    try:
        from apscheduler.triggers.cron import CronTrigger  # type: ignore
    except Exception:
        return None
    timezone_name = str(schedule.get("timezone") or "Europe/Lisbon")
    try:
        return CronTrigger.from_crontab(cron, timezone=timezone_name)
    except Exception as exc:
        logger.warning("Cron inválido em %s (%s): %s", channel.get("id"), cron, exc)
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
            logger.warning("Agendador social inativo: %s", exc)
            return status()
        try:
            _scheduler = cls(timezone="UTC")
            _scheduler.start()
            _started = True
            _error = None
            logger.info("Agendador social arrancou.")
        except Exception as exc:
            _error = str(exc)
            _scheduler = None
            _started = False
            logger.warning("Não foi possível arrancar o agendador social: %s", exc)
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
                logger.debug("Erro ao parar o agendador social: %s", exc)
        _scheduler = None
        _started = False


def reload_jobs() -> Dict[str, Any]:
    """Sincroniza os jobs com as definições guardadas."""
    with _lock:
        if not _started or _scheduler is None:
            return status()
        wanted: Dict[str, Any] = {}
        for channel in social.list_channels():
            if not channel.get("enabled"):
                continue
            trigger = _trigger_for(channel)
            if trigger is None:
                continue
            wanted[f"{JOB_PREFIX}{channel['id']}"] = (channel, trigger)

        try:
            current = {job.id: job for job in _scheduler.get_jobs()}
        except Exception:
            current = {}

        for job_id in current:
            if job_id.startswith(JOB_PREFIX) and job_id not in wanted:
                try:
                    _scheduler.remove_job(job_id)
                except Exception:
                    pass

        for job_id, (channel, trigger) in wanted.items():
            try:
                _scheduler.add_job(
                    _job_function,
                    trigger=trigger,
                    id=job_id,
                    name=f"Pesquisa social · {channel['name']}",
                    args=[channel["id"]],
                    replace_existing=True,
                    max_instances=1,
                    coalesce=True,
                    misfire_grace_time=300,
                )
            except Exception as exc:
                logger.warning("Não foi possível agendar %s: %s", channel["id"], exc)
    return status()


def remove_job(channel_id: str) -> None:
    with _lock:
        if _scheduler is None:
            return
        try:
            _scheduler.remove_job(f"{JOB_PREFIX}{channel_id}")
        except Exception:
            pass


def status() -> Dict[str, Any]:
    """Estado do agendador + próximas execuções por canal."""
    with _lock:
        scheduler = _scheduler
        running = bool(_started and scheduler is not None)
        jobs: List[Dict[str, Any]] = []
        if running:
            try:
                for job in scheduler.get_jobs():
                    if not job.id.startswith(JOB_PREFIX):
                        continue
                    next_run = getattr(job, "next_run_time", None)
                    jobs.append(
                        {
                            "id": job.id,
                            "channel_id": job.id[len(JOB_PREFIX) :],
                            "name": job.name,
                            "next_run_time": next_run.isoformat() if isinstance(next_run, datetime) else None,
                        }
                    )
            except Exception as exc:
                logger.debug("Falha ao listar jobs sociais: %s", exc)
        jobs.sort(key=lambda j: str(j.get("next_run_time") or "~"))
        return {
            "available": running,
            "jobs": jobs,
            "jobs_total": len(jobs),
            "error": _error,
        }
