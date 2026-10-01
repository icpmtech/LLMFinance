"""Rotas FastAPI para o módulo Pessoas e Cargos do IQ OS.

Exposições principais:
- GET /people/status
- POST /people/ingest/{nif}  (re)gerar pessoas/cargos para uma empresa
- POST /people/ingest-cire  indexar as pessoas que constam dos processos do CIRE
- GET /people/ingest-cire/jobs[/{job_id}]  progresso da ingestão do CIRE
- POST /people/{nif}/social-collect  obter dados públicos (redes sociais + internet)
- GET /people/{nif}/social  conteúdos recolhidos (imagens, vídeos, textos)
- GET /people/{nif}/360  análise 360 (risco, relações e ficha analítica)
- GET /people/search
- GET /people/{nif}
- GET /people/{nif}/graph
- GET /people/company/{company_nif}/graph
"""
from __future__ import annotations

import threading
import uuid
from datetime import datetime
from typing import Annotated, Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from starlette.concurrency import run_in_threadpool

from api.auth_routes import CurrentSession, optional_session, require_session
from api.elasticsearch_client import (
    combined_graph_for_company,
    companies_with_people,
    company_people_from_index,
    get_es_client,
    get_person_by_nif,
    index_people_from_cire,
    index_people_from_societario,
    node_summaries_status,
    people_autocomplete,
    people_filters,
    people_graph_for_company,
    people_graph_for_person,
    people_index_presence,
    people_status,
    search_people,
)
from api.people_360 import person_360, social_bundle
from api.people_social import SOURCES as SOCIAL_SOURCES
from api.people_social import collect_person_social
from api.node_summary import saved_summary as load_node_summary
from api.node_summary import node_summary, normalize_node
from api.people_politician import enrich_politician, party_news, build_political_graph, _co_party_people, _person_party

router = APIRouter(prefix="/people", tags=["people"])


class PersonRole(BaseModel):
    role: str
    role_org: Optional[str] = None
    company_nif: Optional[str] = None
    company_name: Optional[str] = None
    date: Optional[str] = None
    publication_date: Optional[str] = None
    acto: Optional[str] = None
    event: Optional[str] = None
    quota: Optional[float] = None
    causa: Optional[str] = None
    residencia: Optional[str] = None
    publication_id: Optional[str] = None
    nacionalidade: Optional[str] = None


class Person(BaseModel):
    nif: str
    name: str
    name_keyword: Optional[str] = None
    is_company: bool = False
    roles: List[PersonRole] = Field(default_factory=list)
    companies: List[Dict[str, str]] = Field(default_factory=list)
    companies_count: int = 0
    roles_count: int = 0
    first_seen: Optional[str] = None
    last_seen: Optional[str] = None
    source: Optional[str] = None
    ingested_at: Optional[str] = None
    photo_path: Optional[str] = None
    photo_url: Optional[str] = None
    biography: Optional[str] = None
    metadata: Optional[Dict[str, Any]] = None
    latest_roles: Optional[List[Dict[str, Any]]] = None
    tags: Optional[List[str]] = None
    doc_id: Optional[str] = None

    model_config = {"extra": "allow"}


class PeopleSearchResponse(BaseModel):
    total: int
    items: List[Person]
    from_: int = Field(alias="from")
    size: int
    filters: Optional[Dict[str, Any]] = None
    error: Optional[str] = None

    class Config:
        populate_by_name = True


class PeopleAutocompleteItem(BaseModel):
    nif: Optional[str] = None
    name: str = ""
    is_company: bool = False
    roles_count: int = 0
    companies_count: int = 0
    role: Optional[str] = None
    company_name: Optional[str] = None
    origin: Optional[str] = None
    last_seen: Optional[str] = None


class PeopleAutocompleteResponse(BaseModel):
    q: str = ""
    items: List[PeopleAutocompleteItem] = Field(default_factory=list)
    error: Optional[str] = None


