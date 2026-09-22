"""Rotas das empresas/entidades globais (`/companies-global/*`).

Uma vista única sobre todas as fontes de entidades e empresas do IQ OS:

- `GET /companies-global/sources` — catálogo de fontes com volumetria indexada
- `GET /companies-global/search`  — pesquisa em todas as fontes (ou numa só)

A leitura é pública, com uma exceção deliberada: a fonte **CRM** só é pesquisada
quando há sessão, porque as contas são privadas por utilizador.
"""
from __future__ import annotations

import logging
from typing import Annotated, Any, Dict, Optional

from fastapi import APIRouter, Depends, Query

from api import companies_global_service
from api.auth_routes import CurrentSession, optional_session

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/companies-global", tags=["companies-global"])

Session = Annotated[Optional[CurrentSession], Depends(optional_session)]


def _scope(session: Optional[CurrentSession]) -> Optional[Dict[str, Any]]:
    """Âmbito de visibilidade das fontes privadas (CRM)."""
    if not session:
        return None
    return {
        "user_id": session.user.id,
        "email": session.user.email,
        "see_all": (session.user.role or "member") == "admin",
    }


@router.get("/sources")
def companies_global_sources(session: Session = None) -> Dict[str, Any]:
    """Fontes disponíveis (nome, país e volumetria) para os separadores da app."""
    return companies_global_service.sources_summary(_scope(session))


@router.get("/search")
def companies_global_search(
    q: str = Query("", description="Nome, NIF/NIPC, marca, órgão ou conta a pesquisar."),
    source: str = Query("all", description="Fonte: all | entity | firma | trademark | organo_es | adjudicataria_es | crm"),
    size: int = Query(24, ge=1, le=100, description="Resultados a devolver."),
    offset: int = Query(0, ge=0, description="Resultados a saltar (na fonte escolhida)."),
    session: Session = None,
) -> Dict[str, Any]:
    """Pesquisa empresas e entidades, com a contagem por fonte."""
    return companies_global_service.search(
        q,
        source=source,
        size=size,
        offset=offset,
        session_scope=_scope(session),
    )
