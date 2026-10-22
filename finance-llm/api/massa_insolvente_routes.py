"""Rotas do módulo Massa Insolvente (`/massa-insolvente/*`).

Fonte: ``citius.mj.pt`` → «Publicidade da Composição da Massa Insolvente»
(art.º 152.º do CIRE, Ministério da Justiça).
"""
from __future__ import annotations

import logging
import threading
import uuid
from datetime import datetime, timezone
from typing import Annotated, Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from api import massa_insolvente_service as massa_service
from api.auth_routes import CurrentSession, require_session

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/massa-insolvente", tags=["massa-insolvente"])

Session = Annotated[CurrentSession, Depends(require_session)]

MAX_JOBS = 20


# ------------------------------------------------------------------ modelos
class MassaCollectRequest(BaseModel):
    """Critérios da recolha (os mesmos campos do formulário do portal)."""

    desde: Optional[str] = Field(None, description="Data inicial (AAAA-MM-DD ou DD/MM/AAAA)")
    ate: Optional[str] = Field(None, description="Data final (AAAA-MM-DD ou DD/MM/AAAA)")
    dias: Optional[str] = Field("15", description="Atalho do portal: 15 (últimos 15 dias)")
    tipo_ativo: Optional[str] = Field(None, description="Tipo de ativo (rótulo, ex.: «Imóvel»)")
    localizacao: Optional[str] = Field(None, description="Localização (concelho, ex.: «Braga [Braga]»)")
    area_negocio: Optional[str] = Field(None, description="Área de negócio / CAE (rótulo)")
    max_pages: int = Field(20, ge=1, le=2000, description="Máximo de páginas por janela")
    max_items: Optional[int] = Field(None, ge=1, description="Máximo de anúncios a recolher")
    window_days: Optional[int] = Field(
        None, ge=1, le=366,
        description="Divide o intervalo em janelas deste tamanho",
    )
    min_interval: float = Field(1.2, ge=0, le=30, description="Intervalo mínimo entre pedidos ao portal (segundos)")
    proxy: Optional[str] = Field(None, description="Proxy HTTP(S) para os pedidos ao portal")
    force: bool = Field(False, description="Reprocessar mesmo que o intervalo já tenha sido recolhido")
    index: bool = Field(True, description="Importar para o Elasticsearch depois de gravar o JSON")
    split_runs: bool = Field(
        False,
        description="Gravar uma recolha por janela de datas em vez de um único ficheiro",
    )


class MassaIngestRequest(BaseModel):
    """Importação de uma recolha gravada em disco."""

    run_id: Optional[str] = Field(None, description="Recolha a importar (por omissão, a mais recente)")
    items: Optional[List[Dict[str, Any]]] = Field(None, description="Itens avulsos, em alternativa ao run_id")
    save_json: bool = Field(False, description="Quando são enviados items avulsos, gravá-los também")
    update_existing: bool = Field(False, description="Reescrever os documentos que já existem no índice")


# ------------------------------------------------------------------ jobs
_jobs: Dict[str, Dict[str, Any]] = {}
_lock = threading.Lock()


def _job_update(job_id: str, **fields: Any) -> None:
    with _lock:
        job = _jobs.get(job_id)
        if job:
            job.update(fields)
            job["updated_at"] = datetime.now(timezone.utc).isoformat()