class PeopleFiltersResponse(BaseModel):
    available: bool = True
    roles: List[Dict[str, Any]] = Field(default_factory=list)
    origins: List[Dict[str, Any]] = Field(default_factory=list)
    types: List[Dict[str, Any]] = Field(default_factory=list)
    with_cire: int = 0
    error: Optional[str] = None


class PeopleGraphResponse(BaseModel):
    person_nif: Optional[str] = None
    person_name: Optional[str] = None
    company_nif: Optional[str] = None
    company_name: Optional[str] = None
    nodes: List[Dict[str, Any]]
    edges: List[Dict[str, Any]]
    node_count: int
    edge_count: int
    meta: Optional[Dict[str, Any]] = None


class PeopleIngestResponse(BaseModel):
    nif: Optional[str]
    indexed_count: int
    total: int
    errors: int = 0
    #: Publicações societárias lidas na extração (0 = a entidade ainda não tem publicações).
    publications: int = 0
    error: Optional[str] = None


class PeopleStatusResponse(BaseModel):
    index: str
    documents: int
    is_company: List[Dict[str, Any]] = Field(default_factory=list)
    total_company_links: int = 0
    top_roles: List[Dict[str, Any]] = Field(default_factory=list)
    by_source: List[Dict[str, Any]] = Field(default_factory=list)
    summaries: Optional[Dict[str, Any]] = None
    error: Optional[str] = None


class PeopleCireIngestRequest(BaseModel):
    """Parâmetros da ingestão de pessoas a partir dos processos do CIRE."""

    limit: Optional[int] = Field(default=None, ge=1, description="Máximo de publicações do CIRE a ler (útil para testes).")
    include_companies: bool = Field(default=False, description="Incluir pessoas coletivas (credores institucionais, sociedades insolventes).")
    papeis: Optional[List[str]] = Field(
        default=None,
        description="Filtrar papéis do processo (ex.: ['Insolvente', 'Administrador da insolvência']).",
    )
    wait: bool = Field(default=False, description="Esperar pelo fim da ingestão em vez de devolver o id do trabalho.")


class PeopleCireJobResponse(BaseModel):
    job_id: str
    status: str
    started_at: Optional[str] = None
    finished_at: Optional[str] = None
    progress: Dict[str, Any] = Field(default_factory=dict)
    result: Optional[Dict[str, Any]] = None
    error: Optional[str] = None


class PeopleSocialCollectRequest(BaseModel):
    """Pedido de recolha de dados públicos de uma pessoa."""

    sources: List[str] = Field(
        default_factory=lambda: list(SOCIAL_SOURCES),
        description="Fontes a recolher: internet, linkedin, tiktok, facebook.",
    )
    limit: int = Field(default=8, ge=1, le=8, description="Páginas a ler por fonte.")


class PeopleSocialCollectResponse(BaseModel):
    nif: Optional[str] = None
    name: Optional[str] = None
    collected_at: Optional[str] = None
    queries: List[Dict[str, Any]] = Field(default_factory=list)
    sources: List[Dict[str, Any]] = Field(default_factory=list)
    items: int = 0
    items_indexed: int = 0
    engine_hint: Optional[str] = None
    error: Optional[str] = None


class PeopleSocialResponse(BaseModel):
    """Conteúdos públicos já recolhidos sobre a pessoa."""

    nif: str
    total: int = 0
    images: List[Dict[str, Any]] = Field(default_factory=list)
    videos: List[Dict[str, Any]] = Field(default_factory=list)
    texts: List[Dict[str, Any]] = Field(default_factory=list)
    by_platform: List[Dict[str, Any]] = Field(default_factory=list)
    sentiment: Dict[str, Any] = Field(default_factory=dict)
    last_collected: Optional[str] = None


class People360Response(BaseModel):
    """Análise 360 de uma pessoa: ficha, risco, relações e ficha analítica."""

    nif: str
    name: Optional[str] = None
    is_company: bool = False
    generated_at: Optional[str] = None
    profile: Dict[str, Any] = Field(default_factory=dict)
    cire: Dict[str, Any] = Field(default_factory=dict)
    social: Dict[str, Any] = Field(default_factory=dict)
    risk: Dict[str, Any] = Field(default_factory=dict)
    graph: Dict[str, Any] = Field(default_factory=dict)
    analysis: Dict[str, Any] = Field(default_factory=dict)
    error: Optional[str] = None


