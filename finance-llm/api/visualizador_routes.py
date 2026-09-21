"""Rotas do **Visualizador** (`/visualizador/*`) — BI sobre os dados da plataforma.

Endpoints:

* `GET  /visualizador/meta` — catálogo de datasets, tipos de gráfico e limites;
* `GET  /visualizador/datasets/{id}` — dimensões, medidas e filtros de um dataset;
* `POST /visualizador/query` — consulta analítica (dimensões × medidas × fórmulas);
* `POST /visualizador/records` — regiões individuais (drill-through e tabela);
* `POST /visualizador/values` — valores distintos de uma dimensão (filtros);
* `POST /visualizador/export/csv` · `/xlsx` — exportação do resultado;
* `GET/POST/DELETE /visualizador/dashboards…` — dashboards privados do utilizador.

As leituras de dados públicos são abertas (como `/search` e `/contracts`); os
datasets marcados como privados (CRM, Email) e a escrita exigem sessão.
"""
from __future__ import annotations

import logging
from typing import Annotated, Any, Dict, List, Optional

from fastapi import APIRouter, Body, Depends, HTTPException, Query, Response
from pydantic import BaseModel, Field

from api import visualizador_service as service
from api import visualizador_store as store
from api import visualizador_templates as templates
from api.auth_routes import CurrentSession, optional_session, require_session

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/visualizador", tags=["visualizador"])

Session = Annotated[Optional[CurrentSession], Depends(optional_session)]
Writer = Annotated[CurrentSession, Depends(require_session)]


# ---------------------------------------------------------------------------
# Modelos
# ---------------------------------------------------------------------------
class VisualQueryRequest(BaseModel):
    dataset: str = Field(..., description="Id do dataset (ex.: `contrato`, `noticia`, `marca`).")
    dimensions: List[Any] = Field(default_factory=list, description="Até 3 dimensões: `\"ano\"` ou `{\"id\": \"data\", \"interval\": \"mes\"}`.")
    measures: List[Any] = Field(default_factory=list, description="Medidas do catálogo ou `{\"kind\": \"soma\", \"field\": \"preco\"}`.")
    formulas: List[Any] = Field(default_factory=list, description="Medidas calculadas: `{\"id\", \"label\", \"expression\": \"[Valor] / [Contagem]\"}`.")
    filters: Dict[str, Any] = Field(default_factory=dict, description="Filtros por dimensão (escalar, lista ou `{min, max}`).")
    search: Optional[str] = Field(None, description="Pesquisa livre no texto do dataset.")
    sort: Optional[Any] = Field(None, description="`{\"by\": \"valor\", \"order\": \"desc\"}` ou o id da medida.")
    limit: int = Field(25, ge=1, le=1000, description="Grupos a devolver por dimensão (top-N do Elasticsearch).")
    inner_limit: Optional[int] = Field(None, ge=1, le=200, description="Grupos por dimensão interior.")
    top_n: Optional[int] = Field(None, ge=0, le=1000, description="Mostrar apenas os N primeiros grupos.")
    others: bool = Field(False, description="Agregar o resto num grupo «Outros» (só medidas aditivas).")
    missing_label: Optional[str] = Field("Não especificado", description="Rótulo do grupo sem valor (null desativa).")
    model_config = {"populate_by_name": True}


class RecordsRequest(BaseModel):
    dataset: str
    filters: Dict[str, Any] = Field(default_factory=dict)
    search: Optional[str] = None
    sort: Optional[Any] = None
    size: int = Field(25, ge=1, le=200)
    from_: int = Field(0, ge=0, alias="from")
    model_config = {"populate_by_name": True}


class ValuesRequest(BaseModel):
    dataset: str
    field: str
    q: Optional[str] = None
    filters: Dict[str, Any] = Field(default_factory=dict)
    search: Optional[str] = None
    limit: int = Field(50, ge=1, le=200)


class DashboardPayload(BaseModel):
    id: Optional[str] = None
    name: str
    description: Optional[str] = None
    dataset: Optional[str] = None
    filters: Dict[str, Any] = Field(default_factory=dict)
    visuals: List[Any] = Field(default_factory=list)
    layout: Optional[Dict[str, Any]] = None
    theme: Optional[str] = None
    tags: List[str] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Ajudantes
