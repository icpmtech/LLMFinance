"""Rotas da recolha massiva de empresas (`/empresas-recolha/*`).

Partilha a mesma semântica do módulo de recolha societária: arrancar jobs em
segundo plano, listar exportações por distrito/concelho, pré-visualizar e
re-executar recolhas.
"""
from __future__ import annotations

import logging
from typing import Annotated, Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from api import empresas_recolha_service as service
from api.auth_routes import CurrentSession, optional_session, require_session

logger = logging.getLogger(__name__)


def _councils_from_exports(distrito: str) -> List[str]:
    """Devolve os concelhos de um distrito que têm exportações."""
    base = service.export_dir() / service._slugify(distrito)
    if not base.exists():
        return []
    return sorted({p.name for p in base.iterdir() if p.is_dir()})

router = APIRouter(prefix="/empresas-recolha", tags=["empresas-recolha"])

Session = Annotated[CurrentSession, Depends(require_session)]
ReadSession = Annotated[CurrentSession, Depends(optional_session)]


class RecolhaEmpresasRequest(BaseModel):
    """Pedido de recolha massiva de empresas por distrito/concelho."""

    distrito: str = Field(..., min_length=1, description="Distrito (ex.: Évora)")
    concelho: str = Field(..., min_length=1, description="Concelho (ex.: Alandroal)")
    start_page: int = Field(1, ge=1, description="Página inicial do diretório")
    max_pages: int = Field(1, ge=1, le=50, description="Número de páginas a recolher")
    detail: bool = Field(True, description="Recolher o texto integral da ficha de cada empresa")
    delay: float = Field(1.0, ge=0, le=10, description="Segundos entre pedidos de detalhe")
    ingest: bool = Field(False, description="Indexar automaticamente no finance_scraped")


class EmpresaDetailRequest(BaseModel):
    """Pedido de pré-visualização de uma ficha individual."""

    url: str = Field(..., min_length=10, description="URL da página de detalhe (ex.: /empresa/<nif>/<slug>)")


@router.get("/meta")
def recolha_meta(session: ReadSession = None) -> Dict[str, Any]:
    """Metadados do módulo: pasta de exportação e distritos/concelhos disponíveis."""
    return {
        "module": "empresas-recolha",
        "export_dir": str(service.export_dir()),
        "export_dir_env": service.EXPORT_DIR_ENV,
        "districts": service.districts_from_exports(),
    }


@router.get("/concelhos/{distrito}")
def recolha_concelhos(
    distrito: str,
    session: ReadSession = None,
) -> Dict[str, Any]:
    """Lista os concelhos de um distrito que já têm exportações."""
    return {"distrito": distrito, "concelhos": _councils_from_exports(distrito)}


@router.get("/jobs")
def recolha_list_jobs(
    limit: int = Query(20, ge=1, le=100),
    session: ReadSession = None,
) -> Dict[str, Any]:
    """Lista os trabalhos de recolha mais recentes."""
    return {"jobs": service.list_jobs(limit=limit)}


@router.get("/jobs/{job_id}")
def recolha_get_job(
    job_id: str,
    session: ReadSession = None,
) -> Dict[str, Any]:
    """Estado de um trabalho de recolha."""
    return service.get_job(job_id)


@router.post("/jobs")
def recolha_start_job(
    req: RecolhaEmpresasRequest,
    session: Session,
) -> Dict[str, Any]:
    """Arranca uma recolha em segundo plano por distrito/concelho."""
    try:
        return service.start_job(
            distrito=req.distrito,
            concelho=req.concelho,
            start_page=req.start_page,
            max_pages=req.max_pages,
            detail=req.detail,
            delay=req.delay,
            ingest=req.ingest,
        )
    except Exception as exc:
        logger.exception("Falha a arrancar recolha de empresas")
        raise HTTPException(status_code=502, detail=f"Erro ao arrancar a recolha: {exc}") from exc


@router.post("/sync")
def recolha_sync(
    req: RecolhaEmpresasRequest,
    session: Session,
) -> Dict[str, Any]:
    """Executa uma recolha síncrona (bloqueia até terminar)."""
    return service.run_sync(
        distrito=req.distrito,
        concelho=req.concelho,
        start_page=req.start_page,
        max_pages=req.max_pages,
        detail=req.detail,
        delay=req.delay,
        ingest=req.ingest,
    )


@router.get("/exports")
def recolha_list_exports(
    distrito: Optional[str] = Query(None, description="Filtrar por distrito"),
    concelho: Optional[str] = Query(None, description="Filtrar por concelho (requer distrito)"),
    limit: int = Query(100, ge=1, le=500),
    session: ReadSession = None,
) -> Dict[str, Any]:
    """Lista os ficheiros JSON exportados."""
    return service.list_exports(distrito=distrito, concelho=concelho, limit=limit)


@router.get("/exports/view")
def recolha_read_export(
    path: str = Query(..., description="Caminho relativo ao export_dir"),
    session: ReadSession = None,
) -> Dict[str, Any]:
    """Lê um ficheiro de exportação."""
    res = service.read_export(path)
    if res.get("error"):
        raise HTTPException(status_code=404, detail=res["error"])
    return res


@router.post("/detail")
def recolha_detail(
    req: EmpresaDetailRequest,
    session: Session,
) -> Dict[str, Any]:
    """Recolhe o detalhe de uma empresa individual."""
    return service.preview_item(req.url)
