"""Rotas do módulo «Venda de Bens Penhorados» (`/vendas/*`).

Fontes:
- ``citius.mj.pt`` → «Venda de Bens Penhorados em Processos Executivos».
- ``e-leiloes.pt`` → vendas promovidas pelos agentes de execução.

Fluxo do módulo (como os restantes da solução)
1. **Recolha** — `POST /vendas/collect` pesquisa os portais e grava os dados em
   JSON (`data/vendas_penhorados/runs/<run_id>.json` + `.meta.json`). Corre em
   segundo plano; o progresso vê-se em `GET /vendas/jobs/{id}`.
2. **Importação** — `POST /vendas/ingest` lê o JSON gravado e indexa no
   Elasticsearch (`finance_vendas_penhorados`). Pode repetir-se (o `_id` é o
   `venda_id`: os documentos já existentes são ignorados).
3. **Pesquisa** — `GET /vendas/search` e `GET /vendas/status` sobre o índice.

Leitura (pública)
- `GET  /vendas/meta`       — metadados do módulo
- `GET  /vendas/options`    — opções do formulário do CITIUS (cache 1 h)
- `GET  /vendas/status`     — volumetria do índice
- `GET  /vendas/search`     — pesquisar vendas indexadas
- `GET  /vendas/runs`       — recolhas gravadas em `data/vendas_penhorados/runs`
- `GET  /vendas/runs/{id}`  — resumo/estado de uma recolha
- `GET  /vendas/jobs`       — recolhas em curso e recentes

Escrita (sessão)
- `POST   /vendas/collect`        — arrancar recolha (grava JSON, opcionalmente importa)
- `POST   /vendas/ingest`         — importar uma recolha gravada para o Elasticsearch
- `DELETE /vendas/runs/{run_id}`  — apagar os ficheiros de uma recolha
"""
from __future__ import annotations

import logging
import threading
import uuid
from datetime import datetime, timezone
from typing import Annotated, Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from api import vendas_service
from api.auth_routes import CurrentSession, require_session

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/vendas", tags=["vendas"])

Session = Annotated[CurrentSession, Depends(require_session)]

MAX_JOBS = 20


# ------------------------------------------------------------------ modelos
class VendasCollectRequest(BaseModel):
    """Critérios da recolha de vendas de bens penhorados."""

    fontes: List[str] = Field(
        default_factory=lambda: ["citius", "eleiloes"],
        description="Fontes a recolher: citius | eleiloes (ou ambas)",
    )
    tribunais: Optional[List[str]] = Field(
        None,
        description="Lista de tribunais/serviços do CITIUS (rótulos). Omisso = todos.",
    )
    desde: Optional[str] = Field(
        None,
        description="Data mínima da venda (AAAA-MM-DD). Por omissão usa a janela aceite pelo CITIUS.",
    )
    ate: Optional[str] = Field(
        None,
        description="Data máxima da venda (AAAA-MM-DD). Por omissão usa a janela aceite pelo CITIUS.",
    )
    tipo_bem: Optional[str] = Field(None, description="Tipo de bem (rótulo ou id do CITIUS)")
    modalidade: Optional[str] = Field(None, description="Modalidade de venda (rótulo ou id do CITIUS)")
    estado: Optional[str] = Field(None, description="Estado da venda (rótulo ou id do CITIUS)")
    max_pages_per_tribunal: int = Field(50, ge=1, le=5000, description="Máximo de páginas CITIUS por tribunal")
    max_pages_eleiloes: int = Field(100, ge=1, le=5000, description="Máximo de páginas do e-leiloes.pt")
    max_details: int = Field(
        vendas_service.DEFAULT_MAX_DETAILS,
        ge=0,
        le=5000,
        description="Máximo de detalhes CITIUS a pedir (um por bem)",
    )
    max_items: Optional[int] = Field(None, ge=1, description="Máximo total de bens a recolher")
    min_interval: float = Field(1.0, ge=0, le=30, description="Intervalo mínimo entre pedidos (segundos)")
    partial_every: int = Field(
        vendas_service.DEFAULT_PARTIAL_PAGES,
        ge=0,
        le=1000,
        description="Páginas entre gravações parciais (0 = só no fim)",
    )
    workers: int = Field(1, ge=1, le=8, description="Sessões em paralelo (reservado; atualmente 1)")
    proxy: Optional[str] = Field(None, description="Proxy HTTP(S) para os pedidos aos portais")
    index: bool = Field(True, description="Importar para o Elasticsearch depois de gravar o JSON")


