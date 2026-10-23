"""Rotas FastAPI do módulo **Empresas locais**.

- `GET  /empresas-locais`            — pesquisa Google-like (q + filtros)
- `GET  /empresas-locais/stats`      — resumo do índice
- `GET  /empresas-locais/{doc_id}`   — ficha de uma empresa local
- `POST /empresas-locais/recolher`   — recolher do Excel e indexar
"""
from __future__ import annotations

from typing import Annotated, Any, Dict, Optional

from fastapi import APIRouter, Depends, Query
from starlette.concurrency import run_in_threadpool

from api import empresas_locais_service as empresas
from api.auth_routes import CurrentSession, optional_session

router = APIRouter(prefix="/empresas-locais", tags=["empresas_locais"])

Session = Annotated[CurrentSession, Depends(optional_session)]


@router.get("", summary="Pesquisar empresas locais")
async def empresas_locais_pesquisar(
    q: Optional[str] = Query(None, description="Texto livre: designação, entidade, setor…"),
    entidade_local: Optional[str] = Query(None, description="Entidade local participante (substring)"),
    setor: Optional[str] = Query(None, description="Setor de atividade (substring)"),
    page: int = Query(1, ge=1),
    size: int = Query(30, ge=1, le=500),
    session: Session = None,
) -> Dict[str, Any]:
    return await run_in_threadpool(
        empresas.pesquisar,
        q=q,
        entidade_local=entidade_local,
        setor=setor,
        size=size,
        page=page,
    )


@router.get("/stats", summary="Resumo das empresas locais indexadas")
async def empresas_locais_stats(session: Session = None) -> Dict[str, Any]:
    return await run_in_threadpool(empresas.stats)


@router.get("/{doc_id}", summary="Ficha de uma empresa local")
async def empresas_locais_ficha(
    doc_id: str,
    session: Session = None,
) -> Dict[str, Any]:
    return await run_in_threadpool(empresas.ficha, doc_id)


@router.post("/recolher", summary="Recolher do Excel e indexar no Elasticsearch")
async def empresas_locais_recolher(
    forcar: bool = Query(False, description="Ignorar a cache e recolher de novo"),
    session: Session = None,
) -> Dict[str, Any]:
    return await run_in_threadpool(empresas.recolher_e_indexar, forcar)
