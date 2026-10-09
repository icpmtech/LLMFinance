"""Rotas do módulo **Benchmark de preços e concorrência** (`/benchmark/*`).

Dá a uma entidade do sistema (empresa que vende ao Estado ou entidade que
compra), e opcionalmente um CPV, a leitura do mercado em que se move:

- `GET /benchmark/meta`    — volumetria do índice de contratos e anos
- `GET /benchmark/cpv`     — CPV mais usados (seletor), com descrição
- `GET /benchmark/entity`  — preço de referência, concorrência, historial e oportunidades
- `POST /benchmark/compare`— comparação de **até 10 empresas** no mesmo segmento

`/benchmark/entity` aceita a entidade por `nif` (preferido) ou `name`, o papel
(`adjudicatario` = vende, `adjudicante` = compra), o `cpv_code` e a janela de
anos. Todos os valores são em euros.
"""
from __future__ import annotations

import logging
from typing import Any, Dict, Optional

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from api import benchmark_service as benchmark

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/benchmark", tags=["benchmark"])


class BenchmarkCompareEntity(BaseModel):
    """Uma das empresas a comparar."""

    nif: Optional[str] = Field(None, description="NIF da entidade (preferido)")
    name: Optional[str] = Field(None, description="Nome da entidade (usado quando não há NIF)")


class BenchmarkCompareRequest(BaseModel):
    """Comparação de até 10 empresas no mesmo segmento."""

    entities: list[BenchmarkCompareEntity] = Field(..., description="Empresas a comparar (1 a 10)")
    role: str = Field(
        "adjudicatario",
        description="Papel comum a todas: `adjudicatario` (vendem) ou `adjudicante` (compram)",
    )
    cpv_code: Optional[str] = Field(None, description="Código CPV do segmento (prefixo aceite)")
    year_from: Optional[int] = Field(None, description="Ano inicial (inclusive)")
    year_to: Optional[int] = Field(None, description="Ano final (inclusive)")
    region: Optional[str] = Field(None, description="Região/NUTS ou distrito português")
    top: int = Field(10, ge=1, le=50, description="Quantas posições mostrar no ranking do segmento")


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


@router.post("/compare")
def benchmark_compare_endpoint(req: BenchmarkCompareRequest) -> Dict[str, Any]:
    """Compara até 10 empresas no mesmo segmento (papel + CPV + anos).

    Devolve, para cada empresa, os contratos, o valor, a média e a mediana do
    segmento, a quota de valor, a posição no ranking do segmento e o índice de
    preço face à mediana do mercado — mais o preço de referência do mercado (uma
    só vez) e o ranking do segmento com as empresas comparadas assinaladas.
    """
    entidades = [
        {"nif": item.nif, "name": item.name}
        for item in req.entities
        if (item.nif or "").strip() or (item.name or "").strip()
    ]
    if not entidades:
        raise HTTPException(status_code=422, detail="Indique as empresas a comparar (nif ou name).")
    if len(entidades) > benchmark.MAX_COMPARE:
        raise HTTPException(
            status_code=422,
            detail=f"Só é possível comparar até {benchmark.MAX_COMPARE} empresas de cada vez.",
        )
    resultado = benchmark.benchmark_compare(
        entities=entidades,
        role=req.role,
        cpv_code=req.cpv_code,
        year_from=req.year_from,
        year_to=req.year_to,
        region=req.region,
        top=req.top,
    )
    if resultado.get("error"):
        raise HTTPException(status_code=502, detail=str(resultado["error"]))
    return resultado
