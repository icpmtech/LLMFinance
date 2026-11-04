"""Rotas do módulo «Lista Pública de Execuções» (`/execucoes/*`).

Fonte:
- ``citius.mj.pt`` → «Lista Pública de Execuções».

Fluxo do módulo (como os restantes da solução)
1. **Recolha** — `POST /execucoes/collect` pesquisa o portal e grava os dados em
   JSON (`data/execucoes/runs/<run_id>.json` + `.meta.json`). Corre em segundo
   plano; o progresso vê-se em `GET /execucoes/jobs/{id}`.
2. **Importação** — `POST /execucoes/ingest` lê o JSON gravado e indexa no
   Elasticsearch (`finance_execucoes`). Pode repetir-se (o `_id` é o `pub_id`:
   os documentos já existentes são ignorados).
3. **Pesquisa** — `GET /execucoes/search` e `GET /execucoes/status` sobre o índice.

Leitura (pública)
- `GET  /execucoes/meta`       — metadados do módulo
- `GET  /execucoes/options`    — opções do formulário do CITIUS (cache 1 h)
- `GET  /execucoes/status`     — volumetria do índice
- `GET  /execucoes/search`     — pesquisar execuções indexadas
- `GET  /execucoes/runs`       — recolhas gravadas em `data/execucoes/runs`
- `GET  /execucoes/runs/{id}`  — resumo/estado de uma recolha
- `GET  /execucoes/jobs`       — recolhas em curso e recentes

Escrita (sessão)
- `POST   /execucoes/collect`        — arrancar recolha (grava JSON, opcionalmente importa)
- `POST   /execucoes/ingest`         — importar uma recolha gravada para o Elasticsearch
- `DELETE /execucoes/runs/{run_id}`  — apagar os ficheiros de uma recolha
"""
from __future__ import annotations

import logging
import threading
import uuid
from datetime import datetime, timezone
from typing import Annotated, Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from api import execucoes_service
from api.auth_routes import CurrentSession, require_session
from collectors.citius_execucoes import DIAS_OPCOES

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/execucoes", tags=["execucoes"])

Session = Annotated[CurrentSession, Depends(require_session)]

MAX_JOBS = 20


# ------------------------------------------------------------------ modelos
class ExecucoesCollectRequest(BaseModel):
    """Critérios da recolha da Lista Pública de Execuções."""

    nome: Optional[str] = Field(None, description="Nome do executado (parcial)")
    documento: Optional[str] = Field(None, description="Número do documento de identificação")
    tipo_documento: Optional[str] = Field(
        None,
        description="Tipo de documento: nif | bi | passaporte | cartaconducao",
    )
    numero_processo: Optional[str] = Field(None, description="Número do processo")
    dias: str = Field("todos", description="Atalho de datas: 15 | 30 | todos")
    letras: Optional[List[str]] = Field(
        None,
        description="Lista de letras do alfabeto a recolher (A-Z ou '0'). Omisso = recolha completa.",
    )
    max_pages_per_letra: int = Field(
        execucoes_service.DEFAULT_MAX_PAGES_PER_LETRA,
        ge=1,
        le=12000,
        description="Máximo de páginas CITIUS por letra",
    )
    max_items: Optional[int] = Field(None, ge=1, description="Máximo total de registos a recolher")
    min_interval: float = Field(
        execucoes_service.DEFAULT_MIN_INTERVAL,
        ge=0,
        le=30,
        description="Intervalo mínimo entre pedidos (segundos)",
    )
    proxy: Optional[str] = Field(None, description="Proxy HTTP(S) para os pedidos ao portal")
    index: bool = Field(True, description="Importar para o Elasticsearch depois de gravar o JSON")


class ExecucoesIngestRequest(BaseModel):
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


# ------------------------------------------------------------------ jobs
_jobs: Dict[str, Dict[str, Any]] = {}
_lock = threading.Lock()


def _job_update(job_id: str, **fields: Any) -> None:
    with _lock:
        job = _jobs.get(job_id)
        if job:
            job.update(fields)
            job["updated_at"] = datetime.now(timezone.utc).isoformat()


