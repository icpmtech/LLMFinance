"""Rotas do **Estúdio de relatórios** (`/reports/studio/*`).

Área de criação de relatórios, reservada a **administradores**, **gestores de
plataforma** e às contas da lista *Gestores de relatórios* (`settings.
report_managers`). Serve para o gestor da plataforma montar um relatório com os
dados das fontes (as mesmas do Visualizador), com gráficos, tabelas e grafos,
ajudar-se com a IA, gerar o PDF e publicá-lo — no **catálogo da plataforma** ou
na **loja** — com preço.

Endpoints:

* `GET  /reports/studio/me` — se a conta tem acesso e o que pode fazer;
* `GET  /reports/studio/state` — estado (fontes, modelos, PDF, IA, limites);
* `GET  /reports/studio/sources` — fontes, dimensões e medidas;
* `GET  /reports/studio/templates` — modelos prontos;
* `GET  /reports/studio/reports` — relatórios criados;
* `POST /reports/studio/reports` — cria (a partir de um modelo ou do zero);
* `GET/PUT/DELETE /reports/studio/reports/{id}` — ficha, gravação e remoção;
* `POST /reports/studio/reports/{id}/duplicate` — duplicar;
* `POST /reports/studio/query` — corre blocos de um rascunho (pré-visualização);
* `POST /reports/studio/reports/{id}/run` — corre o relatório gravado;
* `POST /reports/studio/reports/{id}/pdf` — gera e guarda o PDF;
* `GET  /reports/studio/reports/{id}/files/{file}` — descarrega um PDF;
* `DELETE /reports/studio/reports/{id}/files/{file}` — remove um PDF;
* `POST /reports/studio/reports/{id}/publish` · `/unpublish` — publica/retira;
* `POST /reports/studio/ai` · `/reports/studio/reports/{id}/ai` — ajuda da IA.

A publicação é feita por `reports_store` (catálogo) e `shop_store` (loja), com a
chave de entrega automática `estudio:<id>`: o cliente paga e recebe o PDF sem a
equipa ter de intervir.
"""
from __future__ import annotations

from typing import Annotated, Any, Dict, List, Optional

from fastapi import APIRouter, Body, Depends, HTTPException, Query
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from api import events_service as events
from api import reports_studio as studio
from api import reports_store as store
from api.auth_routes import CurrentSession, require_session

router = APIRouter(prefix="/reports/studio", tags=["reports"])


# --------------------------------------------------------------------- sessão
def _email(session: CurrentSession) -> str:
    return str(session.user.email or "").lower()


def _role(session: CurrentSession) -> str:
    return str(session.user.role or "member")


def require_studio(session: Annotated[CurrentSession, Depends(require_session)]) -> CurrentSession:
    """Administradores, gestores de plataforma e gestores de relatórios."""
    if not studio.can_studio(_email(session), _role(session)):
        raise HTTPException(
            status_code=403,
            detail=(
                "O estúdio de relatórios está reservado a administradores e gestores de relatórios. "
                "Peça a um administrador para o autorizar."
            ),
        )
    return session


StudioSession = Annotated[CurrentSession, Depends(require_studio)]


# -------------------------------------------------------------------- modelos
class BlockPayload(BaseModel):
    id: Optional[str] = None
    type: str = Field(..., description="heading | text | note | ai | kpi | chart | table | graph | empresa | web")
    title: str = ""
    text: Optional[str] = None
    prompt: Optional[str] = None
    source: Optional[str] = None
    dimensions: List[Any] = Field(default_factory=list)
    measures: List[Any] = Field(default_factory=list)
    filters: Any = Field(default_factory=dict)
    search: Optional[str] = None
    chart: Optional[str] = None
    limit: Optional[int] = None
    top_n: Optional[int] = None
    width: Optional[int] = None
    format: Optional[str] = None
    empresa: Optional[str] = Field(None, description="Bloco `empresa`: NIF ou nome (aceita `{{empresa}}`/`{{nif}}`)")
    query: Optional[str] = Field(None, description="Bloco `web`: pesquisa a fazer (aceita `{{nome}}`)")
    site: Optional[str] = None


class ReportPayload(BaseModel):
    id: Optional[str] = None
    title: Optional[str] = None
    subtitle: Optional[str] = None
    description: Optional[str] = None
    summary: Optional[str] = None
    template: Optional[str] = None
    tags: List[Any] = Field(default_factory=list)
    theme: Optional[str] = None
    targets_note: Optional[str] = None
    blocks: Optional[List[Any]] = None
    vars: Optional[Dict[str, Any]] = Field(None, description="Parâmetros do relatório (ex.: `empresa`)")


class RunPayload(BaseModel):
    report: Optional[Dict[str, Any]] = Field(None, description="Rascunho (blocos em `blocks`) ou `id` de um relatório gravado")
    blocks: Optional[List[Any]] = None
    block_ids: Optional[List[str]] = None


