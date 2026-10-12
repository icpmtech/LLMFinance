"""Rotas para o módulo **Autárquicas 2025** (candidatos às eleições locais).

- `GET /people/autarquicas/candidates`      — lista de candidatos com filtros
- `GET /people/autarquicas/candidates/{name}` — detalhe de um candidato
- `POST /people/autarquicas/refresh`        — forçar recolha nova
- `GET /people/autarquicas/stats`           — resumo e volumetria
"""
from __future__ import annotations

from typing import Annotated, Any, Dict, Optional

from fastapi import APIRouter, Depends, Query

from api import autarquicas_service as autarquicas
from api.auth_routes import CurrentSession, optional_session

router = APIRouter(prefix="/people/autarquicas", tags=["autarquicas"])

Session = Annotated[CurrentSession, Depends(optional_session)]


@router.get("/candidates", summary="Lista de candidatos às autárquicas 2025")
def autarquicas_candidates(
    q: Optional[str] = Query(None, description="Nome ou partido (sub-string)"),
    district: Optional[str] = Query(None, description="Distrito (substring, ex.: Lisboa)"),
    concelho: Optional[str] = Query(None, description="Concelho (substring)"),
    party: Optional[str] = Query(None, description="Sigla ou nome do partido/coligação"),
    page: int = Query(1, ge=1),
    size: int = Query(50, ge=1, le=500),
    refresh: bool = Query(False, description="Forçar recolha nova do site oficial"),
    session: Session = None,
) -> Dict[str, Any]:
    return autarquicas.list_candidates(
        q=q,
        district=district,
        concelho=concelho,
        party=party,
        refresh=refresh,
        size=size,
        page=page,
    )


@router.get("/candidates/{name}", summary="Detalhe de um candidato")
def autarquicas_candidate_detail(
    name: str,
    party: Optional[str] = Query(None, description="Sigla do partido/coligação"),
    concelho: Optional[str] = Query(None, description="Concelho"),
    session: Session = None,
) -> Dict[str, Any]:
    return autarquicas.candidate_detail(name=name, party=party, concelho=concelho)


@router.post("/refresh", summary="Forçar recolha nova dos candidatos")
def autarquicas_refresh(session: Session = None) -> Dict[str, Any]:
    return autarquicas.refresh_candidates()


@router.get("/stats", summary="Resumo dos candidatos indexados")
def autarquicas_stats(session: Session = None) -> Dict[str, Any]:
    return autarquicas.stats()
