"""Agenda da série de sentimento de mercado (APScheduler).

Um único *job* (`sentiment_market:build`) reconstrói os últimos dias da série
segundo a expressão cron guardada em `data/sentiment_market/settings.json`
(defeito: todos os dias às 06:30, `Europe/Lisbon`). A construção é idempotente
(`ticker|dia`), por isso reprocessar o mesmo dia só atualiza.

Como no leitor de RSS, o agendador:

- `start()`      — arranca no *lifespan* da API (idempotente);
- `shutdown()`   — para ao encerrar;
- `reload_jobs()`— aplica as definições atuais;
- `run_now()`    — corre a construção já (para a interface);
- `status()`     — estado, próxima execução e resultado da última corrida.

Sem APScheduler, a construção manual (`POST /sentiment/market/build`) continua a
funcionar e o motivo aparece explicado na interface.
"""
from __future__ import annotations

import logging
import threading
from datetime import datetime
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

JOB_ID = "sentiment_market:build"
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
    """Corpo do job: reconstrói os últimos dias da série e guarda o resultado."""
    from api import sentiment_market as market

    try:
        settings_now = market.settings()
        if not settings_now.get("enabled", True):
            return
        result = market.build(days=settings_now.get("days") or 3)
        record_run(result)
        logger.info(
            "Série de sentimento reconstruída: %s notícia(s), %s documento(s).",
            result.get("news"),
            result.get("documents"),
        )
    except Exception as exc:
        record_run({"error": str(exc)})
        logger.warning("Construção agendada do sentimento de mercado falhou: %s", exc)


def record_run(result: Dict[str, Any]) -> Dict[str, Any]:
    """Guarda o resultado de uma construção (agendada ou pedida na interface)."""
    global _last_run_at, _last_result
    with _lock:
        if result.get("error"):
            _last_result = {"error": str(result["error"])}
        else:
            _last_result = {
                "window": result.get("window"),
                "tickers": result.get("tickers"),
                "news": result.get("news"),
                "documents": result.get("documents"),
                "errors": (result.get("errors") or [])[:5],
            }
        _last_run_at = datetime.now().astimezone().isoformat()
        return _last_result


def _trigger(settings_now: Dict[str, Any]) -> Optional[Any]:
    cron = str(settings_now.get("cron") or "").strip()
    if not cron:
        return None
    try:
        from apscheduler.triggers.cron import CronTrigger  # type: ignore
    except Exception:
        return None
    timezone_name = str(settings_now.get("timezone") or "Europe/Lisbon")
    try:
        return CronTrigger.from_crontab(cron, timezone=timezone_name)
    except Exception as exc:
        logger.warning("Cron do sentimento de mercado inválido (%s): %s", cron, exc)
        return None


def start() -> Dict[str, Any]:
    global _scheduler, _started, _error
    with _lock:
        if _started:
            return status()
        try:
            cls = _load_scheduler_class()
        except Exception as exc:
            _error = str(exc)
            logger.warning("Agendador do sentimento de mercado inativo: %s", exc)
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
            logger.warning("Não foi possível arrancar o agendador do sentimento de mercado: %s", exc)
            return status()
    reload_jobs()
    return status()


def shutdown() -> None:
    global _scheduler, _started
    with _lock:
        if _scheduler is not None:
            try:
                _scheduler.shutdown(wait=False)
            except Exception as exc:  # pragma: no cover
                logger.debug("Erro ao parar o agendador do sentimento de mercado: %s", exc)
        _scheduler = None
        _started = False


def reload_jobs() -> Dict[str, Any]:
    from api import sentiment_market as market

    with _lock:
        if not _started or _scheduler is None:
            return status()
        settings_now = market.settings()
        try:
            _scheduler.remove_job(JOB_ID)
        except Exception:
            pass
        if settings_now.get("enabled", True):
            trigger = _trigger(settings_now)
            if trigger is not None:
                try:
                    _scheduler.add_job(
                        _job_function,
                        trigger=trigger,
                        id=JOB_ID,
                        replace_existing=True,
                        max_instances=1,
                        coalesce=True,
                        # Um portátil suspenso não deve perder a reconstrução do dia.
                        misfire_grace_time=3600,
                    )
                except Exception as exc:  # pragma: no cover
                    logger.warning("Não foi possível agendar a série de sentimento: %s", exc)
    return status()


def run_now(*, days: Optional[int] = None, only_missing: bool = False) -> Dict[str, Any]:
    """Corre a construção já (para a interface)."""
    from api import sentiment_market as market

    result = market.build(days=days, only_missing=only_missing)
    record_run(result)
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
    """Estado do agendador e das definições (para a interface e as rotas)."""
    from api import sentiment_market as market

    settings_now = market.settings()
    trigger = _trigger(settings_now) if settings_now.get("enabled", True) else None
    return {
        "running": bool(_started),
        "error": _error,
        "job_id": JOB_ID,
        "scheduled": trigger is not None,
        "cron": settings_now.get("cron") or "",
        "timezone": settings_now.get("timezone") or "Europe/Lisbon",
        "enabled": bool(settings_now.get("enabled", True)),
        "days": settings_now.get("days") or 3,
        "next_run_at": _next_run_at(),
        "last_run_at": _last_run_at,
        "last_result": _last_result,
        "settings": settings_now,
    }