class PublishPayload(BaseModel):
    target: str = Field("site", description="site | loja | todos")
    price: Optional[float] = None
    list_price: Optional[float] = None
    delivery_days: Optional[int] = None
    max_targets: Optional[int] = None
    code: Optional[str] = None
    badge: Optional[str] = None
    note: Optional[str] = None
    short_description: Optional[str] = None
    description: Optional[str] = None
    tax_rate: Optional[float] = None
    attributes: Optional[List[Dict[str, Any]]] = None
    targets_note: Optional[str] = None


class AiPayload(BaseModel):
    mode: str = Field("sumario", description="sumario | texto | insights | blocos")
    report: Optional[str] = None
    block: Optional[str] = None
    source: Optional[str] = None
    prompt: Optional[str] = None
    title: Optional[str] = None
    blocks: Optional[List[Any]] = None
    backend: Optional[str] = None


def _scope(session: CurrentSession) -> Dict[str, Any]:
    return {
        "user_id": session.user.id,
        "email": session.user.email,
        "see_all": _role(session) == "admin",
    }


def _report_or_404(report_id: str) -> Dict[str, Any]:
    doc = studio.get_report(report_id)
    if doc is None:
        raise HTTPException(status_code=404, detail="Relatório não encontrado.")
    return doc


# ------------------------------------------------------------------ contexto
@router.get("/me")
def studio_me(session: StudioSession) -> Dict[str, Any]:
    """Confirma o acesso e resume o que esta conta pode fazer no estúdio."""
    return {
        "studio": True,
        "email": _email(session),
        "name": str(session.user.name or "") or _email(session),
        "role": _role(session),
        "manager": _email(session) in store.report_managers(),
        "channels": [{"id": target, "label": studio.TARGET_LABELS[target]} for target in studio.TARGETS],
        "reports": studio.list_reports(limit=1)["stats"],
    }


@router.get("/state")
def studio_state(session: StudioSession) -> Dict[str, Any]:
    """Estado do estúdio (fontes, modelos, limites, PDF e IA)."""
    return studio.state(_scope(session))


@router.get("/sources")
def studio_sources(session: StudioSession) -> Dict[str, Any]:
    """Fontes de dados: dimensões, medidas e gráficos sugeridos."""
    return studio.sources(_scope(session))


@router.get("/templates")
def studio_templates(session: StudioSession) -> Dict[str, Any]:
    """Modelos de relatório prontos (já validados contra as fontes)."""
    return studio.templates(_scope(session))


@router.get("/templates/{template_id}")
def studio_template(template_id: str, session: StudioSession) -> Dict[str, Any]:
    try:
        return studio.template(template_id, _scope(session))
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


# ----------------------------------------------------------------- relatórios
@router.get("/reports")
def studio_list_reports(
    session: StudioSession,
    q: str = Query(""),
    status: str = Query(""),
    template: str = Query(""),
    channel: str = Query(""),
    limit: int = Query(200, ge=1, le=300),
) -> Dict[str, Any]:
    """Relatórios do estúdio (mais recentes primeiro)."""
    return studio.list_reports(q=q, status=status, template=template, channel=channel, limit=limit)


@router.post("/reports", status_code=201)
def studio_create_report(payload: ReportPayload, session: StudioSession) -> Dict[str, Any]:
    """Cria um relatório — a partir de um modelo (`template`) ou do zero."""
    data = {key: value for key, value in payload.model_dump().items() if value is not None}
    try:
        created = studio.create_report(data, _email(session))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    events.log_event("info", "reports", f"Relatório «{created['report']['title']}» criado no estúdio por {_email(session)}", data={})
    return created


@router.get("/reports/{report_id}")
def studio_get_report(report_id: str, session: StudioSession) -> Dict[str, Any]:
    return studio.report_view(_report_or_404(report_id), include_internal=True)


@router.put("/reports/{report_id}")
def studio_save_report(report_id: str, payload: ReportPayload, session: StudioSession) -> Dict[str, Any]:
    """Grava o relatório (blocos, texto, metadados)."""
    _report_or_404(report_id)
    data = {key: value for key, value in payload.model_dump().items() if value is not None}
    data["id"] = report_id
    try:
        return studio.save_report(data, _email(session))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.delete("/reports/{report_id}")
def studio_delete_report(report_id: str, session: StudioSession) -> Dict[str, Any]:
    _report_or_404(report_id)
    if not studio.delete_report(report_id, _email(session)):
        raise HTTPException(status_code=404, detail="Relatório não encontrado.")
    return {"removed": True, "reports": studio.list_reports(limit=1)["stats"]}


@router.post("/reports/{report_id}/duplicate", status_code=201)
def studio_duplicate_report(report_id: str, session: StudioSession, title: Optional[str] = Body(None, embed=True)) -> Dict[str, Any]:
    _report_or_404(report_id)
    try:
        return studio.duplicate_report(report_id, _email(session), title=title or "")
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


