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

Templates de sites
- `GET    /scraper/templates`                 — galeria de definições prontas (site → fonte)
- `GET    /scraper/templates/{template_id}`   — um template (com a definição que cria)
- `POST   /scraper/templates/{id}/preview`    — testar o template sem guardar           (sessão)
- `POST   /scraper/templates/{id}/source`     — criar a fonte a partir do template       (sessão)
- `POST   /scraper/sources/{id}/apply-template` — reaplicar o template à fonte          (sessão)
"""
from __future__ import annotations

import logging
import re
from typing import Annotated, Any, Dict, List, Optional

from fastapi import APIRouter, Body, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from api import scraper_ai
from api import scraper_scheduler as scheduler
from api import scraper_sentiment
from api import scraper_service as scraper
from api import scraper_templates as templates
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
    detail: Optional[Dict[str, Any]] = Field(
        None, description="Texto integral: {enabled, selector, max_items, delay, max_chars}"
    )
    sentiment: Optional[Dict[str, Any]] = Field(
        None, description="Sentimento por item: {enabled, engine, provider, model, max_items, field}"
    )

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


class SentimentPayload(BaseModel):
    """Análise de sentimento dos itens já recolhidos."""

    source_id: Optional[str] = Field(None, description="Limitar a uma fonte.")
    q: Optional[str] = Field(None, description="Limitar a uma pesquisa de texto.")
    tags: Optional[List[str]] = Field(None, description="Limitar a etiquetas.")
    limit: int = Field(50, ge=1, le=200, description="Itens a analisar (mais itens = mais chamadas ao modelo).")
    engine: str = Field("auto", description="auto | ai | lexicon")
    provider: Optional[str] = Field(None, description="Fornecedor de IA (por omissão: o do utilizador).")
    model: Optional[str] = None
    reanalyze: bool = Field(False, description="Analisar também os itens que já têm sentimento.")


class TemplateSourcePayload(BaseModel):
    """Ajustes ao criar a fonte a partir de um template (todos opcionais)."""

    id: Optional[str] = Field(None, description="Identificador da fonte (por omissão: derivado do nome).")
    name: Optional[str] = None
    description: Optional[str] = None
    enabled: Optional[bool] = Field(None, description="Ligar já o agendamento cron do template.")
    cron: Optional[str] = Field(None, description="Substituir a periodicidade sugerida pelo template.")
    max_pages: Optional[int] = Field(None, ge=1, le=500, description="Páginas da lista a percorrer.")
    detail_max_items: Optional[int] = Field(
        None, ge=0, le=200, description="Itens por execução com texto integral (0 desliga)."
    )
    respect_robots: Optional[bool] = None
    tags: Optional[List[str]] = None


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
        "template_categories": templates.CATEGORIES,
        "sentiment_engines": [
            {"id": engine, "label": scraper_sentiment.ENGINE_LABELS[engine]} for engine in scraper_sentiment.ENGINES
        ],
        "sentiment_fields": [
            {"id": field, "label": scraper_sentiment.FIELD_LABELS[field]} for field in scraper_sentiment.FIELDS
        ],
        "sentiment_labels": list(scraper_sentiment.LABELS),
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
def run_source(source_id: str, session: Session) -> Dict[str, Any]:
    """Arranca uma recolha imediata (em segundo plano) e devolve o `run_id`."""
    try:
        # O utilizador da sessão serve para o sentimento usar a chave de IA dele.
        result = scraper.start_run(source_id, trigger="manual", user_id=session.user.id)
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
    sentiment: Optional[List[str]] = Query(None, description="Filtrar por sentimento (positivo/neutro/negativo)."),
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
        sentiments=sentiment,
        date_from=date_from,
        date_to=date_to,
        size=size,
        from_=offset,
        sort=sort,
    )


@router.post("/sentiment")
def analyze_sentiment(payload: SentimentPayload, session: Session) -> Dict[str, Any]:
    """Dá sentimento aos itens já recolhidos (modelo de IA; léxico como reserva).

    É o que permite ter sentimento em recolhas antigas sem repetir a recolha — e,
    a partir daí, filtrar e resumir a pesquisa por sentimento.
    """
    if payload.engine not in scraper_sentiment.ENGINES:
        raise HTTPException(status_code=422, detail="Motor de sentimento inválido (auto, ai ou lexicon).")
    return scraper.sentiment_backfill(
        source_id=payload.source_id,
        q=payload.q,
        tags=payload.tags,
        limit=payload.limit,
        engine=payload.engine,
        provider=payload.provider or "",
        model=payload.model or "",
        user_id=session.user.id,
        reanalyze=payload.reanalyze,
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


# ------------------------------------------------------------------ templates
@router.get("/templates")
def list_templates(category: Optional[str] = Query(None, description="Filtrar por categoria.")) -> Dict[str, Any]:
    """Galeria de definições prontas (Jornal Económico, ECO, Público, Expansión…)."""
    items = templates.list_templates(category)
    return {"total": len(items), "categories": templates.CATEGORIES, "items": items}


@router.get("/templates/{template_id}")
def get_template(template_id: str) -> Dict[str, Any]:
    """Um template e a definição de fonte que ele cria."""
    item = templates.get_template(template_id)
    if not item:
        raise HTTPException(status_code=404, detail="Template não encontrado.")
    try:
        item = {**item, "source": templates.build_source(template_id)}
    except (KeyError, ValueError) as exc:
        logger.warning("Template %s inválido: %s", template_id, exc)
    return {"item": item}


@router.post("/templates/{template_id}/preview")
def preview_template(
    template_id: str,
    _session: Session,
    limit: int = Query(3, ge=1, le=25),
    max_pages: int = Query(1, ge=1, le=10),
) -> Dict[str, Any]:
    """Testa o template contra o site (não guarda nada e não indexa)."""
    try:
        source = templates.build_source(template_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Template não encontrado.") from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    try:
        return scraper.preview_source(source, limit=limit, max_pages=max_pages)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("/templates/{template_id}/source")
def create_source_from_template(
    template_id: str, payload: TemplateSourcePayload, _session: Session
) -> Dict[str, Any]:
    """Cria uma fonte a partir do template, com os ajustes indicados."""
    overrides: Dict[str, Any] = {}
    changes = payload.model_dump(exclude_unset=True)
    if payload.id:
        overrides["id"] = payload.id
    for key in ("name", "description", "respect_robots"):
        if changes.get(key) is not None:
            overrides[key] = changes[key]
    if payload.enabled is not None:
        overrides["enabled"] = payload.enabled
    if payload.cron:
        overrides["schedule"] = {"cron": payload.cron}
    if payload.max_pages:
        overrides["pagination"] = {"max_pages": payload.max_pages}
    if payload.detail_max_items is not None:
        overrides["detail"] = {"max_items": payload.detail_max_items}
    if payload.tags:
        overrides["tags"] = payload.tags
    try:
        source = templates.build_source(template_id, overrides)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Template não encontrado.") from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    if source.get("enabled") and not (source.get("schedule") or {}).get("cron"):
        raise HTTPException(
            status_code=422,
            detail="Para ligar a fonte é preciso uma expressão cron (o template sugere uma).",
        )
    try:
        created = scraper.upsert_source(source)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    scheduler.reload_jobs()
    return {"item": created, "template": templates.get_template(template_id)}


@router.post("/sources/{source_id}/apply-template")
def apply_template_to_source(
    source_id: str,
    _session: Session,
    template_id: Optional[str] = Query(None, description="Template a aplicar (por omissão: o da fonte)."),
) -> Dict[str, Any]:
    """Reaplica a definição do template a uma fonte existente.

    Serve para quando o site muda de `class` e o template é corrigido aqui: a
    fonte guardada continua com os seletores antigos até ser reaplicada. Mantêm-se
    o identificador, o nome, o interruptor, a agenda e as etiquetas.
    """
    source = scraper.get_source(source_id)
    if not source:
        raise HTTPException(status_code=404, detail="Fonte não encontrada.")
    # Chamada direta (testes) traz o valor por omissão do FastAPI em vez de None.
    explicit = template_id if isinstance(template_id, str) and template_id.strip() else None
    if not explicit and not source.get("template_id"):
        raise HTTPException(
            status_code=422,
            detail="Esta fonte não veio de um template; indique `template_id` para a substituir.",
        )
    try:
        refreshed = templates.refresh_source(source, explicit)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Template não encontrado.") from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    try:
        saved = scraper.upsert_source({**refreshed, "_must_exist": True})
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Fonte não encontrada.") from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    scheduler.reload_jobs()
    return {"item": saved, "template": templates.get_template(saved.get("template_id") or explicit or "")}
