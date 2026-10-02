"""Rotas dos contratos públicos de França (`/contracts-fr/*`) — DECP.

O índice Elasticsearch (`contratos_fr`) é alimentado por
`collectors/contratos_fr.py` a partir de `data/contratos-franca/decp-*.json`.

- `GET  /contracts-fr/status`             — volumetria indexada (total, anos, natures)
- `GET  /contracts-fr/meta`               — ficheiros DECP disponíveis e JSONLs locais
- `POST /contracts-fr/search`             — pesquisa com filtros e facetas
- `GET  /contracts-fr/autocomplete?q=`    — sugestões (acheteurs, adjudicatários, CPV)
- `GET  /contracts-fr/entities?q=&kind=`  — entidades (acheteurs e titulaires)
- `GET  /contracts-fr/{doc_id}`           — detalhe de um contrato
- `POST /contracts-fr/import`             — importar um ficheiro DECP (normaliza e indexa) (sessão)
- `GET  /contracts-fr/imports`            — importações em curso/recentes
- `GET  /contracts-fr/import/{job_id}`    — progresso de uma importação
"""
from __future__ import annotations

import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Annotated, Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from api.auth_routes import CurrentSession, require_session
from api.elasticsearch_client import (
    contratos_fr_autocomplete,
    contratos_fr_status,
    contratos_fr_years_available,
    get_contrato_fr,
    get_contratos_fr_analytics,
    search_contratos_fr,
    search_contratos_fr_entities,
)
from api.models import (
    ContratoFrAnalyticsRequest,
    ContratoFrAutocompleteRequest,
    ContratoFrEntitySearchRequest,
    ContratoFrImportRequest,
    ContratoFrImportResponse,
    ContratoFrIngestRequest,
    ContratoFrSearchRequest,
    ContractAnalyticsResponse,
)

router = APIRouter(prefix="/contracts-fr", tags=["contratos-fr"])

Session = Annotated[CurrentSession, Depends(require_session)]

MAX_JOBS = 20


# ------------------------------------------------------------------- importações
_jobs: Dict[str, Dict[str, Any]] = {}
_lock = threading.Lock()


def _job_update(job_id: str, **fields: Any) -> None:
    with _lock:
        job = _jobs.get(job_id)
        if job:
            job.update(fields)
            job["updated_at"] = datetime.now(timezone.utc).isoformat()


def _run_import(job_id: str, req: ContratoFrImportRequest) -> None:
    """Trabalhador da importação: normaliza o DECP e indexa no Elasticsearch."""
    from collectors import contratos_fr as pipeline

    try:
        source_dir = Path(pipeline.SOURCE_DIR)
        if req.filename:
            source_path = source_dir / req.filename
        else:
            # Se não for indicado, escolher o ficheiro mais recente.
            files = sorted(source_dir.glob("decp-*.json"))
            if not files:
                _job_update(job_id, state="error", message="Nenhum ficheiro DECP encontrado", finished=True)
                return
            source_path = files[-1]

        if not source_path.exists():
            _job_update(job_id, state="error", message=f"Ficheiro não encontrado: {source_path}", finished=True)
            return

        _job_update(job_id, state="running", stage="normalizar", filename=source_path.name)
        norm = pipeline.build_jsonl(source_path, force=req.force, limit=req.limit, on_progress=lambda p: None)
        idx: Dict[str, Any] = {"indexed_count": 0}
        if req.index and norm.get("count"):
            _job_update(job_id, stage="indexar", docs=norm.get("count", 0))
            idx = pipeline.index_jsonl(Path(norm["path"]), max_records=req.limit)

        _job_update(
            job_id,
            state="done",
            stage="concluido",
            docs=norm.get("count", 0),
            indexed=idx.get("indexed_count", 0),
            errors=idx.get("errors", 0),
            path=norm.get("path"),
            finished=True,
            message=f"{norm.get('count', 0)} documentos normalizados, {idx.get('indexed_count', 0)} indexados",
        )
    except Exception as exc:  # noqa: BLE001
        _job_update(job_id, state="error", message=str(exc), finished=True)


