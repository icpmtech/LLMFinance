"""Rotas do módulo Arquivo.pt (`/arquivo/*`).

Pesquisa e recolha de páginas preservadas pelo Arquivo.pt (FCT).

Leitura (pública):
- `GET /arquivo/meta`   — metadados do módulo
- `GET /arquivo/status` — volumetria do índice local
- `GET /arquivo/search` — pesquisar capturas indexadas

Escrita (sessão):
- `POST /arquivo/collect` — recolher resultados do Arquivo.pt e indexá-los
"""
from __future__ import annotations

import logging
from typing import Annotated, Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from collectors import arquivo as collector

from api import arquivo_service
from api.auth_routes import CurrentSession, optional_session, require_session

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/arquivo", tags=["arquivo"])

Session = Annotated[CurrentSession, Depends(require_session)]
ReadSession = Annotated[Optional[CurrentSession], Depends(optional_session)]


class ArquivoCollectRequest(BaseModel):
    """Pedido de recolha ao Arquivo.pt."""

    q: str = Field(..., description="Termos de pesquisa")
    max_pages: int = Field(collector.DEFAULT_MAX_PAGES, ge=1, le=50, description="Máximo de páginas a percorrer")
    max_items: int = Field(collector.DEFAULT_MAX_ITEMS, ge=1, le=200, description="Resultados por página")
    site: Optional[str] = Field(None, description="Filtrar por domínio (ex.: portugal.gov.pt)")
    type: Optional[str] = Field(None, description="Tipo MIME (ex.: html, pdf)")
    from_ts: Optional[str] = Field(None, description="Timestamp inicial (YYYYmmddHHMMSS)")
    to_ts: Optional[str] = Field(None, description="Timestamp final (YYYYmmddHHMMSS)")
    ingest: bool = Field(True, description="Indexar no Elasticsearch")
    min_interval: float = Field(collector.DEFAULT_MIN_INTERVAL, ge=0, le=10, description="Intervalo mínimo entre pedidos (s)")


class ArquivoIngestRequest(BaseModel):
    """Indexação manual de itens já normalizados."""

    items: List[Dict[str, Any]] = Field(default_factory=list, description="Itens normalizados do Arquivo.pt")
    kind: str = Field("search", description="Tipo de captura (search | cdx)")


@router.get("/meta")
def arquivo_meta() -> Dict[str, Any]:
    """Metadados do módulo Arquivo.pt."""
    return arquivo_service.meta()


@router.get("/status")
def arquivo_status() -> Dict[str, Any]:
    """Volumetria do índice local de capturas do Arquivo.pt."""
    res = arquivo_service.status()
    if res.get("error"):
        raise HTTPException(status_code=502, detail=res["error"])
    return res


@router.get("/search")
def arquivo_search(
    q: Optional[str] = Query(None, description="Texto livre (título, URL, domínio, snippet)"),
    domain: Optional[str] = Query(None, description="Filtrar por domínio"),
    url: Optional[str] = Query(None, description="Filtrar por URL exato"),
    mime_type: Optional[str] = Query(None, description="Tipo MIME"),
    type: Optional[str] = Query(None, description="Tipo de captura indexada"),
    from_date: Optional[str] = Query(None, description="Data mínima de captura (AAAA-MM-DD)"),
    to_date: Optional[str] = Query(None, description="Data máxima de captura (AAAA-MM-DD)"),
    kind: Optional[str] = Query(None, description="Origem da captura (search | cdx)"),
    sort: str = Query("relevance", description="Ordenação: relevance | date_desc | date_asc | domain"),
    size: int = Query(20, ge=1, le=200),
    offset: int = Query(0, ge=0),
) -> Dict[str, Any]:
    """Pesquisa capturas do Arquivo.pt indexadas localmente."""
    res = arquivo_service.search(
        q=q,
        domain=domain,
        url=url,
        mime_type=mime_type,
        type=type,
        from_date=from_date,
        to_date=to_date,
        kind=kind,
        sort=sort,
        size=size,
        offset=offset,
    )
    if res.get("error"):
        raise HTTPException(status_code=502, detail=res["error"])
    return res


@router.post("/collect")
def arquivo_collect(
    req: ArquivoCollectRequest,
    session: Session = None,  # type: ignore[assignment]
) -> Dict[str, Any]:
    """Recolhe resultados do Arquivo.pt e indexa-os no Elasticsearch."""
    res = arquivo_service.collect(
        q=req.q,
        max_pages=req.max_pages,
        max_items=req.max_items,
        site=req.site,
        type=req.type,
        from_ts=req.from_ts,
        to_ts=req.to_ts,
        ingest=req.ingest,
        min_interval=req.min_interval,
    )
    if res.get("error"):
        raise HTTPException(status_code=502, detail=res["error"])
    return res


@router.post("/ingest")
def arquivo_ingest(
    req: ArquivoIngestRequest,
    session: Session = None,  # type: ignore[assignment]
) -> Dict[str, Any]:
    """Indexa itens do Arquivo.pt já normalizados."""
    res = arquivo_service.index_items(req.items, kind=req.kind)
    if res.get("error"):
        raise HTTPException(status_code=502, detail=res["error"])
    return res
