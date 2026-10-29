"""Rotas FastAPI do **custo de vida por concelho** (`/custo-vida/*`).

- `GET  /custo-vida/concelhos`        — lista (308) com filtros, ordenação e índice
- `GET  /custo-vida/meta`             — fontes, referências, cobertura e limites
- `GET  /custo-vida/concelho/{nome}`  — ficha de um concelho
- `POST /custo-vida/recolher`         — recolher as fontes, reconstruir e indexar

O que a página pública mostra vem daqui: o mapa e a tabela do site são gerados
a partir do mesmo índice, para não haver dois números para a mesma coisa.
"""
from __future__ import annotations

from typing import Annotated, Any, Dict, Optional

from fastapi import APIRouter, Depends, Query
from starlette.concurrency import run_in_threadpool

from api import custo_vida_service as custo_vida
from api.auth_routes import CurrentSession, optional_session
from collectors import custo_vida as recolha

router = APIRouter(prefix="/custo-vida", tags=["custo_vida"])

Session = Annotated[CurrentSession, Depends(optional_session)]


@router.get("/concelhos", summary="Custo de vida e índice por concelho")
async def custo_vida_concelhos(
    q: Optional[str] = Query(None, description="Nome do concelho"),
    distrito: Optional[str] = Query(None, description="Distrito"),
    nuts: Optional[str] = Query(None, description="Região NUTS III"),
    ordenar: str = Query(
        "indice",
        description="indice | custo | renda | gasoleo | imi | nome | populacao",
    ),
    ordem: str = Query("desc", description="asc | desc"),
    size: int = Query(400, ge=1, le=500),
    page: int = Query(1, ge=1),
    session: Session = None,
) -> Dict[str, Any]:
    from api import elasticsearch_client as es

    return await run_in_threadpool(
        es.listar_custo_vida,
        q=q,
        distrito=distrito,
        nuts=nuts,
        ordenar=ordenar,
        ordem=ordem,
        size=size,
        page=page,
    )


@router.get("/meta", summary="Fontes, referências e cobertura do índice")
async def custo_vida_meta(session: Session = None) -> Dict[str, Any]:
    def _meta() -> Dict[str, Any]:
        from api import elasticsearch_client as es

        construido = custo_vida.construir()
        return {**(construido.get("meta") or {}), "indice": es.custo_vida_status()}

    return await run_in_threadpool(_meta)


@router.get("/concelho/{nome}", summary="Ficha de um concelho")
async def custo_vida_concelho(nome: str, session: Session = None) -> Dict[str, Any]:
    from api import elasticsearch_client as es

    return await run_in_threadpool(es.obter_custo_vida, nome)


@router.post("/recolher", summary="Recolher as fontes, reconstruir e indexar")
async def custo_vida_recolher(session: Session = None) -> Dict[str, Any]:
    def _recolher() -> Dict[str, Any]:
        from api import elasticsearch_client as es

        componentes = recolha.recolher_tudo()
        construido = custo_vida.construir(componentes)
        resultado = es.index_custo_vida_bulk(construido.get("docs") or [])
        return {"componentes": sorted(componentes), **resultado, "meta": construido.get("meta")}

    return await run_in_threadpool(_recolher)
