"""Rotas do módulo **DORA** (`/dora/*`).

DORA — Digital Operational Resilience Act: registo de informação, incidentes,
riscos, workflows, relatórios ITS/RTS e conteúdo original/traduzido da EIOPA.

Endpoints de leitura são públicos. Escrita exige sessão.
"""
from __future__ import annotations

import logging
from typing import Annotated, Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from starlette.concurrency import run_in_threadpool

from api import dora_service as service
from api.auth_routes import CurrentSession, require_session

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/dora", tags=["dora"])

Session = Annotated[CurrentSession, Depends(require_session)]

SEVERIDADE_PATTERN = "^(critico|alto|medio|baixo|informacao)$"
ESTADO_PATTERN = "^(aberto|em_analise|contido|resolvido|fechado)$"
IMPACTO_PATTERN = "^(critico|alto|medio|baixo)$"
PROBABILIDADE_PATTERN = "^(quase_certo|provavel|possivel|improvavel|raro)$"
TIPO_REGISTO_PATTERN = "^(entidade|funcao|sistema|fornecedor|contrato|outro)$"
TIPO_RELATORIO_PATTERN = "^(register-of-information|incidents|risk|third-party|tls|oversight|combined)$"


def _ou_erro(payload: Dict[str, Any]) -> Dict[str, Any]:
    erro = str(payload.get("error") or "")
    if not erro:
        return payload
    if "Elasticsearch" in erro:
        raise HTTPException(status_code=503, detail=erro)
    if "obrigatório" in erro or "inválid" in erro or "desconhecido" in erro or "deve ser" in erro or "Indique" in erro:
        raise HTTPException(status_code=400, detail=erro)
    raise HTTPException(status_code=404, detail=erro)


# ---------------------------------------------------------------------------
# Metadados e conteúdo
# ---------------------------------------------------------------------------


@router.get("/meta", summary="Metadados e conteúdo DORA (PT + original)")
def dora_meta() -> Dict[str, Any]:
    """Devolve o conteúdo recolhido da EIOPA em português e no original inglês."""
    return service.meta()


@router.get("/conteudo", summary="Pesquisar no conteúdo DORA indexado")
def dora_conteudo_pesquisa(
    q: str = Query(..., min_length=2, description="Termo de pesquisa"),
    idioma: Optional[str] = Query(None, pattern="^(pt|en)$", description="Idioma do conteúdo"),
    size: int = Query(20, ge=1, le=100),
    from_: int = Query(0, ge=0, le=500, alias="from"),
) -> Dict[str, Any]:
    return _ou_erro(service.conteudo_pesquisa(q, idioma=idioma, size=size, from_=from_))


@router.post("/conteudo/ingestao", summary="Indexar conteúdo DORA da EIOPA")
def dora_conteudo_ingestao(session: Session) -> Dict[str, Any]:
    return _ou_erro(service.conteudo_ingestao(session.user_id))


# ---------------------------------------------------------------------------
# Register of Information
# ---------------------------------------------------------------------------


class RegistoItem(BaseModel):
    id: Optional[str] = Field(None, description="Identificador do item")
    tipo: str = Field(..., pattern=TIPO_REGISTO_PATTERN, description="entidade | funcao | sistema | fornecedor | contrato | outro")
    nome: str = Field(..., min_length=1, max_length=500)
    descricao: Optional[str] = Field(None, max_length=4000)
    entidade_id: Optional[str] = Field(None, description="ID da entidade proprietária")
    entidade_nome: Optional[str] = None
    fornecedor_ids: List[str] = Field(default_factory=list)
    sistema_ids: List[str] = Field(default_factory=list)
    funcao_ids: List[str] = Field(default_factory=list)
    contrato_ids: List[str] = Field(default_factory=list)
    tags: List[str] = Field(default_factory=list)
    dados: Dict[str, Any] = Field(default_factory=dict)


@router.get("/registo", summary="Pesquisar no Register of Information")
async def dora_registo_pesquisa(
    q: Optional[str] = Query(None, min_length=2),
    tipo: Optional[str] = Query(None, pattern=TIPO_REGISTO_PATTERN),
    entidade_id: Optional[str] = Query(None),
    size: int = Query(20, ge=1, le=100),
    from_: int = Query(0, ge=0, le=500, alias="from"),
) -> Dict[str, Any]:
    return _ou_erro(
        await run_in_threadpool(
            service.registo_pesquisa,
            q=q,
            tipo=tipo,
            entidade_id=entidade_id,
            size=size,
            from_=from_,
        )
    )


