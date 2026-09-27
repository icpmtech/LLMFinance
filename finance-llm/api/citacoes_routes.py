"""Rotas do módulo «Citação e Notificação Edital» (`/citacoes/*`).

Fonte: ``citius.mj.pt`` → «Citação e Notificação Edital» (Ministério da Justiça).
São as citações e notificações **editais** — publicadas quando o citando/
notificado não foi encontrado — com o tribunal, o ato, a referência, o processo,
a espécie, a data e os intervenientes (exequente, executado, réu, requerido,
agente de execução, …), além do documento em PDF.

Fluxo do módulo (como os restantes da solução)
1. **Recolha** — `POST /citacoes/collect` pesquisa o portal pelo nome do
   interveniente, percorre a lista de resultados e grava os dados em **JSON**
   (`data/citacoes/runs/<run_id>.json` + `.meta.json`). Corre em segundo plano;
   o progresso vê-se em `GET /citacoes/jobs/{id}`.
2. **Importação** — `POST /citacoes/ingest` lê o JSON gravado e indexa no
   Elasticsearch (`finance_citacoes_edital`). Pode repetir-se (o `_id` é o
   `pub_id`: os documentos já existentes são ignorados).
3. **Pesquisa** — `GET /citacoes/search` e `GET /citacoes/status` sobre o índice.

Leitura (pública)
- `GET  /citacoes/meta`       — metadados do módulo
- `GET  /citacoes/options`    — serviços/tribunais do portal (cache 1 h)
- `GET  /citacoes/status`     — volumetria do índice
- `GET  /citacoes/search`     — pesquisar éditos indexados
- `GET  /citacoes/graph`      — grafo (rede de entidades, tribunais, tipos e tempo)
- `GET  /citacoes/map`        — mapa OpenStreetMap (por sede, comarca ou serviço)
- `GET  /citacoes/documentos/{pub_id}` — texto extraído do PDF de um édito
- `GET  /citacoes/runs`       — recolhas gravadas em `data/citacoes/runs`
- `GET  /citacoes/runs/{id}`  — resumo/estado de uma recolha
- `GET  /citacoes/jobs`       — recolhas em curso e recentes

Escrita (sessão)
- `POST   /citacoes/collect`        — arrancar recolha (grava JSON, extrai os PDF, opcionalmente importa)
- `POST   /citacoes/runs/{id}/documentos` — extrair o texto dos PDF de uma recolha já gravada
- `POST   /citacoes/jobs/{id}/stop` — parar uma recolha em curso
- `POST   /citacoes/ingest`         — importar uma recolha gravada para o Elasticsearch
- `DELETE /citacoes/runs/{run_id}`  — apagar os ficheiros de uma recolha
"""
from __future__ import annotations

import logging
import threading
import uuid
from datetime import datetime, timezone
from typing import Annotated, Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from api import citacoes_service
from api.auth_routes import CurrentSession, require_session

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/citacoes", tags=["citacoes"])

Session = Annotated[CurrentSession, Depends(require_session)]

MAX_JOBS = 20


