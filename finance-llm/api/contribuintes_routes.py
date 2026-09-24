"""Rotas do módulo Contribuintes (`/contribuintes/*`).

Um só índice (`finance_contribuintes`) com **todos os contribuintes do sistema**:
um documento por NIF/NIPC, agregado dos contratos públicos (PT e ES), cadastro
de entidades, publicações societárias, CIRE, PessoasIQ, firmas, marcas e CRM.

Leitura (pública)
- `GET  /contribuintes/meta`          — metadados (fontes percorridas, tipos, agenda)
- `GET  /contribuintes/status`        — volumetria, distribuições e histórico de sincronizações
- `GET  /contribuintes/schedule`      — agendamento cron (estado e próxima execução)
- `GET  /contribuintes/search`        — pesquisar contribuintes (nome/NIF + filtros)
- `GET  /contribuintes/autocomplete`  — sugestões para caixas de pesquisa
- `GET  /contribuintes/jobs`          — sincronizações em curso e recentes
- `GET  /contribuintes/jobs/{job_id}` — estado de uma sincronização
- `GET  /contribuintes/{nif}`         — ficha do contribuinte (evidência por fonte)

Escrita (sessão)
- `POST   /contribuintes/sync`        — sincronizar (total ou só algumas fontes)
- `PUT    /contribuintes/schedule`    — definir o cron da sincronização automática
- `DELETE /contribuintes/index`       — esvaziar o índice (obriga a nova sincronização)
"""
from __future__ import annotations

import logging
from typing import Annotated, Any, Dict, List, Optional

from fastapi import APIRouter, Body, Depends, HTTPException, Query, Response
from pydantic import BaseModel, Field

from api import contribuintes_report as report
from api import contribuintes_service as service
from api.auth_routes import CurrentSession, require_session

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/contribuintes", tags=["contribuintes"])

Session = Annotated[CurrentSession, Depends(require_session)]


# ------------------------------------------------------------------ modelos
class SyncRequest(BaseModel):
    """Pedido de sincronização do índice de contribuintes."""

    sources: Optional[List[str]] = Field(
        None,
        description=(
            "Fontes a percorrer (ids de `/contribuintes/meta`). Em falta, todas — e nesse caso "
            "o índice é substituído por completo (os contribuintes que já não apareçam são apagados)."
        ),
    )
    page_size: Optional[int] = Field(
        None, ge=100, le=5000, description="Valores distintos por página de agregação (omissão: da configuração)."
    )
    wait: bool = Field(
        False,
        description=(
            "Esperar pelo fim da sincronização e devolver o resumo. Por omissão corre em segundo "
            "plano e devolve um `job_id` (acompanhar em `/contribuintes/jobs/{id}`)."
        ),
    )


class ScheduleRequest(BaseModel):
    """Configuração da sincronização automática (cron de 5 campos)."""

    enabled: Optional[bool] = Field(None, description="Ligar/desligar a sincronização automática")
    cron: Optional[str] = Field(None, description="Expressão cron: minuto hora dia mês dia-semana (ex.: «0 3 * * *»)")
    timezone: Optional[str] = Field(None, description="Fuso horário da expressão (ex.: «Europe/Lisbon»)")
    sources: Optional[List[str]] = Field(None, description="Fontes a percorrer na sincronização automática")
    page_size: Optional[int] = Field(None, ge=100, le=5000, description="Valores distintos por página de agregação")


# ------------------------------------------------------------------ leitura
@router.get("/meta")
def contribuintes_meta() -> Dict[str, Any]:
    """Metadados do módulo: índice, fontes percorridas, tipos, agendamento e relatórios."""
    payload = service.meta()
    payload["reports"] = report.available()
    return payload


@router.get("/status")
def contribuintes_status() -> Dict[str, Any]:
    """Volumetria do índice de contribuintes, distribuições e últimas sincronizações."""
    return service.status()


@router.get("/schedule")
def contribuintes_schedule() -> Dict[str, Any]:
    """Agendamento cron da sincronização (estado, próxima execução e histórico)."""
    return service.schedule()


