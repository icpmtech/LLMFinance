"""Rotas do módulo de recolha (`/scraper/*`) — o «web scraping» do IQ OS.

O módulo recolhe dados de sites a partir de **definições** (fontes), com
execuções manuais ou agendadas (cron) e pesquisa sobre os itens recolhidos.
Segue o mesmo desenho dos restantes módulos: leitura pública, escrita com sessão.

Definições (fontes)
- `GET    /scraper/meta`                      — metadados (fetchers, cursores, presets de cron)
- `GET    /scraper/status`                    — diagnóstico do ambiente + volumetria
- `GET    /scraper/stats`                     — resumo para o painel
- `GET    /scraper/sources`                   — listar fontes
- `POST   /scraper/sources`                   — criar fonte                (sessão)
- `GET    /scraper/sources/{id}`              — obter fonte
- `PATCH  /scraper/sources/{id}`              — atualizar fonte (parcial)   (sessão)
- `DELETE /scraper/sources/{id}`              — apagar fonte                (sessão)

Execução
- `POST   /scraper/sources/{id}/run`          — recolher agora              (sessão)
- `POST   /scraper/preview`                   — testar uma definição (mesmo sem guardar) (sessão)
- `POST   /scraper/sources/{id}/preview`      — testar uma fonte guardada    (sessão)
- `GET    /scraper/runs`                      — histórico de execuções
- `GET    /scraper/runs/{run_id}`             — detalhe de uma execução
- `GET    /scraper/runs/{run_id}/items`       — itens gravados (JSONL)
- `GET    /scraper/sources/{id}/runs`         — execuções de uma fonte

Pesquisa e agendamento
- `GET    /scraper/search`                    — pesquisar itens recolhidos (Elasticsearch)
- `GET    /scraper/jobs`                      — jobs de cron e próximas execuções      (sessão)
- `POST   /scraper/jobs/reload`               — reaplicar as definições ao agendador    (sessão)
"""
from __future__ import annotations

import logging
import re
from typing import Annotated, Any, Dict, List, Optional

from fastapi import APIRouter, Body, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from api import scraper_ai
from api import scraper_scheduler as scheduler
from api import scraper_service as scraper
from api.auth_routes import CurrentSession, require_session

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/scraper", tags=["scraper"])

Session = Annotated[CurrentSession, Depends(require_session)]


# ------------------------------------------------------------------- modelos
class SourcePayload(BaseModel):
    """Definição de uma fonte (todos os campos opcionais num PATCH)."""

    id: Optional[str] = None
    name: Optional[str] = None
    description: Optional[str] = None
    url: Optional[str] = None
    enabled: Optional[bool] = None
    fetcher: Optional[str] = Field(None, description="http | dynamic | stealth")
    list: Optional[Dict[str, Any]] = Field(None, description="{selector, type}")
    fields: Optional[List[Dict[str, Any]]] = Field(None, description="[{name, selector, type, attr, all, cast}]")
    pagination: Optional[Dict[str, Any]] = Field(None, description="{selector, type, attr, max_pages}")
    options: Optional[Dict[str, Any]] = Field(None, description="Opções do fetcher (impersonate, headless, timeout…)")
    schedule: Optional[Dict[str, Any]] = Field(None, description="{cron, timezone}")
    respect_robots: Optional[bool] = None
    tags: Optional[List[str]] = None
    id_fields: Optional[List[str]] = Field(None, description="Campos que identificam um item (evita duplicados)")
    title_field: Optional[str] = None
    summary_field: Optional[str] = None
    text_field: Optional[str] = None
    tags_field: Optional[str] = None

    model_config = {"extra": "allow"}


class PreviewPayload(BaseModel):
    """Definição a testar + limites de amostragem."""

    source: Dict[str, Any] = Field(default_factory=dict)
    limit: int = Field(5, ge=1, le=50)
    max_pages: int = Field(1, ge=1, le=10)