class VendasIngestRequest(BaseModel):
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


def _run_collect(job_id: str, req: VendasCollectRequest) -> None:
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
                tribunal=info.get("tribunal") or None,
            )

        resultado = vendas_service.collect(
            fontes=req.fontes,
            tribunais=req.tribunais,
            desde=req.desde,
            ate=req.ate,
            tipo_bem=req.tipo_bem,
            modalidade=req.modalidade,
            estado=req.estado,
            max_pages_per_tribunal=req.max_pages_per_tribunal,
            max_pages_eleiloes=req.max_pages_eleiloes,
            max_details=req.max_details,
            max_items=req.max_items,
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
            pages=meta_info["pages"],
            details=meta_info.get("details"),
            duration_s=meta_info.get("duration_s"),
            errors=meta_info.get("errors") or [],
        )

        if req.index and meta_info["collected"]:
            _job_update(job_id, stage="importar")
            ingest = vendas_service.ingest_run(resultado["run_id"])
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
        logger.exception("Recolha de vendas penhoradas falhou (job %s)", job_id)
        _job_update(job_id, state="error", stage="erro", error=str(exc), finished=True)


# ------------------------------------------------------------------ leitura
@router.get("/meta")
def vendas_meta() -> Dict[str, Any]:
    """Metadados do módulo: fontes, índice, ficheiros e limites."""
    return vendas_service.meta()


@router.get("/options")
def vendas_options(refresh: bool = Query(False, description="Ignorar a cache das opções")) -> Dict[str, Any]:
    """Opções dos formulários do CITIUS (tribunais, tipos de bem, modalidades, estados)."""
    return vendas_service.form_options(force=refresh)


@router.get("/status")
def vendas_status_endpoint() -> Dict[str, Any]:
    """Volumetria do índice (documentos, datas, valores e distribuições)."""
    res = vendas_service.status()
    if res.get("error"):
        raise HTTPException(status_code=502, detail=res["error"])
    return res