# ---------------------------------------------------------------------------
def _scope(session: Optional[CurrentSession]) -> Optional[Dict[str, Any]]:
    """Âmbito de visibilidade dos dados privados (o mesmo do resto da API)."""
    if not session:
        return None
    return {
        "user_id": session.user.id,
        "email": session.user.email,
        "see_all": (session.user.role or "member") == "admin",
    }


def _query_payload(request: VisualQueryRequest) -> Dict[str, Any]:
    return request.model_dump(by_alias=True)


# ---------------------------------------------------------------------------
# Catálogo
# ---------------------------------------------------------------------------
@router.get("/meta")
def visualizador_meta(session: Session = None) -> Dict[str, Any]:
    """Catálogo de datasets, tipos de gráfico, operadores e limites."""
    return service.catalog(_scope(session))


@router.get("/datasets/{dataset_id}")
def visualizador_dataset(dataset_id: str, session: Session = None) -> Dict[str, Any]:
    """Dimensões, medidas, filtros e sugestões de um dataset."""
    try:
        dataset = service.get_dataset(dataset_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    summary = service._dataset_summary(dataset, _scope(session))  # noqa: SLF001 (resumo interno reutilizado)
    return {
        "dataset": summary,
        "dimensions": dataset.get("dimensions") or [],
        "measures": dataset.get("measures") or [],
        "filters": dataset.get("filters") or [],
        "defaults": dataset.get("defaults") or {},
        "suggestions": dataset.get("suggestions") or [],
        "count_field": dataset.get("count_field"),
        "source": dataset.get("source"),
    }


# ---------------------------------------------------------------------------
# Consulta
# ---------------------------------------------------------------------------
@router.post("/query")
def visualizador_query(request: VisualQueryRequest, session: Session = None) -> Dict[str, Any]:
    """Consulta analítica: dimensões × medidas (+ fórmulas), pronta a desenhar."""
    result = service.run_query(_query_payload(request), scope=_scope(session))
    if result.get("error") and not result.get("rows"):
        # Erros de autorização/limites não são 500: devolvem-se como aviso.
        return result
    return result


@router.post("/records")
def visualizador_records(request: RecordsRequest, session: Session = None) -> Dict[str, Any]:
    """Registos individuais (drill-through dos visuais)."""
    return service.run_records(request.model_dump(by_alias=True), scope=_scope(session))


@router.post("/values")
def visualizador_values(request: ValuesRequest, session: Session = None) -> Dict[str, Any]:
    """Valores distintos de uma dimensão (para os seletores de filtros)."""
    return service.distinct_values(request.model_dump(), scope=_scope(session))


# ---------------------------------------------------------------------------
# Exportação
# ---------------------------------------------------------------------------
def _export(request: VisualQueryRequest, session: Optional[CurrentSession], fmt: str) -> Response:
    result = service.run_query(_query_payload(request), scope=_scope(session))
    if result.get("error") and not result.get("rows"):
        raise HTTPException(status_code=400, detail=str(result.get("error")))
    label = (result.get("dataset") or {}).get("label") or request.dataset
    try:
        if fmt == "csv":
            filename, content, media = service.export_csv(result, label)
        else:
            filename, content, media = service.export_xlsx(result, label)
    except RuntimeError as exc:
        raise HTTPException(status_code=501, detail=str(exc)) from exc
    return Response(
        content=content,
        media_type=media,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.post("/export/csv")
def visualizador_export_csv(request: VisualQueryRequest, session: Session = None) -> Response:
    """Exporta o resultado da consulta para CSV (separador `;`, pronto para Excel)."""
    return _export(request, session, "csv")


@router.post("/export/xlsx")
def visualizador_export_xlsx(request: VisualQueryRequest, session: Session = None) -> Response:
    """Exporta o resultado da consulta para Excel, com folha de definição."""
    return _export(request, session, "xlsx")


# ---------------------------------------------------------------------------
# Templates
# ---------------------------------------------------------------------------
@router.get("/templates")
def list_templates(session: Session = None) -> Dict[str, Any]:
    """Dashboards-modelo prontos a usar, validados contra o catálogo atual."""
    return templates.resolve_templates(_scope(session))


@router.post("/templates/{template_id}/dashboard")
def create_from_template(template_id: str, session: Writer,
                         name: Optional[str] = Body(None, embed=True)) -> Dict[str, Any]:
    """Cria um dashboard do utilizador a partir de um template."""
    try:
        templates.get_template(template_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    scope = _scope(session)
    listing = templates.resolve_templates(scope)
    resolved = next((item for item in listing["items"] if item["id"] == template_id), None)
    if not resolved:
        raise HTTPException(status_code=400, detail="Template indisponível: usa campos que já não existem no catálogo.")
    saved = store.save_dashboard(templates.as_dashboard(resolved, name=name), scope["user_id"], owner_email=scope.get("email"))
    return {"dashboard": saved, "warnings": resolved.get("warnings") or []}


# ---------------------------------------------------------------------------
# Dashboards
# ---------------------------------------------------------------------------
@router.get("/dashboards")
def list_dashboards(session: Session = None) -> Dict[str, Any]:
    """Dashboards do utilizador (administradores veem também os da equipa)."""
    scope = _scope(session)
    if not scope:
        return {"total": 0, "items": [], "shared": 0,
                "note": "Inicie sessão para guardar e reutilizar dashboards.", "stats": None}
    return {
        **store.list_dashboards(scope["user_id"], see_all=bool(scope.get("see_all"))),
        "stats": store.stats(scope["user_id"], see_all=bool(scope.get("see_all"))),
        "note": None,
    }


@router.get("/dashboards/{dashboard_id}")
def get_dashboard(dashboard_id: str, session: Session = None) -> Dict[str, Any]:
    scope = _scope(session)
    if not scope:
        raise HTTPException(status_code=401, detail="Inicie sessão para abrir dashboards guardados.")
    try:
        return store.get_dashboard(dashboard_id, scope["user_id"], see_all=bool(scope.get("see_all")))
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc


@router.post("/dashboards")
def save_dashboard(payload: DashboardPayload, session: Writer) -> Dict[str, Any]:
    """Cria ou atualiza um dashboard (por id) do utilizador autenticado."""
    scope = _scope(session)
    try:
        return store.save_dashboard(payload.model_dump(), scope["user_id"], owner_email=scope.get("email"))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc


@router.post("/dashboards/{dashboard_id}/duplicate")
def duplicate_dashboard(dashboard_id: str, session: Writer, name: Optional[str] = Body(None, embed=True)) -> Dict[str, Any]:
    scope = _scope(session)
    try:
        return store.duplicate_dashboard(dashboard_id, scope["user_id"], owner_email=scope.get("email"), name=name)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc


@router.delete("/dashboards/{dashboard_id}")
def delete_dashboard(dashboard_id: str, session: Writer) -> Dict[str, Any]:
    scope = _scope(session)
    try:
        return store.delete_dashboard(dashboard_id, scope["user_id"])
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc


@router.get("/export/dashboards")
def export_dashboards(session: Session = None, ids: Optional[str] = Query(None, description="Ids separados por vírgula.")) -> Dict[str, Any]:
    """Exporta definições de dashboards (portáteis, sem dados pessoais)."""
    scope = _scope(session)
    if not scope:
        raise HTTPException(status_code=401, detail="Inicie sessão para exportar dashboards.")
    listing = store.list_dashboards(scope["user_id"], see_all=bool(scope.get("see_all")))
    wanted = {item.strip() for item in (ids or "").split(",") if item.strip()}
    payloads = []
    for item in listing["items"]:
        if wanted and item["id"] not in wanted:
            continue
        try:
            payloads.append(store.get_dashboard(item["id"], scope["user_id"], see_all=bool(scope.get("see_all"))))
        except (KeyError, PermissionError):
            continue
    return {"total": len(payloads), "dashboards": store.export_payloads(payloads)}
