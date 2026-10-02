"""Rotas para o catálogo CAE.

Fornece autocomplete e listagem de códigos CAE com descrição, baseado no
markdown `data/docs/CAE-Rev.4.md`.
"""

from __future__ import annotations

from typing import Any, List, Optional

from fastapi import APIRouter, Query
from pydantic import BaseModel, Field

from api.cae_catalog import all_cae_entries, search_cae_entries

router = APIRouter(prefix="/cae", tags=["cae"])


class CaeEntry(BaseModel):
    code: str = Field(..., description="Código CAE.")
    name: str = Field(..., description="Designação / descrição do CAE.")
    level: str = Field(..., description="Nível hierárquico: Secção, Divisão, Grupo, Classe ou Subclasse.")
    section: str = Field(..., description="Letra da secção a que pertence.")
    path: str = Field(..., description="Caminho hierárquico resumido.")


class CaeListResponse(BaseModel):
    items: List[CaeEntry]
    total: int


class CaeAutocompleteResponse(BaseModel):
    items: List[CaeEntry]


@router.get("/list", response_model=CaeListResponse)
def list_cae(
    q: Optional[str] = Query(None, description="Texto ou código a pesquisar."),
    limit: int = Query(200, ge=1, le=2000, description="Máximo de resultados a devolver."),
):
    """Lista códigos CAE com descrição."""
    items = search_cae_entries(q or "", limit=limit) if q and q.strip() else all_cae_entries(limit=limit)
    return CaeListResponse(items=[CaeEntry(**item) for item in items], total=len(items))


@router.get("/autocomplete", response_model=CaeAutocompleteResponse)
def autocomplete_cae(
    q: str = Query(..., min_length=1, description="Texto ou código a pesquisar."),
    limit: int = Query(50, ge=1, le=200, description="Máximo de sugestões."),
):
    """Sugestões de CAE por código ou designação."""
    items = search_cae_entries(q, limit=limit)
    return CaeAutocompleteResponse(items=[CaeEntry(**item) for item in items])


@router.get("/{code}", response_model=CaeEntry)
def get_cae(code: str):
    """Devolve a descrição de um código CAE concreto."""
    from api.cae_catalog import get_cae_catalog

    entry = get_cae_catalog().find(code)
    if not entry:
        from fastapi import HTTPException

        raise HTTPException(status_code=404, detail=f"CAE {code} não encontrado")
    return CaeEntry(**entry)