def _run_collect(job_id: str, req: MassaCollectRequest) -> None:
    try:
        _job_update(job_id, state="running", stage="recolher")

        def on_progress(info: Dict[str, Any]) -> None:
            etapa = info.get("stage") or "recolher"
            _job_update(
                job_id,
                stage=etapa,
                page=info.get("page"),
                pages=info.get("pages"),
                collected=info.get("total_collected") if info.get("total_collected") is not None else info.get("collected"),
                declared_total=info.get("declared_total") or info.get("collected"),
                window=info.get("window"),
                runs_done=info.get("runs"),
                indexed=info.get("indexed") or None,
                file=info.get("file") or None,
                warnings=info.get("warnings") or None,
            )

        resultado = massa_service.collect(
            desde=req.desde,
            ate=req.ate,
            dias=req.dias,
            tipo_ativo=req.tipo_ativo,
            localizacao=req.localizacao,
            area_negocio=req.area_negocio,
            max_pages=req.max_pages,
            max_items=req.max_items,
            window_days=req.window_days,
            min_interval=req.min_interval,
            proxy=req.proxy,
            force=req.force,
            split_runs=req.split_runs,
            ingest_each=req.index and req.split_runs,
            on_progress=on_progress,
            stop=lambda: bool(_jobs.get(job_id, {}).get("stop_requested")),
        )
        meta_info = resultado["meta"]
        _job_update(
            job_id,
            run_id=resultado["run_id"],
            collected=meta_info["collected"],
            declared_total=meta_info["declared_total"],
            pages=meta_info["pages"],
            windows=len(meta_info.get("windows") or []),
            runs=meta_info.get("runs") or [],
            runs_done=len(meta_info.get("runs") or []),
            file=meta_info.get("file"),
            indexed=meta_info.get("indexed") or None,
            skipped_existing=meta_info.get("skipped_existing") or 0,
            errors=meta_info.get("errors") or [],
            warnings=meta_info.get("warnings") or [],
            skipped_windows=meta_info.get("skipped_windows") or [],
        )

        nada_novo = not meta_info["collected"] and bool(meta_info.get("skipped_windows"))
        if req.index and not nada_novo and not req.split_runs:
            _job_update(job_id, stage="importar")
            ingest = massa_service.ingest_run(resultado["run_id"])
            _job_update(
                job_id,
                indexed=ingest.get("indexed_count", 0),
                skipped_existing=ingest.get("skipped_existing", 0),
                index_total=ingest.get("index_total"),
            )

        estado = "stopped" if meta_info.get("stopped") else "done"
        if nada_novo:
            estado = "skipped"
        if meta_info.get("errors") and not meta_info["collected"] and not nada_novo:
            estado = "error"
        _job_update(job_id, state=estado, stage="concluído", finished=True)
    except Exception as exc:  # noqa: BLE001
        logger.exception("Recolha Massa Insolvente falhou (job %s)", job_id)
        _job_update(job_id, state="error", stage="erro", error=str(exc), finished=True)


# ------------------------------------------------------------------ leitura
@router.get("/meta")
def massa_meta() -> Dict[str, Any]:
    """Metadados do módulo: fonte, índice, ficheiros e limites."""
    return massa_service.meta()


@router.get("/options")
def massa_options(refresh: bool = Query(False, description="Ignorar a cache das opções")) -> Dict[str, Any]:
    """Tipos de ativo, localizações e áreas de negócio disponíveis no portal."""
    return massa_service.form_options(force=refresh)


@router.get("/status")
def massa_status() -> Dict[str, Any]:
    """Volumetria do índice (documentos, insolventes, processos, datas)."""
    res = massa_service.status()
    if res.get("error"):
        raise HTTPException(status_code=502, detail=res["error"])
    return res


