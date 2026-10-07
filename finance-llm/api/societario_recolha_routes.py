"""Rotas da **recolha massiva de dados societários** (`/societario/recolha/*`).

Complementa o módulo societário pontual (`/societario/*`): aqui escolhem-se os
alvos por **ano dos contratos** e/ou por **empresa**, corre-se uma recolha em lote
(2captcha) que grava **um ficheiro JSON por entidade**, e indexam-se esses
ficheiros em `finance_publicacoes_mj`.

- `GET    /societario/recolha/meta`              — pasta dos JSON, índice, limites
- `GET    /societario/recolha/years`             — anos com contratos (facetas)
- `GET    /societario/recolha/targets`           — alvos (ano, empresa, papel, valor…)
- `GET    /societario/recolha/empresas`          — pesquisar empresas (firma/NIF) para recolher
- `GET    /societario/recolha/empresas/{nif}`    — ficha: o que existe e os dados societários
- `POST   /societario/recolha/empresas/{nif}/obter` — recolher os dados de uma empresa
- `POST   /societario/recolha/jobs`              — arranca a recolha massiva (segundo plano)
- `GET    /societario/recolha/jobs[/{id}]`       — progresso dos trabalhos
- `GET    /societario/recolha/exports`           — ficheiros JSON exportados
- `GET    /societario/recolha/exports/{nif}`     — pré-visualização de um ficheiro (200 com
  `exists=false` quando ainda não há ficheiro: é o estado normal durante a recolha)
- `POST   /societario/recolha/exports/ingest`    — indexar os JSON no Elasticsearch
- `DELETE /societario/recolha/exports/{nif}`     — apagar um ficheiro exportado
"""
from __future__ import annotations

import logging
from typing import Annotated, Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from api import societario_recolha as recolha
from api.auth_routes import CurrentSession, optional_session, require_session

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/societario/recolha", tags=["societario"])

Session = Annotated[CurrentSession, Depends(require_session)]
ReadSession = Annotated[CurrentSession, Depends(optional_session)]

#: Papéis aceites no filtro (lado do contrato).
PAPEL_PATTERN = "^(ambos|adjudicatario|adjudicatario[a]?s?|adjudicante|adjudicantes)$"


class RecolhaJobRequest(BaseModel):
    """Parâmetros do trabalho de recolha massiva (um JSON por entidade)."""

    # --- que entidades recolher ---
    ano_ini: Optional[int] = Field(None, ge=1900, le=2100, description="Ano mínimo dos contratos")
    ano_fim: Optional[int] = Field(None, ge=1900, le=2100, description="Ano máximo dos contratos")
    papel: str = Field("ambos", description="Lado do contrato: ambos | adjudicatario | adjudicante")
    q: Optional[str] = Field(None, description="Firma/denominação da empresa (ou NIF)")
    nifs: Optional[List[str]] = Field(None, description="Empresas concretas (NIF/NIPC)")
    min_contracts: int = Field(1, ge=1, description="Mínimo de contratos no cadastro")
    min_value: Optional[float] = Field(None, ge=0, description="Valor total mínimo (€)")
    exclude_collected: bool = Field(True, description="Ignorar entidades que já têm publicações indexadas")
    max_entities: int = Field(50, ge=1, le=500, description="Máximo de entidades a recolher neste trabalho")

    # --- o que recolher no portal ---
    tipo: str = Field("0", description="Tipo de publicação (0 = todos os actos)")
    with_details: bool = Field(True, description="Abrir o detalhe de cada publicação (dados societários)")
    max_pages: int = Field(50, ge=1, le=500, description="Máximo de páginas da grelha por entidade")
    data_ini: Optional[str] = Field(None, description="Data inicial (AAAA-MM-DD); com a final, divide em janelas de 10 dias")
    data_fim: Optional[str] = Field(None, description="Data final (AAAA-MM-DD)")

    # --- ritmo e captcha ---
    # 4 s é o intervalo por omissão do próprio cliente (`PublicacoesMjCaptchaClient`)
    # e o que a UI envia. Com 1 s o portal do MJ passa a responder com a mensagem de
    # throttling e a entidade só entra depois de gastar as tentativas todas.
    min_interval: float = Field(4.0, ge=0, le=60, description="Intervalo mínimo entre pedidos ao portal (s)")
    rate_limit_pause: float = Field(
        90.0, ge=0, le=600, description="Pausa (s) quando o portal do MJ limita os pedidos, antes de tentar de novo"
    )
    rate_limit_retries: int = Field(2, ge=0, le=10, description="Novas tentativas por entidade quando o portal limita")
    recaptcha_timeout: int = Field(180, ge=30, le=600, description="Timeout da resolução do reCAPTCHA (s)")
    stop_on_captcha: bool = Field(False, description="Parar o trabalho ao primeiro captcha rejeitado")
    api_key: Optional[str] = Field(None, description="API key da 2captcha (fallback à variável de ambiente)")
    proxy: Optional[str] = Field(None, description="Proxy HTTP(S) para o portal e a 2captcha")
    debug: bool = Field(False, description="Guardar páginas HTML de debug (MJ_DEBUG=1)")

    # --- destino ---
    ingest: bool = Field(True, description="Indexar logo no Elasticsearch (e alimentar o PessoasIQ) além de gravar o JSON")