class SuggestPayload(BaseModel):
    """Pedido de sugestão de definição (IA + análise da página)."""

    url: str = Field(..., description="Página a analisar.")
    hint: Optional[str] = Field(None, description="O que se quer recolher (ajuda o modelo).")
    fetcher: Optional[str] = Field(None, description="http | dynamic | stealth (para sites com JavaScript).")
    options: Dict[str, Any] = Field(default_factory=dict)
    provider: Optional[str] = Field(None, description="Fornecedor de IA (por omissão: o predefinido).")
    model: Optional[str] = None
    use_ai: bool = Field(True, description="Falso para devolver apenas a análise determinística.")


# ------------------------------------------------------------------ metadados
@router.get("/meta")
def scraper_meta() -> Dict[str, Any]:
    """Metadados para construir o formulário de definições na UI."""
    return {
        "fetchers": [
            {"id": kind, "label": scraper.FETCHER_LABELS[kind], "options": scraper.DEFAULT_OPTIONS[kind]}
            for kind in scraper.FETCHERS
        ],
        "selector_kinds": list(scraper.SELECTOR_KINDS),
        "casts": ["text", "int", "float", "bool", "date"],
        "cron_presets": scraper.CRON_PRESETS,
        "default_timezone": "Europe/Lisbon",
        "index": "finance_scraped",
    }


@router.get("/status")
def scraper_availability() -> Dict[str, Any]:
    """Diagnóstico: Scrapling/browsers instalados, Elasticsearch e agendador."""
    return scraper.availability()


@router.get("/stats")
def scraper_stats() -> Dict[str, Any]:
    """Resumo do módulo (fontes, execuções, itens recolhidos/indexados)."""
    return scraper.stats()


# -------------------------------------------------------------------- fontes
@router.get("/sources")
def list_sources() -> Dict[str, Any]:
    sources = scraper.list_sources()
    return {"total": len(sources), "items": sources}


@router.post("/sources")
def create_source(payload: SourcePayload, _session: Session) -> Dict[str, Any]:
    try:
        source = scraper.upsert_source(payload.model_dump(exclude_unset=True))
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    scheduler.reload_jobs()
    return {"item": source}


@router.get("/sources/{source_id}")
def get_source(source_id: str) -> Dict[str, Any]:
    source = scraper.get_source(source_id)
    if not source:
        raise HTTPException(status_code=404, detail="Fonte não encontrada.")
    return {"item": source}


@router.patch("/sources/{source_id}")
def update_source(source_id: str, payload: SourcePayload, _session: Session) -> Dict[str, Any]:
    patch = payload.model_dump(exclude_unset=True)
    patch["id"] = source_id
    patch["_must_exist"] = True
    try:
        source = scraper.upsert_source(patch)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Fonte não encontrada.") from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    scheduler.reload_jobs()
    return {"item": source}


@router.delete("/sources/{source_id}")
def delete_source(
    source_id: str,
    _session: Session,
    purge_items: bool = Query(False, description="Apagar também os itens já indexados."),
) -> Dict[str, Any]:
    try:
        result = scraper.delete_source(source_id, purge_items=purge_items)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Fonte não encontrada.") from exc
    scheduler.remove_job(source_id)
    return result


# ------------------------------------------------------------------ execução
@router.post("/sources/{source_id}/run")
def run_source(source_id: str, _session: Session) -> Dict[str, Any]:
    """Arranca uma recolha imediata (em segundo plano) e devolve o `run_id`."""
    try:
        result = scraper.start_run(source_id, trigger="manual")
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Fonte não encontrada.") from exc
    if result.get("already_running"):
        return {"run_id": result["run_id"], "status": "running", "already_running": True}
    return result


@router.post("/preview")
def preview_source(payload: PreviewPayload, _session: Session) -> Dict[str, Any]:
    """Testa uma definição (mesmo antes de a guardar) e devolve uma amostra."""
    if not payload.source:
        raise HTTPException(status_code=422, detail="Envie a definição da fonte em `source`.")
    try:
        return scraper.preview_source(payload.source, limit=payload.limit, max_pages=payload.max_pages)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("/sources/{source_id}/preview")