class NodeSummaryRequest(BaseModel):
    """Pedido de resumo de um nó do grafo (`person:123`, `company:456`, `source:host`)."""

    node_id: Optional[str] = Field(default=None, description="Identificador do nó (ex.: `person:501964843`).")
    nif: Optional[str] = Field(default=None, description="NIF/NIPC do nó (alternativa ao `node_id`).")
    name: Optional[str] = Field(default=None, description="Nome/rótulo do nó (usado na pesquisa e como recurso).")
    kind: Optional[str] = Field(default=None, description="person | company | entity | source.")
    limit: int = Field(default=6, ge=1, le=10, description="Resultados de pesquisa por consulta.")
    pages: int = Field(default=2, ge=0, le=4, description="Páginas web a ler por completo (para além dos resumos da pesquisa).")
    reuse_hours: float = Field(
        default=0.0,
        ge=0,
        le=720,
        description="Reaproveitar o resumo gravado se for mais recente do que estas horas (0 = gerar sempre).",
    )
    backend: Optional[str] = Field(default=None, description="Modelo a usar (ex.: `openai:gpt-4o-mini`); por omissão, o do utilizador.")


class NodeSummaryResponse(BaseModel):
    """Resumo de um nó: texto, evidência da web e factos internos (guardado no Elasticsearch)."""

    node_id: str
    nif: Optional[str] = None
    name: Optional[str] = None
    kind: Optional[str] = None
    summary: Optional[str] = None
    mode: Optional[str] = None
    provider: Optional[str] = None
    model: Optional[str] = None
    backend: Optional[Dict[str, Any]] = None
    facts: Dict[str, Any] = Field(default_factory=dict)
    evidence: List[Dict[str, Any]] = Field(default_factory=list)
    evidence_count: int = 0
    pages_read: int = 0
    queries: List[Any] = Field(default_factory=list)
    generated_at: Optional[str] = None
    generations: Optional[int] = None
    saved: bool = False
    cached: bool = False
    found: bool = True
    notes: List[str] = Field(default_factory=list)
    warnings: List[str] = Field(default_factory=list)
    error: Optional[str] = None


class PeoplePresenceRequest(BaseModel):
    """NIF/NIPC a validar no índice de pessoas."""

    nifs: List[str] = Field(default_factory=list)


class PeoplePresenceResponse(BaseModel):
    total: int = 0
    indexed: List[str] = Field(default_factory=list)
    missing: List[str] = Field(default_factory=list)
    error: Optional[str] = None


class PeopleCompanyItem(BaseModel):
    """Empresa com pessoas/cargos no PessoasIQ."""

    nif: str
    name: Optional[str] = None
    people_count: int = 0
    roles_count: int = 0


class PeopleCompaniesResponse(BaseModel):
    total: int = 0
    items: List[PeopleCompanyItem] = Field(default_factory=list)
    error: Optional[str] = None


class PeopleCompanyResponse(BaseModel):
    """Ficha de empresa no PessoasIQ: dados da empresa + pessoas com cargos nela."""

    nif: str
    name: Optional[str] = None
    total: int = 0
    people: List[Dict[str, Any]] = Field(default_factory=list)
    error: Optional[str] = None


@router.get("/status", response_model=PeopleStatusResponse)
def people_status_route(session: Annotated[CurrentSession, Depends(optional_session)]):
    result = people_status()
    result["summaries"] = node_summaries_status()
    return PeopleStatusResponse(**result)


@router.post("/exists", response_model=PeoplePresenceResponse)
def people_exists_route(
    payload: PeoplePresenceRequest,
    session: Annotated[CurrentSession, Depends(optional_session)] = None,
):
    """Diz quais dos NIF indicados já têm ficha no PessoasIQ (e quais faltam)."""
    return PeoplePresenceResponse(**people_index_presence(payload.nifs))


