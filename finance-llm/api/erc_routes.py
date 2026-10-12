"""Rotas do módulo **Portal da Transparência da ERC** (`/erc/*`).

O portal da ERC (`portaltransparencia.erc.pt`) publica as **entidades
proprietárias de órgãos de comunicação social**, as **pessoas** dos seus órgãos
sociais e os **OCS detidos**. Este módulo recolhe tudo, guarda em JSONL e indexa
em `finance_erc_entidades`, `finance_erc_pessoas` e `finance_erc_ocs`.

Endpoints:

- `GET  /erc/meta`              — pastas, volumetria em disco e índices usados
- `GET  /erc/resumo`            — painel: contagens, distritos, tipos e funções
- `GET  /erc/listagem`          — entidades anunciadas pelo portal (com cache)
- `POST /erc/recolher`          — recolhe entidades, pessoas e OCS (segundo plano)
- `POST /erc/indexar`           — indexa os JSONL nos índices `finance_erc_*` (segundo plano)
- `GET  /erc/jobs[/{job_id}]`   — progresso dos trabalhos
- `GET  /erc/entidades`         — pesquisa de entidades proprietárias de OCS
- `GET  /erc/entidades/{id}`    — ficha da entidade (dados gerais, pessoas, OCS, estrutura)
- `GET  /erc/pessoas`           — pesquisa de pessoas reguladas
- `GET  /erc/pessoas/{id}`      — ficha da pessoa (cargos e participações)
- `GET  /erc/ocs`               — pesquisa de órgãos de comunicação social
- `GET  /erc/export.csv`        — exportação em CSV (entidades, pessoas ou OCS)
"""
from __future__ import annotations

import logging
from typing import Annotated, Any, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import Response
from pydantic import BaseModel, Field

from api import erc_service as erc
from api.auth_routes import CurrentSession, optional_session, require_session

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/erc", tags=["erc"])

Session = Annotated[CurrentSession, Depends(require_session)]
ReadSession = Annotated[CurrentSession, Depends(optional_session)]


class ErcRecolherRequest(BaseModel):
    """O que recolher do portal da ERC."""

    limite: Optional[int] = Field(
        None, ge=1, description="Número máximo de entidades a ler (por omissão, todas)"
    )
    pausa: Optional[float] = Field(None, ge=0, le=10, description="Pausa entre pedidos, em segundos")
    com_pessoas: bool = Field(True, description="Abrir a ficha de cada pessoa dos órgãos sociais")
    com_estrutura: bool = Field(True, description="Ler a estrutura de propriedade (detentores/detidas)")
    com_ocs: bool = Field(True, description="Registar os órgãos de comunicação social detidos")
    com_financeiro: bool = Field(False, description="Ler também os dados financeiros por exercício (mais lento)")
    guardar_html: bool = Field(True, description="Guardar o HTML de cada página em data/erc/raw")
    forcar: bool = Field(False, description="Reler a listagem em vez de usar a cache em disco")
    indexar: bool = Field(False, description="Indexar no Elasticsearch no fim da recolha")


class ErcIndexarRequest(BaseModel):
    """O que indexar."""

    forcar: bool = Field(False, description="Reindexar mesmo o que já está indexado")


@router.get("/meta")
def erc_meta(session: ReadSession = None) -> Dict[str, Any]:
    """Pasta dos dados, contagens em disco, listagem em cache e índices usados."""
    return erc.meta()


@router.get("/resumo")
def erc_resumo(session: ReadSession = None) -> Dict[str, Any]:
    """Painel do módulo: contagens, distritos, tipos de sociedade e funções."""
    return erc.resumo()


@router.get("/listagem")
def erc_listagem(
    refrescar: bool = Query(False, description="Voltar a ler a listagem no portal"),
    session: ReadSession = None,
) -> Dict[str, Any]:
    """Entidades anunciadas pelo portal (listagem completa, com cache em disco)."""
    try:
        entidades = erc.ler_listagem(forcar=refrescar)
    except Exception as exc:  # noqa: BLE001 - sem rede, a listagem em cache serve
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return {"total": len(entidades), "items": entidades}


@router.post("/recolher")
def erc_recolher(payload: ErcRecolherRequest, session: Session = None) -> Dict[str, Any]:
    """Recolhe o portal em segundo plano (entidades, pessoas e OCS)."""
    return erc.start_job("recolher", payload.model_dump())


