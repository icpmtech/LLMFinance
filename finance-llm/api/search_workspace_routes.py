"""Portfólio da Pesquisa total: pesquisas guardadas e conteúdo favoritado.

- `GET    /search/portfolio`            — pesquisas guardadas (as minhas e as antigas sem dono)
- `POST   /search/portfolio`            — guardar a pesquisa atual (consulta + âmbito + filtros)
- `DELETE /search/portfolio/{item_id}`  — retirar do portfólio
- `GET    /search/favorites`            — itens favoritados (de qualquer âmbito)
- `POST   /search/favorites`            — favoritar um resultado
- `DELETE /search/favorites/{kind}/{item_id}` — desfavoritar

Guardar **a pesquisa** (e não o resultado) é deliberado: refazer a pergunta devolve o
que existe hoje, que é o que se quer num portfólio de trabalho. As escritas exigem
sessão (o portfólio é privado); as leituras são públicas mas filtradas pelo dono
quando há sessão — documentos antigos, sem `owner_id`, continuam visíveis.
"""
from __future__ import annotations

import logging
from typing import Annotated, Any, Dict, Optional

from fastapi import APIRouter, Body, Depends, HTTPException, Query

from api import elasticsearch_client as es
from api.auth_routes import CurrentSession, optional_session

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/search", tags=["search-workspace"])

Session = Annotated[Optional[CurrentSession], Depends(optional_session)]


def _writer(session: Optional[CurrentSession]) -> str:
    """Email de quem escreve (o portfólio é de quem o faz)."""
    if not session:
        raise HTTPException(401, "Inicie sessão para guardar no portfólio")
    return session.user.email


def _owner(session: Optional[CurrentSession]) -> Optional[str]:
    return session.user.email if session else None


@router.get("/portfolio")
def portfolio_list(session: Session = None) -> Dict[str, Any]:
    """Pesquisas guardadas no portfólio (mais recentes primeiro)."""
    result = es.list_saved_searches(_owner(session))
    if result.get("error"):
        return {"items": [], "total": 0, "error": result["error"]}
    return result


@router.post("/portfolio")
def portfolio_save(
    payload: Dict[str, Any] = Body(...),
    session: Session = None,
) -> Dict[str, Any]:
    """Guarda a pesquisa atual no portfólio (nome opcional)."""
    email = _writer(session)
    result = es.save_search(payload, owner=email)
    if result.get("error"):
        raise HTTPException(400, result["error"])
    return result


@router.delete("/portfolio/{item_id}")
def portfolio_delete(item_id: str, session: Session = None) -> Dict[str, Any]:
    """Retira uma pesquisa do portfólio."""
    _writer(session)
    result = es.delete_search(item_id)
    if result.get("error"):
        raise HTTPException(400, result["error"])
    return result


@router.get("/favorites")
def favorites_list(session: Session = None) -> Dict[str, Any]:
    """Itens favoritados (empresas, contratos, notícias, pessoas…)."""
    result = es.list_favorites(_owner(session))
    if result.get("error"):
        return {"items": [], "total": 0, "error": result["error"]}
    return result


@router.post("/favorites")
def favorites_save(
    payload: Dict[str, Any] = Body(...),
    session: Session = None,
) -> Dict[str, Any]:
    """Favorita um resultado da pesquisa (ou de outra app)."""
    email = _writer(session)
    result = es.save_favorite(payload, owner=email)
    if result.get("error"):
        raise HTTPException(400, result["error"])
    return result


@router.delete("/favorites/{kind}/{item_id}")
def favorites_delete(kind: str, item_id: str, session: Session = None) -> Dict[str, Any]:
    """Desfavorita um resultado."""
    _writer(session)
    result = es.delete_favorite(kind, item_id)
    if result.get("error"):
        raise HTTPException(400, result["error"])
    return result


@router.get("/favorites/check")
def favorites_check(session: Session = None, q: str = Query("", description="Pesquisa no rótulo (opcional)")) -> Dict[str, Any]:
    """Chaves `kind:id` favoritadas — para a interface marcar as estrelas de uma vez."""
    result = es.list_favorites(_owner(session))
    termo = (q or "").strip().lower()
    itens = result.get("items") or []
    if termo:
        itens = [item for item in itens if termo in str(item.get("label") or "").lower()]
    return {
        "keys": [f"{item.get('kind')}:{item.get('id')}" for item in itens],
        "total": len(itens),
    }
