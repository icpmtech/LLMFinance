"""Agendamento (cron) da recolha automática de filings SEC EDGAR.

O módulo mantém um `BackgroundScheduler` com:
- um job por ticker da lista local (`data/tickers_extended.json`); cada job
  (`sec:<ticker>`) executa a ingestão EDGAR num horário configurável;
- um job bulk diário (`sec:bulk`) que descarrega e ingere os arquivos ZIP
  diários `submissions.zip` e `companyfacts.zip`.

- `start()`       — arranca o agendador (chamado no lifespan da API);
- `shutdown()`    — para o agendador ao encerrar a API;
- `reload_jobs()` — sincroniza jobs com a lista de tickers atual;
- `status()`      — estado e próximas execuções (para UI e /sec/schedule);
- `run_now(ticker, user_id)` — executa manualmente a recolha de um ticker.

Só arranca se o APScheduler estiver instalado.
"""
from __future__ import annotations

import logging
import threading
from datetime import datetime
from typing import Any, Dict, List, Optional

from api import sec_service as service
from api.tools import _load_tickers, _normalize_ticker

logger = logging.getLogger(__name__)

JOB_PREFIX = "sec:"
DEFAULT_CRON = "0 4 * * 0"  # domingo 04h00 UTC
BULK_CRON = "0 5 * * *"  # 05h00 UTC diariamente
DEFAULT_TIMEZONE = "UTC"

_scheduler: Optional[Any] = None
_started = False
_error: Optional[str] = None
_lock = threading.RLock()


def _load_scheduler_class() -> Any:
    try:
        from apscheduler.schedulers.background import BackgroundScheduler  # type: ignore
        return BackgroundScheduler
    except Exception as exc:  # pragma: no cover
        raise RuntimeError(
            'O APScheduler não está instalado (pip install "apscheduler>=3.10").'
        ) from exc


def _trigger_for(cron: Optional[str] = None, timezone_name: Optional[str] = None) -> Optional[Any]:
    cron = str(cron or DEFAULT_CRON).strip()
    if not cron:
        return None
    try:
        from apscheduler.triggers.cron import CronTrigger  # type: ignore
    except Exception:
        return None
    timezone_name = str(timezone_name or DEFAULT_TIMEZONE)
    try:
        return CronTrigger.from_crontab(cron, timezone=timezone_name)
    except Exception as exc:
        logger.warning("Cron inválido para SEC (%s): %s", cron, exc)
        return None


def _job_function(ticker: str, user_id: Optional[str] = None) -> None:
    """Corpo do job: procura CIK e ingere filings do ticker."""
    try:
        ticker = _normalize_ticker(ticker)
        companies = service.search_companies_sec(ticker, max_results=10)
        if companies.get("error"):
            logger.warning("Agendador SEC: não encontrou %s — %s", ticker, companies["error"])
            return
        for company in companies.get("items", []):
            if company.get("ticker") == ticker:
                result = service.index_filings_for_cik(company["cik"], limit=20, user_id=user_id)
                result_xbrl = service.index_company_facts(company["cik"], user_id=user_id)
                logger.info(
                    "Cron SEC %s: %s filings, %s factos",
                    ticker,
                    result.get("indexed"),
                    result_xbrl.get("indexed_facts"),
                )
                return
        logger.warning("Agendador SEC: ticker %s não mapeado no catálogo SEC.", ticker)
    except Exception as exc:
        logger.warning("Cron SEC %s falhou: %s", ticker, exc)


def _bulk_job_function(user_id: Optional[str] = None) -> None:
    """Corpo do job bulk: descarrega e ingere os arquivos ZIP diários da SEC."""
    try:
        status = service.bulk_ingest_both(user_id=user_id)
        logger.info(
            "Cron SEC bulk: submissions=%s, companyfacts=%s",
            status.get("submissions", {}).get("indexed"),
            status.get("companyfacts", {}).get("indexed"),
        )
    except Exception as exc:
        logger.warning("Cron SEC bulk falhou: %s", exc)


