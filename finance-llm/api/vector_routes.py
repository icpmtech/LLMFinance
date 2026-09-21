"""Rotas REST para vector search no Elasticsearch.

- POST /elastic/vectors/index      — indexa embeddings em falta
- POST /elastic/vectors/search   — pesquisa semântica/híbrida
- GET  /elastic/vectors/status    — estatísticas de embeddings
"""
from __future__ import annotations

import asyncio
from typing import Any, Dict, Optional

from fastapi import APIRouter, BackgroundTasks, Body, Query

from api import vector_service as service

# Estado global simples para tarefas de indexação em background.
_index_jobs: dict[str, dict] = {}

router = APIRouter(prefix="/elastic/vectors", tags=["vectors"])


def _run_index_job(job_id: str, es_index: str, batch_size: int, max_docs: Optional[int]):
    """Corre num thread separado para não bloquear o worker uvicorn."""

    async def _runner():
        _index_jobs[job_id]["status"] = "running"
        result = await service.index_missing_embeddings_async(
            es_index,
            batch_size=batch_size,
            max_docs=max_docs,
            progress_callback=lambda idx, err: _index_jobs[job_id].update({"indexed": idx, "errors": err}),
        )
        _index_jobs[job_id].update({"status": "completed" if not result.get("error") else "error", "result": result})

    asyncio.run(_runner())


@router.post("/index")
async def index_embeddings(
    background_tasks: BackgroundTasks,
    payload: Optional[Dict[str, Any]] = Body(default=None),
):
    """Indexa embeddings para documentos que ainda não os têm.

    Body opcional:
    {
        "index": "contratos" | "finance_entities",
        "batch_size": 64,
        "max_docs": 1000,
        "async": true
    }
    """
    payload = payload or {}
    index = payload.get("index", "contratos")
    if index not in ("contratos", "finance_entities"):
        return {"error": "Índice não suportado"}
    es_index = service.CONTRACTS_INDEX if index == "contratos" else service.ENTITIES_INDEX

    use_async = payload.get("async", True)
    batch_size = payload.get("batch_size", 64)
    max_docs = payload.get("max_docs")

    if not use_async:
        return service.index_missing_embeddings(es_index, batch_size=batch_size, max_docs=max_docs)

    job_id = f"{index}_{asyncio.get_event_loop().time()}"
    _index_jobs[job_id] = {
        "index": index,
        "es_index": es_index,
        "status": "queued",
        "indexed": 0,
        "errors": 0,
        "started_at": None,
    }
    background_tasks.add_task(_run_index_job, job_id, es_index, batch_size, max_docs)
    _index_jobs[job_id]["started_at"] = asyncio.get_event_loop().time()
    return {"job_id": job_id, "status": "queued", "index": index, "es_index": es_index}


@router.get("/index/jobs/{job_id}")
async def get_index_job(job_id: str):
    """Devolve estado de uma tarefa de indexação."""
    job = _index_jobs.get(job_id)
    if not job:
        return {"error": "Job não encontrado"}
    return job


@router.get("/index/jobs")
async def list_index_jobs():
    """Lista tarefas de indexação."""
    return {"jobs": list(_index_jobs.values())}


@router.post("/search")
async def vector_search(
    payload: Dict[str, Any] = Body(...),
):
    """Pesquisa semântica/híbrida.

    Body:
    {
        "query": "contratos de software no Porto",
        "index": "contratos",
        "mode": "vector" | "hybrid",
        "top_k": 20,
        "filters": {"year_from": 2022, "year_to": 2026, "district": "Porto", "nif": "503504564"},
        "min_score": 0.0
    }
    """
    query = payload.get("query", "").strip()
    if not query:
        return {"error": "Query em falta"}
    index_key = payload.get("index", "contratos")
    mode = payload.get("mode", "vector")
    top_k = int(payload.get("top_k", 20))
    filters = payload.get("filters") or {}
    min_score = float(payload.get("min_score", 0.0))

    if mode == "hybrid":
        if index_key != "contratos":
            return {"error": "Modo hybrid apenas suportado para contratos"}
        return service.hybrid_search_contracts(query, top_k=top_k, filters=filters)

    es_index = service.CONTRACTS_INDEX if index_key == "contratos" else service.ENTITIES_INDEX
    return service.vector_search(es_index, query, top_k=top_k, filters=filters, min_score=min_score)


@router.get("/status")
async def vector_status():
    """Devolve estatísticas de embeddings por índice."""
    return service.vector_search_status()


@router.post("/ensure-mappings")
async def ensure_mappings():
    """Garante que os campos dense_vector existem nos índices."""
    return service.ensure_vector_indices()
