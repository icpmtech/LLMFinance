"""Rotas do diretório RigorBiz (`/rigorbiz/*`).

Endpoints:
- ``GET /rigorbiz/meta``      — total e disponibilidade do diretório
- ``GET /rigorbiz/search``    — pesquisa por nome/NIF/CAE/localidade
- ``GET /rigorbiz/{nif}``     — ficha de uma empresa (por NIF)
- ``POST /rigorbiz/collect``  — inicia/retoma recolha total (sessão obrigatória)
- ``GET /rigorbiz/collect/status`` — estado da recolha (checkpoint)

A leitura é pública; a recolha em massa requer sessão por respeitar o site
alvo e evitar uso não autorizado.
"""
from __future__ import annotations

import logging
from typing import Annotated, Any, Dict, Optional

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from api import rigorbiz_service as service
from api.auth_routes import CurrentSession, optional_session, require_session
from api.rigorbiz_collector import collect_all, collect_sample

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/rigorbiz", tags=["rigorbiz"])

Session = Annotated[CurrentSession, Depends(require_session)]
ReadSession = Annotated[Optional[CurrentSession], Depends(optional_session)]


class CollectRequest(BaseModel):
    """Pedido de recolha de empresas da RigorBiz."""

    mode: str = Field("sample", description="all | sample")
    pages: int = Field(1000, ge=1, le=5000, description="Páginas no modo sample")
    delay: float = Field(1.5, ge=0.5, le=5.0, description="Segundos entre páginas")


@router.get("/meta")
def rigorbiz_meta() -> Dict[str, Any]:
    """Volumetria e disponibilidade do diretório RigorBiz."""
    return service.meta()


@router.get("/search")
def rigorbiz_search(
    q: Annotated[str, Query(description="Texto livre: nome, NIF, CAE, localidade…")] = "",
    cae: Annotated[Optional[str], Query(description="Prefixo do código CAE")] = None,
    location: Annotated[Optional[str], Query(description="Texto da localidade")] = None,
    sort: Annotated[str, Query(description="relevance | name")] = "relevance",
    size: Annotated[int, Query(ge=1, le=100)] = 20,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> Dict[str, Any]:
    """Pesquisa empresas no diretório RigorBiz (Elastic se existir, senão JSONL)."""
    return service.search(
        q=q or None,
        cae=cae,
        location=location,
        sort=sort,
        size=size,
        offset=offset,
        use_es=True,
    )


@router.get("/{nif}")
def rigorbiz_detail(nif: str) -> Dict[str, Any]:
    """Ficha de uma empresa do diretório RigorBiz (por NIF)."""
    result = service.detail(nif, use_es=True)
    if not result:
        raise HTTPException(status_code=404, detail="Empresa não encontrada no diretório RigorBiz.")
    return result


@router.post("/collect")
def rigorbiz_collect(
    req: CollectRequest,
    background_tasks: BackgroundTasks,
    session: Session,
) -> Dict[str, Any]:
    """Arranca a recolha de empresas da RigorBiz em segundo plano.

    Usa o runner dedicado que escreve estado em tempo real e indexa a cada batch.
    """
    from api.rigorbiz_runner import run as run_runner
    background_tasks.add_task(run_runner, mode=req.mode, pages=req.pages, delay=req.delay, index_to_es=True)
    return {
        "ok": True,
        "mode": req.mode,
        "pages": req.pages if req.mode != "all" else None,
        "delay": req.delay,
        "message": f"Recolha RigorBiz ({req.mode}) iniciada em segundo plano.",
    }


@router.post("/collect/stop")
def rigorbiz_collect_stop(session: Session) -> Dict[str, Any]:
    """Sinaliza o runner para parar (a recolha atual termina graciosamente)."""
    from api.rigorbiz_runner import stop
    stop()
    return {"ok": True, "message": "Pedido de paragem enviado ao runner."}


@router.get("/collect/status")
def rigorbiz_collect_status() -> Dict[str, Any]:
    """Estado da recolha em tempo real (runner + checkpoint + meta)."""
    from api.rigorbiz_collector import _load_checkpoint
    from api.rigorbiz_runner import get_state
    return {
        "runner": get_state(),
        "checkpoint": _load_checkpoint(),
        "meta": service.meta(),
    }