@router.post("/ingest/{nif}", response_model=PeopleIngestResponse)
def people_ingest_route(
    nif: str,
    replace: bool = True,
    session: Annotated[CurrentSession, Depends(optional_session)] = None,
):
    """Extrai e indexa pessoas/cargos das publicações societárias de uma empresa."""
    result = index_people_from_societario(nif=nif, replace_for_nif=nif if replace else None)
    if result.get("error") and result.get("indexed_count", 0) == 0:
        raise HTTPException(status_code=500, detail=result["error"])
    return PeopleIngestResponse(**result)


# --- Pessoas a partir dos processos de insolvência (CIRE) ---

#: Trabalhos de ingestão do CIRE, por id (o processo é longo e corre em segundo plano).
_CIRE_JOBS: Dict[str, Dict[str, Any]] = {}
_CIRE_JOBS_LOCK = threading.Lock()
_CIRE_JOBS_KEEP = 20


def _new_cire_job() -> Dict[str, Any]:
    return {
        "job_id": uuid.uuid4().hex[:12],
        "status": "running",
        "started_at": datetime.utcnow().isoformat(),
        "finished_at": None,
        "progress": {},
        "result": None,
        "error": None,
    }


def _run_cire_ingest(job: Dict[str, Any], payload: PeopleCireIngestRequest) -> None:
    """Corre a ingestão do CIRE e vai atualizando o estado do trabalho."""
    try:
        result = index_people_from_cire(
            limit=payload.limit,
            include_companies=payload.include_companies,
            papeis=payload.papeis,
            progress=job["progress"],
        )
        job["result"] = result
        job["status"] = "error" if result.get("error") else "done"
        if result.get("error"):
            job["error"] = result["error"]
    except Exception as exc:  # pragma: no cover - salvaguarda para não perder o estado
        job["status"] = "error"
        job["error"] = str(exc)
    finally:
        job["finished_at"] = datetime.utcnow().isoformat()
        with _CIRE_JOBS_LOCK:
            # Manter apenas os trabalhos mais recentes.
            if len(_CIRE_JOBS) > _CIRE_JOBS_KEEP:
                for old_id, _ in sorted(_CIRE_JOBS.items(), key=lambda kv: str(kv[1].get("started_at")))[: len(_CIRE_JOBS) - _CIRE_JOBS_KEEP]:
                    _CIRE_JOBS.pop(old_id, None)


@router.post("/ingest-cire", response_model=PeopleCireJobResponse)
async def people_ingest_cire_route(
    payload: PeopleCireIngestRequest,
    session: Annotated[CurrentSession, Depends(optional_session)] = None,
):
    """Indexa no PessoasIQ as pessoas que constam dos processos do CIRE.

    Corre em segundo plano (673k de publicações) e devolve o id do trabalho, para
    o progresso ser seguido em `GET /people/ingest-cire/jobs/{job_id}`. Com
    `wait=true` espera pelo fim e devolve já o resultado (útil para amostras).
    """
    if payload.wait:
        job = _new_cire_job()
        # Corrida no threadpool: a ingestão leva minutos e não pode bloquear o
        # event loop (bloquear aqui deixava toda a aplicação à espera).
        await run_in_threadpool(_run_cire_ingest, job, payload)
        return PeopleCireJobResponse(**job)

    with _CIRE_JOBS_LOCK:
        running = next((j for j in _CIRE_JOBS.values() if j.get("status") == "running"), None)
        if running:
            raise HTTPException(
                status_code=409,
                detail=f"Já existe uma ingestão de pessoas do CIRE a correr ({running['job_id']}).",
            )
        job = _new_cire_job()
        _CIRE_JOBS[job["job_id"]] = job

    threading.Thread(
        target=_run_cire_ingest,
        args=(job, payload),
        name="people-cire-ingest",
        daemon=True,
    ).start()
    return PeopleCireJobResponse(**job)


