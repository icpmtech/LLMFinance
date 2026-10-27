"""Rotas do módulo **SEC** (`/sec/*`).

Endpoints de leitura são públicos. Ingestão/análise exigem sessão.
"""
from __future__ import annotations

import logging
from typing import Annotated, Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from starlette.concurrency import run_in_threadpool

from api import sec_scheduler
from api import sec_service as service
from api.auth_routes import CurrentSession, require_session

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/sec", tags=["sec"])

Session = Annotated[CurrentSession, Depends(require_session)]


def _ou_erro(payload: Dict[str, Any]) -> Dict[str, Any]:
    erro = str(payload.get("error") or "")
    if not erro:
        return payload
    if "Elasticsearch" in erro:
        raise HTTPException(status_code=503, detail=erro)
    if "obrigatório" in erro or "inválid" in erro or "desconhecido" in erro or "deve ser" in erro or "Indique" in erro:
        raise HTTPException(status_code=400, detail=erro)
    raise HTTPException(status_code=404, detail=erro)


# ---------------------------------------------------------------------------
# Metadados e pesquisa de empresas
# ---------------------------------------------------------------------------


@router.get("/meta", summary="Metadados e status do módulo SEC")
def sec_meta() -> Dict[str, Any]:
    return service.meta()


@router.get("/companies", summary="Pesquisar empresas na SEC")
def sec_companies(
    q: str = Query(..., min_length=1, description="Nome ou ticker da empresa"),
    size: int = Query(20, ge=1, le=100),
) -> Dict[str, Any]:
    return _ou_erro(service.search_companies_sec(q, max_results=size))


# ---------------------------------------------------------------------------
# Filings
# ---------------------------------------------------------------------------


@router.get("/filings/{cik}", summary="Filings recentes de uma empresa")
async def sec_filings(
    cik: str,
    limit: int = Query(40, ge=1, le=200),
    form: Optional[str] = Query(None, description="Filtrar por tipo de form (ex.: 10-K)"),
) -> Dict[str, Any]:
    forms = [f.strip() for f in form.split(",")] if form else None
    result = await run_in_threadpool(service.filings_for_company, cik, limit, forms)
    return _ou_erro(result)


@router.get("/document", summary="Obter texto integral de um documento SEC")
async def sec_document(url: str = Query(..., min_length=10, description="URL do documento no EDGAR")) -> Dict[str, Any]:
    result = await run_in_threadpool(service.fetch_filing_text, url)
    if result.get("error"):
        raise HTTPException(status_code=404, detail=result["error"])
    return result


# ---------------------------------------------------------------------------
# Ingestão
# ---------------------------------------------------------------------------


@router.post("/filings/{cik}/ingestao", summary="Indexar filings e extrair factos")
async def sec_filings_ingestao(
    cik: str,
    session: Session,
    limit: int = Query(20, ge=1, le=200),
) -> Dict[str, Any]:
    return _ou_erro(
        await run_in_threadpool(
            service.index_filings_for_cik,
            cik,
            limit,
            session.user_id,
        )
    )


@router.get("/facts/{cik}/xbrl", summary="Factos XBRL estruturados da empresa")
async def sec_facts_xbrl(cik: str) -> Dict[str, Any]:
    return _ou_erro(await run_in_threadpool(service.company_facts, cik))


@router.post("/facts/{cik}/indexar", summary="Indexar factos XBRL da empresa")
async def sec_facts_indexar(
    cik: str,
    session: Session,
) -> Dict[str, Any]:
    return _ou_erro(await run_in_threadpool(service.index_company_facts, cik, session.user_id))


# ---------------------------------------------------------------------------
# Pesquisa e análise
# ---------------------------------------------------------------------------


@router.get("/search", summary="Pesquisar filings indexados")
async def sec_search(
    q: Optional[str] = Query(None, min_length=2),
    ticker: Optional[str] = Query(None),
    form: Optional[str] = Query(None),
    cik: Optional[str] = Query(None),
    year: Optional[int] = Query(None),
    size: int = Query(20, ge=1, le=100),
    from_: int = Query(0, ge=0, le=500, alias="from"),
) -> Dict[str, Any]:
    return _ou_erro(
        await run_in_threadpool(
            service.search_filings,
            q=q,
            ticker=ticker,
            form=form,
            cik=cik,
            year=year,
            size=size,
            from_=from_,
        )
    )


@router.get("/facts", summary="Pesquisar factos extraídos dos filings")
async def sec_facts(
    q: Optional[str] = Query(None, min_length=2),
    ticker: Optional[str] = Query(None),
    form: Optional[str] = Query(None),
    category: Optional[str] = Query(None),
    size: int = Query(20, ge=1, le=100),
    from_: int = Query(0, ge=0, le=500, alias="from"),
) -> Dict[str, Any]:
    return _ou_erro(
        await run_in_threadpool(
            service.search_facts,
            q=q,
            ticker=ticker,
            form=form,
            category=category,
            size=size,
            from_=from_,
        )
    )


@router.get("/filings/{doc_id}/ficha", summary="Obter filing indexado pelo ID")
async def sec_filing(doc_id: str) -> Dict[str, Any]:
    item = await run_in_threadpool(service.filing_by_id, doc_id)
    if not item:
        raise HTTPException(status_code=404, detail="Documento não encontrado")
    return item


@router.get("/analytics", summary="Agregações por tipo, ano e ticker")
async def sec_analytics() -> Dict[str, Any]:
    return _ou_erro(await run_in_threadpool(service.analytics))


@router.get("/schedule", summary="Estado do agendador SEC")
async def sec_schedule_status() -> Dict[str, Any]:
    return sec_scheduler.status()


@router.post("/schedule/recarregar", summary="Recarregar jobs de agendamento SEC")
async def sec_schedule_reload(session: Session) -> Dict[str, Any]:
    return sec_scheduler.reload_jobs()


@router.post("/schedule/{ticker}/executar", summary="Executar recolha SEC manualmente")
async def sec_schedule_run(ticker: str, session: Session) -> Dict[str, Any]:
    return sec_scheduler.run_now(ticker, session.user_id)