def _job_id(ticker: str) -> str:
    return f"{JOB_PREFIX}{ticker}"


def start(cron: Optional[str] = None, timezone_name: Optional[str] = None) -> Dict[str, Any]:
    """Arranca o agendador SEC em segundo plano (idempotente)."""
    global _scheduler, _started, _error
    with _lock:
        if _started:
            return status()
        try:
            cls = _load_scheduler_class()
        except Exception as exc:
            _error = str(exc)
            logger.warning("Agendador SEC inativo: %s", exc)
            return status()
        try:
            _scheduler = cls(timezone="UTC")
            _scheduler.start()
            _started = True
            _error = None
            logger.info("Agendador SEC arrancou.")
        except Exception as exc:
            _error = str(exc)
            _scheduler = None
            _started = False
            logger.warning("Não foi possível arrancar o agendador SEC: %s", exc)
            return status()
    reload_jobs(cron=cron, timezone_name=timezone_name)
    return status()



def shutdown() -> None:
    """Para o agendador ao encerrar a API."""
    global _scheduler, _started
    with _lock:
        if _scheduler is not None:
            try:
                _scheduler.shutdown(wait=False)
            except Exception as exc:
                logger.debug("Erro ao parar o agendador SEC: %s", exc)
        _scheduler = None
        _started = False


def reload_jobs(cron: Optional[str] = None, timezone_name: Optional[str] = None, bulk_cron: Optional[str] = None) -> Dict[str, Any]:
    """Sincroniza os jobs com a lista de tickers guardada e mantém o job bulk."""
    with _lock:
        if not _started or _scheduler is None:
            return status()
        wanted = set()
        trigger = _trigger_for(cron, timezone_name)
        if trigger is None:
            return status()
        for ticker in _load_tickers():
            ticker = _normalize_ticker(ticker)
            job_id = _job_id(ticker)
            wanted.add(job_id)
            if _scheduler.get_job(job_id) is None:
                _scheduler.add_job(
                    _job_function,
                    trigger=trigger,
                    id=job_id,
                    name=f"SEC EDGAR: {ticker}",
                    replace_existing=True,
                    args=[ticker, None],
                )
        # Job bulk diário.
        bulk_job_id = f"{JOB_PREFIX}bulk"
        wanted.add(bulk_job_id)
        bulk_trigger = _trigger_for(bulk_cron or BULK_CRON, timezone_name)
        if bulk_trigger and _scheduler.get_job(bulk_job_id) is None:
            _scheduler.add_job(
                _bulk_job_function,
                trigger=bulk_trigger,
                id=bulk_job_id,
                name="SEC EDGAR: bulk submissions + companyfacts",
                replace_existing=True,
                args=[None],
            )
        elif _scheduler.get_job(bulk_job_id) is not None and bulk_trigger is None:
            _scheduler.remove_job(bulk_job_id)
        # Remover tickers que deixaram de existir.
        for job in list(_scheduler.get_jobs()):
            if job.id.startswith(JOB_PREFIX) and job.id not in wanted:
                _scheduler.remove_job(job.id)
    return status()


def status() -> Dict[str, Any]:
    """Estado do agendador e próximas execuções."""
    with _lock:
        jobs: List[Dict[str, Any]] = []
        if _started and _scheduler is not None:
            for job in _scheduler.get_jobs():
                if job.id.startswith(JOB_PREFIX):
                    next_run: Optional[str] = None
                    try:
                        next_dt = job.next_run_time
                        next_run = next_dt.isoformat() if next_dt else None
                    except Exception:
                        pass
                    jobs.append({"id": job.id, "name": job.name, "next_run": next_run})
        return {
            "started": _started,
            "error": _error,
            "job_count": len(jobs),
            "jobs": jobs,
        }


def run_now(ticker: str, user_id: Optional[str] = None) -> Dict[str, Any]:
    """Executa manualmente a recolha SEC para um ticker."""
    ticker = _normalize_ticker(ticker)
    _job_function(ticker, user_id=user_id)
    return {"ticker": ticker, "triggered": True}
