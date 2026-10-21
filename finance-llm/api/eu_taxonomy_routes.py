"""Rotas do módulo **EU Taxonomy Navigator** (`/eu-taxonomy/*`).

Endpoints de leitura pública (como nos restantes módulos de dados abertos):

- `GET /eu-taxonomy/status`              — estado do snapshot e do índice
- `GET /eu-taxonomy/panorama`            — objetivos, setores e contagens
- `GET /eu-taxonomy/pesquisa`            — pesquisa de atividades/objetivos/setores
- `GET /eu-taxonomy/atividade/{id}`      — ficha de uma atividade

Endpoints de escrita (sessão + permissão `eu-taxonomy`):

- `POST /eu-taxonomy/coletar`            — recolha, tradução, indexação e snapshot
- `POST /eu-taxonomy/traduzir`           — tradução incremental PT dos nomes e descrições
"""
from __future__ import annotations

import logging
from typing import Annotated, Any, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from starlette.concurrency import run_in_threadpool

from api import eu_taxonomy_navigator as navigator
from api import eu_taxonomy_service as service
from api.auth_routes import CurrentSession, require_session
from api.permissions_service import require_write

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/eu-taxonomy", tags=["eu-taxonomy"])

Session = Annotated[CurrentSession, Depends(require_session)]


class ColetarPayload(BaseModel):
    force: bool = Field(False, description="Força o re-download da API oficial")
    translate: bool = Field(True, description="Traduz nomes e descrições para português")


class TraduzirPayload(BaseModel):
    provider: Optional[str] = Field(None, description="Fornecedor de IA (não obrigatório: usa Helsinki local)")
    model: Optional[str] = Field(None, description="Modelo de IA")


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


@router.post("/traduzir", summary="Traduzir nomes e descrições das atividades para PT")
async def eu_taxonomy_traduzir(
    payload: TraduzirPayload,
    session: Session,
) -> Dict[str, Any]:
    """Traduz incrementalmente os textos ainda sem tradução no snapshot."""
    require_write("eu-taxonomy", session)

    def _traduzir() -> Dict[str, Any]:
        if not navigator.SNAPSHOT_PATH.exists():
            return {"error": "Snapshot ainda não existe. Execute a recolha primeiro."}
        import json

        snapshot = json.loads(navigator.SNAPSHOT_PATH.read_text(encoding="utf-8"))
        activities = snapshot.get("activities", [])
        translated = navigator.translate_docs(
            activities,
            provider=payload.provider,
            model=payload.model,
            user_id=str(session.user_id) if session else None,
        )
        snapshot["activities"] = translated
        navigator.save_snapshot(snapshot)
        # Reindexa as atividades (os objetivos/setores já estão em PT)
        from api.elasticsearch_client import index_eu_taxonomy

        index_result = index_eu_taxonomy(translated + snapshot.get("objectives", []) + snapshot.get("sectors", []))
        return {
            "translated_names": sum(1 for a in translated if a.get("name_pt")),
            "translated_descriptions": sum(1 for a in translated if a.get("description_pt")),
            "index": index_result,
        }

    return await run_in_threadpool(_traduzir)
