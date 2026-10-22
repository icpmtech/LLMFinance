"""Rotas da lista de sociedades com **mais de 200 ações** (`/grandes-litigantes/*`).

Enquadramento: n.º 3 do artigo 13.º do Regulamento das Custas Processuais e
Portaria n.º 200/2011, de 20 de maio (taxas de justiça das tabelas I-C e II-B).

- `GET  /grandes-litigantes/meta`              — pasta, índices, volumetria e enquadramento
- `GET  /grandes-litigantes/fontes`            — fonte oficial, faixas e ligações
- `GET  /grandes-litigantes/search`            — pesquisa (texto, NIPC, ano, faixa) com facetas
- `GET  /grandes-litigantes/sociedade/{nipc}`  — ficha: anos em que a sociedade entrou na lista
- `GET  /grandes-litigantes/export.csv`        — CSV da pesquisa atual
- `GET  /grandes-litigantes/recolhas`          — recolhas registadas (data, anos, nº de registos)
- `GET  /grandes-litigantes/snapshots`         — instantâneos JSON guardados no disco
- `GET  /grandes-litigantes/snapshots/{base}`  — pré-visualização de um instantâneo
- `POST /grandes-litigantes/collect`           — recolha (+ indexação) em segundo plano
- `POST /grandes-litigantes/ingest`            — (re)indexa os instantâneos guardados
- `GET  /grandes-litigantes/jobs[/{job_id}]`   — progresso dos trabalhos

A leitura é pública; a recolha exige sessão (é um pedido ao portal do Estado e
fica registado quem o fez).
"""
from __future__ import annotations

import logging
from typing import Annotated, Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel, Field

from api import grandes_litigantes_service as service
from api.auth_routes import CurrentSession, optional_session, require_session

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/grandes-litigantes", tags=["grandes-litigantes"])

Session = Annotated[CurrentSession, Depends(require_session)]
ReadSession = Annotated[Optional[CurrentSession], Depends(optional_session)]


class GrandesLitigantesCollectRequest(BaseModel):
    """Como recolher a lista."""

    termo: str = Field("", description="Pesquisa livre (vazio = lista completa)")
    tipo: str = Field("nipc", description="Tipo da pesquisa livre: `nipc` ou `nome`")
    max_paginas: int = Field(200, ge=1, le=200, description="Máximo de páginas (o portal serve ~30 linhas por página)")
    indexar: bool = Field(True, description="Indexar no Elasticsearch logo após a recolha")


class GrandesLitigantesIngestRequest(BaseModel):
    """Indexação dos instantâneos guardados."""

    bases: Optional[List[str]] = Field(None, description="Indexar só estes instantâneos (por omissão, todos)")


@router.get("/meta")
def grandes_litigantes_meta(session: ReadSession = None) -> Dict[str, Any]:
    """Pasta dos dados, índices, volumetria e enquadramento legal."""
    return service.meta()


@router.get("/fontes")
def grandes_litigantes_fontes(session: ReadSession = None) -> Dict[str, Any]:
    """Fonte oficial, faixas do artigo 13.º e ligações de referência."""
    return {
        "fonte": {
            "id": service.FONTE,
            "label": service.FONTE_LABEL,
            "url": service.SOURCE_URL,
        },
        "faixas": service.FAIXAS,
        "enquadramento": {
            "norma": "n.º 3 do artigo 13.º do Regulamento das Custas Processuais",
            "portaria": "Portaria n.º 200/2011, de 20 de maio",
            "tabelas": ["I-C", "II-B"],
            "limiar": "mais de 200 ações, procedimentos ou execuções no ano civil anterior",
            "publicacao": "lista elaborada pela DGAJ, em colaboração com o IGFEJ, até 15 de janeiro",
            "notificacao": "até 25 de janeiro, por carta registada para a sede no registo comercial",
            "autoliquidacao": "até 15 de fevereiro do ano seguinte",
        },
        "ligacoes": [
            {"label": "Consulta no Portal CITIUS", "url": service.SOURCE_URL},
            {
                "label": "Tribunais.org.pt — Lista de sociedades com mais de 200 ações",
                "url": "https://tribunais.org.pt/Publicacoes/Lista-de-Sociedades-com-mais-de-200-acoes",
            },
        ],
    }


