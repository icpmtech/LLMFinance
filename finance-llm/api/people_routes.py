"""Rotas FastAPI para o módulo Pessoas e Cargos do IQ OS.

Exposições principais:
- GET /people/status
- POST /people/ingest/{nif}  (re)gerar pessoas/cargos para uma empresa
- POST /people/ingest-cire  indexar as pessoas que constam dos processos do CIRE
- GET /people/ingest-cire/jobs[/{job_id}]  progresso da ingestão do CIRE
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

from api.auth_routes import CurrentSession, optional_session, require_session
from api.elasticsearch_client import (
    combined_graph_for_company,
    get_es_client,
    get_person_by_nif,
    index_people_from_cire,
    index_people_from_societario,
    people_graph_for_company,
    people_graph_for_person,
    people_index_presence,
    people_status,
    search_people,
)

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


class PeopleSearchResponse(BaseModel):
    total: int
    items: List[Person]
    from_: int = Field(alias="from")
    size: int

    class Config:
        populate_by_name = True


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
    error: Optional[str] = None


class PeopleStatusResponse(BaseModel):
    index: str
    documents: int
    is_company: List[Dict[str, Any]] = Field(default_factory=list)
    total_company_links: int = 0
    top_roles: List[Dict[str, Any]] = Field(default_factory=list)
    by_source: List[Dict[str, Any]] = Field(default_factory=list)
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


class PeoplePresenceRequest(BaseModel):
    """NIF/NIPC a validar no índice de pessoas."""

    nifs: List[str] = Field(default_factory=list)


class PeoplePresenceResponse(BaseModel):
    total: int = 0
    indexed: List[str] = Field(default_factory=list)
    missing: List[str] = Field(default_factory=list)
    error: Optional[str] = None


@router.get("/status", response_model=PeopleStatusResponse)
async def people_status_route(session: Annotated[CurrentSession, Depends(optional_session)]):
    return people_status()


@router.post("/exists", response_model=PeoplePresenceResponse)
async def people_exists_route(
    payload: PeoplePresenceRequest,
    session: Annotated[CurrentSession, Depends(optional_session)] = None,
):
    """Diz quais dos NIF indicados já têm ficha no PessoasIQ (e quais faltam)."""
    return PeoplePresenceResponse(**people_index_presence(payload.nifs))


@router.post("/ingest/{nif}", response_model=PeopleIngestResponse)
async def people_ingest_route(
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
        _run_cire_ingest(job, payload)
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


@router.get("/search", response_model=PeopleSearchResponse)
async def people_search_route(
    q: Optional[str] = None,
    nif: Optional[str] = None,
    company_nif: Optional[str] = None,
    role: Optional[str] = None,
    is_company: Optional[bool] = None,
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
        size=size,
        from_=from_,
    )
    if result.get("error"):
        raise HTTPException(status_code=500, detail=result["error"])
    return PeopleSearchResponse(**result)


@router.get("/{nif}", response_model=Person)
async def people_detail_route(
    nif: str,
    session: Annotated[CurrentSession, Depends(optional_session)] = None,
):
    person = get_person_by_nif(nif)
    if person.get("error"):
        raise HTTPException(status_code=404, detail=person["error"])
    return Person(**person)


@router.get("/{nif}/graph", response_model=PeopleGraphResponse)
async def people_person_graph_route(
    nif: str,
    session: Annotated[CurrentSession, Depends(optional_session)] = None,
):
    result = people_graph_for_person(nif)
    if result.get("error"):
        raise HTTPException(status_code=500, detail=result["error"])
    return PeopleGraphResponse(**result)


@router.get("/company/{company_nif}/graph", response_model=PeopleGraphResponse)
async def people_company_graph_route(
    company_nif: str,
    session: Annotated[CurrentSession, Depends(optional_session)] = None,
):
    result = people_graph_for_company(company_nif)
    if result.get("error"):
        raise HTTPException(status_code=500, detail=result["error"])
    return PeopleGraphResponse(**result)


@router.get("/company/{company_nif}/graph/full", response_model=PeopleGraphResponse)
async def people_company_graph_full_route(
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