class RecolhaIngestRequest(BaseModel):
    """Indexação dos ficheiros JSON exportados."""

    nifs: Optional[List[str]] = Field(None, description="Indexar só estas entidades (por omissão, todas)")
    with_people: bool = Field(True, description="Atualizar também as fichas do PessoasIQ")
    only_missing: bool = Field(False, description="Saltar as entidades que já têm tudo indexado")


class RecolhaEmpresaRequest(BaseModel):
    """Como recolher os dados societários de **uma** empresa."""

    with_details: bool = Field(True, description="Abrir o detalhe de cada publicação")
    max_pages: int = Field(50, ge=1, le=500, description="Máximo de páginas da grelha")
    tipo: str = Field("0", description="Tipo de publicação (0 = todos os actos)")
    data_ini: Optional[str] = Field(None, description="Data inicial (AAAA-MM-DD)")
    data_fim: Optional[str] = Field(None, description="Data final (AAAA-MM-DD)")
    min_interval: float = Field(4.0, ge=0, le=60, description="Intervalo mínimo entre pedidos ao portal (s)")
    rate_limit_pause: float = Field(90.0, ge=0, le=600, description="Pausa (s) quando o portal limita")
    rate_limit_retries: int = Field(2, ge=0, le=10, description="Novas tentativas quando o portal limita")
    recaptcha_timeout: int = Field(180, ge=30, le=600, description="Timeout da resolução do reCAPTCHA (s)")
    stop_on_captcha: bool = Field(False, description="Parar ao primeiro captcha rejeitado")
    api_key: Optional[str] = Field(None, description="API key da 2captcha (fallback à variável de ambiente)")
    proxy: Optional[str] = Field(None, description="Proxy HTTP(S) para o portal e a 2captcha")
    debug: bool = Field(False, description="Guardar páginas HTML de debug")
    ingest: bool = Field(True, description="Indexar logo no Elasticsearch (e alimentar o PessoasIQ)")


@router.get("/meta")
def recolha_meta(session: ReadSession = None) -> Dict[str, Any]:
    """Pasta dos ficheiros JSON, índice de destino e volumetria do que está exportado."""
    return recolha.meta()


@router.get("/years")
def recolha_years(session: ReadSession = None) -> Dict[str, Any]:
    """Anos com contratos indexados — o eixo do filtro «ir pelos anos dos contratos»."""
    res = recolha.years()
    if res.get("error"):
        raise HTTPException(status_code=502, detail=res["error"])
    return res