@router.get("/search")
def grandes_litigantes_search(
    q: Annotated[str, Query(description="Designação (texto livre) ou NIPC")] = "",
    nipc: Annotated[Optional[str], Query(description="NIPC exato (aceita letras, ex. `LU 31006073`)")] = None,
    ano: Annotated[Optional[int], Query(description="Ano civil da lista")] = None,
    faixa: Annotated[Optional[List[str]], Query(description="Faixa: `201-500` ou `501+`")] = None,
    sort: Annotated[str, Query(description="relevancia | nome | ano | faixa | nipc")] = "relevancia",
    order: Annotated[str, Query(description="asc | desc")] = "asc",
    page: Annotated[int, Query(ge=1)] = 1,
    size: Annotated[int, Query(ge=1, le=200)] = 25,
) -> Dict[str, Any]:
    """Pesquisa as sociedades da lista, com facetas por ano e por faixa."""
    return service.search(
        q=q or None, nipc=nipc, ano=ano, faixa=faixa, sort=sort, order=order, page=page, size=size
    )


@router.get("/sociedade/{nipc}")
def grandes_litigantes_sociedade(nipc: str, session: ReadSession = None) -> Dict[str, Any]:
    """Ficha de uma sociedade: todos os anos em que entrou na lista."""
    return service.por_nipc(nipc)


@router.get("/export.csv", response_class=PlainTextResponse)
def grandes_litigantes_export(
    q: Annotated[str, Query()] = "",
    nipc: Annotated[Optional[str], Query()] = None,
    ano: Annotated[Optional[int], Query()] = None,
    faixa: Annotated[Optional[List[str]], Query()] = None,
    sort: Annotated[str, Query()] = "nome",
    order: Annotated[str, Query()] = "asc",
    maximo: Annotated[int, Query(ge=1, le=20000)] = 5000,
) -> PlainTextResponse:
    """CSV (separador `;`) da pesquisa, com os mesmos filtros da API."""
    corpo = service.export_csv(
        q=q or None, nipc=nipc, ano=ano, faixa=faixa, sort=sort, order=order, maximo=maximo
    )
    return PlainTextResponse(
        corpo,
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": 'attachment; filename="grandes-litigantes.csv"'},
    )


@router.get("/recolhas")
def grandes_litigantes_recolhas(session: ReadSession = None) -> Dict[str, Any]:
    """Recolhas registadas (data, anos abrangidos, nº de registos e ficheiro)."""
    return service.list_recolhas()


@router.get("/snapshots")
def grandes_litigantes_snapshots(session: ReadSession = None) -> Dict[str, Any]:
    """Instantâneos JSON guardados no disco."""
    return service.list_snapshots()


@router.get("/snapshots/{base}")
def grandes_litigantes_snapshot(
    base: str, limit_items: int = Query(25, ge=1, le=500), session: ReadSession = None
) -> Dict[str, Any]:
    """Pré-visualização de um instantâneo (cabeçalho + amostra de registos)."""
    try:
        payload = service.read_export(base)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    registos = payload.get("registos") or []
    return {
        **{k: v for k, v in payload.items() if k != "registos"},
        "registos": registos[:limit_items],
        "total": len(registos),
    }


@router.post("/collect")
def grandes_litigantes_collect(
    payload: GrandesLitigantesCollectRequest, session: Session = None
) -> Dict[str, Any]:
    """Arranca a recolha da lista (e a indexação) em segundo plano."""
    return service.start_job(payload.model_dump())


@router.post("/ingest")
def grandes_litigantes_ingest(
    payload: GrandesLitigantesIngestRequest, session: Session = None
) -> Dict[str, Any]:
    """(Re)indexa os instantâneos guardados em `finance_grandes_litigantes`."""
    return service.indexar_ficheiros(payload.bases)


@router.get("/jobs")
def grandes_litigantes_jobs(session: ReadSession = None) -> Dict[str, Any]:
    """Estado dos trabalhos de recolha."""
    return service.list_jobs()


@router.get("/jobs/{job_id}")
def grandes_litigantes_job(job_id: str, session: ReadSession = None) -> Dict[str, Any]:
    """Estado de um trabalho de recolha."""
    job = service.job_status(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Trabalho não encontrado.")
    return job
