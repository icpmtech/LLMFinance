"""Rotas do módulo de **pesquisa social** (`/social/*`).

Recolhe publicações de LinkedIn, TikTok, Reddit e Facebook a partir de
**canais** (definições), com execuções manuais ou agendadas (cron) e pesquisa
sobre o que foi recolhido. Segue o desenho dos restantes módulos: leitura
pública, escrita com sessão.

Catálogo e diagnóstico
- `GET    /social/meta`                      — metadados (plataformas, variantes, presets de cron)
- `GET    /social/platforms`                 — catálogo das plataformas (o que exige credenciais)
- `GET    /social/status`                    — diagnóstico do ambiente + volumetria
- `GET    /social/stats`                     — resumo para o painel

Canais
- `GET    /social/channels`                  — listar canais
- `POST   /social/channels`                  — criar canal                       (sessão)
- `GET    /social/channels/{id}`             — obter canal
- `PATCH  /social/channels/{id}`             — atualizar canal (parcial)         (sessão)
- `DELETE /social/channels/{id}`             — apagar canal                       (sessão)

Execução
- `POST   /social/channels/{id}/run`         — recolher agora (segundo plano)    (sessão)
- `POST   /social/preview`                   — testar uma definição sem guardar  (sessão)
- `POST   /social/channels/{id}/preview`     — testar um canal guardado          (sessão)
- `GET    /social/runs`                      — histórico de execuções
- `GET    /social/channels/{id}/runs`        — execuções de um canal
- `GET    /social/runs/{run_id}`             — detalhe de uma execução
- `GET    /social/runs/{run_id}/items`       — publicações gravadas (JSONL)

Pesquisa e agendamento
- `GET    /social/search`                    — pesquisar publicações (Elasticsearch)
- `GET    /social/jobs`                      — jobs de cron e próximas execuções  (sessão)
- `POST   /social/jobs/reload`               — reaplicar as definições ao agendador (sessão)

Modelos prontos
- `GET    /social/templates`                 — galeria de canais prontos
- `GET    /social/templates/{template_id}`   — um template (com o canal que cria)
- `POST   /social/templates/{id}/preview`    — testar o template sem guardar      (sessão)
- `POST   /social/templates/{id}/channel`    — criar o canal a partir do template (sessão)
"""
from __future__ import annotations

import logging
from typing import Annotated, Any, Dict, List, Optional

from fastapi import APIRouter, Body, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from api import scraper_sentiment
from api import social_collectors as collectors
from api import social_scheduler as scheduler
from api import social_service as social
from api.auth_routes import CurrentSession, require_session

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/social", tags=["social"])

Session = Annotated[CurrentSession, Depends(require_session)]


# ------------------------------------------------------------------- modelos
class ChannelPayload(BaseModel):
    """Definição de um canal (todos os campos opcionais num PATCH)."""

    id: Optional[str] = None
    name: Optional[str] = None
    description: Optional[str] = None
    platform: Optional[str] = Field(None, description="linkedin | tiktok | reddit | facebook")
    kind: Optional[str] = Field(None, description="Variante dentro da plataforma (company, subreddit, hashtag, page…)")
    target: Optional[str] = Field(None, description="Alvo: slug da empresa, subreddit, hashtag, página…")
    enabled: Optional[bool] = None
    limit: Optional[int] = Field(None, ge=1, le=collectors.MAX_LIMIT)
    options: Optional[Dict[str, Any]] = Field(
        None, description="Opções do coletor (proxy, token, client_id, client_secret, user_agent…)"
    )
    schedule: Optional[Dict[str, Any]] = Field(None, description="{cron, timezone}")
    tags: Optional[List[str]] = None
    notes: Optional[str] = None
    sentiment: Optional[Dict[str, Any]] = Field(
        None, description="Sentimento por publicação: {enabled, engine, provider, model, max_items}"
    )

    model_config = {"extra": "allow"}


class PreviewPayload(BaseModel):
    """Definição a testar + limite de amostragem."""

    channel: Dict[str, Any] = Field(default_factory=dict)
    limit: int = Field(5, ge=1, le=50)


class TemplateChannelPayload(BaseModel):
    """Ajustes ao criar um canal a partir de um template."""

    name: Optional[str] = None
    target: Optional[str] = None
    enabled: Optional[bool] = Field(None, description="Ligar já o agendamento cron do template.")
    cron: Optional[str] = Field(None, description="Substituir a periodicidade sugerida pelo template.")
    limit: Optional[int] = Field(None, ge=1, le=collectors.MAX_LIMIT)
    tags: Optional[List[str]] = None
    options: Optional[Dict[str, Any]] = None