@router.get("/ingest-cire/jobs", response_model=List[PeopleCireJobResponse])
async def people_ingest_cire_jobs_route(
    session: Annotated[CurrentSession, Depends(optional_session)] = None,
):
    """Estado dos trabalhos de ingestão de pessoas do CIRE (mais recentes primeiro)."""
    with _CIRE_JOBS_LOCK:
        jobs = sorted(_CIRE_JOBS.values(), key=lambda j: str(j.get("started_at") or ""), reverse=True)
    return [PeopleCireJobResponse(**job) for job in jobs]


@router.get("/ingest-cire/jobs/{job_id}", response_model=PeopleCireJobResponse)
async def people_ingest_cire_job_route(
    job_id: str,
    session: Annotated[CurrentSession, Depends(optional_session)] = None,
):
    job = _CIRE_JOBS.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Trabalho de ingestão do CIRE não encontrado.")
    return PeopleCireJobResponse(**job)


# --- Dados públicos da pessoa (redes sociais + internet) e análise 360 ---


@router.post("/{nif}/social-collect", response_model=PeopleSocialCollectResponse)
def people_social_collect_route(
    nif: str,
    payload: PeopleSocialCollectRequest,
    session: Annotated[CurrentSession, Depends(optional_session)] = None,
):
    """Vai buscar o que é público sobre a pessoa (LinkedIn, TikTok, Facebook e internet).

    Pesquisa o nome (com o NIF e as empresas da ficha, para desambiguar), classifica
    as ligações por plataforma, lê cada uma e guarda título, texto, imagem e vídeo
    em `finance_social` ligados à pessoa. O que estiver bloqueado fica registado
    como ligação — a resposta diz o que cada fonte conseguiu.

    É uma rota **síncrona** (o FastAPI corre-a no threadpool): a recolha lê páginas
    externas durante dezenas de segundos e não pode bloquear o *event loop*, senão
    a aplicação inteira fica à espera.
    """
    result = collect_person_social(nif, sources=payload.sources, limit=payload.limit)
    if result.get("error") and not result.get("sources"):
        raise HTTPException(status_code=404, detail=result["error"])
    return PeopleSocialCollectResponse(**result)


@router.get("/{nif}/social", response_model=PeopleSocialResponse)
def people_social_route(
    nif: str,
    size: int = Query(default=100, ge=1, le=200),
    session: Annotated[CurrentSession, Depends(optional_session)] = None,
):
    """Conteúdos já recolhidos sobre a pessoa (imagens, vídeos e textos)."""
    bundle = social_bundle(nif, size=size)
    if bundle.get("error"):
        raise HTTPException(status_code=500, detail=bundle["error"])
    return PeopleSocialResponse(
        nif=nif,
        total=bundle.get("total") or 0,
        images=bundle.get("images") or [],
        videos=bundle.get("videos") or [],
        texts=bundle.get("texts") or [],
        by_platform=bundle.get("by_platform") or [],
        sentiment=bundle.get("sentiment") or {},
        last_collected=bundle.get("last_collected"),
    )


@router.get("/{nif}/360", response_model=People360Response)
async def people_360_route(
    nif: str,
    with_ai: bool = True,
    cire_size: int = Query(default=200, ge=1, le=1000),
    social_size: int = Query(default=200, ge=0, le=200),
    backend: Optional[str] = None,
    session: Annotated[CurrentSession, Depends(optional_session)] = None,
):
    """Análise 360 da pessoa: ficha, insolvências, presença digital, risco, grafo e ficha analítica.

    O risco é uma pontuação explicável (0–100): cada fator traz os pontos e a
    evidência. A ficha analítica é redigida por IA quando há modelo configurado e,
    sem ele, montada apenas com os factos (`with_ai=false` força a versão factual).
    """
    report = await person_360(
        nif,
        session=session,
        backend=backend,
        with_ai=bool(with_ai),
        social_size=social_size,
        cire_size=cire_size,
    )
    if report.get("error"):
        raise HTTPException(status_code=404, detail=report["error"])
    return People360Response(**report)