# ------------------------------------------------------------------ modelos
class CitacoesCollectRequest(BaseModel):
    """Critérios da recolha (os campos do formulário do portal)."""

    nome: Optional[str] = Field(
        None,
        description=(
            "Nome do interveniente a pesquisar. O portal exige o nome no formulário, mas o "
            "servidor aceita o campo vazio: com `todos=true` (ou sem nome) a recolha traz a "
            "**lista completa** de éditos publicados."
        ),
    )
    todos: bool = Field(
        False,
        description=(
            "Recolher a lista completa do portal (sem filtrar por nome). Implica uma recolha longa "
            "(o portal tem dezenas de milhares de éditos): usar com `meses` para limitar ao período."
        ),
    )
    tribunal: Optional[str] = Field(
        None,
        description="Serviço/tribunal (rótulo, ex.: «Porto - Tribunal Judicial da Comarca do Porto»); omisso = todos",
    )
    dias: str = Field("todos", description="Atalho do portal: 15 | 30 | todos")
    meses: Optional[int] = Field(
        citacoes_service.DEFAULT_MONTHS,
        ge=0,
        le=citacoes_service.MAX_MONTHS,
        description=(
            "Últimos N meses a recolher (por omissão 6). O portal devolve os éditos por data "
            "descendente, pelo que a recolha para sozinha ao passar esse limite. Use 0 para recolher tudo."
        ),
    )
    max_pages: int = Field(200, ge=1, le=5000, description="Máximo de páginas (10 éditos/página)")
    max_items: Optional[int] = Field(None, ge=1, description="Máximo de éditos a recolher")
    extrair_documentos: bool = Field(
        True,
        description=(
            "Descarregar e analisar o PDF de cada édito (texto integral, modelo, valor da execução, "
            "prazo e NIF dos intervenientes). O token do documento está ligado à sessão da pesquisa, "
            "pelo que a extração tem de ser feita durante a recolha."
        ),
    )
    max_documentos: int = Field(
        citacoes_service.DEFAULT_MAX_DOCUMENTOS,
        ge=0,
        le=5000,
        description="Documentos a extrair por recolha (0 = todos os éditos recolhidos). Cada documento é um pedido ao portal.",
    )
    min_interval: float = Field(1.2, ge=0, le=30, description="Intervalo mínimo entre pedidos ao portal (segundos)")
    partial_every: int = Field(
        citacoes_service.DEFAULT_PARTIAL_PAGES,
        ge=0,
        le=1000,
        description=(
            "Páginas entre gravações do progresso parcial em JSON (0 = só no fim). A lista completa "
            "tem ~2 700 páginas e leva horas: com isto, um bloqueio do portal não perde o que já foi recolhido."
        ),
    )
    workers: int = Field(
        1,
        ge=1,
        le=8,
        description=(
            "Sessões em paralelo na recolha completa: o trabalho divide-se pelos 257 serviços/tribunais "
            "(cada sessão só pode paginar em série). Com 4 sessões, os ~27 mil éditos passam de ~5 h para pouco "
            "mais de 1 h. Ignorado quando a recolha é por nome."
        ),
    )
    proxy: Optional[str] = Field(None, description="Proxy HTTP(S) para os pedidos ao portal")
    index: bool = Field(True, description="Importar para o Elasticsearch depois de gravar o JSON")


class CitacoesIngestRequest(BaseModel):
    """Importação de uma recolha gravada em disco."""
    run_id: Optional[str] = Field(None, description="Recolha a importar (por omissão, a mais recente)")
    items: Optional[List[Dict[str, Any]]] = Field(None, description="Itens avulsos, em alternativa ao `run_id`")
    save_json: bool = Field(False, description="Quando são enviados `items` avulsos, gravá-los também como recolha")
    update_existing: bool = Field(
        False,
        description=(
            "Reescrever os documentos que já existem no índice (por omissão são ignorados: "
            "`skipped_existing` conta quantos já lá estavam)"
        ),
    )


class CitacoesDocumentosRequest(BaseModel):
    """Extração do texto dos PDF de uma recolha gravada."""

    max_documentos: int = Field(
        citacoes_service.DEFAULT_MAX_DOCUMENTOS,
        ge=0,
        le=5000,
        description="Documentos a extrair nesta passagem (0 = todos)",
    )
    max_text_chars: int = Field(
        citacoes_service.MAX_TEXT_CHARS, ge=500, le=500_000, description="Teto de caracteres guardados por documento"
    )
    force: bool = Field(False, description="Extrair outra vez mesmo nos éditos que já têm texto")
    min_interval: float = Field(1.2, ge=0, le=30, description="Intervalo mínimo entre pedidos ao portal (segundos)")
    index: bool = Field(True, description="Reenviar ao Elasticsearch os éditos atualizados")


