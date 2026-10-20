"""Rotas FastAPI do módulo **Governo** (`/governo/*`).

Expõe as fichas e o grafo de relações construídos por `api/governo_service.py`:

* `GET /governo/overview` — números, ministérios, membros e o grafo geral;
* `GET /governo/graph` — só o grafo (ministério → membro → gabinete);
* `GET /governo/membros` — lista/pesquisa dos membros do Governo;
* `GET /governo/ficha/{member_id}` — ficha do membro: detalhe, remunerações do
  gabinete, relações e grafo;
* `GET /governo/pessoa/{nif}` — ficha de uma pessoa de entidade, com cargos,
  empresas e grafo (e a ligação ao Governo, quando existe);
* `GET /governo/pesquisa?q=` — pesquisa unificada de membros e pessoas.
"""
from __future__ import annotations

from typing import Annotated, Any, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import Response
from starlette.concurrency import run_in_threadpool

from api import governo_service
from api.auth_routes import CurrentSession, optional_session
from api.elasticsearch_client import search_people

router = APIRouter(prefix="/governo", tags=["governo"])

ReadSession = Annotated[Optional[CurrentSession], Depends(optional_session)]


def _spa_para_browser(request: Request) -> Optional[Response]:
    """Devolve a SPA quando o pedido vem de um browser (deep link), senão `None`.

    O endereço da ficha serve a API (JSON, para o `fetch` do frontend) e a
    página (HTML, para quem abre o link diretamente). O `import` é local
    porque `api.main` importa este módulo.
    """
    aceita = request.headers.get("accept") or ""
    if "text/html" not in aceita:
        return None
    from api.main import spa_page_response

    return spa_page_response(str(request.url.path))


@router.get("/overview")
async def governo_overview(session: ReadSession = None) -> Dict[str, Any]:
    """Visão geral do Governo: totais, ministérios, membros e grafo de relações."""
    return await run_in_threadpool(governo_service.graph_overview)


@router.get("/graph")
async def governo_graph(session: ReadSession = None) -> Dict[str, Any]:
    """Grafo ministério → membro → gabinete (formato `StudioGraph`)."""
    overview = await run_in_threadpool(governo_service.graph_overview)
    return {"graph": overview.get("graph"), "stats": overview.get("stats")}


@router.get("/membros")
async def governo_membros(
    q: Optional[str] = Query(None, description="Nome, cargo ou área"),
    area: Optional[str] = Query(None, description="Slug da área (ex.: `cultura`)"),
    size: int = Query(40, ge=1, le=200),
    offset: int = Query(0, ge=0),
    session: ReadSession = None,
) -> Dict[str, Any]:
    """Lista/pesquisa os membros do Governo."""
    return await run_in_threadpool(governo_service.list_members, q or "", area or "", size, offset)


@router.get("/ficha/{member_id}")
async def governo_ficha(member_id: str, request: Request, session: ReadSession = None) -> Any:
    """Ficha de um membro do Governo: detalhe, remunerações, relações e grafo."""
    pagina = _spa_para_browser(request)
    if pagina is not None:
        return pagina
    detail = await run_in_threadpool(governo_service.member_detail, member_id)
    if detail.get("error"):
        raise HTTPException(status_code=404, detail=detail["error"])
    return detail


@router.get("/pessoa/{nif}")
async def governo_pessoa(nif: str, session: ReadSession = None) -> Dict[str, Any]:
    """Ficha de uma pessoa de entidade: cargos, empresas, grafo e ligação ao Governo."""
    detail = await run_in_threadpool(governo_service.person_detail, nif)
    if detail.get("error"):
        raise HTTPException(status_code=404, detail=detail["error"])
    return detail


@router.get("/pesquisa")
async def governo_pesquisa(
    q: str = Query("", description="Nome, cargo ou NIF"),
    size: int = Query(12, ge=1, le=50),
    session: ReadSession = None,
) -> Dict[str, Any]:
    """Pesquisa membros do Governo e pessoas indexadas com o mesmo nome."""
    term = q.strip()
    if not term:
        return {"q": q, "membros": [], "pessoas": []}
    membros = await run_in_threadpool(governo_service.list_members, term, "", size, 0)
    pessoas = await run_in_threadpool(search_people, q=term, size=size)
    return {
        "q": q,
        "membros": membros.get("items", []),
        "pessoas": (pessoas.get("items") or [])[:size],
    }

