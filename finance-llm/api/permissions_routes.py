"""Rotas do módulo de permissões (`/permissions/*`).

* `GET  /permissions`        — catálogo de módulos e matriz por papel (administração);
* `PUT  /permissions`        — grava a matriz (só administradores);
* `GET  /permissions/me`     — permissões efetivas do utilizador autenticado;
* `POST /permissions/reset`  — repõe a matriz por omissão (só administradores).

Ler as permissões de terceiros é informação de administração; qualquer conta
autenticada pode consultar **as suas** (`/permissions/me`), que é o que o
frontend usa para esconder ações de escrita a quem só lê.
"""
from __future__ import annotations

import logging
from typing import Annotated, Any, Dict

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from api import events_service as events
from api import permissions_service as perms
from api.auth_routes import CurrentSession, require_session

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/permissions", tags=["permissions"])

Session = Annotated[CurrentSession, Depends(require_session)]


class MatrixPayload(BaseModel):
    matrix: Dict[str, Any]


def _require_admin(session: CurrentSession) -> None:
    if (session.user.role or "member") != "admin":
        raise HTTPException(status_code=403, detail="Só um administrador pode alterar as permissões.")


@router.get("/me")
def my_permissions(session: Session) -> Dict[str, Any]:
    """O que a conta autenticada pode fazer — usado pelo frontend para esconder ações."""
    return perms.effective_for_user({"role": session.user.role})


@router.get("")
def get_permissions(session: Session) -> Dict[str, Any]:
    """Catálogo de módulos e matriz completa (só administradores)."""
    _require_admin(session)
    return perms.state()


@router.put("")
def put_permissions(payload: MatrixPayload, session: Session) -> Dict[str, Any]:
    """Grava a matriz de permissões."""
    _require_admin(session)
    try:
        resultado = perms.save(payload.matrix, utilizador=session.user.email)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    alterados = _diff(perms.default_matrix(), resultado["matrix"])
    events.log_event(
        "warning",
        "admin",
        f"Permissões atualizadas ({len(alterados)} regra(s) fora do padrão)",
        data={"alteradas": alterados[:40], "total": len(alterados)},
        user_id=session.user.id,
        user_email=session.user.email,
    )
    return resultado


@router.post("/reset")
def reset_permissions(session: Session) -> Dict[str, Any]:
    """Repõe a matriz por omissão (admin tudo, manager conteúdo, member só ler)."""
    _require_admin(session)
    try:
        resultado = perms.save(perms.default_matrix(), utilizador=session.user.email)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    events.log_event(
        "warning",
        "admin",
        "Permissões repostas nos valores por omissão",
        user_id=session.user.id,
        user_email=session.user.email,
    )
    return resultado


def _diff(padrao: Dict[str, Any], efetiva: Dict[str, Any]) -> list:
    """Regras que ficaram diferentes do padrão (é o que interessa auditar)."""
    return [
        f"{role}.{module}.{acao}={efetiva[role][module][acao]}"
        for role in perms.ROLES
        for module in perms.MODULE_IDS
        for acao in perms.ACTIONS
        if padrao[role][module][acao] != efetiva[role][module][acao]
    ]
