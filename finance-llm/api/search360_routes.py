"""Rotas do módulo de pesquisa 360 (`/search360/*`).

O meta-modelo de análise e exploração: pesquisa federada (plataforma + documentos
+ Wikipédia/Wikidata + dados abertos + investigação + web + IA), dossiê de um
tema, biblioteca de pastas/ficheiros, grafo de navegação, indicadores e síntese
com citações.

Leitura (pública; os dados privados do CRM só aparecem com sessão):

- `GET  /search360/meta`                — catálogo de fontes, índices e cache
- `GET  /search360/suggest?q=`          — sugestões de tema (entidades + títulos)
- `POST /search360/search`              — pesquisa federada (fontes escolhidas, facetas, plano)
- `POST /search360/topic`               — dossiê 360 de um tema (tudo o que existe sobre ele)
- `POST /search360/library`             — organização dos resultados em pastas e ficheiros
- `POST /search360/graph`               — grafo de navegação do tema
- `POST /search360/ai/synthesis`        — síntese citada (IA quando configurada)
- `GET  /search360/status`              — diagnóstico rápido (índices e fontes com dados)

Guardar (requer sessão):

- `GET|POST|DELETE /search360/projects…`   — projetos (áreas de trabalho)
- `GET|POST|PATCH|DELETE /search360/dossiers…` — dossiês guardados (retrato do tema)
- `POST /search360/dossiers/{id}/refresh`  — volta a pesquisar o tema e guarda o retrato novo
- `GET  /search360/dossiers/{id}/export?format=md|json` — exportar
"""
from __future__ import annotations

import logging
from typing import Annotated, Any, Dict, List, Optional
from fastapi import APIRouter, Body, Depends, HTTPException, Query
from fastapi.responses import Response

from api import search360_service as service
from api import search360_sources as sources
from api import search360_store as store
from api.auth_routes import CurrentSession, optional_session

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/search360", tags=["search360"])

Session = Annotated[Optional[CurrentSession], Depends(optional_session)]


def _scope(session: Optional[CurrentSession]) -> Optional[Dict[str, Any]]:
    if not session:
        return None
    return {
        "user_id": session.user.id,
        "email": session.user.email,
        "see_all": (session.user.role or "member") == "admin",
    }


def _sources_param(value: Optional[List[str]]) -> Optional[List[str]]:
    """Aceita `sources` como lista repetida ou separada por vírgulas."""
    if not value:
        return None
    flat: List[str] = []
    for entry in value:
        flat.extend(part.strip() for part in str(entry).split(",") if part.strip())
    known = [source_id for source_id in flat if source_id in sources.CATALOG_BY_ID]
    unknown = [source_id for source_id in flat if source_id not in sources.CATALOG_BY_ID]
    if unknown:
        raise HTTPException(status_code=422, detail=f"Fontes desconhecidas: {', '.join(unknown)}.")
    return known or None


@router.get("/meta")
def meta() -> Dict[str, Any]:
    """Metamodelo: fontes disponíveis, famílias, capacidades e índices internos."""
    data = service.status()
    return {
        **data,
        "about": {
            "name": "Pesquisa 360",
            "description": (
                "Meta-modelo de analítica e exploração: federa as fontes da plataforma com a Wikipédia, "
                "Wikidata, dados abertos e investigação, organiza tudo em dossiê, biblioteca e grafo, e "
                "sintetiza com citações através dos modelos de IA configurados."
            ),
            "capabilities": ["search", "topic", "library", "graph", "metrics", "synthesis"],
        },
    }


@router.get("/status")
def status() -> Dict[str, Any]:
    """Diagnóstico rápido: fontes e volumetria dos índices internos."""
    data = service.status()
    return {
        "sources": [{"id": entry["id"], "label": entry["label"], "family": entry["family"], "available": entry.get("available")} for entry in data["sources"]],
        "indexes": data["indexes"],
        "cache": data["cache"],
    }


@router.get("/suggest")
def suggest(q: str = Query(..., min_length=1), limit: int = Query(6, ge=1, le=12), session: Session = None) -> Dict[str, Any]:
    """Sugestões de tema: entidades da plataforma e títulos de enciclopédia."""
    plan = service.plan(q)
    suggestions: List[Dict[str, Any]] = []
    try:
        internal = sources.internal_search(q, limit=limit, scope=_scope(session))
        for candidate in (internal.get("entities") or [])[:limit]:
            suggestions.append(
                {
                    "label": candidate.get("title"),
                    "hint": candidate.get("subtitle"),
                    "kind": candidate.get("kind"),
                    "source": "Plataforma",
                    "value": candidate.get("title"),
                }
            )
    except Exception as exc:  # sugestões nunca devem falhar
        logger.info("Sugestões internas falharam: %s", exc)
    return {"term": q, "plan": plan, "suggestions": suggestions[:limit]}


