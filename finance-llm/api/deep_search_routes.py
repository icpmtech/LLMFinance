"""Rotas da **Pesquisa profunda** (`/deep-search/*`) — resposta citada sobre os dados.

- `GET  /deep-search/meta`    — âmbitos disponíveis, limites e modelo predefinido
- `GET  /deep-search/search`  — só a recuperação de fontes (JSON, sem IA)
- `POST /deep-search/ask`     — resposta do modelo em SSE (tokens + fontes citadas)

A leitura usa os mesmos índices da «Pesquisa total» (`search_service`), por isso
o âmbito **CRM** só entra quando há sessão (dados privados por utilizador).
"""
from __future__ import annotations

import logging
from typing import Annotated, Any, Dict, List, Optional, Sequence

from fastapi import APIRouter, Depends, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from api import deep_search_service as deep
from api.auth_routes import CurrentSession, optional_session

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/deep-search", tags=["deep-search"])

Session = Annotated[Optional[CurrentSession], Depends(optional_session)]


class DeepSearchAsk(BaseModel):
    """Pedido de resposta: pergunta + âmbitos + modelo (vazio = predefinido)."""

    question: str = Field(..., description="Pergunta em linguagem natural.")
    backend: str = Field("", description="Backend/modelo (ex.: `openai:gpt-4o-mini`). Vazio = predefinição do utilizador.")
    sources: Optional[List[str]] = Field(None, description="Âmbitos a usar (ids de `/deep-search/meta`). Vazio = todos.")
    mode: str = Field(deep.DEFAULT_MODE, description="Recuperação: hybrid (palavras + semântica) | text | vector.")
    per_source: int = Field(deep.PER_SOURCE_DEFAULT, ge=deep.PER_SOURCE_MIN, le=deep.PER_SOURCE_MAX, description="Candidatos lidos por âmbito.")
    max_sources: int = Field(deep.MAX_SOURCES_DEFAULT, ge=0, le=deep.MAX_SOURCES_MAX, description="Máximo de fontes (0 = sem limite).")
    temperature: float = Field(0.2, ge=0.0, le=1.5, description="Criatividade do modelo.")
    max_tokens: int = Field(1400, ge=128, le=4096, description="Limite de tokens da resposta.")
    history: Optional[List[Dict[str, str]]] = Field(None, description="Turnos anteriores ([{role, content}]) para perguntas de seguimento.")


def _visibility(session: Optional[CurrentSession]) -> Optional[Dict[str, Any]]:
    """Âmbito de visibilidade do CRM (privado por utilizador)."""
    if not session:
        return None
    return {
        "user_id": session.user.id,
        "email": session.user.email,
        "see_all": (session.user.role or "member") == "admin",
    }


def _parse_sources(raw: Optional[str]) -> Optional[List[str]]:
    if not raw:
        return None
    return [part.strip() for part in raw.split(",") if part.strip()]


@router.get("/meta")
def deep_search_meta(session: Session = None) -> Dict[str, Any]:
    """Catálogo de âmbitos + limites + backend predefinido do utilizador."""
    user_id = getattr(getattr(session, "user", None), "id", None)
    defaults: Dict[str, Any] = {}
    if user_id:
        from api import providers_service as providers

        defaults = providers.load_user_config(user_id).get("defaults") or {}
    catalog = deep.source_catalog()
    return {
        **catalog,
        "defaults": {
            "sources": catalog["defaults"],
            "provider": defaults.get("provider") or "",
            "model": defaults.get("model") or "",
            "backend": (
                f"{defaults['provider']}:{defaults.get('model') or ''}".rstrip(":")
                if defaults.get("provider")
                else ""
            ),
        },
        "has_session": bool(user_id),
    }


@router.get("/suggest")
def deep_search_suggest(
    q: str = Query(..., description="Texto escrito na caixa da pergunta."),
    limit: int = Query(8, ge=1, le=20, description="Número máximo de sugestões."),
    session: Session = None,
) -> Dict[str, Any]:
    """Sugestões de autocompletar: empresas, contratos de Espanha, recolha e mercado."""
    return deep.suggest_terms(q, limit=limit, session_scope=_visibility(session))


@router.get("/search")
def deep_search_sources(
    q: str = Query(..., description="Pergunta ou termos a pesquisar."),
    sources: Optional[str] = Query(None, description="Âmbitos separados por vírgula (ex.: `contracts,imprensa`)."),
    mode: str = Query(deep.DEFAULT_MODE, description="Recuperação: hybrid | text | vector."),
    per_source: int = Query(deep.PER_SOURCE_DEFAULT, ge=deep.PER_SOURCE_MIN, le=deep.PER_SOURCE_MAX),
    max_sources: int = Query(deep.MAX_SOURCES_DEFAULT, ge=0, le=deep.MAX_SOURCES_MAX, description="Máximo de fontes (0 = sem limite)."),
    session: Session = None,
) -> Dict[str, Any]:
    """Só a recuperação: devolve as fontes numeradas, sem chamar nenhum modelo."""
    return deep.retrieve(
        q,
        sources=_parse_sources(sources),
        per_source=per_source,
        max_sources=max_sources,
        session_scope=_visibility(session),
        mode=mode,
    )


@router.post("/ask")
async def deep_search_ask(req: DeepSearchAsk, session: Session = None):
    """Responde à pergunta em SSE: primeiro as fontes, depois os tokens da resposta."""
    user_id = getattr(getattr(session, "user", None), "id", None)
    stream = deep.stream_answer(
        req.question,
        backend=req.backend,
        user_id=user_id,
        sources=req.sources,
        per_source=req.per_source,
        max_sources=req.max_sources,
        temperature=req.temperature,
        max_tokens=req.max_tokens,
        history=req.history,
        session_scope=_visibility(session),
        mode=req.mode,
    )
    return StreamingResponse(
        stream,
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-transform",
            "Connection": "keep-alive",
            # Sem isto, um proxy à frente (nginx) acumula a resposta inteira.
            "X-Accel-Buffering": "no",
        },
    )
