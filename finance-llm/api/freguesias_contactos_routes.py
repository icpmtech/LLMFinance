"""Rotas FastAPI do módulo **Contactos das juntas de freguesia**.

- `GET  /freguesias/contactos`            — pesquisa Google-like (q + filtros)
- `GET  /freguesias/contactos/stats`      — resumo do índice
- `GET  /freguesias/contactos/{codigo}`   — ficha de uma freguesia (código INE)
- `POST /freguesias/contactos/recolher`   — recolher do Excel e indexar
"""
from __future__ import annotations

from typing import Annotated, Any, Dict, Optional

from fastapi import APIRouter, Depends, Query
from starlette.concurrency import run_in_threadpool

from api import freguesias_contactos_service as contactos
from api.auth_routes import CurrentSession, optional_session

router = APIRouter(prefix="/freguesias/contactos", tags=["freguesias_contactos"])

Session = Annotated[CurrentSession, Depends(optional_session)]


@router.get("", summary="Pesquisar contactos das juntas de freguesia")
async def freguesias_pesquisar(
    q: Optional[str] = Query(None, description="Texto livre: freguesia, presidente, e-mail, morada, telefone…"),
    municipio: Optional[str] = Query(None, description="Município (substring)"),
    codigo_ine: Optional[str] = Query(None, description="Código INE da freguesia (6 dígitos)"),
    page: int = Query(1, ge=1),
    size: int = Query(30, ge=1, le=500),
    session: Session = None,
) -> Dict[str, Any]:
    return await run_in_threadpool(
        contactos.pesquisar,
        q=q,
        municipio=municipio,
        codigo_ine=codigo_ine,
        size=size,
        page=page,
    )


@router.get("/stats", summary="Resumo dos contactos de freguesias indexados")
async def freguesias_stats(session: Session = None) -> Dict[str, Any]:
    return await run_in_threadpool(contactos.stats)


@router.get("/{codigo_ine}", summary="Ficha de contactos de uma freguesia")
async def freguesias_ficha(
    codigo_ine: str,
    session: Session = None,
) -> Dict[str, Any]:
    return await run_in_threadpool(contactos.ficha, codigo_ine)


@router.post("/recolher", summary="Recolher do Excel e indexar no Elasticsearch")
async def freguesias_recolher(
    forcar: bool = Query(False, description="Ignorar a cache e recolher de novo"),
    session: Session = None,
) -> Dict[str, Any]:
    return await run_in_threadpool(contactos.recolher_e_indexar, forcar)
