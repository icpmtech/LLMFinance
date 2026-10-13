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
- `GET  /erc/analise`           — ranking de risco, transparência e crédito
- `POST /erc/financeiro/recolher` — recolhe os dados financeiros por exercício
- `GET  /erc/financeiro`        — painel financeiro (totais por exercício e risco)
- `POST /erc/analisar`          — recalcula a análise de risco de todas as entidades
- `GET  /erc/export.csv`        — exportação em CSV (entidades, pessoas, OCS, análise, financeiro)
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
    saltar_existentes: bool = Field(
        False, description="Ignorar as entidades já recolhidas (retomar sem repetir)"
    )
    trabalhadores: int = Field(
        1, ge=1, le=8, description="Pedidos em paralelo (o portal é público: 1 é o mais cortês)"
    )
    indexar: bool = Field(False, description="Indexar no Elasticsearch no fim da recolha")


class ErcIndexarRequest(BaseModel):
    """O que indexar."""

    forcar: bool = Field(False, description="Reindexar mesmo o que já está indexado")


class ErcRecolherFinanceiroRequest(BaseModel):
    """Recolha dos dados financeiros (`geral=dafin`), exercício a exercício."""

    limite: Optional[int] = Field(None, ge=1, description="Entidades a varrer (por omissão, todas)")
    ano_inicio: Optional[int] = Field(None, ge=1990, le=2100, description="Primeiro exercício a sondar")
    ano_fim: Optional[int] = Field(None, ge=1990, le=2100, description="Último exercício a sondar")
    vazios_seguidos: int = Field(
        0, ge=0, le=20,
        description="Parar o varrimento após N exercícios vazios seguidos (0 = varrer a janela toda)",
    )
    pausa: Optional[float] = Field(None, ge=0, le=10, description="Pausa entre pedidos, em segundos")
    trabalhadores: int = Field(8, ge=1, le=16, description="Pedidos em paralelo (o portal satura acima de 8)")
    apenas_sem_financeiro: bool = Field(True, description="Só as entidades que ainda não têm dados financeiros")
    indexar: bool = Field(True, description="Indexar no Elasticsearch no fim")


class ErcAnalisarRequest(BaseModel):
    """Recálculo da análise de risco."""

    indexar: bool = Field(True, description="Indexar no Elasticsearch no fim")


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


@router.post("/financeiro/recolher")
def erc_recolher_financeiro(payload: ErcRecolherFinanceiroRequest, session: Session = None) -> Dict[str, Any]:
    """Recolhe os dados financeiros por exercício em segundo plano.

    O portal não publica a lista de exercícios de cada entidade, por isso a
    janela (`ano_inicio`..`ano_fim`) é sondada ano a ano: um pedido por ano e por
    entidade, com os anos sem publicação a devolverem vazio.
    """
    return erc.start_job("recolher_financeiro", payload.model_dump())


@router.post("/analisar")
def erc_analisar(payload: ErcAnalisarRequest, session: Session = None) -> Dict[str, Any]:
    """Recalcula transparência, crédito e risco de todas as entidades (sem rede)."""
    return erc.start_job("analisar", payload.model_dump())


@router.get("/financeiro")
def erc_financeiro(session: ReadSession = None) -> Dict[str, Any]:
    """Painel financeiro: entidades com contas, totais por exercício e risco."""
    return erc.painel_financeiro()


@router.get("/analise")
def erc_analise(
    q: Optional[str] = Query(None, description="Nome, tipo de sociedade, actividade ou distrito"),
    banda: Optional[str] = Query(None, description="Banda de risco (`baixo`, `moderado`, `elevado`, `critico`)"),
    nivel_transparencia: Optional[str] = Query(None, description="`alta`, `media`, `baixa`, `muito_baixa`"),
    nivel_credito: Optional[str] = Query(None, description="`A`..`E` ou `sem dados`"),
    distrito: Optional[str] = Query(None, description="Distrito"),
    risco_min: Optional[float] = Query(None, ge=0, le=100, description="Risco mínimo (0-100, maior = pior)"),
    risco_max: Optional[float] = Query(None, ge=0, le=100, description="Risco máximo"),
    transparencia_min: Optional[float] = Query(None, ge=0, le=100),
    credito_min: Optional[float] = Query(None, ge=0, le=100),
    com_financeiro: Optional[bool] = Query(None, description="Só entidades com (ou sem) contas publicadas"),
    ordenar: str = Query(
        "risco",
        pattern="^(risco|transparencia|credito|rendimentos|resultados|capital_proprio|autonomia|recentes|nome)$",
        description="Campo de ordenação (desc, excepto `nome`)",
    ),
    page: int = Query(1, ge=1),
    size: int = Query(25, ge=1, le=500),
    session: ReadSession = None,
) -> Dict[str, Any]:
    """Ranking das entidades por risco, transparência, crédito ou números publicados."""
    return erc.listar_analise(
        q=q, banda=banda, nivel_transparencia=nivel_transparencia, nivel_credito=nivel_credito, distrito=distrito,
        risco_min=risco_min, risco_max=risco_max, transparencia_min=transparencia_min, credito_min=credito_min,
        com_financeiro=com_financeiro, ordenar=ordenar, page=page, size=size,
    )


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
    tipo: str = Query("entidades", pattern="^(entidades|pessoas|ocs|analise|financeiro)$", description="O que exportar"),
    maximo: int = Query(50000, ge=1, le=200000, description="Máximo de registos"),
    session: ReadSession = None,
) -> Response:
    """Exporta entidades, pessoas, OCS, a análise de risco ou a série financeira em CSV."""
    conteudo = erc.export_csv(tipo, maximo=maximo)
    return Response(
        content=conteudo.encode("utf-8"),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="erc-{tipo}.csv"'},
    )
