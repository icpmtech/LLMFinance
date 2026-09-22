"""Rotas para criar, editar e executar agentes dinâmicos do IQ OS.

Endpoints:
- GET    /agents         lista configurações acessíveis
- POST   /agents         cria/actualiza configuração
- GET    /agents/{id}    detalhe
- DELETE /agents/{id}    apagar
- POST   /agents/{id}/run  executar (JSON)
- POST   /agents/{id}/stream  executar (SSE)
"""
from __future__ import annotations

import json
import logging
from typing import Annotated, Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse

from api import auth_service as auth
from api.agent_graph_engine import (
    delete_agent_config,
    get_agent_config,
    list_agent_configs,
    run_agent,
    save_agent_config,
    stream_agent,
)
from api.auth_routes import optional_session, require_session, CurrentSession
from api.models import AgentConfig, AgentConfigListResponse, AgentRunRequest, AgentRunResponse

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/agents", tags=["agents"])

SessionOrNone = Annotated[Optional[CurrentSession], Depends(optional_session)]
RequiredSession = Annotated[CurrentSession, Depends(require_session)]


def _is_admin(session: Optional[CurrentSession]) -> bool:
    if not session:
        return False
    return (session.user.role or "member") == "admin"


def _user_id(session: Optional[CurrentSession]) -> Optional[str]:
    if not session:
        return None
    return session.user.id or None


@router.get("", response_model=AgentConfigListResponse)
async def list_agents(session: SessionOrNone):
    """Lista todos os agentes dinâmicos acessíveis ao utilizador."""
    agents = await list_agent_configs(_user_id(session), is_admin=_is_admin(session))
    return AgentConfigListResponse(agents=agents, total=len(agents))


@router.post("", response_model=AgentConfig)
async def create_or_update_agent(payload: AgentConfig, session: RequiredSession):
    """Cria ou actualiza uma configuração de agente."""
    if payload.agent_id:
        existing = await get_agent_config(payload.agent_id, _user_id(session), is_admin=_is_admin(session))
        if existing and existing.owner_id != session.user.id and not _is_admin(session):
            raise HTTPException(status_code=403, detail="Não tens permissão para editar este agente.")
    return await save_agent_config(payload, _user_id(session))


@router.get("/{agent_id}", response_model=AgentConfig)
async def get_agent(agent_id: str, session: SessionOrNone):
    """Devolve a configuração de um agente dinâmico."""
    config = await get_agent_config(agent_id, _user_id(session), is_admin=_is_admin(session))
    if not config:
        raise HTTPException(status_code=404, detail="Agente não encontrado.")
    return config


@router.delete("/{agent_id}")
async def delete_agent(agent_id: str, session: RequiredSession):
    """Remove um agente dinâmico."""
    deleted = await delete_agent_config(agent_id, _user_id(session), is_admin=_is_admin(session))
    if not deleted:
        raise HTTPException(status_code=404, detail="Agente não encontrado ou sem permissão.")
    return {"ok": True, "agent_id": agent_id}


@router.post("/{agent_id}/run", response_model=AgentRunResponse)
async def run_agent_endpoint(agent_id: str, req: AgentRunRequest, session: SessionOrNone):
    """Executa um agente dinâmico e devolve a resposta final."""
    req.agent_id = agent_id
    return await run_agent(req, _user_id(session), is_admin=_is_admin(session))


@router.post("/{agent_id}/stream")
async def stream_agent_endpoint(agent_id: str, req: AgentRunRequest, session: SessionOrNone):
    """Executa um agente dinâmico e faz streaming SSE da resposta."""
    req.agent_id = agent_id

    async def event_stream():
        async for chunk in stream_agent(req, _user_id(session), is_admin=_is_admin(session)):
            yield chunk

    return StreamingResponse(event_stream(), media_type="text/event-stream")


@router.get("/tools/catalog")
async def tools_catalog(session: SessionOrNone):
    """Devolve o catálogo de ferramentas disponíveis para construir agentes."""
    from api.agent_graph_engine import AVAILABLE_TOOLS

    return {
        "tools": [
            {"tool_id": name, "name": tool.name, "description": tool.description}
            for name, tool in AVAILABLE_TOOLS.items()
        ]
    }
