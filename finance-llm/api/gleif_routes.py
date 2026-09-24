"""Rotas do módulo GLEIF / LEI (`/gleif/*`).

Um índice (`finance_gleif_lei`) com os registos LEI do *Golden Copy* do GLEIF e
uma **golden copy local** em `data/gleif/lei.jsonl`.

Leitura (pública)
- `GET  /gleif/meta`          — metadados (índice, ficheiro, origens, facetas)
- `GET  /gleif/status`        — volumetria, distribuições e série temporal
- `GET  /gleif/suggest`       — sugestões para a caixa de pesquisa
- `GET  /gleif/search`        — pesquisar registos LEI (nome/LEI/NIF + filtros)
- `GET  /gleif/map`           — agregado por país/região (mapa OSM)
- `GET  /gleif/export.csv`    — exportar a golden copy local em CSV
- `GET  /gleif/jobs`          — ingestões em curso e recentes
- `GET  /gleif/jobs/{id}`     — estado de uma ingestão
- `GET  /gleif/records/{lei}`  — ficha de um registo LEI

Escrita (sessão)
- `POST   /gleif/ingest`      — recolher/indexar (API, ficheiro golden copy ou local)
- `DELETE /gleif/index`       — esvaziar o índice
"""
from __future__ import annotations

import logging
from typing import Annotated, Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from pydantic import BaseModel, Field

from api import gleif_service as service
from api.auth_routes import CurrentSession, require_session

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/gleif", tags=["gleif"])

Session = Annotated[CurrentSession, Depends(require_session)]


# ------------------------------------------------------------------ modelos
class IngestRequest(BaseModel):
    """Pedido de recolha/indexação de registos LEI."""

    source: str = Field(
        "api",
        description=(
            "Origem dos dados: `api` (API oficial do GLEIF, por país), "
            "`file` (golden copy local em data/gleif/lei.jsonl), "
            "`golden-copy` (ficheiro local ZIP/CSV/XML/JSON), "
            "`golden-copy-download` (descarregar o Golden Copy do leidata.gleif.org)."
        ),
    )
    countries: Optional[List[str]] = Field(
        None, description="Códigos ISO 3166-1 (ex.: [«PT»]). Em falta, o país por omissão do módulo."
    )
    path: Optional[str] = Field(None, description="Ficheiro Golden Copy (nome em data/gleif/golden-copy ou caminho absoluto).")
    limit: Optional[int] = Field(None, ge=1, description="Máximo de registos a recolher (amostra; útil para testes).")
    replace: bool = Field(True, description="Substituir os registos dos países indicados em vez de acrescentar.")
    download: bool = Field(False, description="Forçar novo descarregamento do ficheiro Golden Copy.")
    wait: bool = Field(False, description="Esperar pelo fim e devolver o resumo (senão devolve um `job_id`).")


# ------------------------------------------------------------------ leitura
@router.get("/meta")
def gleif_meta() -> Dict[str, Any]:
    """Metadados do módulo GLEIF / LEI."""
    return service.meta()


@router.get("/status")
def gleif_status() -> Dict[str, Any]:
    """Estado do índice e da golden copy local (volumetria e distribuições)."""
    return service.status()


@router.get("/suggest")
def gleif_suggest(
    q: str = Query("", description="Prefixo/pesquisa parcial do nome da entidade ou LEI"),
    size: int = Query(8, ge=1, le=50),
) -> Dict[str, Any]:
    """Sugestões para a caixa de pesquisa (nome, LEI, país e cidade)."""
    return service.autocomplete(q, size=size)


