"""Rotas do módulo **Subvenções públicas** (`/subvencoes/*`).

Lê os ficheiros `.ods` publicados pela IGF na pasta `data/subvencoes` (um por
ano, ou uma subpasta por ano) e disponibiliza-os para consulta:

- `GET  /subvencoes/meta`                — pasta, anos no disco, o que está lido e indexado
- `GET  /subvencoes/ficheiros`           — ficheiros encontrados na pasta (ano, tamanho, mtime)
- `GET  /subvencoes/lotes`               — ficheiros já lidos (JSONL) e respetivos totais
- `POST /subvencoes/ler`                 — lê a pasta **por ano** para JSONL (segundo plano)
- `POST /subvencoes/indexar`             — indexa os JSONL em `finance_subvencoes` (segundo plano)
- `GET  /subvencoes/jobs[/{id}]`         — progresso dos trabalhos
- `GET  /subvencoes/resumo`              — painel: totais por ano, top entidades e beneficiários
- `GET  /subvencoes/search`              — pesquisa (ano, NIF, entidade, beneficiário, valor, datas, texto)
- `GET  /subvencoes/amostra/{ano}`       — amostra lida do disco (funciona sem Elasticsearch)
- `GET  /subvencoes/beneficiario/{nif}`  — o que um NIF recebeu (por ano e por entidade)
- `GET  /subvencoes/entidade/{nif}`      — o que uma entidade obrigada atribuiu
- `GET  /subvencoes/export.csv`          — exportação da pesquisa
"""
from __future__ import annotations

import logging
from typing import Annotated, Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import Response
from pydantic import BaseModel, Field

from api import subvencoes_service as subvencoes
from api.auth_routes import CurrentSession, optional_session, require_session

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/subvencoes", tags=["subvencoes"])

Session = Annotated[CurrentSession, Depends(require_session)]
ReadSession = Annotated[CurrentSession, Depends(optional_session)]


class SubvencoesLerRequest(BaseModel):
    """O que ler da pasta."""

    anos: Optional[List[int]] = Field(
        None, description="Anos a ler (por omissão, todos os ficheiros encontrados na pasta)"
    )
    forcar: bool = Field(False, description="Reler mesmo os ficheiros que já estão lidos (mesmo `sha256`)")


class SubvencoesIndexarRequest(BaseModel):
    """O que indexar."""

    anos: Optional[List[int]] = Field(None, description="Anos a indexar (por omissão, todos os que estão lidos)")
    forcar: bool = Field(False, description="Reindexar mesmo os lotes já indexados")


@router.get("/meta")
def subvencoes_meta(session: ReadSession = None) -> Dict[str, Any]:
    """Pasta dos dados, ficheiros no disco por ano e volumetria lida/indexada."""
    return subvencoes.meta()


@router.get("/ficheiros")
def subvencoes_ficheiros(session: ReadSession = None) -> Dict[str, Any]:
    """Ficheiros de subvenções encontrados na pasta (com o ano atribuído)."""
    itens = subvencoes.ficheiros()
    return {
        "dir": str(subvencoes.data_dir()),
        "total": len(itens),
        "anos": sorted({item["ano"] for item in itens if item.get("ano") is not None}, reverse=True),
        "items": itens,
    }


@router.get("/lotes")
def subvencoes_lotes(session: ReadSession = None) -> Dict[str, Any]:
    """Ficheiros já lidos para JSONL, com registos e montante por lote."""
    return subvencoes.listar_lotes()


@router.post("/ler")
def subvencoes_ler(payload: SubvencoesLerRequest | None = None, session: Session = None) -> Dict[str, Any]:
    """Lê a pasta **por ano** e normaliza cada ficheiro para JSONL (segundo plano)."""
    dados = (payload or SubvencoesLerRequest()).model_dump()
    return subvencoes.start_job("ler", dados)


@router.post("/indexar")
def subvencoes_indexar(payload: SubvencoesIndexarRequest | None = None, session: Session = None) -> Dict[str, Any]:
    """Indexa os JSONL já lidos no Elasticsearch (segundo plano)."""
    dados = (payload or SubvencoesIndexarRequest()).model_dump()
    return subvencoes.start_job("indexar", dados)


@router.get("/jobs")
def subvencoes_jobs(session: ReadSession = None) -> Dict[str, Any]:
    """Trabalhos de leitura e indexação (mais recentes primeiro)."""
    return subvencoes.list_jobs()