def _run_collect(job_id: str, req: ExecucoesCollectRequest) -> None:
    """Trabalhador da recolha: invoca o serviço e atualiza o job."""
    try:
        _job_update(job_id, state="running", stage="recolher")

        def on_progress(info: Dict[str, Any]) -> None:
            _job_update(
                job_id,
                stage=info.get("stage") or "recolher",
                page=info.get("page"),
                pages=info.get("pages"),
                declared_total=info.get("declared_total"),
                collected=info.get("collected"),
                letra=info.get("letra") or None,
            )

        resultado = execucoes_service.collect(
            nome=req.nome,
            documento=req.documento,
            tipo_documento=req.tipo_documento,
            numero_processo=req.numero_processo,
            dias=req.dias,
            letras=req.letras,
            max_pages_per_letra=req.max_pages_per_letra,
            max_items=req.max_items,
            min_interval=req.min_interval,
            proxy=req.proxy,
            on_progress=on_progress,
            stop=lambda: bool(_jobs.get(job_id, {}).get("stop_requested")),
        )
        meta_info = resultado["meta"]
        _job_update(
            job_id,
            run_id=resultado["run_id"],
            collected=meta_info["collected"],
            pages=meta_info["pages"],
            duration_s=meta_info.get("duration_s"),
            errors=meta_info.get("errors") or [],
        )

        if req.index and meta_info["collected"]:
            _job_update(job_id, stage="importar")
            ingest = execucoes_service.ingest_run(resultado["run_id"])
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
        logger.exception("Recolha da Lista Pública de Execuções falhou (job %s)", job_id)
        _job_update(job_id, state="error", stage="erro", error=str(exc), finished=True)


# ------------------------------------------------------------------ leitura
@router.get("/meta")
def execucoes_meta() -> Dict[str, Any]:
    """Metadados do módulo: fonte, índice, ficheiros e limites."""
    return execucoes_service.meta()


@router.get("/options")
def execucoes_options(refresh: bool = Query(False, description="Ignorar a cache das opções")) -> Dict[str, Any]:
    """Opções do formulário do CITIUS (alfabeto)."""
    res = execucoes_service.form_options(force=refresh)
    if res.get("error"):
        raise HTTPException(status_code=502, detail=res["error"])
    return res


@router.get("/status")
def execucoes_status_endpoint() -> Dict[str, Any]:
    """Volumetria do índice (documentos, datas, valores e distribuições)."""
    res = execucoes_service.status()
    if res.get("error"):
        raise HTTPException(status_code=502, detail=res["error"])
    return res


@router.get("/search")
def execucoes_search(
    q: Optional[str] = Query(None, description="Texto livre (nome, processo, tribunal, agente)"),
    nome_executado: Optional[str] = Query(None, description="Nome do executado (parcial)"),
    numero_processo: Optional[str] = Query(None, description="Número do processo (parcial)"),
    tribunal: Optional[str] = Query(None, description="Tribunal (texto parcial)"),
    comarca: Optional[str] = Query(None, description="Comarca (exato)"),
    unidade_organica: Optional[str] = Query(None, description="Unidade orgânica (texto parcial)"),
    agente_execucao: Optional[str] = Query(None, description="Agente de execução (texto parcial)"),
    estado: Optional[str] = Query(None, description="Estado da execução (exato)"),
    data_from: Optional[str] = Query(None, description="Data mínima de entrada (AAAA-MM-DD)"),
    data_to: Optional[str] = Query(None, description="Data máxima de entrada (AAAA-MM-DD)"),
    valor_min: Optional[float] = Query(None, ge=0, description="Valor mínimo da execução (€)"),
    valor_max: Optional[float] = Query(None, ge=0, description="Valor máximo da execução (€)"),
    size: int = Query(20, ge=1, le=200, description="Itens por página"),
    from_: int = Query(0, ge=0, alias="from", description="Índice de início"),
) -> Dict[str, Any]:
    """Pesquisa execuções já indexadas."""
    res = execucoes_service.search(
        q=q,
        nome_executado=nome_executado,
        numero_processo=numero_processo,
        tribunal=tribunal,
        comarca=comarca,
        unidade_organica=unidade_organica,
        agente_execucao=agente_execucao,
        estado=estado,
        data_from=data_from,
        data_to=data_to,
        valor_min=valor_min,
        valor_max=valor_max,
        size=size,
        from_=from_,
    )
    if res.get("error"):
        raise HTTPException(status_code=502, detail=res["error"])
    return res


@router.get("/runs")
def execucoes_runs(limit: int = Query(50, ge=1, le=200)) -> Dict[str, Any]:
    """Recolhas gravadas em `data/execucoes/runs` (com a contagem no índice)."""
    items = execucoes_service.runs_with_index_counts(limit=limit)
    return {"items": items, "total": len(items), "directory": str(execucoes_service.RUNS_DIR)}