# --- Resumo de um nó do grafo (IA + pesquisa na web, guardado no ES) ---


@router.get("/summary", response_model=NodeSummaryResponse)
def node_summary_get_route(
    node_id: Optional[str] = None,
    nif: Optional[str] = None,
    name: Optional[str] = None,
    session: Annotated[CurrentSession, Depends(optional_session)] = None,
):
    """Último resumo **já gravado** de um nó (não gera nada nem gasta tokens)."""
    result = load_node_summary(node_id=node_id, nif=nif, name=name)
    if not result.get("found"):
        normalized, _, _ = normalize_node(node_id=node_id, nif=nif, name=name)
        return NodeSummaryResponse(node_id=normalized, nif=nif, name=name, found=False)
    return NodeSummaryResponse(**result)


@router.post("/summary", response_model=NodeSummaryResponse)
async def node_summary_post_route(
    payload: NodeSummaryRequest,
    session: Annotated[CurrentSession, Depends(optional_session)] = None,
):
    """Gera o resumo de um nó (factos do IQ OS + web + modelo) e guarda-o no Elasticsearch.

    Serve qualquer nó do grafo: pessoas, empresas, entidades e sites. O resumo é
    **sempre gravado** em `finance_node_summaries`; usar `reuse_hours` > 0 para
    reaproveitar um resumo recente em vez de gerar outro.
    """
    result = await node_summary(
        node_id=payload.node_id,
        nif=payload.nif,
        name=payload.name,
        kind=payload.kind,
        session=session,
        backend=payload.backend,
        limit=payload.limit,
        pages=payload.pages,
        reuse_hours=payload.reuse_hours,
    )
    return NodeSummaryResponse(**result)

@router.get("/search", response_model=PeopleSearchResponse)
def people_search_route(
    q: Optional[str] = None,
    nif: Optional[str] = None,
    company_nif: Optional[str] = None,
    role: Optional[str] = None,
    is_company: Optional[bool] = None,
    origin: Optional[str] = Query(default=None, description="`cire` ou `societario`"),
    source: Optional[str] = Query(default=None, description="Sub-string do campo `source` (ex.: `parlamento`, `wikipedia`)"),
    party: Optional[str] = Query(default=None, description="Partido político (sub-string, case-insensitive)"),
    min_roles: Optional[int] = Query(default=None, ge=0),
    min_companies: Optional[int] = Query(default=None, ge=0),
    sort: str = Query(default="relevance", pattern="^(relevance|roles|recent|name)$"),
    size: int = Query(default=20, ge=1, le=200),
    from_: int = Query(default=0, ge=0, alias="from"),
    session: Annotated[CurrentSession, Depends(optional_session)] = None,
):
    result = search_people(
        q=q,
        nif=nif,
        company_nif=company_nif,
        role=role,
        is_company=is_company,
        origin=origin,
        source=source,
        party=party,
        min_roles=min_roles,
        min_companies=min_companies,
        sort=sort,
        size=size,
        from_=from_,
    )
    if result.get("error"):
        raise HTTPException(status_code=500, detail=result["error"])
    return PeopleSearchResponse(**result)


@router.get("/autocomplete", response_model=PeopleAutocompleteResponse)
def people_autocomplete_route(
    q: str = Query(default="", description="Nome, prefixo do nome ou NIF"),
    limit: int = Query(default=8, ge=1, le=25),
    is_company: Optional[bool] = None,
    session: Annotated[CurrentSession, Depends(optional_session)] = None,
):
    """Sugestões para a caixa de pesquisa (nome, NIF, cargo mais recente)."""
    result = people_autocomplete(q, limit=limit, is_company=is_company)
    if result.get("error"):
        raise HTTPException(status_code=500, detail=result["error"])
    return PeopleAutocompleteResponse(**result)


