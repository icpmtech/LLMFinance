"""Rotas do módulo **Devedores** (`/devedores/*`).

Recolha e pesquisa das listas públicas de devedores:

- `GET  /devedores/meta`            — pasta, índices e volumetria recolhida
- `GET  /devedores/fontes`          — catálogo (ficheiros das Finanças e escalões da Segurança Social)
- `GET  /devedores/files`           — recolhas registadas (PDF + JSON + data da recolha)
- `GET  /devedores/files/{base}/pdf`— descarrega o PDF guardado de uma recolha
- `GET  /devedores/files/{base}`    — pré-visualiza o JSON exportado
- `POST /devedores/collect`         — arranca a recolha (segundo plano)
- `GET  /devedores/jobs[/{id}]`     — progresso dos trabalhos
- `POST /devedores/ingest`          — (re)indexa os JSON exportados
- `GET  /devedores/search`          — área de pesquisa (nome/NIF, tipo, entidade, escalão, data)
- `GET  /devedores/devedor/{nif}`   — ficha: registos de um NIF/NIPC em todas as listas
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Annotated, Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from api import devedores_service as devedores
from api.auth_routes import CurrentSession, optional_session, require_session

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/devedores", tags=["devedores"])

Session = Annotated[CurrentSession, Depends(require_session)]
ReadSession = Annotated[CurrentSession, Depends(optional_session)]


class DevedoresCollectRequest(BaseModel):
    """Como recolher as listas de devedores."""

    entidades: List[str] = Field(
        default_factory=lambda: ["financas"],
        description="Fontes a recolher: `financas` (PDF oficiais) e/ou `seguranca_social` (experimental)",
    )
    ficheiros: Optional[List[str]] = Field(
        None, description="Ficheiros das Finanças a recolher (por omissão, todos); ex.: `listaFS1.pdf`"
    )
    forcar: bool = Field(False, description="Recolher de novo mesmo os ficheiros que já estão recolhidos")
    escaloes_ss: Optional[List[str]] = Field(None, description="Escalões da Segurança Social (por omissão, todos)")
    tipos_ss: Optional[List[str]] = Field(None, description="Tipos da Segurança Social: singulares | coletivos")
    max_paginas: int = Field(400, ge=1, le=5000, description="Máximo de páginas por escalão na Segurança Social")


class DevedoresIngestRequest(BaseModel):
    """Indexação dos JSON exportados."""

    bases: Optional[List[str]] = Field(None, description="Indexar só estas recolhas (por omissão, todas)")


@router.get("/meta")
def devedores_meta(session: ReadSession = None) -> Dict[str, Any]:
    """Pasta dos dados, índices e volumetria do que está recolhido."""
    return devedores.meta()


@router.get("/fontes")
def devedores_fontes(session: ReadSession = None) -> Dict[str, Any]:
    """Catálogo das fontes: ficheiros das Finanças e escalões da Segurança Social."""
    return devedores.fontes()


@router.get("/files")
def devedores_files(session: ReadSession = None) -> Dict[str, Any]:
    """Recolhas registadas (ficheiro, tipo, escalão, data da recolha, PDF e JSON)."""
    return devedores.list_recolhas()


@router.get("/files/{base}")
def devedores_file(base: str, limit_items: int = Query(25, ge=1, le=500), session: ReadSession = None) -> Dict[str, Any]:
    """Pré-visualização de um JSON exportado (cabeçalho + amostra de registos)."""
    try:
        payload = devedores.read_export(base)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    registos = payload.get("registos") or []
    return {**{k: v for k, v in payload.items() if k != "registos"}, "registos": registos[:limit_items], "total": len(registos)}


@router.get("/files/{base}/pdf")
def devedores_file_pdf(base: str) -> FileResponse:
    """Descarrega o PDF guardado de uma recolha."""
    manifest = devedores.read_manifest().get("recolhas") or {}
    entrada = next((item for item in manifest.values() if str(item.get("base")) == str(base)), None)
    caminho = (entrada or {}).get("pdf_path")
    if not caminho or not Path(caminho).exists():
        raise HTTPException(status_code=404, detail="PDF da recolha não encontrado.")
    return FileResponse(caminho, media_type="application/pdf", filename=Path(caminho).name)


@router.post("/collect")
def devedores_collect(payload: DevedoresCollectRequest, session: Session = None) -> Dict[str, Any]:
    """Arranca uma recolha em segundo plano (PDF + JSON por ficheiro + índice)."""
    return devedores.start_job(payload.model_dump())


@router.get("/jobs")
def devedores_jobs(session: ReadSession = None) -> Dict[str, Any]:
    """Estado dos trabalhos de recolha."""
    return devedores.list_jobs()


@router.get("/jobs/{job_id}")
def devedores_job(job_id: str, session: ReadSession = None) -> Dict[str, Any]:
    """Estado de um trabalho de recolha."""
    job = devedores.job_status(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Trabalho não encontrado.")
    return job


@router.post("/ingest")
def devedores_ingest(payload: DevedoresIngestRequest | None = None, session: Session = None) -> Dict[str, Any]:
    """Indexa os JSON já exportados no Elasticsearch."""
    bases = (payload.bases if payload else None) or None
    return devedores.indexar_ficheiros(bases)


@router.get("/search")
def devedores_search(
    q: Optional[str] = Query(None, description="Nome do devedor (aceita também um NIF com 9 dígitos)"),
    nif: Optional[str] = Query(None, description="NIF/NIPC exacto"),
    entidade: Optional[str] = Query(None, description="financas | seguranca_social"),
    tipo: Optional[str] = Query(None, description="singulares | coletivos"),
    escalao: Optional[List[str]] = Query(None, description="Escalões da dívida (repetível)"),
    valor_minimo: Optional[float] = Query(None, ge=0, description="Só escalões cujo limite inferior é igual ou superior"),
    ficheiro: Optional[str] = Query(None, description="Ficheiro de origem (ex.: listaFC6.pdf)"),
    lista_atualizada_em: Optional[str] = Query(None, description="Data de publicação da lista (AAAA-MM-DD)"),
    collected_from: Optional[str] = Query(None, description="Recolhas a partir de (AAAA-MM-DD)"),
    collected_to: Optional[str] = Query(None, description="Recolhas até (AAAA-MM-DD)"),
    sort: str = Query("relevancia", pattern="^(relevancia|nome|escalao|recolha|lista)$"),
    order: str = Query("desc", pattern="^(asc|desc)$"),
    page: int = Query(1, ge=1),
    size: int = Query(25, ge=1, le=200),
    session: ReadSession = None,
) -> Dict[str, Any]:
    """Área de pesquisa das listas de devedores."""
    return devedores.search(
        q=q,
        nif=nif,
        entidade=entidade,
        tipo=tipo,
        escalao=escalao,
        valor_minimo=valor_minimo,
        ficheiro=ficheiro,
        lista_atualizada_em=lista_atualizada_em,
        collected_from=collected_from,
        collected_to=collected_to,
        sort=sort,
        order=order,
        page=page,
        size=size,
    )


@router.get("/devedor/{nif}")
def devedores_devedor(nif: str, session: ReadSession = None) -> Dict[str, Any]:
    """Registos de um NIF/NIPC em todas as listas (Finanças e Segurança Social)."""
    return devedores.por_nif(nif)