# ------------------------------------------------------------------- leitura
@router.get("/status")
def contratos_fr_status_endpoint() -> Dict[str, Any]:
    """Volumetria do índice `contratos_fr`."""
    res = contratos_fr_status()
    if res.get("error"):
        raise HTTPException(status_code=502, detail=res.get("error"))
    return res


@router.get("/meta")
def contratos_fr_meta() -> Dict[str, Any]:
    """Ficheiros DECP disponíveis, JSONLs normalizados e anos indexados."""
    from collectors import contratos_fr as pipeline

    sources = pipeline._list_sources()
    return {
        "sources": sources,
        "indexed_years": contratos_fr_years_available(),
        "processed_dir": str(pipeline.PROCESSED_DIR),
    }


@router.get("/analytics")
def contratos_fr_analytics_endpoint(
    q: Optional[str] = None,
    ano: Optional[int] = None,
    nature: Optional[str] = None,
    procedure: Optional[str] = None,
    acheteur: Optional[str] = None,
    acheteur_id: Optional[str] = None,
    adjudicatario: Optional[str] = None,
    adjudicatario_id: Optional[str] = None,
    cpv_code: Optional[str] = None,
    lieu_execution_code: Optional[str] = None,
    lieu_execution_type: Optional[str] = None,
    min_value: Optional[float] = None,
    max_value: Optional[float] = None,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    date_field: Optional[str] = Query(None, description="date_notification | date_publication"),
) -> ContractAnalyticsResponse:
    """Agregações analíticas para o dashboard de contratos de França."""
    res = get_contratos_fr_analytics(
        q=q,
        ano=ano,
        nature=nature,
        procedure=procedure,
        acheteur=acheteur,
        acheteur_id=acheteur_id,
        adjudicatario=adjudicatario,
        adjudicatario_id=adjudicatario_id,
        cpv_code=cpv_code,
        lieu_execution_code=lieu_execution_code,
        lieu_execution_type=lieu_execution_type,
        min_value=min_value,
        max_value=max_value,
        start_date=start_date,
        end_date=end_date,
        date_field=date_field,
    )
    if res.get("error"):
        raise HTTPException(status_code=502, detail=res.get("error"))
    return ContractAnalyticsResponse(**res)


@router.post("/search")
def contratos_fr_search_endpoint(req: ContratoFrSearchRequest) -> Dict[str, Any]:
    """Pesquisa contratos de França com filtros e facetas."""
    res = search_contratos_fr(
        q=req.q,
        ano=req.ano,
        nature=req.nature,
        procedure=req.procedure,
        acheteur=req.acheteur,
        acheteur_id=req.acheteur_id,
        adjudicatario=req.adjudicatario,
        adjudicatario_id=req.adjudicatario_id,
        cpv_code=req.cpv_code,
        lieu_execution_code=req.lieu_execution_code,
        lieu_execution_type=req.lieu_execution_type,
        min_value=req.min_value,
        max_value=req.max_value,
        start_date=req.start_date,
        end_date=req.end_date,
        date_field=req.date_field,
        size=req.size,
        from_=req.from_,
        sort_by=req.sort_by,
        sort_order=req.sort_order,
        with_facets=req.with_facets,
    )
    if res.get("error"):
        raise HTTPException(status_code=502, detail=res.get("error"))
    return res


@router.get("/autocomplete")
def contratos_fr_autocomplete_endpoint(
    q: str = Query(..., min_length=1),
    size: int = Query(10, ge=1, le=50),
) -> Dict[str, Any]:
    """Sugestões de acheteurs, adjudicatários e CPV."""
    res = contratos_fr_autocomplete(q=q, size=size)
    if res.get("error"):
        raise HTTPException(status_code=502, detail=res.get("error"))
    return res