@router.get("/filters", response_model=PeopleFiltersResponse)
def people_filters_route(session: Annotated[CurrentSession, Depends(optional_session)] = None):
    """Facetas disponíveis para os filtros (cargos, origens e tipos)."""
    result = people_filters()
    if result.get("error"):
        raise HTTPException(status_code=500, detail=result["error"])
    return PeopleFiltersResponse(**result)


# --- Empresas (pesquisa por empresa: empresa + pessoas + grafo) ---------------

@router.get("/companies", response_model=PeopleCompaniesResponse)
def people_companies_route(
    q: Optional[str] = Query(default=None, description="Firma/denominação, NIF/NIPC ou nome de quem lá tem cargos"),
    size: int = Query(default=20, ge=1, le=100),
    session: Annotated[CurrentSession, Depends(optional_session)] = None,
):
    """Empresas com pessoas/cargos registados (pesquisa por empresa).

    Procura contratos societários/CIRE das pessoas: uma empresa aparece aqui
    mesmo sem ficha própria, porque o vínculo é o cargo da pessoa nela.
    """
    result = companies_with_people(q=q, size=size)
    if result.get("error"):
        raise HTTPException(status_code=500, detail=result["error"])
    return PeopleCompaniesResponse(**result)


@router.get("/companies/{company_nif}", response_model=PeopleCompanyResponse)
def people_company_route(
    company_nif: str,
    size: int = Query(default=200, ge=1, le=500),
    session: Annotated[CurrentSession, Depends(optional_session)] = None,
):
    """Ficha de empresa: pessoas com cargos nessa empresa (mais recentes primeiro)."""
    result = company_people_from_index(company_nif, size=size)
    if result.get("error"):
        raise HTTPException(status_code=500, detail=result["error"])
    return PeopleCompanyResponse(**result)


# ---------------------------------------------------------------------------
# Enriquecimento político (perfis, notícias do partido, grafo de eventos)
# ---------------------------------------------------------------------------

class PoliticianEnrichRequest(BaseModel):
    """Pedido para gerar/reativar o enriquecimento político de uma pessoa."""

    backend: Optional[str] = Field(default=None, description="Modelo a usar (ex.: openai:gpt-4o-mini).")
    save: bool = Field(default=True, description="Guardar o resultado em finance_node_summaries.")
    reuse_hours: float = Field(default=0.0, ge=0, le=720, description="Reaproveitar resultado recente.")
    limit_party_news: int = Field(default=12, ge=1, le=30)
    max_co_party: int = Field(default=20, ge=0, le=50)


class PoliticianProfileResponse(BaseModel):
    """Perfil técnico + biográfico de um político."""

    nif: str
    name: Optional[str] = None
    party: Optional[str] = None
    technical_profile: Dict[str, Any] = Field(default_factory=dict)
    biographical_profile: Dict[str, Any] = Field(default_factory=dict)
    party_news: Dict[str, Any] = Field(default_factory=dict)
    political_graph: Dict[str, Any] = Field(default_factory=dict)
    generated_at: Optional[str] = None
    cached: bool = False
    saved: Optional[bool] = None
    evidence_count: int = 0
    error: Optional[str] = None


@router.post("/{nif}/politician/enrich", response_model=PoliticianProfileResponse)
async def politician_enrich_route(
    nif: str,
    payload: PoliticianEnrichRequest,
    session: Annotated[CurrentSession, Depends(optional_session)] = None,
):
    """Gera/reativa o enriquecimento político: perfis, notícias do partido e grafo."""
    result = await enrich_politician(
        nif,
        session=session,
        backend=payload.backend,
        save=payload.save,
        reuse_hours=payload.reuse_hours,
        limit_party_news=payload.limit_party_news,
        max_co_party=payload.max_co_party,
    )
    if result.get("error"):
        raise HTTPException(status_code=404, detail=result["error"])
    return PoliticianProfileResponse(**result)


