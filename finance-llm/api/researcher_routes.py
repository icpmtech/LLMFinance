"""Rotas REST para o agente investigador de contratação pública."""
from __future__ import annotations

from typing import Annotated, Any, Optional

from fastapi import APIRouter, Body, Depends
from pydantic import BaseModel

from api.auth_routes import CurrentSession, optional_session
from api.researcher_service import investigate

router = APIRouter(prefix="/researcher", tags=["researcher"])

Session = Annotated[Optional[CurrentSession], Depends(optional_session)]


class InvestigateRequest(BaseModel):
    question: str
    backend: Optional[str] = None


@router.post("/investigate")
async def researcher_investigate(payload: InvestigateRequest):
    """Executa uma investigação e devolve relatório com audit trail."""
    if not payload.question:
        return {"status": "error", "message": "Pergunta em falta"}

    return await investigate(payload.question, backend=payload.backend, session=None)


@router.get("/tools")
async def list_researcher_tools():
    """Devolve o catálogo fechado de ferramentas disponíveis."""
    from api.researcher_service import TOOL_SCHEMA

    return {"tools": [{"name": k, "schema": v} for k, v in TOOL_SCHEMA.items()]}