@router.get("/entities")
def contratos_fr_entities_endpoint(
    q: str = Query("", description="Nome (total ou parcial) do acheteur ou titulaire."),
    kind: str = Query("all", description="acheteur | adjudicatario | all"),
    ano: Optional[int] = Query(None, description="Ano dos contratos a considerar."),
    size: int = Query(20, ge=1, le=100),
    from_: int = Query(0, ge=0, alias="from"),
) -> Dict[str, Any]:
    """Entidades de França (acheteurs e titulaires) por nome."""
    only = kind if kind in ("acheteur", "adjudicatario") else None
    res = search_contratos_fr_entities(q=q or None, kind=only, ano=ano, size=size, from_=from_)
    if res.get("error"):
        raise HTTPException(status_code=502, detail=res.get("error"))
    return res


@router.get("/imports")
def contratos_fr_imports_endpoint() -> Dict[str, Any]:
    """Importações em curso e recentes (mais recentes primeiro)."""
    with _lock:
        jobs = sorted(_jobs.values(), key=lambda j: j.get("created_at", ""), reverse=True)
    return {"jobs": jobs[:MAX_JOBS]}


@router.get("/import/{job_id}")
def contratos_fr_import_status_endpoint(job_id: str) -> Dict[str, Any]:
    """Progresso de uma importação."""
    with _lock:
        job = _jobs.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Importação não encontrada")
    return job


@router.post("/import")
def contratos_fr_import_endpoint(req: ContratoFrImportRequest, session: Session) -> Dict[str, Any]:
    """Arranca a importação de um ficheiro DECP em segundo plano (normaliza e indexa)."""
    from collectors import contratos_fr as pipeline

    if req.filename:
        source_path = Path(pipeline.SOURCE_DIR) / req.filename
        if not source_path.exists():
            raise HTTPException(status_code=404, detail=f"Ficheiro não encontrado: {req.filename}")

    job_id = uuid.uuid4().hex[:12]
    job = {
        "id": job_id,
        "filename": req.filename,
        "limit": req.limit,
        "index": req.index,
        "force": req.force,
        "state": "queued",
        "stage": "em espera",
        "docs": 0,
        "indexed": 0,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "created_by": getattr(session, "user_id", None) or getattr(session, "email", None),
        "finished": False,
    }
    with _lock:
        _jobs[job_id] = job
        if len(_jobs) > MAX_JOBS:
            for old in sorted(_jobs.values(), key=lambda j: j.get("created_at", ""))[: len(_jobs) - MAX_JOBS]:
                _jobs.pop(old["id"], None)

    threading.Thread(target=_run_import, args=(job_id, req), name=f"contratos-fr-{job_id}", daemon=True).start()
    return job


@router.get("/{doc_id}")
def contrato_fr_detail_endpoint(doc_id: str) -> Dict[str, Any]:
    """Detalhe de um contrato de França (pelo `_id` do documento no Elasticsearch)."""
    res = get_contrato_fr(doc_id)
    if res.get("error"):
        raise HTTPException(status_code=404, detail=res.get("error"))
    return res


# Endpoints adicionais compatíveis com os modelos reutilizados no esquema PT/ES.
@router.post("/ingest")
def contratos_fr_ingest_endpoint(req: ContratoFrIngestRequest, session: Session) -> ContratoFrImportResponse:
    """Ingestão síncrona de um ficheiro DECP (normaliza e, opcionalmente, indexa)."""
    from collectors import contratos_fr as pipeline

    if req.filename:
        source_path = Path(pipeline.SOURCE_DIR) / req.filename
    else:
        files = sorted(Path(pipeline.SOURCE_DIR).glob("decp-*.json"))
        if not files:
            raise HTTPException(status_code=404, detail="Nenhum ficheiro DECP encontrado")
        source_path = files[-1]

    if not source_path.exists():
        raise HTTPException(status_code=404, detail=f"Ficheiro não encontrado: {source_path.name}")

    norm = pipeline.build_jsonl(source_path, force=req.force, limit=req.limit)
    resp = ContratoFrImportResponse(
        total=norm.get("count", 0),
        errors=norm.get("errors", 0),
        path=norm.get("path"),
        seconds=norm.get("seconds"),
    )
    return resp
