"""Rotas do anúncio de páginas públicas aos motores de busca (`/indexnow/*`).

- `GET  /indexnow/state` — o que está ligado, o que falta anunciar, o que se enviou
- `POST /indexnow/sync`  — anunciar agora (`forcar=true` reenvia tudo o que é público)

O ficheiro que prova a posse do domínio (`/{chave}.txt`) é servido por
`api/main.py`, na **raiz** — é lá que o protocolo o procura.

A administração é também onde se liga e desliga isto: a chave vive no catálogo de
chaves de serviços (`Administração → Chaves e integrações`), não numa variável de
ambiente que exija reiniciar o backend.
"""
from __future__ import annotations

from typing import Annotated, Any, Dict

from fastapi import APIRouter, Depends, Query

from api import events_service as events
from api import indexnow
from api.admin_routes import require_admin
from api.auth_routes import CurrentSession

router = APIRouter(prefix="/indexnow", tags=["indexnow"])

AdminSession = Annotated[CurrentSession, Depends(require_admin)]


@router.get("/state")
def indexnow_state(session: AdminSession) -> Dict[str, Any]:
    """Estado do anúncio: chave, endereços públicos e o que ainda não foi anunciado."""
    return indexnow.estado()


@router.post("/sync")
def indexnow_sync(
    session: AdminSession,
    forcar: bool = Query(False, description="Reenviar tudo o que é público agora, mesmo sem alterações"),
) -> Dict[str, Any]:
    """Anuncia já aos motores o que mudou desde o último anúncio."""
    resultado = indexnow.sincronizar(motivo=f"manual:{session.user.email}", forcar=forcar)
    events.log_event(
        "info",
        "indexnow",
        f"Anúncio manual: {resultado.get('submetidos', 0)} endereço(s) submetido(s)",
        data={
            "forcar": forcar,
            "submetidos": resultado.get("submetidos", 0),
            "novos": resultado.get("novos"),
            "alterados": resultado.get("alterados"),
            "removidos": resultado.get("removidos"),
        },
        user_id=session.user.id,
        user_email=session.user.email,
    )
    return resultado