@router.get("/search")
def contribuintes_search(
    q: Optional[str] = Query(None, description="Designação, NIF/NIPC ou papel a procurar"),
    source: Optional[str] = Query(None, description="Fonte (contratos, cire, entidades, societario, marcas, firmas, pessoas, crm, contratos_es)"),
    role: Optional[str] = Query(None, description="Papel: adjudicante, adjudicatario, insolvente, credor, gerente, titular_marca, …"),
    type: Optional[str] = Query(None, description="Tipo: empresa, pessoa, empresario, entidade_publica, estrangeiro, outro"),
    country: Optional[str] = Query(None, description="País (Portugal, Espanha, …)"),
    is_company: Optional[bool] = Query(None, description="Só pessoas coletivas (ou o contrário)"),
    has_contracts: Optional[bool] = Query(None, description="Só contribuintes com (ou sem) contratos públicos"),
    sort: str = Query("relevance", description="Ordenação: relevance, activity, contracts, value, name, nif"),
    page: int = Query(1, ge=1, description="Página (1 = primeira)"),
    size: int = Query(20, ge=1, le=200, description="Resultados por página"),
) -> Dict[str, Any]:
    """Pesquisa contribuintes no índice agregado de todo o sistema."""
    result = service.search(
        q,
        source=source,
        role=role,
        type_=type,
        country=country,
        is_company=is_company,
        has_contracts=has_contracts,
        sort=sort,
        size=size,
        from_=(page - 1) * size,
    )
    if result.get("error"):
        raise HTTPException(status_code=503, detail=result["error"])
    result["page"] = page
    return result


@router.get("/autocomplete")
def contribuintes_autocomplete(
    q: str = Query("", description="Início do nome ou NIF"),
    size: int = Query(10, ge=1, le=25),
) -> Dict[str, Any]:
    """Sugestões de contribuintes (nome/NIF) para autocompletar."""
    return {"items": service.autocomplete(q, size=size)}


@router.get("/jobs")
def contribuintes_jobs() -> Dict[str, Any]:
    """Sincronizações em curso e recentes."""
    return {"jobs": service.jobs(), "running": service.sync_running()}


@router.get("/jobs/{job_id}")
def contribuintes_job(job_id: str) -> Dict[str, Any]:
    """Estado e progresso de uma sincronização."""
    job = service.job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Sincronização não encontrada.")
    return job