# ------------------------------------------------------------------ jobs
_jobs: Dict[str, Dict[str, Any]] = {}
_lock = threading.Lock()


def _job_update(job_id: str, **fields: Any) -> None:
    with _lock:
        job = _jobs.get(job_id)
        if job:
            job.update(fields)
            job["updated_at"] = datetime.now(timezone.utc).isoformat()


def _run_collect(job_id: str, req: CitacoesCollectRequest) -> None:
    """Trabalhador da recolha: grava o JSON e (opcionalmente) importa para o Elasticsearch."""
    try:
        _job_update(job_id, state="running", stage="recolher")

        def on_progress(info: Dict[str, Any]) -> None:
            _job_update(
                job_id,
                stage=info.get("stage") or "recolher",
                page=info.get("page"),
                pages=info.get("pages"),
                collected=info.get("collected"),
                declared_total=info.get("declared_total"),
                documento=info.get("documento"),
                documentos=info.get("documentos"),
                documento_titulo=info.get("titulo") or None,
                documento_referencia=info.get("referencia") or None,
                documentos_extraidos=info.get("extraidos"),
                documentos_falhados=info.get("falhados"),
                servicos_feitos=info.get("servicos_feitos"),
                servicos_total=info.get("servicos_total"),
                servico=info.get("servico") or None,
            )

        resultado = citacoes_service.collect(
            nome=req.nome,
            todos=req.todos,
            tribunal=req.tribunal,
            dias=req.dias,
            meses=req.meses,
            max_pages=req.max_pages,
            max_items=req.max_items,
            extrair_documentos=req.extrair_documentos,
            max_documentos=req.max_documentos,
            min_interval=req.min_interval,
            partial_every=req.partial_every,
            workers=req.workers,
            proxy=req.proxy,
            on_progress=on_progress,
            stop=lambda: bool(_jobs.get(job_id, {}).get("stop_requested")),
        )
        meta_info = resultado["meta"]
        _job_update(
            job_id,
            run_id=resultado["run_id"],
            collected=meta_info["collected"],
            declared_total=meta_info["declared_total"],
            declared_pages=meta_info.get("declared_pages"),
            pages=meta_info["pages"],
            older_than_cutoff=meta_info.get("older_than_cutoff"),
            duration_s=meta_info.get("duration_s"),
            documentos_extraidos=meta_info.get("documentos_extraidos"),
            documentos_falhados=meta_info.get("documentos_falhados"),
            documentos_caracteres=meta_info.get("documentos_caracteres"),
            errors=meta_info.get("errors") or [],
        )

        if req.index and meta_info["collected"]:
            _job_update(job_id, stage="importar")
            ingest = citacoes_service.ingest_run(resultado["run_id"])
            _job_update(
                job_id,
                indexed=ingest.get("indexed_count", 0),
                skipped_existing=ingest.get("skipped_existing", 0),
                index_total=ingest.get("index_total"),
            )

        estado = "stopped" if meta_info.get("stopped") else "done"
        if meta_info.get("errors") and not meta_info["collected"]:
            estado = "error"
        if not meta_info["collected"] and not meta_info.get("errors"):
            estado = "empty"
        _job_update(job_id, state=estado, stage="concluído", finished=True)
    except Exception as exc:  # noqa: BLE001
        logger.exception("Recolha de citações editais falhou (job %s)", job_id)
        _job_update(job_id, state="error", stage="erro", error=str(exc), finished=True)


