"""Análise, ontologia e relatórios de uma pesquisa da Pesquisa total.

- `GET  /search/analysis/contracts` — custos do conjunto encontrado (PT+ES) e
  empresas/pessoas associadas, por NIF.
- `GET  /search/graph`              — ontologia da pesquisa (nós/arestas + Mermaid).
- `POST /search/chat`               — chat de IA que responde sobre os resultados da pesquisa.
- `POST /search/report/pdf`         — relatório PDF dos contratos filtrados.
- `POST /search/report/excel`       — o mesmo em Excel (uma folha por secção).

Tudo leituras sobre índices públicos (contratos, entidades, pessoas) — não há
escritas aqui; o que se guarda (portfólio, favoritos) vive em
`search_workspace_routes.py`.
"""
from __future__ import annotations

import json
import logging
from typing import Annotated, Any, Dict, Optional

from fastapi import APIRouter, Body, Depends, HTTPException, Query, Response

from api import search_analysis, search_chat, search_ontology, search_report
from api.auth_routes import CurrentSession, optional_session

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/search", tags=["search-analysis"])

Session = Annotated[Optional[CurrentSession], Depends(optional_session)]

XLSX_MEDIA = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


def _session_scope(session: Optional[CurrentSession]) -> Optional[Dict[str, Any]]:
    if not session:
        return None
    return {
        "user_id": session.user.id,
        "email": session.user.email,
        "see_all": (session.user.role or "member") == "admin",
    }


@router.get("/analysis/contracts")
def contracts_analysis(
    q: str = Query("", description="Termo da pesquisa (o mesmo da Pesquisa total)."),
    year: Optional[int] = Query(None, description="Limita a um ano."),
    top: int = Query(8, ge=3, le=25, description="Quantos itens por ranking."),
    links: bool = Query(True, description="Inclui fichas de empresas e pessoas associadas."),
) -> Dict[str, Any]:
    """Quanto valem os contratos encontrados, como se distribuem e quem está por trás."""
    result = search_analysis.contracts_analysis(q, year=year, top=top, with_links=links)
    if result.get("error"):
        raise HTTPException(400, result["error"])
    return result


@router.get("/graph")
def search_graph(
    q: str = Query("", description="Termo da pesquisa."),
    scope: str = Query("all", description="Âmbito (o mesmo da Pesquisa total)."),
    filters: Optional[str] = Query(None, description="Filtros do âmbito, em JSON."),
    size: int = Query(12, ge=3, le=50, description="Resultados por âmbito a incluir no grafo."),
    session: Session = None,
) -> Dict[str, Any]:
    """Ontologia da pesquisa: o termo, o que ele encontrou e as ligações reais entre eles."""
    from api.search_service import parse_filters  # vocabulário igual ao da pesquisa

    return search_ontology.search_ontology(
        q,
        scope=scope,
        filters=parse_filters(filters),
        size=size,
        session_scope=_session_scope(session),
    )


def _download(content: bytes, filename: str, media_type: str) -> Response:
    return Response(
        content=content,
        media_type=media_type,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.post("/chat")
async def search_chat_ask(
    payload: Dict[str, Any] = Body(...),
    session: Session = None,
) -> Dict[str, Any]:
    """Chat de IA sobre a pesquisa: os resultados dela são o contexto da resposta.

    Sem fornecedor de IA com chave (Definições de IA), devolve `error` explicativo
    em vez de uma resposta inventada.
    """
    from api.search_service import parse_filters

    filtros = payload.get("filters") or {}
    return await search_chat.ask_search(
        str(payload.get("question") or ""),
        query=str(payload.get("q") or payload.get("query") or ""),
        scope=str(payload.get("scope") or "all"),
        filters=parse_filters(json.dumps(filtros) if filtros else None),
        history=payload.get("history") or [],
        include_analysis=bool(payload.get("include_analysis", True)),
        backend=payload.get("backend"),
        session=session,
    )


@router.get("/chat/status")
def search_chat_status(session: Session = None) -> Dict[str, Any]:
    """Fornecedor de IA que responderá ao chat (para a interface avisar sem tentar)."""
    from api.ontology_ai import available_backend

    resolvido = available_backend(session, None)
    return {
        "available": bool(resolvido.get("kind") == "cloud" and resolvido.get("api_key")),
        "provider": resolvido.get("provider"),
        "model": resolvido.get("model"),
        "note": resolvido.get("note"),
        "kind": resolvido.get("kind"),
    }


def _analysis_from_body(payload: Dict[str, Any]) -> Dict[str, Any]:
    query = str(payload.get("q") or payload.get("query") or "").strip()
    if not query:
        raise HTTPException(400, "Falta o termo da pesquisa (`q`).")
    return search_analysis.contracts_analysis(
        query,
        year=payload.get("year"),
        top=int(payload.get("top") or 8),
        with_links=bool(payload.get("links", True)),
    )


@router.post("/report/pdf")
def search_report_pdf(payload: Dict[str, Any] = Body(...)) -> Response:
    """Relatório PDF: resumo, séries, maiores adjudicatários e contratos filtrados."""
    analysis = _analysis_from_body(payload)
    limit = int(payload.get("limit") or search_report.MAX_ROWS_PDF)
    try:
        content = search_report.report_pdf(str(analysis.get("query")), analysis, limit=limit)
    except Exception as exc:
        logger.exception("Relatório PDF da pesquisa falhou: %s", exc)
        raise HTTPException(500, f"Falha ao gerar o PDF: {exc}")
    name = f"contratos-{(analysis.get('query') or 'pesquisa')[:40].replace(' ', '-')}.pdf"
    return _download(content, name, "application/pdf")


@router.post("/report/excel")
def search_report_excel(payload: Dict[str, Any] = Body(...)) -> Response:
    """Relatório Excel: uma folha por secção, com os contratos e valores."""
    analysis = _analysis_from_body(payload)
    limit = int(payload.get("limit") or search_report.MAX_ROWS_EXCEL)
    try:
        content = search_report.report_xlsx(str(analysis.get("query")), analysis, limit=limit)
    except Exception as exc:
        logger.exception("Relatório Excel da pesquisa falhou: %s", exc)
        raise HTTPException(500, f"Falha ao gerar o Excel: {exc}")
    name = f"contratos-{(analysis.get('query') or 'pesquisa')[:40].replace(' ', '-')}.xlsx"
    return _download(content, name, XLSX_MEDIA)