@router.get("/search")
def gleif_search(
    q: Optional[str] = Query(None, description="Nome legal, LEI, NIF de registo, BIC ou cidade"),
    country: Optional[str] = Query(None, description="País da sede legal (ISO 3166-1 alfa-2)"),
    region: Optional[str] = Query(None, description="Região/distrito (ex.: «PT-13»)"),
    status: Optional[str] = Query(None, description="Estado da entidade (ACTIVE, INACTIVE, …)"),
    category: Optional[str] = Query(None, description="Categoria (GENERAL, BRANCH, FUND, …)"),
    legal_form: Optional[str] = Query(None, description="Código da forma jurídica (ISO 20275)"),
    verification: Optional[str] = Query(None, description="Nível de corroboração do registo"),
    lou: Optional[str] = Query(None, description="LEI do LOU que emitiu o registo"),
    city: Optional[str] = Query(None, description="Cidade da sede legal"),
    sort: str = Query("relevance", description="Ordenação: `relevance`, `name`, `updated` ou `registered`"),
    size: int = Query(20, ge=1, le=200),
    from_: int = Query(0, ge=0, alias="from"),
) -> Dict[str, Any]:
    """Pesquisa registos LEI com filtros e facetas."""
    result = service.search(
        q,
        size=size,
        from_=from_,
        sort=sort,
        country=country,
        region=region,
        status=status,
        category=category,
        legal_form=legal_form,
        verification=verification,
        lou=lou,
        city=city,
    )
    if result.get("error"):
        raise HTTPException(status_code=502, detail=result["error"])
    return result


@router.get("/map")
def gleif_map(
    level: str = Query("country", description="Divisão do agregado: `country` ou `region`"),
    metric: str = Query("count", description="Métrica (por agora sempre `count`)"),
    country: Optional[str] = Query(None, description="Restringir a um país"),
    region: Optional[str] = Query(None, description="Restringir a uma região"),
    status: Optional[str] = Query(None),
    category: Optional[str] = Query(None),
    size: int = Query(400, ge=1, le=1000),
) -> Dict[str, Any]:
    """Agregado dos registos por país/região (base do mapa OpenStreetMap)."""
    result = service.map_data(
        level=level if level in {"country", "region"} else "country",
        metric=metric,
        country=country,
        region=region,
        status=status,
        category=category,
        size=size,
    )
    if result.get("error"):
        raise HTTPException(status_code=502, detail=result["error"])
    return result


@router.get("/export.csv")
def gleif_export_csv(limit: int = Query(5000, ge=1, le=200000)) -> Response:
    """Exporta a golden copy local em CSV."""
    payload = service.export_csv(limit=limit)
    return Response(
        content=payload,
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": 'attachment; filename="gleif-lei.csv"'},
    )


@router.get("/jobs")
def gleif_jobs() -> Dict[str, Any]:
    """Ingestões em curso e recentes."""
    return {"jobs": service.jobs()}


@router.get("/jobs/{job_id}")
def gleif_job(job_id: str) -> Dict[str, Any]:
    """Estado de uma ingestão."""
    found = service.job(job_id)
    if not found:
        raise HTTPException(status_code=404, detail="Tarefa não encontrada")
    return found


@router.get("/records/{lei}")
def gleif_detail(lei: str) -> Dict[str, Any]:
    """Ficha de um registo LEI (20 caracteres alfanuméricos).

    A ficha fica sob `/gleif/records/` (e não `/gleif/<lei>`) para não competir
    com as páginas da SPA (`/gleif/mapa`) — mesmo padrão de `/contracts-es/entities`.
    """
    found = service.detail(lei)
    if not found:
        raise HTTPException(status_code=404, detail="LEI não encontrado")
    return found


# ------------------------------------------------------------------ escrita
@router.post("/ingest")
def gleif_ingest(req: IngestRequest, _session: Session) -> Dict[str, Any]:
    """Recolhe registos LEI e guarda-os na golden copy local e no índice."""
    result = service.ingest(
        source=req.source,
        countries=req.countries,
        path=req.path,
        limit=req.limit,
        replace=req.replace,
        download=req.download,
        wait=req.wait,
    )
    if result.get("status") == "error":
        raise HTTPException(status_code=502, detail=result.get("error") or "Falha na ingestão")
    return result


@router.delete("/index")
def gleif_delete_index(_session: Session) -> Dict[str, Any]:
    """Esvazia o índice de registos LEI."""
    result = service.delete_index()
    if result.get("error"):
        raise HTTPException(status_code=502, detail=result["error"])
    return result