@router.get("/jobs/{job_id}")
def subvencoes_job(job_id: str, session: ReadSession = None) -> Dict[str, Any]:
    """Estado de um trabalho."""
    job = subvencoes.job_status(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Trabalho não encontrado.")
    return job


@router.get("/resumo")
def subvencoes_resumo(
    ano: Optional[List[int]] = Query(None, description="Anos a considerar (repetível; por omissão, todos)"),
    session: ReadSession = None,
) -> Dict[str, Any]:
    """Painel do módulo: totais por ano, top entidades/beneficiários e série mensal."""
    resultado = subvencoes.resumo(anos=ano)
    if resultado.get("error"):
        raise HTTPException(status_code=503, detail=str(resultado["error"]))
    return resultado


@router.get("/search")
def subvencoes_search(
    q: Optional[str] = Query(None, description="Texto livre (beneficiário, entidade, finalidade) ou um NIF"),
    ano: Optional[int] = Query(None, description="Ano da **listagem** (o ficheiro)"),
    ano_decisao: Optional[int] = Query(None, description="Ano da decisão do apoio"),
    nif_entidade: Optional[str] = Query(None, description="NIF da entidade obrigada ao reporte"),
    nif_beneficiario: Optional[str] = Query(None, description="NIF/NIPC do beneficiário"),
    entidade: Optional[str] = Query(None, description="Nome (parcial) da entidade obrigada"),
    beneficiario: Optional[str] = Query(None, description="Nome (parcial) do beneficiário"),
    tipo_ato: Optional[str] = Query(None, description="Tipo de ato do fundamento legal (ex.: `Lei`)"),
    beneficiario_tipo: Optional[str] = Query(
        None, description="pessoa_singular | pessoa_coletiva | empresario_individual | entidade_publica | outro"
    ),
    fundamento_legal: Optional[str] = Query(None, description="Fundamento legal exacto (ex.: `Lei n.º 75`)"),
    data_from: Optional[str] = Query(None, description="Decisões a partir de (AAAA-MM-DD)"),
    data_to: Optional[str] = Query(None, description="Decisões até (AAAA-MM-DD)"),
    montante_min: Optional[float] = Query(None, ge=0, description="Montante mínimo (euros)"),
    montante_max: Optional[float] = Query(None, ge=0, description="Montante máximo (euros)"),
    sort: str = Query("montante", pattern="^(relevancia|montante|data|beneficiario|entidade|ano)$"),
    order: str = Query("desc", pattern="^(asc|desc)$"),
    page: int = Query(1, ge=1),
    size: int = Query(25, ge=1, le=200),
    session: ReadSession = None,
) -> Dict[str, Any]:
    """Pesquisa das subvenções concedidas, com facetas e indicadores."""
    resultado = subvencoes.search(
        q=q,
        ano=ano,
        ano_decisao=ano_decisao,
        nif_entidade=nif_entidade,
        nif_beneficiario=nif_beneficiario,
        entidade=entidade,
        beneficiario=beneficiario,
        tipo_ato=tipo_ato,
        beneficiario_tipo=beneficiario_tipo,
        fundamento_legal=fundamento_legal,
        data_from=data_from,
        data_to=data_to,
        montante_min=montante_min,
        montante_max=montante_max,
        sort=sort,
        order=order,
        page=page,
        size=size,
    )
    if resultado.get("error"):
        raise HTTPException(status_code=503, detail=str(resultado["error"]))
    return resultado


@router.get("/amostra/{ano}")
def subvencoes_amostra(
    ano: int,
    limit_items: int = Query(25, ge=1, le=500),
    session: ReadSession = None,
) -> Dict[str, Any]:
    """Amostra dos registos lidos de um ano (não precisa do Elasticsearch)."""
    return subvencoes.preview(ano, limite=limit_items)


@router.get("/beneficiario/{nif}")
def subvencoes_beneficiario(
    nif: str,
    size: int = Query(200, ge=1, le=1000),
    session: ReadSession = None,
) -> Dict[str, Any]:
    """Subvenções recebidas por um NIF, com totais por ano e por entidade."""
    resultado = subvencoes.por_beneficiario(nif, size=size)
    if resultado.get("error"):
        raise HTTPException(status_code=503, detail=str(resultado["error"]))
    if not resultado.get("total"):
        raise HTTPException(status_code=404, detail="Sem subvenções registadas para este NIF.")
    return resultado


@router.get("/entidade/{nif}")
def subvencoes_entidade(
    nif: str,
    size: int = Query(200, ge=1, le=1000),
    session: ReadSession = None,
) -> Dict[str, Any]:
    """Subvenções atribuídas por uma entidade obrigada (NIF)."""
    resultado = subvencoes.por_entidade(nif, size=size)
    if resultado.get("error"):
        raise HTTPException(status_code=503, detail=str(resultado["error"]))
    if not resultado.get("total"):
        raise HTTPException(status_code=404, detail="Sem subvenções registadas para esta entidade.")
    return resultado


@router.get("/export.csv")
def subvencoes_export(
    q: Optional[str] = Query(None),
    ano: Optional[int] = Query(None),
    ano_decisao: Optional[int] = Query(None),
    nif_entidade: Optional[str] = Query(None),
    nif_beneficiario: Optional[str] = Query(None),
    entidade: Optional[str] = Query(None),
    beneficiario: Optional[str] = Query(None),
    tipo_ato: Optional[str] = Query(None),
    beneficiario_tipo: Optional[str] = Query(None),
    fundamento_legal: Optional[str] = Query(None),
    data_from: Optional[str] = Query(None),
    data_to: Optional[str] = Query(None),
    montante_min: Optional[float] = Query(None, ge=0),
    montante_max: Optional[float] = Query(None, ge=0),
    maximo: int = Query(50000, ge=1, le=200000, description="Máximo de registos exportados"),
    session: ReadSession = None,
) -> Response:
    """Exporta em CSV (delimitador `;`) o resultado da pesquisa."""
    try:
        conteudo = subvencoes.csv_bytes(
            maximo=maximo,
            q=q,
            ano=ano,
            ano_decisao=ano_decisao,
            nif_entidade=nif_entidade,
            nif_beneficiario=nif_beneficiario,
            entidade=entidade,
            beneficiario=beneficiario,
            tipo_ato=tipo_ato,
            beneficiario_tipo=beneficiario_tipo,
            fundamento_legal=fundamento_legal,
            data_from=data_from,
            data_to=data_to,
            montante_min=montante_min,
            montante_max=montante_max,
        )
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return Response(
        content=conteudo,
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": 'attachment; filename="subvencoes.csv"'},
    )