@router.get("/{nif}/politician/profile", response_model=PoliticianProfileResponse)
async def politician_profile_route(
    nif: str,
    backend: Optional[str] = None,
    reuse_hours: float = Query(default=24.0, ge=0, le=720),
    session: Annotated[CurrentSession, Depends(optional_session)] = None,
):
    """Devolve perfil técnico e biográfico de um político (reaproveita resultado recente por defeito)."""
    result = await enrich_politician(
        nif,
        session=session,
        backend=backend,
        save=True,
        reuse_hours=reuse_hours,
    )
    if result.get("error"):
        raise HTTPException(status_code=404, detail=result["error"])
    return PoliticianProfileResponse(**result)


@router.get("/{nif}/politician/party-news", response_model=Dict[str, Any])
async def politician_party_news_route(
    nif: str,
    limit: int = Query(default=12, ge=1, le=30),
    session: Annotated[CurrentSession, Depends(optional_session)] = None,
):
    """Notícias e artigos sobre o partido do político."""
    person = get_person_by_nif(nif)
    if person.get("error") or not person.get("name"):
        raise HTTPException(status_code=404, detail=person.get("error") or f"Pessoa {nif} não encontrada.")
    party = _person_party(person)
    if not party:
        return {"party": None, "total": 0, "items": [], "warnings": ["Político sem partido indexado."]}
    result = await party_news(party, person_name=person.get("name"), limit=limit)
    return result


@router.get("/{nif}/politician/graph", response_model=PeopleGraphResponse)
async def politician_graph_route(
    nif: str,
    max_co_party: int = Query(default=20, ge=0, le=50),
    limit_party_news: int = Query(default=12, ge=0, le=30),
    session: Annotated[CurrentSession, Depends(optional_session)] = None,
):
    """Grafo de relações políticas: partido, cargos, colegas e eventos/notícias."""
    person = get_person_by_nif(nif)
    if person.get("error") or not person.get("name"):
        raise HTTPException(status_code=404, detail=person.get("error") or f"Pessoa {nif} não encontrada.")
    party = _person_party(person)
    co_party = _co_party_people(party or "", nif, size=max_co_party) if party else []
    news = await party_news(party, person_name=person.get("name"), limit=limit_party_news) if party else {"items": []}
    graph = build_political_graph(person, party, co_party, news.get("items") or [])
    return PeopleGraphResponse(**graph)


# ---------------------------------------------------------------------------
# Detalhe de uma pessoa
# ---------------------------------------------------------------------------

@router.get("/{nif}", response_model=Person)
def people_detail_route(
    nif: str,
    session: Annotated[CurrentSession, Depends(optional_session)] = None,
):
    person = get_person_by_nif(nif)
    if person.get("error"):
        raise HTTPException(status_code=404, detail=person["error"])
    return Person(**person)


@router.get("/{nif}/graph", response_model=PeopleGraphResponse)
def people_person_graph_route(
    nif: str,
    session: Annotated[CurrentSession, Depends(optional_session)] = None,
):
    result = people_graph_for_person(nif)
    if result.get("error"):
        raise HTTPException(status_code=500, detail=result["error"])
    return PeopleGraphResponse(**result)


@router.get("/company/{company_nif}/graph", response_model=PeopleGraphResponse)
def people_company_graph_route(
    company_nif: str,
    session: Annotated[CurrentSession, Depends(optional_session)] = None,
):
    result = people_graph_for_company(company_nif)
    if result.get("error"):
        raise HTTPException(status_code=500, detail=result["error"])
    return PeopleGraphResponse(**result)


@router.get("/company/{company_nif}/graph/full", response_model=PeopleGraphResponse)
def people_company_graph_full_route(
    company_nif: str,
    include_people: bool = True,
    include_contracts: bool = True,
    contract_limit: int = Query(default=60, ge=1, le=300),
    session: Annotated[CurrentSession, Depends(optional_session)] = None,
):
    """Grafo combinado: pessoas/cargos + contratos públicos + entidades."""
    result = combined_graph_for_company(
        company_nif,
        include_people=include_people,
        include_contracts=include_contracts,
        contract_limit=contract_limit,
    )
    if result.get("error"):
        raise HTTPException(status_code=500, detail=result["error"])
    return PeopleGraphResponse(**result)