# ------------------------------------------------------------------ execução
def _draft(payload: RunPayload) -> Dict[str, Any]:
    """Relatório a executar: o gravado (por id) ou o rascunho do corpo."""
    draft = payload.report or {}
    report_id = str(draft.get("id") or "")
    if report_id:
        doc = studio.get_report(report_id)
        if doc is None:
            raise HTTPException(status_code=404, detail="Relatório não encontrado.")
        return doc
    blocks = draft.get("blocks") if isinstance(draft.get("blocks"), list) else payload.blocks
    if not blocks:
        raise HTTPException(status_code=400, detail="Indique o relatório (`id`) ou os blocos a executar.")
    doc = {key: value for key, value in draft.items() if key != "blocks"}
    doc["blocks"] = blocks
    try:
        normalised = studio.normalise_report({**doc, "title": doc.get("title") or "Pré-visualização"})
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return normalised


@router.post("/query")
def studio_query(payload: RunPayload, session: StudioSession) -> Dict[str, Any]:
    """Corre blocos de um rascunho (a pré-visualização do editor)."""
    doc = _draft(payload)
    return studio.run_report(doc, _scope(session), block_ids=payload.block_ids)


@router.post("/reports/{report_id}/run")
def studio_run_report(report_id: str, session: StudioSession, payload: Optional[RunPayload] = Body(None)) -> Dict[str, Any]:
    """Corre o relatório gravado (dados de todos os blocos)."""
    doc = _report_or_404(report_id)
    block_ids = payload.block_ids if payload else None
    return studio.run_report(doc, _scope(session), block_ids=block_ids)


# -------------------------------------------------------------------- PDF
@router.post("/reports/{report_id}/pdf")
def studio_pdf(report_id: str, session: StudioSession) -> Dict[str, Any]:
    """Gera o PDF do relatório e guarda-o no estúdio."""
    _report_or_404(report_id)
    try:
        result = studio.attach_pdf(report_id, _email(session), _scope(session))
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=501, detail=str(exc)) from exc
    events.log_event("info", "reports", f"PDF do relatório {report_id} gerado no estúdio por {_email(session)}", data={})
    return result


@router.get("/reports/{report_id}/files/{file_id}")
def studio_download(report_id: str, file_id: str, session: StudioSession) -> FileResponse:
    """Download de um PDF do relatório (exige acesso ao estúdio)."""
    doc = _report_or_404(report_id)
    found = studio.file_of(doc, file_id)
    if found is None:
        raise HTTPException(status_code=404, detail="Ficheiro não encontrado.")
    path, item = found
    return FileResponse(path, media_type=str(item.get("mime") or "application/pdf"), filename=str(item.get("name") or path.name))


@router.delete("/reports/{report_id}/files/{file_id}")
def studio_remove_file(report_id: str, file_id: str, session: StudioSession) -> Dict[str, Any]:
    """Remove um PDF do relatório (a definição do relatório não muda)."""
    _report_or_404(report_id)
    try:
        if not studio.drop_file(report_id, file_id, _email(session)):
            raise HTTPException(status_code=404, detail="Ficheiro não encontrado.")
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return {"removed": True, "report": studio.get_report_view(report_id, include_internal=True)}


# -------------------------------------------------------------- publicação
@router.post("/reports/{report_id}/publish")
def studio_publish(report_id: str, payload: PublishPayload, session: StudioSession) -> Dict[str, Any]:
    """Publica o relatório no catálogo da plataforma, na loja ou em ambos."""
    _report_or_404(report_id)
    data = {key: value for key, value in payload.model_dump().items() if value is not None}
    try:
        result = studio.publish(report_id, data, _email(session))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    events.log_event("info", "reports", f"Relatório {report_id} publicado ({data.get('target')}) por {_email(session)}", data={})
    return result


@router.post("/reports/{report_id}/unpublish")
def studio_unpublish(report_id: str, session: StudioSession, target: str = Body("site", embed=True)) -> Dict[str, Any]:
    """Retira o relatório de um canal (o que já foi entregue não é afetado)."""
    _report_or_404(report_id)
    try:
        return studio.unpublish(report_id, target, _email(session))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


# --------------------------------------------------------------------- IA
async def _assist(payload: AiPayload, session: StudioSession) -> Dict[str, Any]:
    data = {key: value for key, value in payload.model_dump().items() if value is not None}
    try:
        return await studio.assist(data, session)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/ai")
async def studio_assist(payload: AiPayload, session: StudioSession) -> Dict[str, Any]:
    """Ajuda da IA sobre um rascunho (sem gravar)."""
    return await _assist(payload, session)


@router.post("/reports/{report_id}/ai")
async def studio_report_assist(report_id: str, payload: AiPayload, session: StudioSession) -> Dict[str, Any]:
    """Ajuda da IA sobre o relatório gravado."""
    _report_or_404(report_id)
    payload.report = report_id
    return await _assist(payload, session)