@router.get("/registo/{tipo}/{item_id}", summary="Obter item do Register of Information")
def dora_registo_item(tipo: str, item_id: str) -> Dict[str, Any]:
    item = service.registo_item(tipo, item_id)
    if not item:
        raise HTTPException(status_code=404, detail="Item não encontrado")
    return item


@router.get("/registo/{tipo}/{item_id}/relacoes", summary="Relações de um item do registo")
def dora_registo_relacoes(tipo: str, item_id: str) -> Dict[str, Any]:
    return _ou_erro(service.registo_relacoes(item_id, tipo))


@router.post("/registo", summary="Criar ou atualizar item no Register of Information")
def dora_registo_guardar(session: Session, payload: RegistoItem) -> Dict[str, Any]:
    return _ou_erro(service.registo_guardar(session.user_id, payload.model_dump(exclude_none=True)))


# ---------------------------------------------------------------------------
# Incidentes ICT
# ---------------------------------------------------------------------------


class IncidenteItem(BaseModel):
    id: Optional[str] = None
    titulo: str = Field(..., min_length=1, max_length=500)
    descricao: Optional[str] = Field(None, max_length=4000)
    referencia: Optional[str] = None
    severidade: str = Field("medio", pattern=SEVERIDADE_PATTERN)
    estado: str = Field("aberto", pattern=ESTADO_PATTERN)
    entidade_id: Optional[str] = None
    entidade_nome: Optional[str] = None
    sistema: Optional[str] = None
    data_inicio: Optional[str] = None
    data_fim: Optional[str] = None
    impacto_financeiro: Optional[float] = None
    dados: Dict[str, Any] = Field(default_factory=dict)


@router.get("/incidentes", summary="Pesquisar incidentes ICT")
async def dora_incidentes_pesquisa(
    q: Optional[str] = Query(None, min_length=2),
    severidade: Optional[str] = Query(None, pattern=SEVERIDADE_PATTERN),
    estado: Optional[str] = Query(None, pattern=ESTADO_PATTERN),
    size: int = Query(20, ge=1, le=100),
    from_: int = Query(0, ge=0, le=500, alias="from"),
) -> Dict[str, Any]:
    return _ou_erro(
        await run_in_threadpool(
            service.incidentes_pesquisa,
            q=q,
            severidade=severidade,
            estado=estado,
            size=size,
            from_=from_,
        )
    )


@router.get("/incidentes/{id_}", summary="Obter incidente")
def dora_incidente(id_: str) -> Dict[str, Any]:
    item = service.incidente(id_)
    if not item:
        raise HTTPException(status_code=404, detail="Incidente não encontrado")
    return item


@router.post("/incidentes", summary="Criar ou atualizar incidente ICT")
def dora_incidente_guardar(session: Session, payload: IncidenteItem) -> Dict[str, Any]:
    return _ou_erro(service.incidente_guardar(session.user_id, payload.model_dump(exclude_none=True)))


# ---------------------------------------------------------------------------
# Riscos ICT
# ---------------------------------------------------------------------------


class RiscoItem(BaseModel):
    id: Optional[str] = None
    nome: str = Field(..., min_length=1, max_length=500)
    descricao: Optional[str] = Field(None, max_length=4000)
    categoria: Optional[str] = None
    impacto: str = Field("medio", pattern=IMPACTO_PATTERN)
    probabilidade: str = Field("possivel", pattern=PROBABILIDADE_PATTERN)
    ativo: Optional[str] = None
    entidade_id: Optional[str] = None
    entidade_nome: Optional[str] = None
    mitigacao: Optional[str] = None
    dados: Dict[str, Any] = Field(default_factory=dict)


