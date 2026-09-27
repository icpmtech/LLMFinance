"""Agendamento (cron) do World Model, sobre o APScheduler.

Mantém **um** job (`world:rebuild`) que reconstrói o mundo a partir dos dados
públicos e, opcionalmente, corre um ciclo da rede dinâmica — mantendo o estado
e as previsões frescas sem intervenção. A expressão cron vive na configuração do
módulo (`data/world/config.json`, editável na página do World Model):

- `start()`       — arranca o agendador (chamado no *lifespan* da API);
- `shutdown()`    — para o agendador (ao encerrar a API);
- `reload_jobs()` — aplica a configuração atual (após guardar o horário);
- `status()`      — estado e próxima execução (para a UI e `/world/schedule`).

Só arranca se o APScheduler estiver instalado; sem ele, a reconstrução manual
continua a funcionar e o motivo é explicado na UI.
"""
from __future__ import annotations

import logging
import threading
from datetime import datetime
from typing import Any, Dict, Optional

from api import world_jobs
from api import world_model as model

logger = logging.getLogger(__name__)

JOB_ID = "world:rebuild"
_scheduler: Optional[Any] = None
_started = False
_error: Optional[str] = None
_lock = threading.RLock()


def _load_scheduler_class() -> Any:
    try:
        from apscheduler.schedulers.background import BackgroundScheduler  # type: ignore

        return BackgroundScheduler
    except Exception as exc:  # pragma: no cover - depende do ambiente
        raise RuntimeError('O APScheduler não está instalado (pip install "apscheduler>=3.10").') from exc


def _job_function() -> None:
    """Corpo do job: reconstrói o mundo (e treina a rede, se configurado)."""
    if world_jobs.running():
        logger.info("Cron do World Model ignorado: já há uma execução em curso.")
        return
    config = model.load_config()
    try:
        summary = model.rebuild()
        logger.info(
            "Cron do World Model: %s entidades, %s eventos, %s relações (v%s)",
            summary.get("entities"),
            summary.get("events"),
            summary.get("relations"),
            summary.get("version"),
        )
        if config.get("schedule_train_network"):
            # Import tardio: evita carregar numpy no arranque da API.
            from api import world_neural

            state = world_neural.train()
            logger.info("Cron do World Model: rede v%s (%s nós)", state.get("version"), (state.get("metrics") or {}).get("nodes"))
    except Exception as exc:
        logger.warning("Cron do World Model falhou: %s", exc)


def _trigger_for(config: Dict[str, Any]) -> Optional[Any]:
    if not config.get("schedule_enabled"):
        return None
    cron = str(config.get("schedule_cron") or "").strip()
    if not cron:
        return None
    try:
        from apscheduler.triggers.cron import CronTrigger  # type: ignore
    except Exception:
        return None
    timezone_name = str(config.get("schedule_timezone") or "Europe/Lisbon")
    try:
        return CronTrigger.from_crontab(cron, timezone=timezone_name)
    except Exception as exc:
        logger.warning("Cron inválido para o World Model (%s): %s", cron, exc)
        return None


def status() -> Dict[str, Any]:
    """Estado do agendador, configuração e próxima execução."""
    config = model.load_config()
    next_run = None
    if _scheduler is not None:
        try:
            job = _scheduler.get_job(JOB_ID)
            if job is not None and job.next_run_time:
                next_run = job.next_run_time.isoformat()
        except Exception:
            next_run = None
    return {
        "installed": _started,
        "available": _scheduler is not None,
        "error": _error,
        "enabled": bool(config.get("schedule_enabled")),
        "cron": config.get("schedule_cron"),
        "timezone": config.get("schedule_timezone"),
        "train_network": bool(config.get("schedule_train_network")),
        "next_run": next_run,
        "job_id": JOB_ID,
    }


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
            logger.warning("Agendador do World Model inativo: %s", exc)
            return status()
        try:
            _scheduler = cls(timezone="UTC")
            _scheduler.start()
            _started = True
            _error = None
            logger.info("Agendador do World Model arrancou.")
        except Exception as exc:
            _error = str(exc)
            _scheduler = None
            _started = False
            logger.warning("Não foi possível arrancar o agendador do World Model: %s", exc)
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
                logger.debug("Erro ao parar o agendador do World Model: %s", exc)
        _scheduler = None
        _started = False


def reload_jobs() -> Dict[str, Any]:
    """Aplica a configuração atual (cron/ligar-desligar) ao agendador."""
    config = model.load_config()
    trigger = _trigger_for(config)
    with _lock:
        if _scheduler is None:
            return status()
        try:
            if trigger is None:
                existing = _scheduler.get_job(JOB_ID)
                if existing is not None:
                    _scheduler.remove_job(JOB_ID)
            else:
                _scheduler.add_job(
                    _job_function,
                    trigger=trigger,
                    id=JOB_ID,
                    replace_existing=True,
                    max_instances=1,
                    coalesce=True,
                )
        except Exception as exc:
            logger.warning("Não foi possível aplicar o cron do World Model: %s", exc)
    return status()


def schedule() -> Dict[str, Any]:
    """Estado do agendamento (para `/world/schedule`)."""
    payload = status()
    payload["now"] = datetime.utcnow().isoformat()
    return payload
