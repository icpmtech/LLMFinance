"""Rotas FastAPI do módulo **Despesas das câmaras municipais** (`/municipios/*`).

Uma **área por município**, com duas coisas que se cruzam:

- a **despesa** anual do indicador 0013909 do INE (origem DGAL), por
  classificador económico (`D`, `D1`, `D11`, …), em euros;
- a **contratação pública** em que o município é adjudicante, agregada do
  Portal BASE — total, valor, série anual, os anos mais recentes de cada
  município e os principais fornecedores.

- `GET  /municipios/despesas`            — lista de municípios, com filtros e ordenação
  (cada linha traz `contratos_recentes`: os anos mais recentes desse município)
- `GET  /municipios/despesas/meta`       — proveniência dos dados e volumetria
- `GET  /municipios/despesas/mapa`       — todos os municípios com os valores para o mapa
- `GET  /municipios/despesas/{municipio}`— ficha de um município (nome ou código INE)
- `POST /municipios/despesas/recolher`   — recolher do INE e dos contratos, e indexar
"""
from __future__ import annotations

from typing import Annotated, Any, Dict, Optional

from fastapi import APIRouter, Depends, Query
from starlette.concurrency import run_in_threadpool

from api import municipios_service as municipios
from api.auth_routes import CurrentSession, optional_session

router = APIRouter(prefix="/municipios", tags=["municipios"])

Session = Annotated[CurrentSession, Depends(optional_session)]


@router.get("/despesas", summary="Municípios com despesa e contratação")
async def municipios_despesas(
    q: Optional[str] = Query(None, description="Nome do município ou código INE"),
    distrito: Optional[str] = Query(None, description="Distrito (substring)"),
    nuts: Optional[str] = Query(None, description="Código NUTS III (ex.: 1D2)"),
    ano: Optional[int] = Query(None, description="Ano com despesa publicada"),
    ano_contratos: Optional[int] = Query(
        None,
        description="Ano do Portal BASE cuja contratação a lista mostra e ordena (ex.: 2024)",
    ),
    ordenar: str = Query(
        "despesas",
        description=(
            "despesas | pessoal | bens_servicos | capital | contratos | contratos_total | nome. "
            "Com `ano_contratos`, `contratos` e `contratos_total` passam a ser os **desse ano**."
        ),
    ),
    ordem: str = Query("desc", description="asc | desc"),
    min_despesas: Optional[float] = Query(None, description="Despesa total mínima, em euros"),
    page: int = Query(1, ge=1),
    size: int = Query(30, ge=1, le=500),
    session: Session = None,
) -> Dict[str, Any]:
    return await run_in_threadpool(
        municipios.listar,
        q=q, distrito=distrito, nuts=nuts, ano=ano, ano_contratos=ano_contratos,
        ordenar=ordenar, ordem=ordem, min_despesas=min_despesas,
        size=size, page=page,
    )


@router.get("/despesas/meta", summary="Proveniência e volumetria das despesas municipais")
async def municipios_meta(session: Session = None) -> Dict[str, Any]:
    return await run_in_threadpool(municipios.meta)


@router.get("/despesas/mapa", summary="Municípios com os valores para o mapa")
async def municipios_mapa(session: Session = None) -> Dict[str, Any]:
    return await run_in_threadpool(municipios.mapa)


@router.post("/despesas/recolher", summary="Recolher do INE e dos contratos, e indexar")
async def municipios_recolher(
    forcar: bool = Query(False, description="Ignorar a cache local e recolher de novo"),
    session: Session = None,
) -> Dict[str, Any]:
    return await run_in_threadpool(municipios.recolher, forcar)


@router.get("/despesas/{municipio}/fornecedores", summary="Todos os fornecedores de um município")
async def municipio_fornecedores(
    municipio: str,
    ano: Optional[int] = Query(
        None, description="Ano da contratação no Portal BASE; sem ano, todo o período (2012→2026)"
    ),
    q: Optional[str] = Query(None, description="Filtro pelo nome do fornecedor"),
    size: int = Query(100, ge=1, le=500),
    page: int = Query(1, ge=1),
    session: Session = None,
) -> Dict[str, Any]:
    """Lista **completa** dos fornecedores, com pesquisa e paginação.

    A ficha mostra os maiores (`contratos_detalhe.fornecedores`); este endpoint
    dá a lista toda, para se poder ver e procurar qualquer fornecedor.
    """
    return await run_in_threadpool(
        municipios.fornecedores, municipio, ano=ano, q=q, size=size, page=page
    )


@router.get("/despesas/{municipio}", summary="Ficha de um município")
async def municipio_ficha(
    municipio: str,
    ano: Optional[int] = Query(
        None,
        description=(
            "Ano da contratação a detalhar (fornecedores e tipos desse ano), calculado no "
            "índice do Portal BASE (ex.: 2024). A série anual vem sempre completa."
        ),
    ),
    session: Session = None,
) -> Dict[str, Any]:
    """Aceita o nome (tolerante a acentos) ou o código geográfico do INE."""
    return await run_in_threadpool(municipios.ficha, municipio, True, ano)
