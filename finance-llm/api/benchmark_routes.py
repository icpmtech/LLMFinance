"""Rotas do módulo **Benchmark de preços e concorrência** (`/benchmark/*`).

Dá a uma entidade do sistema (empresa que vende ao Estado ou entidade que
compra), e opcionalmente um CPV, a leitura do mercado em que se move:

- `GET /benchmark/meta`    — volumetria do índice de contratos e anos
- `GET /benchmark/cpv`     — CPV mais usados (seletor), com descrição
- `GET /benchmark/entity`  — preço de referência, concorrência, historial e oportunidades

`/benchmark/entity` aceita a entidade por `nif` (preferido) ou `name`, o papel
(`adjudicatario` = vende, `adjudicante` = compra), o `cpv_code` e a janela de
anos. Todos os valores são em euros.
"""
from __future__ import annotations

import logging
from typing import Any, Dict, Optional

from fastapi import APIRouter, HTTPException, Query

from api import benchmark_service as benchmark

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/benchmark", tags=["benchmark"])


@router.get("/meta")
def benchmark_meta() -> Dict[str, Any]:
    """Volumetria do índice `contratos` e anos disponíveis."""
    resultado = benchmark.benchmark_meta()
    if resultado.get("error"):
        raise HTTPException(status_code=503, detail=str(resultado["error"]))
    return resultado


@router.get("/cpv")
def benchmark_cpv(
    q: Optional[str] = Query(None, description="Prefixo do código CPV (ex.: `90511`)"),
    size: int = Query(20, ge=1, le=100, description="Quantos CPV devolver"),
) -> Dict[str, Any]:
    """CPV mais usados no índice (para escolher o segmento)."""
    resultado = benchmark.top_cpv(q=q, size=size)
    if resultado.get("error"):
        raise HTTPException(status_code=503, detail=str(resultado["error"]))
    return resultado


@router.get("/entity")
def benchmark_entity(
    nif: Optional[str] = Query(None, description="NIF da entidade (preferido)"),
    name: Optional[str] = Query(None, description="Nome da entidade (usado quando não há NIF)"),
    role: str = Query(
        "adjudicatario",
        description="Papel da entidade: `adjudicatario` (vende) ou `adjudicante` (compra)",
    ),
    cpv_code: Optional[str] = Query(None, description="Código CPV do segmento (prefixo aceite)"),
    year_from: Optional[int] = Query(None, description="Ano inicial (inclusive)"),
    year_to: Optional[int] = Query(None, description="Ano final (inclusive)"),
    region: Optional[str] = Query(None, description="Região/NUTS ou distrito português"),
    top: int = Query(12, ge=1, le=50, description="Quantas linhas por tabela"),
) -> Dict[str, Any]:
    """Benchmark de preços, concorrência, historial e oportunidades."""
    if not (nif or (name or "").strip()):
        raise HTTPException(status_code=422, detail="Indique a entidade por `nif` ou `name`.")
    resultado = benchmark.benchmark_entity(
        nif=nif,
        name=name,
        role=role,
        cpv_code=cpv_code,
        year_from=year_from,
        year_to=year_to,
        region=region,
        top=top,
    )
    if resultado.get("error"):
        raise HTTPException(status_code=502, detail=str(resultado["error"]))
    return resultado
