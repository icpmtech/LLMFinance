"""Integração de agentes dinâmicos com RAG, Hermes e Researcher.

Fornece helpers para converter agentes configurados em "skills" ou subagentes
reutilizáveis pelos módulos existentes sem reescrever a lógica de cada um.
"""
from __future__ import annotations

import json
import logging
from typing import Any, Dict, List, Optional

from api.agent_graph_engine import get_agent_config, run_agent, stream_agent
from api.models import AgentRunRequest

logger = logging.getLogger(__name__)


async def run_agent_by_name(
    name: str,
    message: str,
    *,
    user_id: Optional[str] = None,
    context: Optional[Dict[str, Any]] = None,
    is_admin: bool = False,
) -> Optional[Dict[str, Any]]:
    """Executa o agente público ou do utilizador com o nome dado."""
    from api.agent_graph_engine import list_agent_configs

    agents = await list_agent_configs(user_id, is_admin=is_admin)
    candidate = next((a for a in agents if a.name.lower() == name.lower()), None)
    if not candidate or not candidate.agent_id:
        return None
    req = AgentRunRequest(agent_id=candidate.agent_id, message=message, context=context or {})
    return (await run_agent(req, user_id, is_admin=is_admin)).model_dump()


async def ask_rag_agent(
    question: str,
    *,
    user_id: Optional[str] = None,
    is_admin: bool = False,
    fallback: Optional[Dict[str, Any]] = None,
) -> Optional[Dict[str, Any]]:
    """Tenta usar um agente chamado 'RAG' configurado pelo utilizador; senão devolve fallback."""
    result = await run_agent_by_name("RAG", question, user_id=user_id, is_admin=is_admin)
    if result:
        return result
    return fallback


async def ask_hermes_agent(
    question: str,
    *,
    user_id: Optional[str] = None,
    is_admin: bool = False,
    fallback: Optional[Dict[str, Any]] = None,
) -> Optional[Dict[str, Any]]:
    """Tenta usar um agente chamado 'Hermes' configurado pelo utilizador; senão devolve fallback."""
    result = await run_agent_by_name("Hermes", question, user_id=user_id, is_admin=is_admin)
    if result:
        return result
    return fallback


async def ask_researcher_agent(
    question: str,
    *,
    user_id: Optional[str] = None,
    is_admin: bool = False,
    fallback: Optional[Dict[str, Any]] = None,
) -> Optional[Dict[str, Any]]:
    """Tenta usar um agente chamado 'Researcher' configurado pelo utilizador; senão devolve fallback."""
    result = await run_agent_by_name("Researcher", question, user_id=user_id, is_admin=is_admin)
    if result:
        return result
    return fallback


def agent_result_to_rag_answer(result: Optional[Dict[str, Any]]) -> str:
    """Extrai texto simples do resultado do agente para resposta RAG."""
    if not result:
        return ""
    msg = result.get("message") or {}
    return str(msg.get("content") or result.get("error") or "")


def agent_result_to_sources(result: Optional[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Extrai fontes do resultado do agente."""
    if not result:
        return []
    return [s.model_dump() if hasattr(s, "model_dump") else dict(s) for s in (result.get("sources") or [])]


def format_agent_as_skill(agent_name: str, result: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """Formata um resultado de agente como se fosse uma skill para a UI."""
    if not result:
        return {"id": None, "name": agent_name, "when": "dynamic", "steps": [], "checks": [], "tools": []}
    steps = result.get("steps") or []
    return {
        "id": result.get("agent_id"),
        "name": agent_name,
        "when": "dynamic",
        "steps": [f"{s.get('kind')}:{s.get('name')}" for s in steps if s.get("kind")],
        "checks": [str(s.get("content", ""))[:120] for s in steps if s.get("content")],
        "tools": [s.get("name") for s in steps if s.get("kind") == "tool"],
    }