def _run_documentos(job_id: str, run_id: str, req: CitacoesDocumentosRequest) -> None:
    """Trabalhador da extração de documentos: reabre a recolha e completa o texto dos PDF."""
    try:
        _job_update(job_id, state="running", stage="documentos")

        def on_progress(info: Dict[str, Any]) -> None:
            _job_update(
                job_id,
                stage="documentos",
                documento=info.get("documento"),
                documentos=info.get("documentos"),
                documento_titulo=info.get("titulo") or None,
                documento_referencia=info.get("referencia") or None,
                documentos_extraidos=info.get("extraidos"),
                documentos_falhados=info.get("falhados"),
            )

        resultado = citacoes_service.extrair_documentos_run(
            run_id,
            max_documentos=req.max_documentos,
            max_text_chars=req.max_text_chars,
            force=req.force,
            min_interval=req.min_interval,
            reindex=req.index,
            on_progress=on_progress,
            stop=lambda: bool(_jobs.get(job_id, {}).get("stop_requested")),
        )
        _job_update(
            job_id,
            estado_final=resultado.get("mensagem") or None,
            collected=resultado.get("extraidos"),
            documentos_extraidos=resultado.get("extraidos"),
            documentos_falhados=resultado.get("falhados"),
            documentos_pendentes=resultado.get("por_extrair"),
            documentos_caracteres=resultado.get("caracteres"),
            indexed=resultado.get("indexado"),
            index_total=resultado.get("index_total"),
            errors=[resultado["error"]] if resultado.get("error") else [],
            stop_requested=False,
        )
        _job_update(job_id, state="done", stage="concluído", finished=True)
    except Exception as exc:  # noqa: BLE001
        logger.exception("Extração de documentos das citações editais falhou (job %s)", job_id)
        _job_update(job_id, state="error", stage="erro", error=str(exc), finished=True)


# ------------------------------------------------------------------ leitura
@router.get("/meta")
def citacoes_meta() -> Dict[str, Any]:
    """Metadados do módulo: fonte, índice, ficheiros e limites."""
    return citacoes_service.meta()


@router.get("/options")
def citacoes_options(refresh: bool = Query(False, description="Ignorar a cache das opções")) -> Dict[str, Any]:
    """Serviços/tribunais disponíveis no formulário do portal."""
    return citacoes_service.form_options(force=refresh)


@router.get("/status")
def citacoes_status_endpoint() -> Dict[str, Any]:
    """Volumetria do índice (documentos, datas e distribuições)."""
    res = citacoes_service.status()
    if res.get("error"):
        raise HTTPException(status_code=502, detail=res["error"])
    return res


@router.get("/search")
def citacoes_search(
    q: Optional[str] = Query(None, description="Texto livre (interveniente, tribunal, processo, ato)"),
    referencia: Optional[str] = Query(None, description="Referência do édito no portal"),
    processo: Optional[str] = Query(None, description="Número/identificação do processo"),
    tribunal: Optional[str] = Query(None, description="Tribunal (texto parcial)"),
    tribunal_comarca: Optional[str] = Query(None, description="Sede do tribunal (terra, exato)"),
    comarca_judicial: Optional[str] = Query(None, description="Comarca judicial (exato, ex.: «Santarém»)"),
    tipo: Optional[str] = Query(None, description="Citação | Notificação | Anúncio"),
    ato: Optional[str] = Query(None, description="Ato publicado (texto parcial)"),
    especie: Optional[str] = Query(None, description="Espécie do processo (texto parcial)"),
    citado: Optional[str] = Query(None, description="Nome do citado/réu/executado principal"),
    nome: Optional[str] = Query(None, description="Nome de um interveniente (qualquer papel)"),
    nomes: Optional[List[str]] = Query(None, description="Várias grafias da mesma entidade (repetir o parâmetro)"),
    papel: Optional[str] = Query(None, description="Papel do interveniente (Exequente, Executado, Réu, Credor, …)"),
    nif: Optional[str] = Query(None, description="NIF/NIPC de um interveniente (da lista ou do documento)"),
    modelo: Optional[str] = Query(None, description="Modelo do documento analisado (ex.: «547/0.05»)"),
    titulo: Optional[str] = Query(None, description="Título do documento analisado (ex.: «CITAÇÃO EDITAL ELETRÓNICA»)"),
    data_from: Optional[str] = Query(None, description="Data de publicação mínima (AAAA-MM-DD)"),
    data_to: Optional[str] = Query(None, description="Data de publicação máxima (AAAA-MM-DD)"),
    has_documento: Optional[bool] = Query(None),
    has_texto: Optional[bool] = Query(None, description="Só éditos com o texto do PDF já extraído"),
    with_texto: bool = Query(False, description="Incluir o texto integral em cada resultado (pesado)"),
    size: int = Query(20, ge=1, le=200),
    from_: int = Query(0, ge=0, alias="from"),
) -> Dict[str, Any]:
    """Pesquisa as citações/notificações editais já indexadas."""
    res = citacoes_service.search(
        q=q,
        referencia=referencia,
        processo=processo,
        tribunal=tribunal,
        tribunal_comarca=tribunal_comarca,
        comarca_judicial=comarca_judicial,
        tipo=tipo,
        ato=ato,
        especie=especie,
        citado=citado,
        nome=nome,
        nomes=nomes,
        papel=papel,
        nif=nif,
        modelo=modelo,
        titulo=titulo,
        data_from=data_from,
        data_to=data_to,
        has_documento=has_documento,
        has_texto=has_texto,
        with_texto=with_texto,
        size=size,
        from_=from_,
    )
    if res.get("error"):
        raise HTTPException(status_code=502, detail=res["error"])
    return res