def preview_saved_source(
    source_id: str,
    _session: Session,
    overrides: Dict[str, Any] = Body(default_factory=dict),
    limit: int = Query(5, ge=1, le=50),
) -> Dict[str, Any]:
    """Testa uma fonte guardada, aceitando alterações pontuais aos seletores."""
    source = scraper.get_source(source_id)
    if not source:
        raise HTTPException(status_code=404, detail="Fonte não encontrada.")
    merged = {**source, **(overrides or {}), "id": source_id}
    try:
        return scraper.preview_source(merged, limit=limit, max_pages=1)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("/runs")
def list_runs(
    source_id: Optional[str] = None,
    limit: int = Query(50, ge=1, le=200),
) -> Dict[str, Any]:
    runs = scraper.list_runs(source_id, limit=limit)
    return {"total": len(runs), "items": [scraper.run_summary(r) for r in runs]}


@router.get("/sources/{source_id}/runs")
def list_source_runs(source_id: str, limit: int = Query(25, ge=1, le=200)) -> Dict[str, Any]:
    runs = scraper.list_runs(source_id, limit=limit)
    return {"total": len(runs), "items": [scraper.run_summary(r) for r in runs]}


@router.get("/runs/{run_id}")
def get_run(run_id: str, source_id: Optional[str] = None) -> Dict[str, Any]:
    meta = scraper.get_run(run_id, source_id)
    if not meta:
        raise HTTPException(status_code=404, detail="Execução não encontrada.")
    return {"item": meta}


@router.get("/runs/{run_id}/items")
def get_run_items(
    run_id: str,
    source_id: str = Query(..., description="Fonte da execução (organiza os ficheiros em disco)."),
    limit: int = Query(100, ge=1, le=1000),
    offset: int = Query(0, ge=0),
) -> Dict[str, Any]:
    meta = scraper.get_run(run_id, source_id)
    if not meta:
        raise HTTPException(status_code=404, detail="Execução não encontrada.")
    return scraper.read_run_items(run_id, source_id, limit=limit, offset=offset)


# ------------------------------------------------------------------ pesquisa
@router.get("/search")
def search_scraped_items(
    q: Optional[str] = Query(None, description="Texto livre (título, resumo, texto e todos os campos)."),
    source_id: Optional[str] = None,
    tag: Optional[List[str]] = Query(None, description="Etiquetas (pode repetir)."),
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    size: int = Query(20, ge=1, le=200),
    offset: int = Query(0, ge=0),
    sort: str = Query("recent", pattern="^(recent|oldest|relevance)$"),
) -> Dict[str, Any]:
    return scraper.search_items(
        q=q,
        source_id=source_id,
        tags=tag,
        date_from=date_from,
        date_to=date_to,
        size=size,
        from_=offset,
        sort=sort,
    )


# ------------------------------------------------------- sugestão com IA
@router.post("/suggest")
async def suggest_source(payload: SuggestPayload, session: Session) -> Dict[str, Any]:
    """Analisa uma página e propõe a definição (IA + heurística de reserva)."""
    urls = [part.strip() for part in re.split(r"[\s,]+", payload.url or "") if part.strip()]
    if not urls:
        raise HTTPException(status_code=422, detail="Indique o URL da página a analisar.")
    return await scraper_ai.suggest_source(
        urls[0],
        hint=payload.hint or "",
        fetcher=(payload.fetcher or "http"),
        options=payload.options or {},
        user_id=session.user.id,
        provider=payload.provider,
        model=payload.model,
        use_ai=payload.use_ai,
    )


# --------------------------------------------------------------- agendamento
@router.get("/jobs")
def list_jobs(_session: Session) -> Dict[str, Any]:
    return scheduler.status()


@router.post("/jobs/reload")
def reload_jobs(_session: Session) -> Dict[str, Any]:
    return scheduler.reload_jobs()