@router.get("/targets")
def recolha_targets(
    ano_ini: Optional[int] = Query(None, ge=1900, le=2100),
    ano_fim: Optional[int] = Query(None, ge=1900, le=2100),
    papel: str = Query("ambos", pattern=PAPEL_PATTERN),
    q: Optional[str] = Query(None, description="Firma/denominação da empresa (ou NIF)"),
    nifs: Optional[List[str]] = Query(None, description="Empresas concretas (repetir o parâmetro)"),
    min_contracts: int = Query(1, ge=1),
    min_value: Optional[float] = Query(None, ge=0),
    exclude_collected: bool = Query(True),
    limit: int = Query(50, ge=1, le=500),
    from_: int = Query(0, ge=0, alias="from"),
    session: ReadSession = None,
) -> Dict[str, Any]:
    """Entidades alvo da recolha societária, filtradas por ano de contrato e/ou empresa.

    ``ano_ini``/``ano_fim`` restringem às empresas com contratos nesses anos
    (`period_contracts`/`period_value` no item); ``q`` procura pela firma ou NIF;
    ``nifs`` fixa empresas concretas.
    """
    try:
        res = recolha.targets(
            ano_ini=ano_ini,
            ano_fim=ano_fim,
            papel=papel,
            q=q,
            nifs=nifs,
            min_contracts=min_contracts,
            min_value=min_value,
            exclude_collected=exclude_collected,
            limit=limit,
            from_=from_,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if res.get("error"):
        raise HTTPException(status_code=502, detail=res["error"])
    return res


@router.post("/jobs")
def recolha_start_job(req: RecolhaJobRequest, session: Session) -> Dict[str, Any]:
    """Arranca a recolha massiva em segundo plano (devolve o id do trabalho)."""
    payload = req.model_dump()
    try:
        return recolha.start_job(payload)
    except Exception as exc:
        logger.exception("Falha a arrancar a recolha massiva")
        raise HTTPException(status_code=502, detail=f"Erro ao arrancar a recolha: {exc}") from exc


# --- empresa a empresa (pesquisar → obter dados → ver dados) -----------------

@router.get("/empresas")
def recolha_empresas(
    q: str = Query(..., min_length=2, description="Firma/denominação ou NIF da empresa"),
    limit: int = Query(10, ge=1, le=50),
    session: ReadSession = None,
) -> Dict[str, Any]:
    """Pesquisar empresas (firma ou NIF) para obter dados societários.

    Cada resultado diz quantos contratos/valor tem, quantas publicações já estão
    indexadas e se já existe ficheiro JSON exportado.
    """
    res = recolha.search_companies(q, limit=limit)
    if res.get("error"):
        raise HTTPException(status_code=502, detail=res["error"])
    return res


@router.get("/empresas/{nif}")
def recolha_empresa(
    nif: str,
    limit_items: int = Query(20, ge=0, le=500, description="Publicações a devolver na pré-visualização"),
    session: ReadSession = None,
) -> Dict[str, Any]:
    """Ficha de empresa: o que já existe (JSON exportado e/ou índice) e os dados."""
    res = recolha.company_overview(nif, limit_items=limit_items)
    if res.get("error"):
        raise HTTPException(status_code=404, detail=res["error"])
    return res


@router.post("/empresas/{nif}/obter")
def recolha_obter_empresa(nif: str, req: RecolhaEmpresaRequest, session: Session) -> Dict[str, Any]:
    """Recolhe (e grava em JSON) os dados societários de uma empresa.

    Reutiliza a máquina dos trabalhos: corre em segundo plano, com pausa e nova
    tentativa se o portal do MJ limitar os pedidos. O progresso segue-se em
    `GET /societario/recolha/jobs/{id}`.
    """
    chave = str(nif or "").strip()
    if not chave:
        raise HTTPException(status_code=400, detail="Indique o NIF/NIPC da empresa.")
    payload = {
        **req.model_dump(),
        "nifs": [chave],
        "max_entities": 1,
        "exclude_collected": False,
    }
    try:
        return recolha.start_job(payload)
    except Exception as exc:
        logger.exception("Falha a arrancar a recolha da empresa %s", chave)
        raise HTTPException(status_code=502, detail=f"Erro ao arrancar a recolha: {exc}") from exc


@router.get("/jobs")
def recolha_jobs(session: ReadSession = None) -> Dict[str, Any]:
    """Estado dos trabalhos de recolha massiva (mais recentes primeiro)."""
    return recolha.list_jobs()


@router.get("/jobs/{job_id}")
def recolha_job(job_id: str, session: ReadSession = None) -> Dict[str, Any]:
    """Progresso de um trabalho de recolha massiva."""
    job = recolha.job_status(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Trabalho de recolha não encontrado.")
    return job


def _controlar(job_id: str, acao: str) -> Dict[str, Any]:
    """Aplica pausa/retoma/paragem a um trabalho e devolve o estado atualizado."""
    funcoes = {"pause": recolha.pause_job, "resume": recolha.resume_job, "stop": recolha.stop_job}
    job = funcoes[acao](job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Trabalho de recolha não encontrado.")
    return job


@router.post("/jobs/{job_id}/pause")
def recolha_pausar_job(job_id: str, session: Session) -> Dict[str, Any]:
    """Pausa a recolha (a thread para no próximo ponto de controlo e espera)."""
    return _controlar(job_id, "pause")


@router.post("/jobs/{job_id}/resume")
def recolha_retomar_job(job_id: str, session: Session) -> Dict[str, Any]:
    """Retoma um trabalho pausado (recomeça a entidade que ficou a meio)."""
    return _controlar(job_id, "resume")


@router.post("/jobs/{job_id}/stop")
def recolha_parar_job(job_id: str, session: Session) -> Dict[str, Any]:
    """Para o trabalho, guardando o que já foi recolhido."""
    return _controlar(job_id, "stop")


@router.get("/exports")
def recolha_exports(session: ReadSession = None) -> Dict[str, Any]:
    """Ficheiros JSON exportados (um por entidade) e volumetria total."""
    return recolha.list_exports()


@router.post("/exports/ingest")
def recolha_ingest_exports(req: RecolhaIngestRequest, session: Session) -> Dict[str, Any]:
    """Indexa os ficheiros JSON exportados em `finance_publicacoes_mj`.

    Por omissão indexa todos os ficheiros; com ``nifs`` só esses. Com
    ``only_missing`` salta o que já está indexado.
    """
    res = recolha.ingest_exports(nifs=req.nifs, with_people=req.with_people, only_missing=req.only_missing)
    if res.get("errors") and not res.get("indexed"):
        raise HTTPException(status_code=502, detail=res["errors"][0].get("error") or "Falha ao indexar.")
    return res


@router.get("/exports/{nif}")
def recolha_export(nif: str, limit_items: int = Query(20, ge=0, le=500), session: ReadSession = None) -> Dict[str, Any]:
    """Pré-visualização do ficheiro exportado de uma entidade.

    «Ainda não há ficheiro» **não é erro**: é o estado normal enquanto o trabalho
    não gravou a primeira página — e a ficha da entidade consulta isto a cada 3 s
    durante a recolha. Devolve-se 200 com `exists=false` e lista vazia (o 404
    enchia os logs de «erro» em cada ciclo e escondia os NIFs realmente inválidos).
    Só um ficheiro **ilegível** ou com formato inesperado continua a dar erro.
    """
    chave = str(nif or "").strip()
    res = recolha.read_export(chave, limit_items=limit_items)
    erro = str(res.get("error") or "")
    if erro:
        if erro.startswith("Sem ficheiro exportado"):
            return {"nif": chave, "exists": False, "items": [], "items_total": 0, "error": None}
        raise HTTPException(status_code=404, detail=erro)
    res["exists"] = True
    return res


@router.delete("/exports/{nif}")
def recolha_delete_export(nif: str, session: Session) -> Dict[str, Any]:
    """Apaga o ficheiro exportado de uma entidade."""
    return recolha.delete_export(nif)
