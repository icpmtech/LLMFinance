"""Rotas FastAPI para o módulo Pessoas e Cargos do IQ OS.

Exposições principais:
- GET /people/status
- POST /people/ingest/{nif}  (re)gerar pessoas/cargos para uma empresa
- GET /people/search
- GET /people/{nif}
- GET /people/{nif}/graph
- GET /people/company/{company_nif}/graph
"""
from __future__ import annotations

from typing import Annotated, Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from api.auth_routes import CurrentSession, optional_session, require_session
from api.elasticsearch_client import (
    combined_graph_for_company,
    get_es_client,
    get_person_by_nif,
    index_people_from_societario,
    people_graph_for_company,
    people_graph_for_person,
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
    error: Optional[str] = None


@router.get("/status", response_model=PeopleStatusResponse)
async def people_status_route(session: Annotated[CurrentSession, Depends(optional_session)]):
    return people_status()


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
