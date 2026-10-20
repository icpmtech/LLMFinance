"""Rotas da **Pesquisa PessoasIQ** (`/pessoas-iq/pesquisa/*`).

Uma pesquisa «estilo Google» de pessoas no IQ OS: uma caixa devolve resultados
agregados de várias fontes — cadastro de pessoas (`finance_people`), políticos,
devedores, executivos municipais, membros do Governo e titulares da Entidade
para a Transparência. Cada origem mantém a sua forma de abrir ficha; aqui
só se expõe a lista unificada com facetas e contagem.

- `GET /pessoas-iq/pesquisa`          — pesquisa unificada (query, fonte, página, tamanho)
- `GET /pessoas-iq/pesquisa/suggest`  — sugestões enquanto se escreve
- `GET /pessoas-iq/pesquisa/fontes`   — catálogo de fontes disponíveis
"""
from __future__ import annotations

import logging
from typing import Annotated, Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.concurrency import run_in_threadpool

from api import pessoas_iq_pesquisa_service as service
from api.auth_routes import CurrentSession, optional_session

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/pessoas-iq/pesquisa", tags=["pessoas-iq-pesquisa"])

Session = Annotated[Optional[CurrentSession], Depends(optional_session)]


@router.get("/fontes", summary="Fontes disponíveis para a pesquisa de pessoas")
def pesquisa_fontes(session: Session = None) -> Dict[str, Any]:
    """Catálogo de fontes, identificadores e descrições."""
    return {"fontes": service.FONTES}


@router.get("/suggest", summary="Sugestões enquanto se escreve")
async def pesquisa_suggest(
    q: Annotated[str, Query(min_length=1, max_length=200)],
    limit: Annotated[int, Query(ge=1, le=20)] = 8,
    session: Session = None,
) -> Dict[str, Any]:
    """Sugestões de pessoas a partir do cadastro e políticos."""
    try:
        result = await run_in_threadpool(service.suggest, q=q, limit=limit)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return result


@router.get("", summary="Pesquisa unificada de pessoas")
async def pesquisa_pessoas(
    q: Annotated[Optional[str], Query(description="Nome, NIF, cargo ou parte do nome")] = None,
    fonte: Annotated[Optional[str], Query(description="Fonte: todas, pessoas, politicos, devedores, municipios, governo, ept")] = "todas",
    page: Annotated[int, Query(ge=1, le=100)] = 1,
    size: Annotated[int, Query(ge=1, le=100)] = 20,
    session: Session = None,
) -> Dict[str, Any]:
    """Pesquisa Google-like de pessoas em todas as fontes conhecidas."""
    try:
        result = await run_in_threadpool(
            service.pesquisar,
            q=q or "",
            fonte=fonte or "todas",
            page=page,
            size=size,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return result