@router.post("/search")
async def search(
    payload: Dict[str, Any] = Body(...),
    sources_filter: Optional[List[str]] = Query(None, alias="sources"),
    session: Session = None,
) -> Dict[str, Any]:
    """Pesquisa federada: um tema, todas as fontes escolhidas, resultado normalizado."""
    term = str(payload.get("term") or payload.get("q") or "").strip()
    if not term:
        raise HTTPException(status_code=422, detail="Indique o tema a pesquisar (`term`).")
    chosen = _sources_param(payload.get("sources") or sources_filter)
    return await service.search(
        term,
        sources_ids=chosen,
        limit=int(payload.get("limit") or 6),
        scope=_scope(session),
    )


@router.post("/topic")
async def topic(payload: Dict[str, Any] = Body(...), session: Session = None) -> Dict[str, Any]:
    """Dossiê 360 de um tema: resultados, biblioteca, grafo, indicadores e síntese."""
    term = str(payload.get("term") or payload.get("q") or "").strip()
    if not term:
        raise HTTPException(status_code=422, detail="Indique o tema (`term`).")
    chosen = _sources_param(payload.get("sources"))
    return await service.topic(
        term,
        sources_ids=chosen,
        limit=int(payload.get("limit") or 6),
        scope=_scope(session),
        session=session,
        backend=payload.get("backend"),
        country=str(payload.get("country") or "PRT").upper()[:3],
        with_synthesis=bool(payload.get("synthesis", True)),
    )


@router.post("/library")
async def library(payload: Dict[str, Any] = Body(...), session: Session = None) -> Dict[str, Any]:
    """Organiza o tema em pastas (por família) e ficheiros (por tipo de conteúdo)."""
    term = str(payload.get("term") or payload.get("q") or "").strip()
    if not term:
        raise HTTPException(status_code=422, detail="Indique o tema (`term`).")
    found = await service.search(
        term,
        sources_ids=_sources_param(payload.get("sources")),
        limit=int(payload.get("limit") or 6),
        scope=_scope(session),
    )
    return service.library(found)


@router.post("/graph")
async def graph(payload: Dict[str, Any] = Body(...), session: Session = None) -> Dict[str, Any]:
    """Grafo de navegação: tema no centro, entidades/documentos/dados em volta."""
    term = str(payload.get("term") or payload.get("q") or "").strip()
    if not term:
        raise HTTPException(status_code=422, detail="Indique o tema (`term`).")
    found = await service.search(
        term,
        sources_ids=_sources_param(payload.get("sources")),
        limit=int(payload.get("limit") or 6),
        scope=_scope(session),
    )
    return service.graph(found, limit=int(payload.get("nodes") or 45))


@router.post("/ai/synthesis")
async def synthesis(payload: Dict[str, Any] = Body(...), session: Session = None) -> Dict[str, Any]:
    """Síntese do tema com citações das fontes (IA configurada ou texto factual)."""
    term = str(payload.get("term") or payload.get("q") or "").strip()
    if not term:
        raise HTTPException(status_code=422, detail="Indique o tema (`term`).")
    found = await service.search(
        term,
        sources_ids=_sources_param(payload.get("sources")),
        limit=int(payload.get("limit") or 6),
        scope=_scope(session),
    )
    series = await service.metrics(found, country=str(payload.get("country") or "PRT").upper()[:3])
    return await service.synthesis(term, found, session=session, backend=payload.get("backend"), metrics=series)


@router.post("/cache/clear")
def clear_cache() -> Dict[str, Any]:
    """Limpa a cache do metamodelo (útil depois de indexar dados novos)."""
    service.clear_cache()
    return {"cleared": True}


# ==========================================================================
# Projetos e dossiês guardados
# ==========================================================================
def _writer(session: Optional[CurrentSession]) -> Optional[CurrentSession]:
    if not session:
        raise HTTPException(status_code=401, detail="Entrar na plataforma para guardar dossiês e projetos.")
    return session


@router.get("/projects")
def list_projects(session: Session = None, ontology: Optional[str] = Query(None)) -> Dict[str, Any]:
    """Projetos (áreas de trabalho) com o número de dossiês guardados em cada um."""
    return store.list_projects(ontology)


@router.post("/projects")
def save_project(payload: Dict[str, Any] = Body(...), session: Session = None, ontology: Optional[str] = Query(None)) -> Dict[str, Any]:
    """Cria ou altera um projeto (`name`, `description`, `color`, `tags`)."""
    writer = _writer(session)
    try:
        item = store.save_project({**payload, "owner": payload.get("owner") or writer.user.email}, ontology)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    return {"saved": True, "project": item}