@router.get("/search")
def vendas_search(
    q: Optional[str] = Query(None, description="Texto livre (título, descrição, processo, morada, nomes)"),
    fonte: Optional[str] = Query(None, description="Fonte: citius | eleiloes"),
    referencia: Optional[str] = Query(None, description="Referência no portal"),
    processo: Optional[str] = Query(None, description="Número/identificação do processo"),
    tribunal: Optional[str] = Query(None, description="Tribunal (texto parcial)"),
    tribunal_comarca: Optional[str] = Query(None, description="Sede do tribunal (terra, exato)"),
    comarca_judicial: Optional[str] = Query(None, description="Comarca judicial (exato)"),
    tipo_bem: Optional[str] = Query(None, description="Tipo de bem (exato)"),
    modalidade: Optional[str] = Query(None, description="Modalidade de venda (exato)"),
    estado: Optional[str] = Query(None, description="Estado da venda (exato)"),
    distrito: Optional[str] = Query(None, description="Distrito"),
    concelho: Optional[str] = Query(None, description="Concelho"),
    morada: Optional[str] = Query(None, description="Morada (texto parcial)"),
    nome: Optional[str] = Query(None, description="Nome de um interveniente/executado"),
    nif: Optional[str] = Query(None, description="NIF/NIPC de um interveniente/executado"),
    data_from: Optional[str] = Query(None, description="Data mínima da venda (AAAA-MM-DD)"),
    data_to: Optional[str] = Query(None, description="Data máxima da venda (AAAA-MM-DD)"),
    valor_min: Optional[float] = Query(None, ge=0, description="Valor base mínimo (€)"),
    valor_max: Optional[float] = Query(None, ge=0, description="Valor base máximo (€)"),
    size: int = Query(20, ge=1, le=200, description="Itens por página"),
    from_: int = Query(0, ge=0, alias="from", description="Índice de início"),
) -> Dict[str, Any]:
    """Pesquisa vendas de bens penhorados já indexadas."""
    res = vendas_service.search(
        q=q,
        fonte=fonte,
        referencia=referencia,
        processo=processo,
        tribunal=tribunal,
        tribunal_comarca=tribunal_comarca,
        comarca_judicial=comarca_judicial,
        tipo_bem=tipo_bem,
        modalidade=modalidade,
        estado=estado,
        distrito=distrito,
        concelho=concelho,
        morada=morada,
        nome=nome,
        nif=nif,
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
def vendas_runs(limit: int = Query(50, ge=1, le=200)) -> Dict[str, Any]:
    """Recolhas gravadas em `data/vendas_penhorados/runs` (com a contagem no índice)."""
    items = vendas_service.runs_with_index_counts(limit=limit)
    return {"items": items, "total": len(items), "directory": str(vendas_service.RUNS_DIR)}


@router.get("/runs/{run_id}")
def vendas_run_detail(run_id: str, with_items: bool = Query(False)) -> Dict[str, Any]:
    """Resumo de uma recolha (e, opcionalmente, os itens gravados no JSON)."""
    try:
        meta_info = vendas_service.load_run_meta(run_id)
        if not meta_info:
            payload = vendas_service.load_run(run_id)
            meta_info = {"run_id": run_id, "collected": payload.get("count", 0)}
        if with_items:
            payload = vendas_service.load_run(run_id)
            meta_info = {**meta_info, "criteria_source": payload.get("criteria"), "items": payload.get("items", [])}
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return meta_info


@router.get("/jobs")
def vendas_jobs(_session: Session) -> Dict[str, Any]:
    """Recolhas em curso e recentes (mais recentes primeiro)."""
    with _lock:
        jobs = sorted(_jobs.values(), key=lambda j: j.get("created_at", ""), reverse=True)
    return {"jobs": jobs[:MAX_JOBS]}


@router.get("/jobs/{job_id}")
def vendas_job(job_id: str, _session: Session) -> Dict[str, Any]:
    """Progresso de uma recolha."""
    with _lock:
        job = _jobs.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Recolha não encontrada")
    return job


# ------------------------------------------------------------------ escrita
@router.post("/collect")
def vendas_collect(req: VendasCollectRequest, session: Session) -> Dict[str, Any]:
    """Arranca a recolha em segundo plano: grava o JSON e (se `index`) importa."""
    for fonte in req.fontes:
        if fonte.lower() not in ("citius", "eleiloes"):
            raise HTTPException(status_code=422, detail=f"Fonte inválida: {fonte} (use citius ou eleiloes)")

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

    threading.Thread(target=_run_collect, args=(job_id, req), name=f"vendas-{job_id}", daemon=True).start()
    return job


@router.post("/jobs/{job_id}/stop")
def vendas_job_stop(job_id: str, _session: Session) -> Dict[str, Any]:
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
def vendas_ingest(req: VendasIngestRequest, _session: Session) -> Dict[str, Any]:
    """Importa para o Elasticsearch uma recolha gravada em JSON (ou itens avulsos)."""
    items = req.items
    run_id = req.run_id
    if items and req.save_json:
        run_id = run_id or vendas_service._new_run_id("ingest", extra="manual")
        payload = {
            "run_id": run_id,
            "source": vendas_service.SOURCE,
            "criteria": {"origem": "ingest"},
            "collected_at": datetime.now(timezone.utc).isoformat(),
            "count": len(items),
            "items": items,
        }
        meta_info = {
            "run_id": run_id,
            "source": vendas_service.SOURCE,
            "criteria": {"origem": "ingest"},
            "collected": len(items),
            "created_at": datetime.now(timezone.utc).isoformat(),
            "index": vendas_service.INDEX_NAME,
            "indexed": 0,
        }
        vendas_service.save_run(payload, meta_info)
    try:
        res = vendas_service.ingest_run(run_id=run_id, items=items, update_existing=req.update_existing)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    if res.get("error"):
        raise HTTPException(status_code=502, detail=res["error"])
    return res


@router.delete("/runs/{run_id}")
def vendas_run_delete(
    run_id: str,
    _session: Session,
    drop_index: bool = Query(False, description="Remover também do Elasticsearch as vendas desta recolha"),
) -> Dict[str, Any]:
    """Apaga os ficheiros (JSON e resumo) de uma recolha gravada."""
    res = vendas_service.delete_run(run_id, drop_index=drop_index)
    if not res.get("removed"):
        raise HTTPException(status_code=404, detail=f"Recolha «{run_id}» não encontrada")
    return res
