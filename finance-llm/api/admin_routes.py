"""Rotas da área de administração (`/admin/*`).

Só acessíveis a contas com o papel `admin`. Dão suporte à aplicação
«Administração» da interface:

- `GET  /admin/overview`            — saúde do sistema (API, Elasticsearch, índices, contas, eventos)
- `GET  /admin/users`               — lista/pesquisa de contas
- `PATCH /admin/users/{user_id}`    — alterar papel/estado/nome
- `DELETE /admin/users/{user_id}`   — apagar conta
- `POST /admin/users/{user_id}/revoke-sessions` — terminar sessões de um utilizador
- `GET  /admin/events`              — visualizador de eventos (pesquisa + paginação)
- `GET  /admin/events/stats`        — contagens por nível/origem/hora
- `POST /admin/events`              — registar um evento manualmente (teste/auditoria)
- `GET  /admin/logs`                — ficheiros de log disponíveis
- `GET  /admin/logs/{name}`         — últimas linhas de um ficheiro de log

As ações de administração ficam elas próprias registadas como eventos de
auditoria (origem `admin`).
"""
from __future__ import annotations

import logging
import os
import platform
from typing import Annotated, Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from api import auth_service as auth
from api import events_service as events
from api.auth_routes import CurrentSession, require_session
from api.elasticsearch_client import (
    AUTH_SESSIONS_INDEX,
    AUTH_USERS_INDEX,
    CONTRACTS_INDEX,
    CRM_INDEX,
    ENTITIES_INDEX,
    EVENTS_INDEX,
    FIRMAS_INDEX,
    TRADEMARKS_INDEX,
    get_es_client,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/admin", tags=["admin"])

ADMIN_ROLES = {"admin"}


def require_admin(session: Annotated[CurrentSession, Depends(require_session)]) -> CurrentSession:
    """Como `require_session`, mas exige o papel `admin`."""
    if (session.user.role or "member") not in ADMIN_ROLES:
        raise HTTPException(status_code=403, detail="Apenas administradores podem aceder a esta área.")
    return session


AdminSession = Annotated[CurrentSession, Depends(require_admin)]


# ------------------------------------------------------------------- modelos
class UserPatch(BaseModel):
    role: Optional[str] = Field(None, description="admin | member")
    status: Optional[str] = Field(None, description="active | suspended")
    name: Optional[str] = None
    title: Optional[str] = None
    organization: Optional[str] = None


class ManualEvent(BaseModel):
    level: str = "info"
    source: str = "admin"
    message: str
    data: Optional[Dict[str, Any]] = None


# -------------------------------------------------------------------- visão geral
def _index_summary(client: Any) -> List[Dict[str, Any]]:
    names = [
        AUTH_USERS_INDEX,
        AUTH_SESSIONS_INDEX,
        EVENTS_INDEX,
        CRM_INDEX,
        CONTRACTS_INDEX,
        ENTITIES_INDEX,
        TRADEMARKS_INDEX,
        FIRMAS_INDEX,
    ]
    summary: List[Dict[str, Any]] = []
    for name in names:
        entry: Dict[str, Any] = {"index": name, "exists": False, "documents": 0, "size": "—"}
        try:
            if not client.indices.exists(index=name):
                summary.append(entry)
                continue
            entry["exists"] = True
            count = client.count(index=name).get("count", 0)
            entry["documents"] = int(count)
            stats = client.indices.stats(index=name, metric="store")
            store = stats.get("_all", {}).get("total", {}).get("store", {}).get("size_in_bytes")
            if isinstance(store, (int, float)):
                entry["size"] = f"{store / (1024 * 1024):.1f} MB"
        except Exception as error:
            entry["error"] = str(error)
        summary.append(entry)
    return summary


def _elastic_info() -> Dict[str, Any]:
    client = get_es_client()
    if not client:
        return {"available": False, "error": "Elasticsearch indisponível"}
    try:
        info = client.info()
        health = client.cluster.health()
        return {
            "available": True,
            "url": os.getenv("ELASTICSEARCH_URL", "http://127.0.0.1:9200"),
            "cluster": info.get("cluster_name"),
            "node": info.get("name"),
            "version": info.get("version", {}).get("number"),
            "status": health.get("status"),
            "nodes": health.get("number_of_nodes"),
            "shards": health.get("active_shards"),
            "index_list": _index_summary(client),
        }
    except Exception as error:
        return {"available": False, "error": str(error)}


@router.get("/overview")
def admin_overview(session: AdminSession) -> Dict[str, Any]:
    """Estado geral da solução, para o painel inicial da administração."""
    account_stats = {"users": 0, "active_sessions": 0}
    try:
        account_stats = auth.stats()
    except Exception as error:
        logger.debug("stats de contas indisponível: %s", error)

    users: List[Dict[str, Any]] = []
    try:
        users = auth.list_users(limit=500)
    except Exception as error:
        logger.debug("listagem de contas indisponível: %s", error)

    roles: Dict[str, int] = {}
    statuses: Dict[str, int] = {}
    for user in users:
        roles[str(user.get("role") or "member")] = roles.get(str(user.get("role") or "member"), 0) + 1
        statuses[str(user.get("status") or "active")] = statuses.get(str(user.get("status") or "active"), 0) + 1

    return {
        "api": {
            "service": "IQ OS API",
            "python": platform.python_version(),
            "platform": f"{platform.system()} {platform.release()}",
            **{key: value for key, value in events.system_info().items() if key in {"host", "pid", "started_at", "uptime_seconds", "buffer_size", "buffer_capacity", "events_file", "root"}},
        },
        "elasticsearch": _elastic_info(),
        "accounts": {
            **account_stats,
            "by_role": [{"key": key, "count": value} for key, value in sorted(roles.items(), key=lambda kv: -kv[1])],
            "by_status": [{"key": key, "count": value} for key, value in sorted(statuses.items(), key=lambda kv: -kv[1])],
        },
        "events": events.event_stats(hours=24),
        "logs": events.list_log_files(),
    }


# -------------------------------------------------------------------- contas
@router.get("/users")
def admin_users(
    session: AdminSession,
    q: Optional[str] = Query(None),
    role: Optional[str] = Query(None),
    status: Optional[str] = Query(None),
    limit: int = Query(200, ge=1, le=1000),
) -> Dict[str, Any]:
    """Lista as contas, com pesquisa por nome/email e filtros de papel/estado."""
    try:
        users = auth.list_users(limit=1000)
    except auth.AuthError as error:
        raise HTTPException(status_code=error.status_code, detail=error.message) from error

    needle = (q or "").strip().lower()
    filtered = []
    for user in users:
        if needle and needle not in f"{user.get('name', '')} {user.get('email', '')}".lower():
            continue
        if role and str(user.get("role") or "member") != role:
            continue
        if status and str(user.get("status") or "active") != status:
            continue
        filtered.append(user)

    filtered.sort(key=lambda item: str(item.get("created_at") or ""), reverse=True)
    total = len(filtered)
    page = filtered[:limit]

    # Sessões por utilizador (para mostrar quem está ligado agora).
    sessions_by_user: Dict[str, int] = {}
    try:
        client = get_es_client()
        if client:
            response = client.search(
                index=AUTH_SESSIONS_INDEX,
                body={
                    "size": 0,
                    "query": {"term": {"revoked": False}},
                    "aggs": {"by_user": {"terms": {"field": "user_id", "size": 1000}}},
                },
            )
            for bucket in response.get("aggregations", {}).get("by_user", {}).get("buckets", []):
                sessions_by_user[str(bucket["key"])] = int(bucket["doc_count"])
    except Exception as error:
        logger.debug("sessões por utilizador indisponíveis: %s", error)

    for user in page:
        user["active_sessions"] = sessions_by_user.get(str(user.get("id")), 0)

    return {"total": total, "items": page, "returned": len(page)}


@router.patch("/users/{user_id}")
def admin_update_user(user_id: str, payload: UserPatch, session: AdminSession) -> Dict[str, Any]:
    """Altera papel, estado ou dados básicos de uma conta."""
    if payload.role is not None and payload.role not in {"admin", "member"}:
        raise HTTPException(status_code=422, detail="Papel inválido (use admin ou member).")
    if payload.status is not None and payload.status not in {"active", "suspended"}:
        raise HTTPException(status_code=422, detail="Estado inválido (use active ou suspended).")
    if user_id == session.user.id and payload.role == "member":
        raise HTTPException(status_code=422, detail="Não pode remover o seu próprio papel de administrador.")
    if user_id == session.user.id and payload.status == "suspended":
        raise HTTPException(status_code=422, detail="Não pode suspender a sua própria conta.")

    patch = {key: value for key, value in payload.model_dump().items() if value is not None}
    if not patch:
        raise HTTPException(status_code=422, detail="Nada para alterar.")

    try:
        updated = auth.update_user(user_id, patch, admin_fields=True)
    except auth.AuthError as error:
        raise HTTPException(status_code=error.status_code, detail=error.message) from error

    events.log_event(
        "warning",
        "admin",
        f"Conta alterada: {updated.get('email')} ({', '.join(f'{k}={v}' for k, v in patch.items())})",
        data={"target_user": updated.get("email"), "patch": patch},
        user_id=session.user.id,
        user_email=session.user.email,
    )
    return {"user": updated}


@router.delete("/users/{user_id}")
def admin_delete_user(user_id: str, session: AdminSession) -> Dict[str, Any]:
    """Apaga a conta e todas as suas sessões."""
    if user_id == session.user.id:
        raise HTTPException(status_code=422, detail="Não pode apagar a sua própria conta por aqui.")
    try:
        target = auth.get_user_by_id(user_id)
        if not target:
            raise HTTPException(status_code=404, detail="Conta não encontrada.")
        auth.revoke_all_sessions(user_id)
        auth.delete_account(user_id)
    except auth.AuthError as error:
        raise HTTPException(status_code=error.status_code, detail=error.message) from error

    events.log_event(
        "warning",
        "admin",
        f"Conta apagada: {target.get('email')}",
        data={"target_user": target.get("email"), "target_id": user_id},
        user_id=session.user.id,
        user_email=session.user.email,
    )
    return {"ok": True, "message": f"Conta {target.get('email')} apagada."}


@router.post("/users/{user_id}/revoke-sessions")
def admin_revoke_sessions(user_id: str, session: AdminSession) -> Dict[str, Any]:
    """Termina todas as sessões de uma conta."""
    try:
        target = auth.get_user_by_id(user_id)
        if not target:
            raise HTTPException(status_code=404, detail="Conta não encontrada.")
        count = auth.revoke_all_sessions(user_id)
    except auth.AuthError as error:
        raise HTTPException(status_code=error.status_code, detail=error.message) from error

    events.log_event(
        "warning",
        "admin",
        f"Sessões terminadas de {target.get('email')} ({count})",
        data={"target_user": target.get("email"), "sessions": count},
        user_id=session.user.id,
        user_email=session.user.email,
    )
    return {"ok": True, "message": f"{count} sessão(ões) terminada(s)."}


# -------------------------------------------------------------------- eventos
@router.get("/events")
def admin_events(
    session: AdminSession,
    level: Optional[str] = Query(None, description="Níveis separados por vírgula (info,warning,error)"),
    source: Optional[str] = Query(None, description="Origem do evento (api, auth, admin, app…)"),
    user: Optional[str] = Query(None),
    q: Optional[str] = Query(None),
    since: Optional[str] = Query(None, description="ISO 8601 (ex.: 2026-09-17T00:00:00Z)"),
    until: Optional[str] = Query(None),
    backend: str = Query("memory", pattern="^(memory|elasticsearch|auto)$"),
    from_: int = Query(0, ge=0, alias="from"),
    size: int = Query(50, ge=1, le=500),
) -> Dict[str, Any]:
    """Visualizador de eventos: pesquisa com filtros, paginação e escolha de fonte."""
    return events.search_events(
        level=level,
        source=source,
        user=user,
        q=q,
        since=since,
        until=until,
        from_=from_,
        size=size,
        backend=backend,
    )


@router.get("/events/stats")
def admin_events_stats(session: AdminSession, hours: int = Query(24, ge=1, le=720)) -> Dict[str, Any]:
    """Contagens de eventos por nível, origem, hora e caminho."""
    return events.event_stats(hours=hours)


@router.post("/events")
def admin_create_event(payload: ManualEvent, session: AdminSession) -> Dict[str, Any]:
    """Regista um evento manual (auditoria/teste do visualizador)."""
    document = events.log_event(
        payload.level,
        payload.source,
        payload.message,
        data=payload.data,
        user_id=session.user.id,
        user_email=session.user.email,
    )
    return {"event": document}


@router.get("/logs")
def admin_logs(session: AdminSession) -> Dict[str, Any]:
    """Ficheiros de log do processo e do backend."""
    return {"files": events.list_log_files()}


@router.get("/logs/{name}")
def admin_log_tail(name: str, session: AdminSession, lines: int = Query(200, ge=1, le=5000)) -> Dict[str, Any]:
    """Últimas linhas de um ficheiro de log."""
    result = events.tail_log_file(name, lines)
    if result.get("error"):
        raise HTTPException(status_code=404, detail=result["error"])
    return result