@router.get("/entidades")
def citacoes_entidades(
    q: Optional[str] = Query(None, description="Nome (ou parte) da entidade/interveniente a procurar"),
    papel: Optional[str] = Query(None, description="Papel do interveniente (Exequente, Executado, Réu, Credor, …)"),
    tipo: Optional[str] = Query(None, description="Citação | Notificação | Anúncio"),
    tribunal: Optional[str] = Query(None, description="Tribunal (texto parcial)"),
    tribunal_comarca: Optional[str] = Query(None, description="Sede do tribunal (terra, exato)"),
    comarca_judicial: Optional[str] = Query(None, description="Comarca judicial (exato, ex.: «Santarém»)"),
    data_from: Optional[str] = Query(None, description="Data de publicação mínima (AAAA-MM-DD)"),
    data_to: Optional[str] = Query(None, description="Data de publicação máxima (AAAA-MM-DD)"),
    has_texto: Optional[bool] = Query(None, description="Só éditos com o texto do PDF já extraído"),
    min_editais: int = Query(1, ge=1, le=1000, description="Ignorar entidades com menos éditos do que isto"),
    size: int = Query(25, ge=1, le=200, description="Máximo de entidades devolvidas"),
) -> Dict[str, Any]:
    """**Entidades dos éditos**: pesquisar por nome e filtrar (papel, tipo, tribunal, datas).

    Devolve, por entidade, o nº de éditos distintos, os papéis em que aparece e os
    NIF/NIPC conhecidos — é o que permite escolher uma entidade e depois filtrar a
    lista de éditos por ela (`GET /citacoes/search?nome=…`).
    """
    res = citacoes_service.entidades(
        q=q,
        papel=papel,
        tipo=tipo,
        tribunal=tribunal,
        tribunal_comarca=tribunal_comarca,
        comarca_judicial=comarca_judicial,
        data_from=data_from,
        data_to=data_to,
        has_texto=has_texto,
        min_editais=min_editais,
        size=size,
    )
    if res.get("error"):
        raise HTTPException(status_code=502, detail=res["error"])
    return res


@router.get("/graph/dimensions")
def citacoes_graph_dimensions() -> Dict[str, Any]:
    """Dimensões, métricas e receitas disponíveis para o grafo."""
    return citacoes_service.grafo_dimensoes()


