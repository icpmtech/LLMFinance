"""Agendador de verificação de trials expirados.

Verifica, de hora a hora, se existem contas ativas cujo trial de 5 dias já
tenha expirado. Em caso afirmativo, suspende a conta, revoga as sessões e
regista o evento. O lembrete por email (trial a expirar) pode ser ligado
configurando SMTP nas definições.

O job arranca no lifespan da aplicação FastAPI e pára no encerramento.
"""
from __future__ import annotations

import logging
import threading
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from api import auth_service as auth
from api import events_service as events
from api import notification_email

logger = logging.getLogger(__name__)

JOB_ID = "trial:expiration-check"
_scheduler: Optional[Any] = None
_started = False
_lock = threading.RLock()


def _load_scheduler_class() -> Any:
    try:
        from apscheduler.schedulers.background import BackgroundScheduler  # type: ignore

        return BackgroundScheduler
    except Exception as exc:
        raise RuntimeError('O APScheduler não está instalado (pip install "apscheduler>=3.10").') from exc


def _check_trials() -> None:
    """Corpo do job: suspende contas com trial expirado e envia lembretes."""
    try:
        affected = auth.suspend_trial_expired_users()
        if affected:
            for user in affected:
                logger.info("Trial expirado — conta suspensa: %s", user.get("email"))
                events.log_event(
                    "warning",
                    "admin",
                    f"Trial expirado: {user.get('email')} (conta suspensa)",
                    data={"target_user": user.get("email"), "target_id": user.get("id")},
                )
                notification_email.send_trial_expiring_email(
                    to=user.get("email") or "",
                    name=user.get("name") or user.get("email") or "",
                    trial_expires_at=user.get("trial_expires_at") or "",
                )
    except Exception as exc:  # noqa: BLE001 - não deve travar o agendador
        logger.warning("Verificação de trials expirados falhou: %s", exc)


def start() -> Dict[str, Any]:
    """Arranca o agendador de trial (idempotente)."""
    global _scheduler, _started
    with _lock:
        if _started:
            return status()
        try:
            cls = _load_scheduler_class()
        except Exception as exc:
            logger.warning("Agendador de trial inativo: %s", exc)
            return status()
        try:
            _scheduler = cls(timezone="UTC")
            _scheduler.start()
            _started = True
            logger.info("Agendador de trial arrancou.")
        except Exception as exc:
            _scheduler = None
            _started = False
            logger.warning("Não foi possível arrancar o agendador de trial: %s", exc)
            return status()
        try:
            from apscheduler.triggers.interval import IntervalTrigger  # type: ignore

            trigger = IntervalTrigger(hours=1, start_date=datetime.now(timezone.utc))
            _scheduler.add_job(_check_trials, trigger=trigger, id=JOB_ID, replace_existing=True)
            _check_trials()  # executa uma primeira verificação no arranque
        except Exception as exc:
            logger.warning("Não foi possível registar o job de trial: %s", exc)
    return status()


def shutdown() -> None:
    """Para o agendador de trial."""
    global _scheduler, _started
    with _lock:
        if _scheduler is not None:
            try:
                _scheduler.shutdown(wait=False)
            except Exception as exc:
                logger.debug("Erro ao parar o agendador de trial: %s", exc)
        _scheduler = None
        _started = False


def status() -> Dict[str, Any]:
    """Estado do agendador."""
    with _lock:
        result: Dict[str, Any] = {"started": _started}
        if _scheduler is not None:
            try:
                job = _scheduler.get_job(JOB_ID)
                if job:
                    result["next_run"] = str(job.next_run_time) if job.next_run_time else None
            except Exception as exc:
                result["error"] = str(exc)
        return result
