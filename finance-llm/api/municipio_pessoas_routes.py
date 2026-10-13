"""Rotas para o módulo **Executivos Municipais**.

- `GET /people/municipio/candidates`      — lista de membros de executivos
- `GET /people/municipio/stats`           — resumo indexado
- `POST /people/municipio/refresh`        — recolher novamente os 308 concelhos
"""
from __future__ import annotations

from typing import Annotated, Any, Dict, Optional

from fastapi import APIRouter, Depends, Query

from api import municipio_pessoas_service as municipios
from api.auth_routes import CurrentSession, optional_session

router = APIRouter(prefix="/people/municipio", tags=["municipio_pessoas"])

Session = Annotated[CurrentSession, Depends(optional_session)]


@router.get("/candidates", summary="Lista de membros de executivos municipais")
def list_municipio_candidates(
    q: Optional[str] = Query(None, description="Nome, partido, cargo ou concelho"),
    district: Optional[str] = Query(None, description="Distrito"),
    concelho: Optional[str] = Query(None, description="Concelho"),
    party: Optional[str] = Query(None, description="Sigla ou nome do partido"),
    role: Optional[str] = Query(None, description="Cargo (Presidente, Vice-Presidente, Vereador)"),
    page: int = Query(1, ge=1),
    size: int = Query(50, ge=1, le=500),
    refresh: bool = Query(False, description="Forçar recolha nova"),
    session: Session = None,
) -> Dict[str, Any]:
    if refresh:
        municipios.refresh_executivos()
    return municipios.search_municipio_pessoas(
        q=q,
        district=district,
        concelho=concelho,
        party=party,
        role=role,
        size=size,
        page=page,
    )


@router.get("/stats", summary="Resumo dos executivos municipais indexados")
def municipio_stats(session: Session = None) -> Dict[str, Any]:
    return municipios.stats()


@router.post("/refresh", summary="Recolher e indexar os executivos dos 308 concelhos")
def municipio_refresh(session: Session = None) -> Dict[str, Any]:
    return municipios.refresh_executivos()