@router.get("/graph")
def citacoes_graph(
    dimension_a: str = Query(..., description="Dimensão dos nós (interveniente, papel, tribunal, comarca, tipo, mes…)"),
    dimension_b: Optional[str] = Query(
        None,
        description="Dimensão das arestas. Igual a `dimension_a` cria uma rede de co-ocorrência "
        "(intervenientes citados no mesmo édito); omisso devolve apenas nós.",
    ),
    metric: str = Query("editais", pattern="^(editais|mencoes)$"),
    q: Optional[str] = Query(None, description="Texto livre (interveniente, tribunal, processo, ato, texto do PDF)"),
    tipo: Optional[str] = Query(None, description="Citação | Notificação | Anúncio"),
    comarca_judicial: Optional[str] = Query(None, description="Comarca judicial (exato)"),
    tribunal: Optional[str] = Query(None, description="Tribunal (texto parcial)"),
    papel: Optional[str] = Query(None, description="Restringe às publicações com este papel"),
    nif: Optional[str] = Query(None, description="Restringe aos éditos com este NIF/NIPC"),
    modelo: Optional[str] = Query(None, description="Restringe pelo modelo do documento analisado"),
    data_from: Optional[str] = Query(None, description="Data de publicação mínima (AAAA-MM-DD)"),
    data_to: Optional[str] = Query(None, description="Data de publicação máxima (AAAA-MM-DD)"),
    has_texto: Optional[bool] = Query(None, description="Só éditos com documento analisado"),
    min_count: int = Query(1, ge=1, le=1000, description="Éditos mínimos para um nó ser incluído"),
    limit: int = Query(60, ge=0, le=5000, description="Nós a manter (0 = todos)"),
    edge_limit: int = Query(400, ge=0, le=20_000, description="Arestas a manter (0 = todas)"),
    max_docs: int = Query(20_000, ge=0, le=50_000, description="Documentos analisados na varredura (0 = teto do servidor)"),
) -> Dict[str, Any]:
    """Constrói o grafo dos éditos (rede de entidades, tribunais, tipos e tempo).

    Cada nó é uma entidade, tribunal, comarca, tipo, modelo ou período; cada
    aresta liga dois valores que co-ocorrem no mesmo édito (ou liga duas
    dimensões distintas, ex.: parte ativa → parte passiva).
    """
    result = citacoes_service.grafo(
        dimension_a=dimension_a,
        dimension_b=dimension_b,
        metric=metric,
        q=q,
        tipo=tipo,
        comarca_judicial=comarca_judicial,
        tribunal=tribunal,
        papel=papel,
        nif=nif,
        modelo=modelo,
        data_from=data_from,
        data_to=data_to,
        has_texto=has_texto,
        min_count=min_count,
        limit=limit,
        edge_limit=edge_limit,
        max_docs=max_docs or 0,
    )
    if result.get("error"):
        raise HTTPException(status_code=502, detail=result["error"])
    return result


@router.get("/map")
def citacoes_map(
    nivel: str = Query(
        "sede",
        pattern="^(sede|comarca|tribunal)$",
        description="Agregação do mapa: sede do tribunal (terra) | comarca judicial | serviço completo",
    ),
    q: Optional[str] = Query(None, description="Texto livre (interveniente, tribunal, processo, ato, texto do PDF)"),
    tipo: Optional[str] = Query(None, description="Citação | Notificação | Anúncio"),
    comarca_judicial: Optional[str] = Query(None, description="Comarca judicial (exato)"),
    tribunal: Optional[str] = Query(None, description="Tribunal (texto parcial)"),
    papel: Optional[str] = Query(None, description="Restringe às publicações com este papel"),
    nif: Optional[str] = Query(None, description="Restringe aos éditos com este NIF/NIPC"),
    modelo: Optional[str] = Query(None, description="Restringe pelo modelo do documento analisado"),
    data_from: Optional[str] = Query(None, description="Data de publicação mínima (AAAA-MM-DD)"),
    data_to: Optional[str] = Query(None, description="Data de publicação máxima (AAAA-MM-DD)"),
    has_texto: Optional[bool] = Query(None, description="Só éditos com documento analisado"),
) -> Dict[str, Any]:
    """Pontos do mapa OpenStreetMap (sede, comarca ou serviço) com contagens e valor.

    A geocodificação é **offline** (tabelas do GeoNames já usadas pelo GLEIF); as
    chaves sem coordenadas conhecidas saem em `sem_localizacao`, para o mapa não
    inventar posições.
    """
    result = citacoes_service.mapa(
        nivel=nivel,
        q=q,
        tipo=tipo,
        comarca_judicial=comarca_judicial,
        tribunal=tribunal,
        papel=papel,
        nif=nif,
        modelo=modelo,
        data_from=data_from,
        data_to=data_to,
        has_texto=has_texto,
    )
    if result.get("error"):
        raise HTTPException(status_code=502, detail=result["error"])
    return result