@router.delete("/projects/{project_id}")
def delete_project(project_id: str, session: Session = None, ontology: Optional[str] = Query(None)) -> Dict[str, Any]:
    """Remove um projeto (os dossiês ficam, sem projeto)."""
    _writer(session)
    return store.delete_project(project_id, ontology)


@router.get("/dossiers")
def list_dossiers(
    project_id: Optional[str] = Query(None),
    term: Optional[str] = Query(None),
    limit: int = Query(60, ge=1, le=200),
    ontology: Optional[str] = Query(None),
) -> Dict[str, Any]:
    """Dossiês guardados (resumo), opcionalmente por projeto ou tema."""
    return store.list_dossiers(project_id=project_id, term=term, limit=limit, ontology_id=ontology)


@router.get("/dossiers/{dossier_id}")
def get_dossier(dossier_id: str, ontology: Optional[str] = Query(None)) -> Dict[str, Any]:
    """Dossiê guardado completo (com o retrato da pesquisa e a síntese)."""
    try:
        return store.get_dossier(dossier_id, ontology)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


@router.post("/dossiers")
async def save_dossier(payload: Dict[str, Any] = Body(...), session: Session = None, ontology: Optional[str] = Query(None)) -> Dict[str, Any]:
    """Guarda o dossiê 360 de um tema (num projeto, com etiquetas e notas).

    Se o corpo não trouxer `snapshot`, o dossiê é construído agora (pesquisa
    federada + indicadores + síntese) e guardado logo a seguir.
    """
    writer = _writer(session)
    term = str(payload.get("term") or "").strip()
    topic = payload.get("topic") if isinstance(payload.get("topic"), dict) else None
    if topic is None and not payload.get("snapshot"):
        if not term:
            raise HTTPException(status_code=422, detail="Indique o tema (`term`) ou envie o dossiê (`topic`/`snapshot`).")
        source_ids = payload.get("sources")
        topic = await service.topic(
            term,
            sources_ids=[str(source) for source in source_ids] if source_ids else None,
            limit=int(payload.get("limit") or 6),
            scope=_scope(session),
            session=session,
            backend=payload.get("backend"),
            country=str(payload.get("country") or "PRT").upper()[:3],
            with_synthesis=bool(payload.get("synthesis", True)),
        )
    try:
        return store.save_dossier({**payload, "author": payload.get("author") or writer.user.email}, topic=topic, ontology_id=ontology)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))


@router.patch("/dossiers/{dossier_id}")
def rename_dossier(dossier_id: str, payload: Dict[str, Any] = Body(...), session: Session = None, ontology: Optional[str] = Query(None)) -> Dict[str, Any]:
    """Altera título, notas, etiquetas ou projeto de um dossiê guardado."""
    _writer(session)
    try:
        return store.rename_dossier(dossier_id, payload, ontology)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


@router.post("/dossiers/{dossier_id}/refresh")
async def refresh_dossier(
    dossier_id: str,
    payload: Dict[str, Any] = Body(default_factory=dict),
    session: Session = None,
    ontology: Optional[str] = Query(None),
) -> Dict[str, Any]:
    """Volta a pesquisar o tema do dossiê e guarda o retrato novo (o anterior fica no histórico)."""
    _writer(session)
    try:
        current = store.get_dossier(dossier_id, ontology)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    term = str(payload.get("term") or current.get("term") or "").strip()
    if not term:
        raise HTTPException(status_code=422, detail="O dossiê não tem tema; indique `term`.")
    topic = await service.topic(
        term,
        limit=int(payload.get("limit") or 6),
        scope=_scope(session),
        session=session,
        backend=payload.get("backend"),
        country=str(payload.get("country") or "PRT").upper()[:3],
        with_synthesis=bool(payload.get("synthesis", True)),
    )
    return store.refresh_dossier(dossier_id, topic=topic, ontology_id=ontology)


@router.delete("/dossiers/{dossier_id}")
def delete_dossier(dossier_id: str, session: Session = None, ontology: Optional[str] = Query(None)) -> Dict[str, Any]:
    """Apaga um dossiê guardado."""
    _writer(session)
    return store.delete_dossier(dossier_id, ontology)


@router.get("/dossiers/{dossier_id}/export")
def export_dossier(
    dossier_id: str,
    format: str = Query("md", pattern="^(md|json)$"),
    ontology: Optional[str] = Query(None),
) -> Any:
    """Exporta um dossiê guardado em Markdown (`.md`) ou JSON."""
    try:
        dossier = store.get_dossier(dossier_id, ontology)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    if format == "json":
        return Response(
            content=store.dossier_json(dossier),
            media_type="application/json",
            headers={"content-disposition": f'attachment; filename="{dossier_id}.json"'},
        )
    return Response(
        content=store.dossier_markdown(dossier),
        media_type="text/markdown; charset=utf-8",
        headers={"content-disposition": f'attachment; filename="{dossier_id}.md"'},
    )
