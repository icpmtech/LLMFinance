"""Rotas do módulo **EU Taxonomy Navigator** (`/eu-taxonomy/*`).

Endpoints de leitura pública (como nos restantes módulos de dados abertos):

- `GET /eu-taxonomy/status`              — estado do snapshot e do índice
- `GET /eu-taxonomy/panorama`            — objetivos, setores e contagens
- `GET /eu-taxonomy/pesquisa`            — pesquisa de atividades/objetivos/setores
- `GET /eu-taxonomy/atividade/{id}`      — ficha de uma atividade

Endpoints de escrita (sessão + permissão `eu-taxonomy`):

- `POST /eu-taxonomy/coletar`            — recolha, indexação e snapshot
- `POST /eu-taxonomy/traduzir`           — arranca a tradução PT em segundo plano
- `GET  /eu-taxonomy/traducao/estado`    — progresso da tradução PT
"""
from __future__ import annotations

import logging
from typing import Annotated, Any, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from starlette.concurrency import run_in_threadpool

from api import eu_taxonomy_service as service
from api.auth_routes import CurrentSession, require_session
from api.permissions_service import require_write

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/eu-taxonomy", tags=["eu-taxonomy"])

Session = Annotated[CurrentSession, Depends(require_session)]


class ColetarPayload(BaseModel):
    force: bool = Field(False, description="Força o re-download da API oficial")
    translate: bool = Field(
        False,
        description="Traduz também para português durante a recolha (demora vários minutos; o normal é traduzir depois)",
    )


@router.get("/status", summary="Estado do módulo EU Taxonomy Navigator")
def eu_taxonomy_status() -> Dict[str, Any]:
    """Devolve o estado do snapshot local e do índice Elasticsearch."""
    return service.status()


@router.get("/panorama", summary="Panorama da Taxonomia UE")
def eu_taxonomy_panorama() -> Dict[str, Any]:
    """Objetivos ambientais, setores e contagens oficiais do Compass."""
    return service.panorama()


@router.get("/pesquisa", summary="Pesquisar atividades, objetivos e setores do Compass")
def eu_taxonomy_pesquisa(
    q: Optional[str] = Query(None, description="Termo de pesquisa (EN ou PT)"),
    kind: Optional[str] = Query(None, description="Filtrar por tipo: activity | objective | sector"),
    sector: Optional[str] = Query(None, description="Nome do setor (EN ou PT)"),
    objective_id: Optional[int] = Query(None, description="ID do objetivo ambiental"),
    nace: Optional[str] = Query(None, description="Código NACE/CAE (ex.: F41, C25)"),
    size: int = Query(20, ge=1, le=200),
    from_: int = Query(0, ge=0, alias="from"),
    sort: str = Query("relevance", pattern="^(relevance|name|sector)$"),
) -> Dict[str, Any]:
    """Pesquisa no índice `finance_eu_taxonomy`."""
    return service.pesquisar(
        q=q,
        kind=kind,
        sector=sector,
        objective_id=objective_id,
        nace=nace,
        size=size,
        from_=from_,
        sort=sort,
    )


@router.get("/atividade/{activity_id}", summary="Ficha de uma atividade do Compass")
def eu_taxonomy_atividade(activity_id: int) -> Dict[str, Any]:
    """Ficha completa de uma atividade (do snapshot local)."""
    doc = service.atividade(activity_id)
    if not doc:
        raise HTTPException(status_code=404, detail="Atividade não encontrada")
    return doc


@router.post("/coletar", summary="Recolher e indexar os dados do EU Taxonomy Navigator")
async def eu_taxonomy_coletar(
    payload: ColetarPayload,
    session: Session,
) -> Dict[str, Any]:
    """Download da API oficial, normalização, tradução, snapshot e indexação."""
    require_write("eu-taxonomy", session)
    return await run_in_threadpool(service.coletar, force=payload.force, translate=payload.translate)


@router.get("/traducao/estado", summary="Progresso da tradução PT do Compass")
def eu_taxonomy_traducao_estado() -> Dict[str, Any]:
    """Andamento (0–100%), contagens e eventuais erros da tradução em curso."""
    return service.estado_traducao()


@router.post("/traduzir", summary="Traduzir nomes e descrições das atividades para PT")
async def eu_taxonomy_traduzir(session: Session) -> Dict[str, Any]:
    """Arranca a tradução incremental em segundo plano (modelo local, sem chaves).

    A resposta volta logo com o estado inicial; o progresso segue em
    `GET /eu-taxonomy/traducao/estado`. Repetir o pedido devolve o trabalho que
    já está a correr em vez de lançar outro.
    """
    require_write("eu-taxonomy", session)
    return service.traduzir_em_fundo()