@router.get("/runs")
def citacoes_runs(limit: int = Query(50, ge=1, le=200)) -> Dict[str, Any]:
    """Recolhas gravadas em `data/citacoes/runs` (com a contagem no índice)."""
    items = citacoes_service.runs_with_index_counts(limit=limit)
    return {"items": items, "total": len(items), "directory": str(citacoes_service.RUNS_DIR)}


@router.get("/runs/{run_id}")
def citacoes_run_detail(run_id: str, with_items: bool = Query(False)) -> Dict[str, Any]:
    """Resumo de uma recolha (e, opcionalmente, os itens gravados no JSON)."""
    try:
        meta_info = citacoes_service.load_run_meta(run_id)
        if not meta_info:
            payload = citacoes_service.load_run(run_id)
            meta_info = {"run_id": run_id, "collected": payload.get("count", 0)}
        if with_items:
            payload = citacoes_service.load_run(run_id)
            meta_info = {**meta_info, "criteria_source": payload.get("criteria"), "items": payload.get("items", [])}
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return meta_info


@router.get("/documentos/{pub_id}")
def citacoes_documento(pub_id: str) -> Dict[str, Any]:
    """Texto extraído do PDF de um édito (e o que a análise retirou dele)."""
    res = citacoes_service.texto_documento(pub_id)
    if res.get("error"):
        raise HTTPException(status_code=404, detail=res["error"])
    return res


@router.get("/jobs")
def citacoes_jobs(_session: Session) -> Dict[str, Any]:
    """Recolhas em curso e recentes (mais recentes primeiro)."""
    with _lock:
        jobs = sorted(_jobs.values(), key=lambda j: j.get("created_at", ""), reverse=True)
    return {"jobs": jobs[:MAX_JOBS]}


@router.get("/jobs/{job_id}")
def citacoes_job(job_id: str, _session: Session) -> Dict[str, Any]:
    """Progresso de uma recolha."""
    with _lock:
        job = _jobs.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Recolha não encontrada")
    return job


# ------------------------------------------------------------------ escrita
@router.post("/collect")
def citacoes_collect(req: CitacoesCollectRequest, session: Session) -> Dict[str, Any]:
    """Arranca a recolha em segundo plano: grava o JSON e (se `index`) importa.

    A gravação em `data/citacoes/runs` é **sempre** feita antes de qualquer
    indexação, para que a recolha possa ser inspecionada e reimportada.
    """
    if req.dias not in ("15", "30", "todos"):
        raise HTTPException(status_code=422, detail="Atalho de dias inválido (use 15, 30 ou todos).")

    job_id = uuid.uuid4().hex[:12]
    job = {
        "id": job_id,
        "state": "queued",
        "stage": "em espera",
        "criteria": req.model_dump(exclude_none=True),
        "collected": 0,
        "pages": 0,
        "indexed": 0,
        "errors": [],
        "stop_requested": False,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "created_by": getattr(getattr(session, "user", None), "id", None) or getattr(session, "email", None),
        "finished": False,
    }
    with _lock:
        _jobs[job_id] = job
        if len(_jobs) > MAX_JOBS:
            for old in sorted(_jobs.values(), key=lambda j: j.get("created_at", ""))[: len(_jobs) - MAX_JOBS]:
                _jobs.pop(old["id"], None)

    threading.Thread(target=_run_collect, args=(job_id, req), name=f"citacoes-{job_id}", daemon=True).start()
    return job


