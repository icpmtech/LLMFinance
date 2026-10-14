"""Agendador do correio da plataforma, sobre o APScheduler.

Um único *job* (`platform-mail:sync`) percorre as caixas do domínio ligadas à
plataforma e traz as mensagens novas para o índice (`finance_mail_messages`). O
intervalo e o ligar/desligar ficam nas definições do módulo
(`Administração → Correio → Agenda`), pelo que mudar o intervalo na interface
produz efeito imediato — sem reiniciar a API.

Como nos outros agendadores da solução:

- `start()`       — arranca no *lifespan* da API (idempotente);
- `shutdown()`    — para ao encerrar;
- `reload_jobs()` — aplica as definições atuais;
- `run_now()`     — sincroniza já (botão «Sincronizar»);
- `status()`      — estado, próxima execução e resultado da última passagem.

A sincronização **manual** funciona sempre, mesmo sem APScheduler instalado — é
essa a razão de o agendador degradar em silêncio com um `error` explicado.
"""
from __future__ import annotations

import logging
import threading
from datetime import datetime
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

JOB_ID = "platform-mail:sync"
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
    """Corpo do job: sincroniza todas as caixas ligadas e guarda o resultado."""
    global _last_run_at, _last_result
    from api import platform_mail_service as service

    try:
        definicoes = service.settings()
        if not definicoes.get("auto_sync") or int(definicoes.get("sync_seconds") or 0) <= 0:
            return
        resultado = service.sync()
        _last_result = resultado
        _last_run_at = datetime.now().astimezone().isoformat()
        if resultado.get("indexed"):
            logger.info(
                "Correio da plataforma: %s mensagem(ns) nova(s) indexada(s) de %s caixa(s).",
                resultado["indexed"],
                len(resultado.get("accounts") or []),
            )
        for erro in resultado.get("errors") or []:
            logger.warning("Correio da plataforma: %s", erro)
    except Exception as exc:  # noqa: BLE001
        _last_result = {"error": str(exc)}
        _last_run_at = datetime.now().astimezone().isoformat()
        logger.warning("Sincronização do correio da plataforma falhou: %s", exc)


def _interval_seconds() -> int:
    from api import platform_mail_service as service

    definicoes = service.settings()
    if not definicoes.get("auto_sync"):
        return 0
    try:
        return max(0, int(definicoes.get("sync_seconds") or 0))
    except (TypeError, ValueError):
        return 0


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
            logger.warning("Agendador do correio da plataforma inativo: %s", exc)
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
            logger.warning("Não foi possível arrancar o agendador do correio da plataforma: %s", exc)
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
                logger.debug("Erro ao parar o agendador do correio da plataforma: %s", exc)
        _scheduler = None
        _started = False


def reload_jobs() -> Dict[str, Any]:
    """Sincroniza o job com as definições guardadas (intervalo em segundos)."""
    with _lock:
        if not _started or _scheduler is None:
            return status()
        try:
            _scheduler.remove_job(JOB_ID)
        except Exception:
            pass
        segundos = _interval_seconds()
        if segundos > 0:
            try:
                from apscheduler.triggers.interval import IntervalTrigger  # type: ignore

                _scheduler.add_job(
                    _job_function,
                    trigger=IntervalTrigger(seconds=segundos),
                    id=JOB_ID,
                    replace_existing=True,
                    max_instances=1,
                    coalesce=True,
                    # Um portátil suspenso ou a API parada uns minutos não devem
                    # perder a passagem: corre uma vez ao voltar.
                    misfire_grace_time=3600,
                )
            except Exception as exc:  # pragma: no cover
                logger.warning("Não foi possível agendar a sincronização do correio: %s", exc)
    return status()


def run_now(*, full: bool = False) -> Dict[str, Any]:
    """Sincroniza já (botão «Sincronizar»), sem passar pela agenda."""
    global _last_run_at, _last_result
    from api import platform_mail_service as service

    resultado = service.sync(full=full)
    _last_result = resultado
    _last_run_at = datetime.now().astimezone().isoformat()
    return resultado


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
    """Estado do agendador (para a aplicação mostrar a agenda)."""
    from api import platform_mail_service as service

    definicoes = service.settings()
    return {
        "running": bool(_started),
        "error": _error,
        "job_id": JOB_ID,
        "scheduled": _interval_seconds() > 0,
        "sync_seconds": definicoes.get("sync_seconds"),
        "auto_sync": bool(definicoes.get("auto_sync")),
        "next_run_at": _next_run_at(),
        "last_run_at": _last_run_at,
        "last_result": _last_result,
        "settings": definicoes,
    }
