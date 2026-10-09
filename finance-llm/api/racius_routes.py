"""Rotas do diretório de empresas do Racius (`/racius/*`).

Leitura pública (como os restantes módulos): a página de pesquisa do diretório
consome `GET /racius/search` e `GET /racius/meta`. Os dados vêm da recolha do
IQ OS (fonte `racius-diretorio`), indexados em `finance_racius`.

- `GET /racius/meta`   — total de empresas e opções dos filtros
- `GET /racius/search` — pesquisa por texto + filtros (distrito, concelho,
  forma jurídica, CAE, capital social), com facetas
"""
from __future__ import annotations

import logging
from typing import Annotated, Optional

from fastapi import APIRouter, Query

from api import racius_service as service

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/racius", tags=["racius"])


@router.get("/meta")
def racius_meta() -> dict:
    """Volumetria e opções de filtro do diretório."""
    return service.meta()


@router.get("/search")
def racius_search(
    q: Annotated[str, Query(description="Texto livre: nome, NIF, morada, atividade…")] = "",
    distrito: Annotated[Optional[str], Query()] = None,
    concelho: Annotated[Optional[str], Query()] = None,
    forma_juridica: Annotated[Optional[str], Query()] = None,
    cae: Annotated[Optional[str], Query()] = None,
    min_capital: Annotated[Optional[float], Query(description="Capital social mínimo (€)")] = None,
    max_capital: Annotated[Optional[float], Query(description="Capital social máximo (€)")] = None,
    sort: Annotated[str, Query(description="relevance | nome | capital | recent | oldest")] = "relevance",
    size: Annotated[int, Query(ge=1, le=100)] = 20,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> dict:
    """Pesquisa empresas no diretório recolhido."""
    return service.search(
        q=q,
        distrito=distrito,
        concelho=concelho,
        forma_juridica=forma_juridica,
        cae=cae,
        min_capital=min_capital,
        max_capital=max_capital,
        sort=sort,
        size=size,
        offset=offset,
    )
