"""Rotas do **Hermes** — o assistente de investigação do IQ OS (`/hermes/*`).

O Hermes recebe uma pergunta, planeia-a, recolhe evidências nas fontes da
plataforma (através do meta-modelo da Pesquisa 360) e responde com citações
numeradas, usando o modelo de IA configurado na conta. Sem modelo disponível
responde em modo factual (contagens, títulos e indicadores).

Rotas:

- `GET  /hermes/meta` — capacidades, modos de investigação, fontes, índices e modelo disponível
- `POST /hermes/ask`  — investiga uma pergunta e devolve resposta + evidências + sub-perguntas

O `ask` aceita:

```json
{
  "question": "Quais são os maiores contratos públicos de energia em 2025?",
  "depth": "rapida | profunda",
  "sources": ["internal", "documents", "..."],
  "backend": "openai:gpt-4o-mini",
  "history": [{"role": "user", "content": "..."}],
  "country": "PRT"
}
```
"""
from __future__ import annotations

import logging
from typing import Annotated, Any, Dict, List, Optional

from fastapi import APIRouter, Body, Depends, HTTPException

from api import hermes_service as service
from api import search360_sources as sources
from api.auth_routes import CurrentSession, optional_session

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/hermes", tags=["hermes"])

Session = Annotated[Optional[CurrentSession], Depends(optional_session)]


def _scope(session: Optional[CurrentSession]) -> Optional[Dict[str, Any]]:
    """Âmbito de leitura dos dados privados (CRM) quando há sessão."""
    if not session:
        return None
    return {
        "user_id": session.user.id,
        "email": session.user.email,
        "see_all": (session.user.role or "member") == "admin",
    }


def _sources_param(value: Any) -> Optional[List[str]]:
    """Aceita `sources` como lista, ou como texto separado por vírgulas."""
    if value is None:
        return None
    entries = value if isinstance(value, (list, tuple)) else str(value).split(",")
    flat = [part.strip() for entry in entries for part in str(entry).split(",") if part.strip()]
    if not flat:
        return None
    unknown = [source_id for source_id in flat if source_id not in sources.CATALOG_BY_ID]
    if unknown:
        raise HTTPException(status_code=422, detail=f"Fontes desconhecidas: {', '.join(unknown)}.")
    return flat


@router.get("/meta")
def meta(session: Session = None) -> Dict[str, Any]:
    """Metamodelo do Hermes: modos, fontes disponíveis, índices e modelo de IA."""
    return service.meta(session)


@router.post("/ask")
async def ask(payload: Dict[str, Any] = Body(...), session: Session = None) -> Dict[str, Any]:
    """Investiga a pergunta e devolve a resposta citada, evidências e sub-perguntas."""
    depth = str(payload.get("depth") or service.DEFAULT_DEPTH)
    if depth not in {item["id"] for item in service.DEPTHS}:
        raise HTTPException(status_code=422, detail=f"Modo de investigação desconhecido: {depth}.")
    history = payload.get("history")
    if not isinstance(history, list):
        history = []
    backend = payload.get("backend")
    try:
        return await service.ask(
            str(payload.get("question") or ""),
            depth=depth,
            sources_ids=_sources_param(payload.get("sources")),
            backend=str(backend) if backend else None,
            history=history,
            scope=_scope(session),
            session=session,
            country=str(payload.get("country") or "PRT"),
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
