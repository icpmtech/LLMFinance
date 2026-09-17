"""Rotas dos fornecedores de IA (`/providers/*`).

- `GET    /providers`               — catálogo (locais + cloud) com o estado das chaves
- `PUT    /providers/keys`          — guardar/remover a chave de um fornecedor
- `PUT    /providers/defaults`      — fornecedor/modelo predefinidos do chat
- `POST   /providers/test`          — testar a ligação a um fornecedor
- `GET    /providers/chat-models`   — lista simples para o selector do chat

As chaves são guardadas por utilizador no índice `finance_provider_keys` e nunca
são devolvidas em claro (só a pista `sk-…abcd`).
"""
from __future__ import annotations

import logging
from typing import Annotated, Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from api import cloud_chat, events_service as events, providers_service as providers
from api.auth_routes import CurrentSession, require_session

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/providers", tags=["providers"])


class KeyPayload(BaseModel):
    provider: str
    api_key: Optional[str] = None


class DefaultsPayload(BaseModel):
    provider: Optional[str] = None
    model: Optional[str] = None


class TestPayload(BaseModel):
    provider: str
    model: Optional[str] = None
    api_key: Optional[str] = None


@router.get("")
def list_providers(session: Annotated[CurrentSession, Depends(require_session)]) -> Dict[str, Any]:
    """Catálogo de fornecedores com o estado das chaves do utilizador."""
    return providers.provider_catalog(session.user.id)


@router.get("/chat-models")
def chat_models(session: Annotated[CurrentSession, Depends(require_session)]) -> Dict[str, Any]:
    """Lista achatada para o selector do chat (só o que está utilizável)."""
    catalog = providers.provider_catalog(session.user.id)
    options: List[Dict[str, Any]] = []
    for entry in catalog["providers"]:
        if entry["kind"] == "local":
            options.append({"id": entry["id"], "label": entry["label"], "group": "Locais", "model": entry["default_model"], "usable": True})
            continue
        group = "Cloud" if entry["id"] != "ollama" else "Local (Ollama)"
        usable = entry["configured"]
        for index, model in enumerate(entry["models"]):
            options.append(
                {
                    "id": f"{entry['id']}:{model}",
                    "label": f"{entry['label']} · {model}",
                    "group": group,
                    "model": model,
                    "provider": entry["id"],
                    "usable": usable,
                    "note": None if usable else "sem chave configurada",
                    "default": index == 0,
                }
            )
    return {"options": options, "defaults": catalog["defaults"]}


@router.put("/keys")
def save_key(payload: KeyPayload, session: Annotated[CurrentSession, Depends(require_session)]) -> Dict[str, Any]:
    """Guarda (ou apaga, com `api_key` vazio) a chave de um fornecedor."""
    if payload.provider not in providers.PROVIDERS_BY_ID:
        raise HTTPException(status_code=404, detail="Fornecedor desconhecido.")
    try:
        providers.save_api_key(session.user.id, payload.provider, payload.api_key)
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error

    stored = bool((payload.api_key or "").strip())
    events.log_event(
        "warning",
        "providers",
        f"Chave {'guardada' if stored else 'removida'}: {payload.provider}",
        user_id=session.user.id,
        user_email=session.user.email,
        data={"provider": payload.provider, "action": "save" if stored else "delete"},
    )
    return providers.provider_catalog(session.user.id)


@router.put("/defaults")
def save_defaults(payload: DefaultsPayload, session: Annotated[CurrentSession, Depends(require_session)]) -> Dict[str, Any]:
    """Guarda o fornecedor/modelo predefinidos."""
    return providers.save_defaults(session.user.id, payload.model_dump())


@router.post("/test")
async def test_provider(payload: TestPayload, session: Annotated[CurrentSession, Depends(require_session)]) -> Dict[str, Any]:
    """Faz um pedido mínimo ao fornecedor para validar chave e modelo."""
    spec = providers.PROVIDERS_BY_ID.get(payload.provider)
    if not spec:
        raise HTTPException(status_code=404, detail="Fornecedor desconhecido.")

    api_key = (payload.api_key or "").strip() or None
    if not api_key:
        api_key, _source = providers.resolve_key(session.user.id, payload.provider)
    if spec.get("key_optional"):
        api_key = api_key or "ollama"
    if not api_key:
        raise HTTPException(status_code=422, detail="Sem chave de API para este fornecedor.")

    model = (payload.model or spec.get("default_model") or "").strip()
    try:
        result = await cloud_chat.test_provider(provider=payload.provider, spec=spec, model=model, api_key=api_key)
    except cloud_chat.CloudError as error:
        events.log_event(
            "warning",
            "providers",
            f"Teste falhou: {payload.provider}/{model} — {error.message}",
            user_id=session.user.id,
            user_email=session.user.email,
            data={"provider": payload.provider, "model": model, "status": error.status},
        )
        raise HTTPException(status_code=502, detail=error.message) from error

    events.log_event(
        "info",
        "providers",
        f"Teste bem-sucedido: {payload.provider}/{model}",
        user_id=session.user.id,
        user_email=session.user.email,
        data={"provider": payload.provider, "model": model},
    )
    return {**result, "provider": payload.provider, "model": model}
