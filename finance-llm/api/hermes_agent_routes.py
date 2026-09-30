"""Rotas do **motor do Hermes Agent** (`/hermes-agent/*`).

O Hermes Agent é o container autónomo da solução (perfil `agents`). Estas rotas
ligam-no aos fornecedores de IA que a plataforma já tem guardados: resolvem a
chave, escrevem-na no volume do container e recriam-no.

- `GET  /hermes-agent/settings`        — definições, plano, diagnóstico e comandos
- `PUT  /hermes-agent/settings`        — grava as definições (sem aplicar)
- `POST /hermes-agent/settings/apply`  — resolve, escreve no container e recria-o
- `GET  /hermes-agent/diagnose`        — o que está no container vs. o que a plataforma quer
- `GET  /hermes-agent/providers`       — fornecedores do IQ OS com o estado das chaves

Todas exigem sessão: escrevem credenciais num container e mexem no compose.
"""
from __future__ import annotations

import logging
from typing import Annotated, Any, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from starlette.concurrency import run_in_threadpool

from api import hermes_agent_settings as service
from api.auth_routes import CurrentSession, require_session

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/hermes-agent", tags=["hermes-agent"])

Session = Annotated[CurrentSession, Depends(require_session)]


class SettingsPayload(BaseModel):
    """Definições do motor do Hermes Agent."""

    llm_provider: Optional[str] = Field(None, description="Fornecedor do IQ OS (ex.: `deepseek`, `openai`).")
    llm_model: Optional[str] = Field(None, description="Modelo; vazio usa o predefinido do fornecedor.")
    llm_base_url: Optional[str] = Field(None, description="Endpoint OpenAI-compatível (vazio usa o do fornecedor).")
    llm_custom_key: Optional[str] = Field(
        None,
        description="Chave personalizada. Enviar string vazia remove a chave personalizada e volta à da plataforma.",
    )
    search_provider: Optional[str] = Field(None, description="`searxng`, `brave` ou `off`.")
    searxng_url: Optional[str] = Field(None, description="URL do SearXNG da plataforma.")
    brave_key: Optional[str] = Field(None, description="Chave da Brave Search (vazio usa BRAVE_API_KEY).")
    recreate: bool = Field(True, description="Recriar o container para aplicar (só usado no `apply`).")


def _patch(payload: SettingsPayload) -> Dict[str, Any]:
    """Só os campos enviados entram no patch (permite atualizações parciais)."""
    data = payload.model_dump(exclude_unset=True, exclude={"recreate"})
    return {key: value for key, value in data.items() if value is not None or key == "llm_custom_key"}


@router.get("/settings")
def get_settings(session: Session) -> Dict[str, Any]:
    """Definições atuais, plano a aplicar, diagnóstico e comandos úteis."""
    user_id = session.user.id
    return service.settings_view(user_id, session.user.email or "")


@router.put("/settings")
def put_settings(payload: SettingsPayload, session: Session) -> Dict[str, Any]:
    """Grava as definições (sem tocar no container)."""
    patch = _patch(payload)
    if not patch:
        raise HTTPException(status_code=422, detail="Nada para gravar.")
    try:
        service.save_settings(patch, session.user.email or "")
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return service.settings_view(session.user.id, session.user.email or "")


@router.post("/settings/apply")
def apply_settings(payload: SettingsPayload, session: Session) -> Dict[str, Any]:
    """Resolve a chave, escreve-a no container e recria-o."""
    patch = _patch(payload)
    try:
        return service.apply_settings(
            session.user.id,
            session.user.email or "",
            patch=patch or None,
            recreate=payload.recreate,
        )
    except RuntimeError as exc:
        # 409 quando falta o essencial (chave/docker), 503 quando o ambiente falha.
        detail = str(exc)
        status = 409 if "Nada para aplicar" in detail else 503
        raise HTTPException(status_code=status, detail=detail) from exc


@router.get("/diagnose")
def diagnose(session: Session) -> Dict[str, Any]:
    """Estado do container comparado com o que a plataforma quer aplicar."""
    return service.diagnose(session.user.id)


@router.get("/providers")
def providers(session: Session) -> Dict[str, Any]:
    """Fornecedores do IQ OS utilizáveis, com o modo (perfil nativo ou `custom`)."""
    return {"providers": service.llm_candidates(session.user.id)}


@router.get("/container")
def container() -> Dict[str, Any]:
    """Estado bruto do container: corre, e o que tem no `config.yaml` e no `.env`."""
    return {
        "container": service.CONTAINER,
        "docker_available": bool(service.docker_path()),
        "running": service.container_running() if service.docker_path() else False,
        "config": service.read_config_values(service.CONFIG_KEYS),
        "env_keys": sorted(
            name for name in service._env_names(service.read_container_env()) if name in service.MANAGED_ENV_KEYS
        ),
    }