# ------------------------------------------------------------------ escrita
@router.post("/sync")
def contribuintes_sync(
    _session: Session,
    payload: Optional[SyncRequest] = Body(default=None),
) -> Dict[str, Any]:
    """Sincroniza o índice a partir das fontes indicadas (por omissão, todas)."""
    request = payload or SyncRequest()
    try:
        result = service.start_sync(
            request.sources,
            page_size=request.page_size,
            trigger="manual",
            background=not request.wait,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    if result.get("error"):
        raise HTTPException(status_code=409, detail=result["error"])
    return result


@router.put("/schedule")
def contribuintes_set_schedule(payload: ScheduleRequest, _session: Session) -> Dict[str, Any]:
    """Define a sincronização automática (cron) do índice de contribuintes."""
    try:
        return service.set_schedule(
            enabled=payload.enabled,
            cron=payload.cron,
            timezone_name=payload.timezone,
            sources=payload.sources,
            page_size=payload.page_size,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.delete("/index")
def contribuintes_delete_index(_session: Session) -> Dict[str, Any]:
    """Esvazia o índice de contribuintes (é reconstruído na próxima sincronização)."""
    result = service.delete_index_documents()
    if result.get("error"):
        raise HTTPException(status_code=503, detail=result["error"])
    return result


# --------------------------------------------------------------- relatórios
# Registadas **antes** de `/{nif}` para que `/contribuintes/export` não seja
# interpretado como um NIF.

LOGO_NOTE = "Com a marca do IQ OS"


def _download(filename: str, content: bytes, media_type: str) -> Response:
    """Devolve o relatório como transferência (nome do ficheiro em ASCII)."""
    return Response(
        content=content,
        media_type=media_type,
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "Cache-Control": "no-store",
        },
    )


def _filters_label(
    q: Optional[str],
    source: Optional[str],
    role: Optional[str],
    type_: Optional[str],
    country: Optional[str],
    is_company: Optional[bool],
    has_contracts: Optional[bool],
    sort: str,
) -> str:
    """Descrição legível dos filtros (vai no cabeçalho do relatório)."""
    parts: List[str] = []
    if q:
        parts.append(f"texto «{q}»")
    if source:
        parts.append(f"fonte: {source}")
    if role:
        parts.append(f"papel: {role}")
    if type_:
        parts.append(f"tipo: {type_}")
    if country:
        parts.append(f"país: {country}")
    if is_company is True:
        parts.append("só pessoas coletivas")
    if is_company is False:
        parts.append("só pessoas singulares")
    if has_contracts is True:
        parts.append("só com contratos")
    if has_contracts is False:
        parts.append("só sem contratos")
    if sort and sort != "relevance":
        parts.append(f"ordenação: {sort}")
    return " · ".join(parts)


@router.get("/export")
def export_contribuintes_list(
    format: str = Query("pdf", pattern="^(pdf|xlsx|csv)$", description="pdf, xlsx ou csv"),
    q: Optional[str] = Query(None, description="Designação, NIF/NIPC ou papel a procurar"),
    source: Optional[str] = None,
    role: Optional[str] = None,
    type: Optional[str] = None,
    country: Optional[str] = None,
    is_company: Optional[bool] = None,
    has_contracts: Optional[bool] = None,
    sort: str = Query("relevance", description="Ordenação da pesquisa"),
    limit: int = Query(1000, ge=1, le=5000, description="Máximo de contribuintes no relatório"),
) -> Response:
    """Relatório (PDF/Excel/CSV) dos contribuintes que correspondem à pesquisa.

    Usa os mesmos filtros de `/contribuintes/search`; o `sort` decide a ordem das
    linhas. O relatório leva a marca do IQ OS (logótipo no PDF e no Excel).
    """
    result = service.search(
        q,
        source=source,
        role=role,
        type_=type,
        country=country,
        is_company=is_company,
        has_contracts=has_contracts,
        sort=sort,
        size=limit,
        from_=0,
    )
    if result.get("error"):
        raise HTTPException(status_code=503, detail=result["error"])
    items = list(result.get("items") or [])
    if not items:
        raise HTTPException(status_code=404, detail="Não há contribuintes para exportar com estes filtros.")
    try:
        filename, content, media_type = report.list_report(
            items,
            total=int(result.get("total") or len(items)),
            format=format,
            filters_label=_filters_label(q, source, role, type, country, is_company, has_contracts, sort),
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return _download(filename, content, media_type)


@router.get("/export/{nif}")
def export_contribuinte(
    nif: str,
    format: str = Query("pdf", pattern="^(pdf|xlsx|csv)$", description="pdf, xlsx ou csv"),
) -> Response:
    """Ficha de um contribuinte em PDF, Excel ou CSV (com a marca do IQ OS)."""
    doc = service.detail(nif)
    error = doc.get("error")
    if error:
        message = str(error)
        if "inválido" in message:
            raise HTTPException(status_code=400, detail=message)
        if "não encontrado" in message:
            raise HTTPException(status_code=404, detail=message)
        raise HTTPException(status_code=503, detail=message)
    try:
        filename, content, media_type = report.contribuinte_report(doc, format=format)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return _download(filename, content, media_type)


# ------------------------------------------------------------------ ficha
@router.get("/{nif}")
def contribuintes_detail(nif: str) -> Dict[str, Any]:
    """Ficha de um contribuinte: identificação, totais por fonte e evidência."""
    result = service.detail(nif)
    error = result.get("error")
    if error:
        message = str(error)
        if "inválido" in message:
            raise HTTPException(status_code=400, detail=message)
        if "não encontrado" in message:
            raise HTTPException(status_code=404, detail=message)
        raise HTTPException(status_code=503, detail=message)
    return result
