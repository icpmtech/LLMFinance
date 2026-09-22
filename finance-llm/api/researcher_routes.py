"""Rotas REST para o agente investigador de contratação pública."""
from __future__ import annotations

import logging
from typing import Annotated, Any, Optional

from fastapi import APIRouter, Body, Depends
from pydantic import BaseModel

logger = logging.getLogger(__name__)

from api.auth_routes import CurrentSession, optional_session
from api.researcher_service import investigate

router = APIRouter(prefix="/researcher", tags=["researcher"])

Session = Annotated[Optional[CurrentSession], Depends(optional_session)]


class InvestigateRequest(BaseModel):
    question: str
    backend: Optional[str] = None


@router.post("/investigate")
async def researcher_investigate(payload: InvestigateRequest, session: Session = None):
    """Executa uma investigação e devolve relatório com audit trail."""
    if not payload.question:
        return {"status": "error", "message": "Pergunta em falta"}

    user_id = getattr(getattr(session, "user", None), "id", None) if session else None
    try:
        from api import agent_integration as agenti

        agent_result = await agenti.ask_researcher_agent(payload.question, user_id=user_id)
        if agent_result:
            return {
                "status": "completed",
                "report": agenti.agent_result_to_rag_answer(agent_result),
                "agent_id": agent_result.get("agent_id"),
                "thread_id": agent_result.get("thread_id"),
                "elapsed_seconds": agent_result.get("elapsed_seconds", 0),
                "agent": True,
            }
    except Exception as exc:
        logger.warning("Falha ao executar agente Researcher dinâmico: %s", exc)

    return await investigate(payload.question, backend=payload.backend, session=None)


@router.get("/tools")
async def list_researcher_tools():
    """Devolve o catálogo fechado de ferramentas disponíveis."""
    from api.researcher_service import TOOL_SCHEMA

    return {"tools": [{"name": k, "schema": v} for k, v in TOOL_SCHEMA.items()]}
