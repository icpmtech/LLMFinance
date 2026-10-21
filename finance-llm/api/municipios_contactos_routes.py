"""Rotas FastAPI do módulo **Contactos das câmaras municipais**.

- `GET  /municipios/contactos`            — pesquisa Google-like (q + filtros)
- `GET  /municipios/contactos/stats`      — resumo do índice
- `GET  /municipios/contactos/{codigo}`   — ficha de um município (código INE)
- `POST /municipios/contactos/recolher`   — recolher do Excel e indexar
"""
from __future__ import annotations

from typing import Annotated, Any, Dict, Optional

from fastapi import APIRouter, Depends, Query
from starlette.concurrency import run_in_threadpool

from api import municipios_contactos_service as contactos
from api.auth_routes import CurrentSession, optional_session

router = APIRouter(prefix="/municipios/contactos", tags=["municipios_contactos"])

Session = Annotated[CurrentSession, Depends(optional_session)]


@router.get("", summary="Pesquisar contactos das câmaras municipais")
async def contactos_pesquisar(
    q: Optional[str] = Query(None, description="Texto livre: município, presidente, e-mail, morada, telefone…"),
    distrito: Optional[str] = Query(None, description="Distrito (substring)"),
    codigo_ine: Optional[str] = Query(None, description="Código INE do município (4 dígitos)"),
    page: int = Query(1, ge=1),
    size: int = Query(30, ge=1, le=500),
    session: Session = None,
) -> Dict[str, Any]:
    return await run_in_threadpool(
        contactos.pesquisar,
        q=q,
        distrito=distrito,
        codigo_ine=codigo_ine,
        size=size,
        page=page,
    )


@router.get("/stats", summary="Resumo dos contactos municipais indexados")
async def contactos_stats(session: Session = None) -> Dict[str, Any]:
    return await run_in_threadpool(contactos.stats)


@router.get("/{codigo_ine}", summary="Ficha de contactos de um município")
async def contactos_ficha(
    codigo_ine: str,
    session: Session = None,
) -> Dict[str, Any]:
    return await run_in_threadpool(contactos.ficha, codigo_ine)


@router.post("/recolher", summary="Recolher do Excel e indexar no Elasticsearch")
async def contactos_recolher(
    forcar: bool = Query(False, description="Ignorar a cache e recolher de novo"),
    session: Session = None,
) -> Dict[str, Any]:
    return await run_in_threadpool(contactos.recolher_e_indexar, forcar)