@router.post("/indexar")
def erc_indexar(payload: ErcIndexarRequest, session: Session = None) -> Dict[str, Any]:
    """Indexa o que está em disco nos índices `finance_erc_*` (segundo plano)."""
    return erc.start_job("indexar", payload.model_dump())


@router.get("/jobs")
def erc_jobs(session: ReadSession = None) -> Dict[str, Any]:
    """Trabalhos de recolha e indexação, mais recentes primeiro."""
    return erc.list_jobs()


@router.get("/jobs/{job_id}")
def erc_job(job_id: str, session: ReadSession = None) -> Dict[str, Any]:
    """Estado de um trabalho."""
    job = erc.job_status(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Trabalho não encontrado")
    return job


@router.get("/entidades")
def erc_entidades(
    q: Optional[str] = Query(None, description="Nome, OCS detido ou pessoa dos órgãos sociais"),
    distrito: Optional[str] = Query(None, description="Distrito"),
    tipo_sociedade: Optional[str] = Query(None, description="Tipo de sociedade"),
    page: int = Query(1, ge=1),
    size: int = Query(25, ge=1, le=500),
    session: ReadSession = None,
) -> Dict[str, Any]:
    """Pesquisa as entidades proprietárias de órgãos de comunicação social."""
    return erc.listar_entidades(q=q, distrito=distrito, tipo_sociedade=tipo_sociedade, page=page, size=size)


@router.get("/entidades/{entidade_id}")
def erc_entidade(entidade_id: str, session: ReadSession = None) -> Dict[str, Any]:
    """Ficha de uma entidade: dados gerais, pessoas, OCS e estrutura de propriedade."""
    doc = erc.get_entidade(entidade_id)
    if not doc:
        raise HTTPException(status_code=404, detail="Entidade não recolhida (use POST /erc/recolher)")
    return doc


@router.get("/pessoas")
def erc_pessoas(
    q: Optional[str] = Query(None, description="Nome, empresa ou participação"),
    distrito: Optional[str] = Query(None, description="Distrito"),
    empresa: Optional[str] = Query(None, description="Nome da empresa onde a pessoa tem cargo"),
    funcao: Optional[str] = Query(None, description="Função/cargo (ex.: Gerente, Administrador)"),
    page: int = Query(1, ge=1),
    size: int = Query(25, ge=1, le=500),
    session: ReadSession = None,
) -> Dict[str, Any]:
    """Pesquisa as pessoas reguladas (órgãos sociais de entidades próprias de OCS)."""
    return erc.listar_pessoas(q=q, distrito=distrito, empresa=empresa, funcao=funcao, page=page, size=size)


@router.get("/pessoas/{pessoa_id}")
def erc_pessoa(pessoa_id: str, session: ReadSession = None) -> Dict[str, Any]:
    """Ficha de uma pessoa: dados gerais, cargos (órgãos sociais) e participações diretas."""
    doc = erc.get_pessoa(pessoa_id)
    if not doc:
        raise HTTPException(status_code=404, detail="Pessoa não recolhida (use POST /erc/recolher)")
    return doc


@router.get("/ocs")
def erc_ocs(
    q: Optional[str] = Query(None, description="Designação ou entidade proprietária"),
    tipo: Optional[str] = Query(None, description="Tipo de OCS (ex.: Online, Rádio, Televisão)"),
    distrito: Optional[str] = Query(None, description="Distrito"),
    proprietaria: Optional[str] = Query(None, description="Entidade proprietária"),
    page: int = Query(1, ge=1),
    size: int = Query(25, ge=1, le=500),
    session: ReadSession = None,
) -> Dict[str, Any]:
    """Pesquisa os órgãos de comunicação social detidos pelas entidades."""
    return erc.listar_ocs(q=q, tipo=tipo, distrito=distrito, proprietaria=proprietaria, page=page, size=size)


@router.get("/export.csv")
def erc_export(
    tipo: str = Query("entidades", pattern="^(entidades|pessoas|ocs)$", description="O que exportar"),
    maximo: int = Query(50000, ge=1, le=200000, description="Máximo de registos"),
    session: ReadSession = None,
) -> Response:
    """Exporta entidades, pessoas ou OCS em CSV."""
    conteudo = erc.export_csv(tipo, maximo=maximo)
    return Response(
        content=conteudo.encode("utf-8"),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="erc-{tipo}.csv"'},
    )