@router.get("/riscos", summary="Pesquisar riscos ICT")
async def dora_riscos_pesquisa(
    q: Optional[str] = Query(None, min_length=2),
    impacto: Optional[str] = Query(None, pattern=IMPACTO_PATTERN),
    probabilidade: Optional[str] = Query(None, pattern=PROBABILIDADE_PATTERN),
    size: int = Query(20, ge=1, le=100),
    from_: int = Query(0, ge=0, le=500, alias="from"),
) -> Dict[str, Any]:
    return _ou_erro(
        await run_in_threadpool(
            service.riscos_pesquisa,
            q=q,
            impacto=impacto,
            probabilidade=probabilidade,
            size=size,
            from_=from_,
        )
    )


@router.get("/riscos/{id_}", summary="Obter risco")
def dora_risco(id_: str) -> Dict[str, Any]:
    item = service.risco(id_)
    if not item:
        raise HTTPException(status_code=404, detail="Risco não encontrado")
    return item


@router.post("/riscos", summary="Criar ou atualizar risco ICT")
def dora_risco_guardar(session: Session, payload: RiscoItem) -> Dict[str, Any]:
    return _ou_erro(service.risco_guardar(session.user_id, payload.model_dump(exclude_none=True)))


# ---------------------------------------------------------------------------
# Workflows / automações
# ---------------------------------------------------------------------------


class WorkflowItem(BaseModel):
    id: Optional[str] = None
    nome: str = Field(..., min_length=1, max_length=500)
    descricao: Optional[str] = Field(None, max_length=4000)
    ativo: bool = True
    trigger: Optional[str] = None
    acao: Optional[str] = None
    passos: List[Dict[str, Any]] = Field(default_factory=list)
    entidade_id: Optional[str] = None


@router.get("/workflows", summary="Pesquisar workflows de conformidade")
async def dora_workflows_pesquisa(
    q: Optional[str] = Query(None, min_length=2),
    ativo: Optional[bool] = Query(None),
    size: int = Query(20, ge=1, le=100),
    from_: int = Query(0, ge=0, le=500, alias="from"),
) -> Dict[str, Any]:
    return _ou_erro(
        await run_in_threadpool(
            service.workflows_pesquisa,
            q=q,
            ativo=ativo,
            size=size,
            from_=from_,
        )
    )


@router.get("/workflows/{id_}", summary="Obter workflow")
def dora_workflow(id_: str) -> Dict[str, Any]:
    item = service.workflow(id_)
    if not item:
        raise HTTPException(status_code=404, detail="Workflow não encontrado")
    return item


@router.post("/workflows", summary="Criar ou atualizar workflow")
def dora_workflow_guardar(session: Session, payload: WorkflowItem) -> Dict[str, Any]:
    return _ou_erro(service.workflow_guardar(session.user_id, payload.model_dump(exclude_none=True)))


# ---------------------------------------------------------------------------
# Relatórios ITS/RTS
# ---------------------------------------------------------------------------


class RelatorioPayload(BaseModel):
    tipo: str = Field(..., pattern=TIPO_RELATORIO_PATTERN)
    entidade_id: str = Field(..., min_length=1)
    nome: Optional[str] = None
    formato: str = Field("json", pattern="^(json|csv|pdf|xlsx)$")
    dados: Dict[str, Any] = Field(default_factory=dict)


@router.get("/relatorios", summary="Pesquisar relatórios")
async def dora_relatorios_pesquisa(
    q: Optional[str] = Query(None, min_length=2),
    tipo: Optional[str] = Query(None, pattern=TIPO_RELATORIO_PATTERN),
    size: int = Query(20, ge=1, le=100),
    from_: int = Query(0, ge=0, le=500, alias="from"),
) -> Dict[str, Any]:
    return _ou_erro(
        await run_in_threadpool(
            service.relatorios_pesquisa,
            q=q,
            tipo=tipo,
            size=size,
            from_=from_,
        )
    )


@router.get("/relatorios/{id_}", summary="Obter relatório")
def dora_relatorio(id_: str) -> Dict[str, Any]:
    item = service.relatorio(id_)
    if not item:
        raise HTTPException(status_code=404, detail="Relatório não encontrado")
    return item


@router.post("/relatorios", summary="Gerar relatório ITS/RTS")
def dora_relatorio_gerar(session: Session, payload: RelatorioPayload) -> Dict[str, Any]:
    return _ou_erro(service.relatorio_gerar(session.user_id, payload.model_dump(exclude_none=True)))