@router.get("/runs/{run_id}")
def execucoes_run_detail(run_id: str, with_items: bool = Query(False)) -> Dict[str, Any]:
    """Resumo de uma recolha (e, opcionalmente, os itens gravados no JSON)."""
    try:
        meta_info = execucoes_service.load_run_meta(run_id)
        if not meta_info:
            payload = execucoes_service.load_run(run_id)
            meta_info = {"run_id": run_id, "collected": payload.get("count", 0)}
        if with_items:
            payload = execucoes_service.load_run(run_id)
            meta_info = {**meta_info, "criteria_source": payload.get("criteria"), "items": payload.get("items", [])}
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return meta_info


@router.get("/jobs")
def execucoes_jobs(_session: Session) -> Dict[str, Any]:
    """Recolhas em curso e recentes (mais recentes primeiro)."""
    with _lock:
        jobs = sorted(_jobs.values(), key=lambda j: j.get("created_at", ""), reverse=True)
    return {"jobs": jobs[:MAX_JOBS]}


@router.get("/jobs/{job_id}")
def execucoes_job(job_id: str, _session: Session) -> Dict[str, Any]:
    """Progresso de uma recolha."""
    with _lock:
        job = _jobs.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Recolha não encontrada")
    return job


# ------------------------------------------------------------------ escrita
@router.post("/collect")
def execucoes_collect(req: ExecucoesCollectRequest, session: Session) -> Dict[str, Any]:
    """Arranca a recolha em segundo plano: grava o JSON e (se `index`) importa."""
    if req.dias not in DIAS_OPCOES:
        raise HTTPException(status_code=422, detail=f"Atalho de dias inválido: {req.dias} (use 15, 30 ou todos)")
    if req.tipo_documento and req.tipo_documento.lower() not in ("nif", "bi", "passaporte", "cartaconducao"):
        raise HTTPException(
            status_code=422,
            detail=f"Tipo de documento inválido: {req.tipo_documento} (use nif, bi, passaporte ou cartaconducao)",
        )

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

    threading.Thread(target=_run_collect, args=(job_id, req), name=f"execucoes-{job_id}", daemon=True).start()
    return job


@router.post("/jobs/{job_id}/stop")
def execucoes_job_stop(job_id: str, _session: Session) -> Dict[str, Any]:
    """Sinaliza uma recolha em curso para parar."""
    with _lock:
        job = _jobs.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Recolha não encontrada")
    if job.get("finished"):
        raise HTTPException(status_code=409, detail="A recolha já terminou")
    _job_update(job_id, stop_requested=True)
    return {"id": job_id, "stop_requested": True, "state": job.get("state")}


@router.post("/ingest")
def execucoes_ingest(req: ExecucoesIngestRequest, _session: Session) -> Dict[str, Any]:
    """Importa para o Elasticsearch uma recolha gravada em JSON (ou itens avulsos)."""
    items = req.items
    run_id = req.run_id
    if items and req.save_json:
        run_id = run_id or execucoes_service._new_run_id("ingest", extra="manual")
        payload = {
            "run_id": run_id,
            "source": execucoes_service.SOURCE,
            "criteria": {"origem": "ingest"},
            "collected_at": datetime.now(timezone.utc).isoformat(),
            "count": len(items),
            "items": items,
        }
        meta_info = {
            "run_id": run_id,
            "source": execucoes_service.SOURCE,
            "criteria": {"origem": "ingest"},
            "collected": len(items),
            "created_at": datetime.now(timezone.utc).isoformat(),
            "index": execucoes_service.INDEX_NAME,
            "indexed": 0,
        }
        execucoes_service.save_run(payload, meta_info)
    try:
        res = execucoes_service.ingest_run(run_id=run_id, items=items, update_existing=req.update_existing)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    if res.get("error"):
        raise HTTPException(status_code=502, detail=res["error"])
    return res


@router.delete("/runs/{run_id}")
def execucoes_run_delete(
    run_id: str,
    _session: Session,
    drop_index: bool = Query(False, description="Remover também do Elasticsearch as execuções desta recolha"),
) -> Dict[str, Any]:
    """Apaga os ficheiros (JSON e resumo) de uma recolha gravada."""
    res = execucoes_service.delete_run(run_id, drop_index=drop_index)
    if not res.get("removed"):
        raise HTTPException(status_code=404, detail=f"Recolha «{run_id}» não encontrada")
    return res
