"""Rotas FastAPI para o módulo **Vereadores e Remunerações**.

- `GET  /people/vereadores`           — lista de vereadores/presidentes
- `GET  /people/vereadores/stats`     — resumo dos dados
- `POST /people/vereadores/refresh`   — recolher/atualizar dados base
- `POST /people/vereadores/import`    — importar JSON de vereadores
- `POST /people/vereadores/import/csv`— importar CSV de vereadores
- `GET  /people/vereadores/concelhos` — lista de concelhos conhecidos
"""
from __future__ import annotations

from typing import Annotated, Any, Dict, List, Optional

from fastapi import APIRouter, Body, Depends, File, HTTPException, Query, UploadFile
from pydantic import BaseModel, Field

from api import vereadores_service as vereadores
from api.auth_routes import CurrentSession, optional_session

router = APIRouter(prefix="/people/vereadores", tags=["vereadores"])

Session = Annotated[CurrentSession, Depends(optional_session)]


class VereadorItem(BaseModel):
    name: str
    concelho: str
    district: str = ""
    party: str = ""
    role: str = "Vereador"
    source: str = "import"
    source_url: Optional[str] = None
    election: str = "Autárquicas 2025"
    year: int = 2025
    remuneration: Optional[Dict[str, Any]] = None
    nif: Optional[str] = None
    notes: Optional[str] = None


class VereadoresImportRequest(BaseModel):
    items: List[VereadorItem]


class VereadoresListResponse(BaseModel):
    total: int
    page: int
    size: int
    items: List[Dict[str, Any]]
    facets: Optional[Dict[str, Any]] = None


@router.get("", summary="Lista de vereadores e presidentes de câmara")
def list_vereadores(
    q: Optional[str] = Query(None, description="Nome ou partido"),
    district: Optional[str] = Query(None, description="Distrito"),
    concelho: Optional[str] = Query(None, description="Concelho"),
    party: Optional[str] = Query(None, description="Partido/coligação"),
    role: Optional[str] = Query(None, description="Cargo (ex.: Vereador, Presidente)"),
    has_remuneration: Optional[bool] = Query(None, description="Filtrar com/sem remuneração"),
    page: int = Query(1, ge=1),
    size: int = Query(50, ge=1, le=500),
    session: Session = None,
) -> VereadoresListResponse:
    result = vereadores.list_vereadores(
        q=q,
        district=district,
        concelho=concelho,
        party=party,
        role=role,
        has_remuneration=has_remuneration,
        size=size,
        page=page,
    )
    return VereadoresListResponse(**result)


@router.get("/stats", summary="Resumo dos vereadores indexados")
def vereadores_stats(session: Session = None) -> Dict[str, Any]:
    return vereadores.stats()


@router.post("/refresh", summary="Atualizar dados base das autárquicas")
def vereadores_refresh(session: Session = None) -> Dict[str, Any]:
    return vereadores.refresh_candidates()


@router.post("/import", summary="Importar vereadores via JSON")
def vereadores_import(
    payload: VereadoresImportRequest,
    session: Session = None,
) -> Dict[str, Any]:
    items = [item.model_dump() for item in payload.items]
    return vereadores.import_vereadores(items)


@router.post("/import/csv", summary="Importar vereadores via CSV")
def vereadores_import_csv(
    file: UploadFile = File(...),
    session: Session = None,
) -> Dict[str, Any]:
    if not file.filename or not file.filename.lower().endswith(".csv"):
        raise HTTPException(status_code=400, detail="Ficheiro deve ser .csv")
    content = file.file.read().decode("utf-8", errors="replace")
    return vereadores.import_vereadores_csv(content)


@router.get("/concelhos", summary="Concelhos conhecidos")
def vereadores_concelhos(session: Session = None) -> Dict[str, Any]:
    return {"concelhos": vereadores.get_concelhos()}