# ------------------------------------------------------------------ metadados
@router.get("/meta")
def social_meta() -> Dict[str, Any]:
    """Metadados para construir o formulário de definições na UI."""
    return {
        "platforms": collectors.platform_catalog(),
        "cron_presets": social.CRON_PRESETS,
        "default_timezone": "Europe/Lisbon",
        "index": "finance_social",
        "run_statuses": list(social.RUN_STATUSES),
        "max_limit": collectors.MAX_LIMIT,
        "default_limit": collectors.DEFAULT_LIMIT,
        "sentiment_engines": [
            {"id": engine, "label": scraper_sentiment.ENGINE_LABELS[engine]} for engine in scraper_sentiment.ENGINES
        ],
        "sentiment_fields": [
            {"id": field, "label": scraper_sentiment.FIELD_LABELS[field]} for field in scraper_sentiment.FIELDS
        ],
    }


@router.get("/platforms")
def list_platforms() -> Dict[str, Any]:
    """Catálogo das plataformas: variantes, se exigem credenciais e notas."""
    items = collectors.platform_catalog()
    return {"total": len(items), "items": items}


@router.get("/status")
def social_availability() -> Dict[str, Any]:
    """Diagnóstico: HTTP, Scrapling/browsers, Elasticsearch e agendador."""
    return social.availability()


@router.get("/stats")
def social_stats() -> Dict[str, Any]:
    """Resumo do módulo (canais, execuções e publicações indexadas)."""
    return social.stats()


# -------------------------------------------------------------------- canais
@router.get("/channels")
def list_channels(enabled_only: bool = Query(False, description="Mostrar só os canais ligados.")) -> Dict[str, Any]:
    items = social.list_channels(include_disabled=not enabled_only)
    return {"total": len(items), "items": items}


@router.post("/channels")
def create_channel(payload: ChannelPayload, _session: Session) -> Dict[str, Any]:
    try:
        channel = social.upsert_channel(payload.model_dump(exclude_unset=True))
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    scheduler.reload_jobs()
    return {"item": channel}


@router.get("/channels/{channel_id}")
def get_channel(channel_id: str) -> Dict[str, Any]:
    channel = social.get_channel(channel_id)
    if not channel:
        raise HTTPException(status_code=404, detail="Canal não encontrado.")
    return {"item": channel}


@router.patch("/channels/{channel_id}")
def update_channel(channel_id: str, payload: ChannelPayload, _session: Session) -> Dict[str, Any]:
    patch = payload.model_dump(exclude_unset=True)
    patch["id"] = channel_id
    patch["_must_exist"] = True
    try:
        channel = social.upsert_channel(patch)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Canal não encontrado.") from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    scheduler.reload_jobs()
    return {"item": channel}


@router.delete("/channels/{channel_id}")
def delete_channel(
    channel_id: str,
    _session: Session,
    purge_items: bool = Query(False, description="Apagar também as publicações já indexadas."),
) -> Dict[str, Any]:
    try:
        result = social.delete_channel(channel_id, purge_items=purge_items)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Canal não encontrado.") from exc
    scheduler.remove_job(channel_id)
    return result