@router.post("/jobs/{job_id}/stop")
def citacoes_job_stop(job_id: str, _session: Session) -> Dict[str, Any]:
    """Pede a paragem de uma recolha em curso (a página atual termina primeiro)."""
    with _lock:
        job = _jobs.get(job_id)
        if not job:
            raise HTTPException(status_code=404, detail="Recolha não encontrada")
        job["stop_requested"] = True
        job["stage"] = "a parar"
        job["updated_at"] = datetime.now(timezone.utc).isoformat()
    return job


@router.post("/runs/{run_id}/documentos")
def citacoes_run_documentos(run_id: str, req: CitacoesDocumentosRequest, session: Session) -> Dict[str, Any]:
    """Extrai (em segundo plano) o texto dos PDF de uma recolha já gravada.

    O token do documento está ligado à sessão da pesquisa, pelo que a operação
    repete a pesquisa no portal com os critérios da recolha e casa os éditos pelo
    `pub_id`. No fim o JSON é atualizado e reenviado ao Elasticsearch.
    """
    job_id = uuid.uuid4().hex[:12]
    job = {
        "id": job_id,
        "kind": "documentos",
        "state": "queued",
        "stage": "em espera",
        "run_id": run_id,
        "criteria": {"run_id": run_id, **req.model_dump(exclude_none=True)},
        "collected": 0,
        "indexed": 0,
        "errors": [],
        "stop_requested": False,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "created_by": getattr(getattr(session, "user", None), "id", None) or getattr(session, "email", None),
        "finished": False,
    }
    with _lock:
        _jobs[job_id] = job
        if len(_jobs) > MAX_JOBS:
            for old in sorted(_jobs.values(), key=lambda j: j.get("created_at", ""))[: len(_jobs) - MAX_JOBS]:
                _jobs.pop(old["id"], None)

    threading.Thread(
        target=_run_documentos, args=(job_id, run_id, req), name=f"citacoes-docs-{job_id}", daemon=True
    ).start()
    return job


@router.post("/ingest")
def citacoes_ingest(req: CitacoesIngestRequest, _session: Session) -> Dict[str, Any]:
    """Importa para o Elasticsearch uma recolha gravada em JSON (ou itens avulsos)."""
    items = req.items
    run_id = req.run_id
    if items and req.save_json:
        run_id = run_id or citacoes_service._new_run_id("ingest")  # noqa: SLF001
        payload = {
            "run_id": run_id,
            "source": "citius_citacoes",
            "criteria": {"origem": "ingest"},
            "collected_at": datetime.now(timezone.utc).isoformat(),
            "count": len(items),
            "items": items,
        }
        meta_info = {
            "run_id": run_id,
            "source": "citius_citacoes",
            "criteria": {"origem": "ingest"},
            "collected": len(items),
            "created_at": datetime.now(timezone.utc).isoformat(),
            "index": citacoes_service.INDEX_NAME,
            "indexed": 0,
        }
        citacoes_service.save_run(payload, meta_info)
    try:
        res = citacoes_service.ingest_run(
            run_id=run_id, items=items, update_existing=req.update_existing
        )
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    if res.get("error"):
        raise HTTPException(status_code=502, detail=res["error"])
    return res


@router.delete("/runs/{run_id}")
def citacoes_run_delete(
    run_id: str,
    _session: Session,
    drop_index: bool = Query(False, description="Remover também do Elasticsearch os éditos desta recolha"),
) -> Dict[str, Any]:
    """Apaga os ficheiros (JSON e resumo) de uma recolha gravada."""
    res = citacoes_service.delete_run(run_id, drop_index=drop_index)
    if not res.get("removed"):
        raise HTTPException(status_code=404, detail=f"Recolha «{run_id}» não encontrada")
    return res
