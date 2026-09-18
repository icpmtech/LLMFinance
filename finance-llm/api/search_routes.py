"""Rotas da pesquisa unificada (`/search/*`) — a pesquisa «estilo Google» do IQ OS.

- `GET /search/scopes`   — catálogo de âmbitos (Recolha, Contratos, Empresas, …)
- `GET /search/unified`  — pesquisa por texto em todos os âmbitos (ou num só)
- `GET /search/suggest`  — sugestões para a caixa de pesquisa

A leitura é pública, com uma exceção deliberada: o âmbito **CRM** só é
pesquisado quando há sessão, porque cada utilizador só pode ver os seus
registos (os administradores veem os da equipa).
"""
from __future__ import annotations

import logging
from typing import Annotated, Any, Dict, Optional

from fastapi import APIRouter, Depends, Query

from api import search_service
from api.auth_routes import CurrentSession, optional_session

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/search", tags=["search"])

Session = Annotated[Optional[CurrentSession], Depends(optional_session)]


def _scope(session: Optional[CurrentSession]) -> Optional[Dict[str, Any]]:
    """Âmbito de visibilidade para o CRM (privado por utilizador)."""
    if not session:
        return None
    return {
        "user_id": session.user.id,
        "email": session.user.email,
        "see_all": (session.user.role or "member") == "admin",
    }


@router.get("/scopes")
def search_scopes() -> Dict[str, Any]:
    """Âmbitos disponíveis (para os separadores da página de pesquisa)."""
    return {"items": search_service.scopes_catalog()}


@router.get("/unified")
def search_unified(
    q: str = Query("", description="Texto a pesquisar (título, descrição, entidades, NIF, ticker…)."),
    scope: str = Query("all", description="Âmbito: all | scraped | contracts | entities | trademarks | firmas | news | market | crm"),
    size: int = Query(8, ge=1, le=50, description="Resultados por âmbito."),
    offset: int = Query(0, ge=0, description="Resultados a saltar (no âmbito escolhido)."),
    session: Session = None,
) -> Dict[str, Any]:
    """Pesquisa em todos os âmbitos em paralelo, com resultados agrupados."""
    return search_service.unified_search(
        q,
        scope=scope,
        size=size,
        offset=offset,
        session_scope=_scope(session),
    )


@router.get("/suggest")
def search_suggest(
    q: str = Query("", min_length=1),
    limit: int = Query(8, ge=1, le=20),
    session: Session = None,
) -> Dict[str, Any]:
    """Sugestões (empresas, recolha e tickers) para autocompletar a pesquisa."""
    return search_service.suggest(q, limit=limit, session_scope=_scope(session))
