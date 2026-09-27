"""Execuções do World Model em segundo plano (reconstrução e treino da rede).

Reconstruir o mundo lê vários índices grandes (contratos PT/ES) e pode demorar
minutos; a rota responde logo com um `job_id` e o progresso vai sendo escrito no
registo (visível em `/world/jobs/{id}` e na página do módulo).

O registo é em memória (como o das recolhas do CIRE): cada job guarda os passos,
o resultado final e o erro, se houver. `MAX_JOBS` limita o histórico.
"""
from __future__ import annotations

import logging
import threading
import time
import uuid
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional

logger = logging.getLogger(__name__)

MAX_JOBS = 20

_lock = threading.RLock()
_jobs: Dict[str, Dict[str, Any]] = {}
_order: List[str] = []


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def submit(kind: str, target: Callable[..., Any], params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Arranca uma execução em segundo plano e devolve o registo do job."""
    job_id = f"{kind}-{uuid.uuid4().hex[:8]}"
    job: Dict[str, Any] = {
        "job_id": job_id,
        "kind": kind,
        "status": "a correr",
        "created_at": _now(),
        "started_at": _now(),
        "finished_at": None,
        "progress": [],
        "params": params or {},
        "result": None,
        "error": None,
    }
    with _lock:
        _jobs[job_id] = job
        _order.append(job_id)
        while len(_order) > MAX_JOBS:
            expired = _order.pop(0)
            _jobs.pop(expired, None)

    def _progress(label: str, **extra: Any) -> None:
        with _lock:
            entry = {"label": label, "at": _now(), **extra}
            job["progress"].append(entry)
        logger.debug("Job %s: %s", job_id, label)

    def _run() -> None:
        started = time.time()
        try:
            # A reconstrução aceita `progress`; o treino da rede não. Decidir
            # pelo assinatura evita repetir o trabalho num TypeError interno.
            accepts_progress = True
            try:
                import inspect

                accepts_progress = "progress" in inspect.signature(target).parameters
            except (TypeError, ValueError):
                accepts_progress = False
            if accepts_progress:
                result = target(params=params or {}, progress=_progress)
            else:
                result = target(params=params or {})
            with _lock:
                job["result"] = result
                job["status"] = "concluído"
        except Exception as exc:  # pragma: no cover - depende do cluster
            logger.warning("Job %s falhou: %s", job_id, exc)
            with _lock:
                job["status"] = "falhou"
                job["error"] = str(exc)[:600]
        finally:
            with _lock:
                job["finished_at"] = _now()
                job["elapsed_s"] = round(time.time() - started, 2)

    threading.Thread(target=_run, name=f"world-{job_id}", daemon=True).start()
    return dict(job)


def get(job_id: str) -> Optional[Dict[str, Any]]:
    """Estado de uma execução."""
    with _lock:
        job = _jobs.get(job_id)
        return dict(job) if job else None


def list_jobs(limit: int = 20) -> List[Dict[str, Any]]:
    """Execuções recentes (mais recentes primeiro)."""
    with _lock:
        jobs = [_jobs[job_id] for job_id in reversed(_order) if job_id in _jobs]
    return [dict(job) for job in jobs[: max(1, int(limit))]]


def running() -> bool:
    """Indica se há uma execução a correr (evita reconstruções concorrentes)."""
    with _lock:
        return any(job["status"] == "a correr" for job in _jobs.values())


def busy_job() -> Optional[Dict[str, Any]]:
    """A execução em curso, se existir."""
    with _lock:
        for job in _jobs.values():
            if job["status"] == "a correr":
                return dict(job)
    return None