# ------------------------------------------------------------------ execução
@router.post("/channels/{channel_id}/run")
def run_channel(channel_id: str, session: Session) -> Dict[str, Any]:
    """Arranca uma recolha imediata (em segundo plano) e devolve o `run_id`."""
    try:
        result = social.start_run(channel_id, trigger="manual", user_id=session.user.id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Canal não encontrado.") from exc
    if result.get("already_running"):
        return {"run_id": result["run_id"], "status": "running", "already_running": True}
    return result


@router.post("/preview")
def preview_channel(payload: PreviewPayload, _session: Session) -> Dict[str, Any]:
    """Testa uma definição (mesmo antes de a guardar) e devolve uma amostra."""
    if not payload.channel:
        raise HTTPException(status_code=422, detail="Envie a definição do canal em `channel`.")
    return social.preview_channel(payload.channel, limit=payload.limit)


@router.post("/channels/{channel_id}/preview")
def preview_saved_channel(
    channel_id: str,
    _session: Session,
    overrides: Dict[str, Any] = Body(default_factory=dict),
    limit: int = Query(5, ge=1, le=50),
) -> Dict[str, Any]:
    """Testa um canal guardado, aceitando alterações pontuais ao alvo/opções."""
    channel = social.get_channel(channel_id, raw=True)
    if not channel:
        raise HTTPException(status_code=404, detail="Canal não encontrado.")
    merged = {**channel, **(overrides or {}), "id": channel_id}
    return social.preview_channel(merged, limit=limit)


@router.get("/runs")
def list_runs(
    channel_id: Optional[str] = None,
    limit: int = Query(50, ge=1, le=200),
) -> Dict[str, Any]:
    runs = social.list_runs(channel_id, limit=limit)
    return {"total": len(runs), "items": runs}


@router.get("/channels/{channel_id}/runs")
def list_channel_runs(channel_id: str, limit: int = Query(25, ge=1, le=200)) -> Dict[str, Any]:
    runs = social.list_runs(channel_id, limit=limit)
    return {"total": len(runs), "items": runs}


@router.get("/runs/{run_id}")
def get_run(run_id: str, channel_id: Optional[str] = None) -> Dict[str, Any]:
    meta = social.get_run(run_id, channel_id)
    if not meta:
        raise HTTPException(status_code=404, detail="Execução não encontrada.")
    return {"item": meta}


@router.get("/runs/{run_id}/items")
def get_run_items(
    run_id: str,
    channel_id: str = Query(..., description="Canal da execução (organiza os ficheiros em disco)."),
    limit: int = Query(100, ge=1, le=1000),
    offset: int = Query(0, ge=0),
) -> Dict[str, Any]:
    meta = social.get_run(run_id, channel_id)
    if not meta:
        raise HTTPException(status_code=404, detail="Execução não encontrada.")
    return social.read_run_items(run_id, channel_id, limit=limit, offset=offset)


# ------------------------------------------------------------------ pesquisa
@router.get("/search")
def search_social_items(
    q: Optional[str] = Query(None, description="Texto livre (título, texto, autor e campos da plataforma)."),
    platform: Optional[str] = Query(None, description="linkedin | tiktok | reddit | facebook"),
    channel_id: Optional[str] = None,
    tag: Optional[List[str]] = Query(None, description="Etiquetas (pode repetir)."),
    sentiment: Optional[List[str]] = Query(None, description="Filtrar por sentimento (positivo/neutro/negativo)."),
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    size: int = Query(20, ge=1, le=200),
    offset: int = Query(0, ge=0),
    sort: str = Query("recent", pattern="^(recent|oldest|relevance|engagement|views)$"),
) -> Dict[str, Any]:
    return social.search_items(
        q=q,
        platform=platform,
        channel_id=channel_id,
        tags=tag,
        sentiments=sentiment,
        date_from=date_from,
        date_to=date_to,
        size=size,
        from_=offset,
        sort=sort,
    )


# --------------------------------------------------------------- agendamento
@router.get("/jobs")
def list_jobs(_session: Session) -> Dict[str, Any]:
    return scheduler.status()


@router.post("/jobs/reload")
def reload_jobs(_session: Session) -> Dict[str, Any]:
    return scheduler.reload_jobs()


# ------------------------------------------------------------------ templates
@router.get("/templates")
def list_templates() -> Dict[str, Any]:
    """Galeria de canais prontos (LinkedIn, Reddit, TikTok, Facebook)."""
    items = social.templates()
    return {"total": len(items), "items": items}


@router.get("/templates/{template_id}")
def get_template(template_id: str) -> Dict[str, Any]:
    """Um template e a definição de canal que ele cria."""
    item = next((t for t in social.templates() if t["id"] == template_id), None)
    if not item:
        raise HTTPException(status_code=404, detail="Template não encontrado.")
    try:
        item = {**item, "channel": social.channel_from_template(template_id)}
    except (KeyError, ValueError) as exc:
        logger.warning("Template social %s inválido: %s", template_id, exc)
    return {"item": item}


@router.post("/templates/{template_id}/preview")
def preview_template(
    template_id: str,
    _session: Session,
    limit: int = Query(3, ge=1, le=25),
    overrides: Dict[str, Any] = Body(default_factory=dict),
) -> Dict[str, Any]:
    """Testa o template ao vivo (não guarda nada e não indexa)."""
    try:
        channel = social.channel_from_template(template_id, overrides)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Template não encontrado.") from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return social.preview_channel(channel, limit=limit)


@router.post("/templates/{template_id}/channel")
def create_from_template(template_id: str, payload: TemplateChannelPayload, _session: Session) -> Dict[str, Any]:
    """Cria (ou atualiza) um canal a partir de um template."""
    overrides: Dict[str, Any] = {}
    if payload.name:
        overrides["name"] = payload.name
    if payload.target:
        overrides["target"] = payload.target
    if payload.limit:
        overrides["limit"] = payload.limit
    if payload.tags:
        overrides["tags"] = payload.tags
    if payload.options:
        overrides["options"] = payload.options
    if payload.enabled is not None:
        overrides["enabled"] = payload.enabled
    if payload.cron is not None:
        overrides["schedule"] = {"cron": payload.cron, "timezone": "Europe/Lisbon"}
    try:
        channel = social.channel_from_template(template_id, overrides)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Template não encontrado.") from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    created = social.upsert_channel(channel)
    scheduler.reload_jobs()
    return {"item": created}