@router.get("/search")
def massa_search(
    q: Optional[str] = Query(None, description="Texto livre (processo, insolvente, ativo, tribunal)"),
    processo: Optional[str] = Query(None, description="Número/identificação do processo"),
    tipo: Optional[str] = Query(None, description="Insolvência | PER | PEAP | PEVE"),
    especie: Optional[str] = Query(None, description="Espécie do processo"),
    tribunal: Optional[str] = Query(None, description="Tribunal (texto parcial)"),
    tribunal_comarca: Optional[str] = Query(None, description="Comarca (exato)"),
    insolvente: Optional[str] = Query(None, description="Nome do insolvente"),
    ativo_tipo: Optional[str] = Query(None, description="Tipo de ativo (ex.: Imóvel, Veículo)"),
    localizacao: Optional[str] = Query(None, description="Localização do ativo"),
    area_negocio: Optional[str] = Query(None, description="Área de negócio"),
    data_from: Optional[str] = Query(None, description="Data de atualização mínima (AAAA-MM-DD)"),
    data_to: Optional[str] = Query(None, description="Data de atualização máxima (AAAA-MM-DD)"),
    valor_min: Optional[float] = Query(None, ge=0, description="Valor mínimo da avaliação"),
    valor_max: Optional[float] = Query(None, ge=0, description="Valor máximo da avaliação"),
    size: int = Query(20, ge=1, le=200),
    from_: int = Query(0, ge=0, alias="from"),
) -> Dict[str, Any]:
    """Pesquisa os anúncios indexados da massa insolvente."""
    res = massa_service.search(
        q=q,
        processo=processo,
        tipo=tipo,
        especie=especie,
        tribunal=tribunal,
        tribunal_comarca=tribunal_comarca,
        insolvente=insolvente,
        ativo_tipo=ativo_tipo,
        localizacao=localizacao,
        area_negocio=area_negocio,
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


@router.get("/coverage")
def massa_coverage() -> Dict[str, Any]:
    """Janelas/dias já recolhidos — para a UI avisar antes de repetir."""
    return massa_service.coverage()


@router.get("/runs")
def massa_runs(limit: int = Query(50, ge=1, le=200)) -> Dict[str, Any]:
    """Recolhas gravadas em `data/massa_insolvente/runs`."""
    items = massa_service.runs_with_index_counts(limit=limit)
    return {"items": items, "total": len(items), "directory": str(massa_service.RUNS_DIR)}


@router.get("/runs/{run_id}")
def massa_run_detail(run_id: str, with_items: bool = Query(False)) -> Dict[str, Any]:
    """Resumo de uma recolha (e, opcionalmente, os itens gravados no JSON)."""
    try:
        meta_info = massa_service.load_run_meta(run_id)
        if not meta_info:
            payload = massa_service.load_run(run_id)
            meta_info = {"run_id": run_id, "collected": payload.get("count", 0)}
        if with_items:
            try:
                payload = massa_service.load_run(run_id)
            except FileNotFoundError:
                meta_info = {
                    **meta_info,
                    "items": [],
                    "warnings": [*(meta_info.get("warnings") or []), "Recolha sem itens gravados."],
                }
            else:
                meta_info = {
                    **meta_info,
                    "criteria_source": payload.get("criteria"),
                    "items": payload.get("items", []),
                }
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return meta_info


@router.get("/jobs")
def massa_jobs(_session: Session) -> Dict[str, Any]:
    """Recolhas em curso e recentes."""
    with _lock:
        jobs = sorted(_jobs.values(), key=lambda j: j.get("created_at", ""), reverse=True)
    return {"jobs": jobs[:MAX_JOBS]}


@router.get("/jobs/{job_id}")
def massa_job(job_id: str, _session: Session) -> Dict[str, Any]:
    """Progresso de uma recolha."""
    with _lock:
        job = _jobs.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Recolha não encontrada")
    return job


# ------------------------------------------------------------------ escrita
@router.post("/collect")
def massa_collect(req: MassaCollectRequest, session: Session) -> Dict[str, Any]:
    """Arranca a recolha em segundo plano: grava o JSON e (se index) importa."""
    if bool(req.desde) != bool(req.ate):
        raise HTTPException(status_code=422, detail="Indique as duas datas (início e fim) ou nenhuma.")

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

    threading.Thread(target=_run_collect, args=(job_id, req), name=f"massa-{job_id}", daemon=True).start()
    return job


@router.post("/jobs/{job_id}/stop")
def massa_job_stop(job_id: str, _session: Session) -> Dict[str, Any]:
    """Pede a paragem de uma recolha em curso."""
    with _lock:
        job = _jobs.get(job_id)
        if not job:
            raise HTTPException(status_code=404, detail="Recolha não encontrada")
        job["stop_requested"] = True
        job["stage"] = "a parar"
        job["updated_at"] = datetime.now(timezone.utc).isoformat()
    return job


@router.post("/ingest")
def massa_ingest(req: MassaIngestRequest, _session: Session) -> Dict[str, Any]:
    """Importa para o Elasticsearch uma recolha gravada em JSON."""
    items = req.items
    run_id = req.run_id
    if items and req.save_json:
        run_id = run_id or massa_service._new_run_id(None, None, None, None, None)  # noqa: SLF001
        payload = {
            "run_id": run_id,
            "source": "citius_massa_insolvente",
            "criteria": {"origem": "ingest"},
            "collected_at": datetime.now(timezone.utc).isoformat(),
            "count": len(items),
            "items": items,
        }
        meta_info = {
            "run_id": run_id,
            "source": "citius_massa_insolvente",
            "criteria": {"origem": "ingest"},
            "collected": len(items),
            "created_at": datetime.now(timezone.utc).isoformat(),
            "index": "finance_massa_insolvente",
            "indexed": 0,
        }
        massa_service.save_run(payload, meta_info)
    try:
        res = massa_service.ingest_run(run_id=run_id, items=items, update_existing=req.update_existing)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    if res.get("error"):
        raise HTTPException(status_code=502, detail=res["error"])
    return res


@router.delete("/runs/{run_id}")
def massa_run_delete(run_id: str, _session: Session) -> Dict[str, Any]:
    """Apaga os ficheiros (JSON e resumo) de uma recolha gravada."""
    res = massa_service.delete_run(run_id)
    if not res.get("removed"):
        raise HTTPException(status_code=404, detail=f"Recolha «{run_id}» não encontrada")
    return res
