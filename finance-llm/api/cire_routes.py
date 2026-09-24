"""Rotas do módulo CIRE (`/cire/*`) — insolvências e revitalizações de empresas.

Fonte: ``citius.mj.pt`` → «Publicidade do PER, do PEAP, do PEVE e da
insolvência» (Ministério da Justiça). É a lista de resultados da pesquisa do
portal: tribunal, processo, espécie, datas e **intervenientes com NIF/NIPC**
(insolvente, administrador da insolvência, credores, …).

Fluxo do módulo (como os restantes da solução)
1. **Recolha** — `POST /cire/collect` percorre a lista do portal e grava os
   dados em **JSON** (`data/cire/runs/<run_id>.json` + `.meta.json`). Corre em
   segundo plano; o progresso vê-se em `GET /cire/jobs/{id}`.
2. **Importação** — `POST /cire/ingest` lê o JSON gravado e indexa no
   Elasticsearch (`finance_cire`). Pode repetir-se (o `_id` é o `pub_id`).
3. **Pesquisa** — `GET /cire/search` e `GET /cire/status` sobre o índice.

Leitura (pública)
- `GET  /cire/meta`                 — metadados do módulo
- `GET  /cire/options`              — tribunais e atos do portal (cache 1h)
- `GET  /cire/status`               — volumetria do índice
- `GET  /cire/search`               — pesquisar publicações indexadas
- `GET  /cire/intervenientes/{nif}` — publicações de um NIF/NIPC interveniente
- `GET  /cire/graph/dimensions`     — dimensões, métricas e receitas do grafo
- `GET  /cire/graph`                — construir o grafo (rede de entidades, comarcas, tipos, tempo)
- `GET  /cire/runs`                 — recolhas gravadas em `data/cire/runs`
- `GET  /cire/runs/{run_id}`        — resumo/estado de uma recolha
- `GET  /cire/jobs`                 — recolhas em curso e recentes

Escrita (sessão)
- `POST /cire/collect`              — arrancar recolha (grava JSON, opcionalmente importa)
- `POST /cire/jobs/{id}/stop`       — parar uma recolha em curso
- `POST /cire/ingest`               — importar uma recolha gravada para o Elasticsearch
- `DELETE /cire/runs/{run_id}`      — apagar os ficheiros de uma recolha
"""
from __future__ import annotations

import logging
import threading
import uuid
from datetime import datetime, timezone
from typing import Annotated, Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from api import cire_service
from api.auth_routes import CurrentSession, require_session
from api.cire_graph import build_cire_graph, cire_graph_dimensions

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/cire", tags=["cire"])

Session = Annotated[CurrentSession, Depends(require_session)]

MAX_JOBS = 20


# ------------------------------------------------------------------ modelos
class CireCollectRequest(BaseModel):
    """Critérios da recolha (os mesmos campos do formulário do portal)."""

    desde: Optional[str] = Field(None, description="Data inicial (AAAA-MM-DD ou DD/MM/AAAA)")
    ate: Optional[str] = Field(None, description="Data final (AAAA-MM-DD ou DD/MM/AAAA)")
    dias: Optional[str] = Field(None, description="Atalho do portal: 15 | 30 | todos")
    nif: Optional[str] = Field(None, description="NIF/NIPC do interveniente")
    nome: Optional[str] = Field(None, description="Designação do interveniente (mín. 3 caracteres)")
    numero_processo: Optional[str] = Field(None, description="Número do processo")
    tribunal: Optional[str] = Field(None, description="Tribunal (rótulo, ex.: «Porto - Tribunal Judicial da Comarca do Porto»)")
    grupo_actos: Optional[str] = Field(None, description="Grupo de atos: 20 (insolvência) | 24 (anúncios) | 25 (atos do administrador)")
    acto: Optional[str] = Field(None, description="Ato (rótulo, ex.: «Anúncio - Portal Citius»)")
    max_pages: int = Field(20, ge=1, le=2000, description="Máximo de páginas (10 documentos/página) por janela")
    max_items: Optional[int] = Field(None, ge=1, description="Máximo de documentos a recolher")
    window_days: Optional[int] = Field(
        None, ge=1, le=366,
        description="Divide o intervalo em janelas deste tamanho (o limite de páginas aplica-se a cada janela)",
    )
    min_interval: float = Field(1.2, ge=0, le=30, description="Intervalo mínimo entre pedidos ao portal (segundos)")
    proxy: Optional[str] = Field(None, description="Proxy HTTP(S) para os pedidos ao portal")
    force: bool = Field(
        False,
        description=(
            "Reprocessar mesmo que o intervalo já tenha sido recolhido. Sem `force`, as janelas "
            "já processadas (registadas em `data/cire/runs`) são ignoradas e o motivo é devolvido "
            "em `warnings`."
        ),
    )
    index: bool = Field(
        True, description="Importar para o Elasticsearch depois de gravar o JSON (a gravação é sempre feita)"
    )
    split_runs: bool = Field(
        False,
        description=(
            "Gravar uma recolha (JSON + importação) por janela de datas em vez de um único ficheiro. "
            "Recomendado em períodos longos (ex.: 2020→hoje): mantém a memória constante, permite "
            "reimportar janelas isoladas e dá progresso por janela."
        ),
    )


class CireIngestRequest(BaseModel):
    """Importação de uma recolha gravada em disco."""

    run_id: Optional[str] = Field(None, description="Recolha a importar (por omissão, a mais recente)")
    items: Optional[List[Dict[str, Any]]] = Field(None, description="Itens avulsos, em alternativa ao `run_id`")
    save_json: bool = Field(
        False, description="Quando são enviados `items` avulsos, gravá-los também como nova recolha"
    )
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


def _run_collect(job_id: str, req: CireCollectRequest) -> None:
    """Trabalhador da recolha: grava o JSON e (opcionalmente) importa para o Elasticsearch."""
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
                window_index=info.get("window_index"),
                window_total=info.get("window_total"),
                runs_done=info.get("runs"),
                indexed=info.get("indexed") or None,
                file=info.get("file") or None,
                warnings=info.get("warnings") or None,
            )

        resultado = cire_service.collect(
            desde=req.desde,
            ate=req.ate,
            dias=req.dias,
            nif=req.nif,
            nome=req.nome,
            numero_processo=req.numero_processo,
            tribunal=req.tribunal,
            grupo_actos=req.grupo_actos,
            acto=req.acto,
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

        # Todas as janelas já tinham sido processadas: não há nada novo a indexar.
        nada_novo = not meta_info["collected"] and bool(meta_info.get("skipped_windows"))
        if req.index and not nada_novo and not req.split_runs:
            _job_update(job_id, stage="importar")
            ingest = cire_service.ingest_run(resultado["run_id"])
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
        logger.exception("Recolha CIRE falhou (job %s)", job_id)
        _job_update(job_id, state="error", stage="erro", error=str(exc), finished=True)


# ------------------------------------------------------------------ leitura
@router.get("/meta")
def cire_meta() -> Dict[str, Any]:
    """Metadados do módulo: fonte, índice, ficheiros e limites."""
    return cire_service.meta()


@router.get("/options")
def cire_options(refresh: bool = Query(False, description="Ignorar a cache das opções")) -> Dict[str, Any]:
    """Tribunais, grupos de atos e atos disponíveis no formulário do portal."""
    return cire_service.form_options(force=refresh)


@router.get("/status")
def cire_status_endpoint() -> Dict[str, Any]:
    """Volumetria do índice (documentos, NIFs, datas e distribuições)."""
    res = cire_service.status()
    if res.get("error"):
        raise HTTPException(status_code=502, detail=res["error"])
    return res


@router.get("/search")
def cire_search(
    q: Optional[str] = Query(None, description="Texto livre (interveniente, tribunal, processo, ato)"),
    referencia: Optional[str] = Query(None, description="Referência do documento no portal"),
    processo: Optional[str] = Query(None, description="Número/identificação do processo"),
    nif: Optional[str] = Query(None, description="NIF/NIPC de qualquer interveniente"),
    tribunal: Optional[str] = Query(None, description="Tribunal (texto parcial)"),
    tribunal_comarca: Optional[str] = Query(None, description="Comarca (exato)"),
    tipo: Optional[str] = Query(None, description="Insolvência | PER | PEAP | PEVE"),
    ato: Optional[str] = Query(None, description="Ato publicado (texto parcial)"),
    especie: Optional[str] = Query(None, description="Espécie do processo (texto parcial)"),
    insolvente: Optional[str] = Query(None, description="Nome do insolvente/devedor"),
    papel: Optional[str] = Query(None, description="Papel do interveniente (Insolvente, Administrador Insolvência, Credor, …)"),
    data_from: Optional[str] = Query(None, description="Data de publicação mínima (AAAA-MM-DD)"),
    data_to: Optional[str] = Query(None, description="Data de publicação máxima (AAAA-MM-DD)"),
    has_documento: Optional[bool] = Query(None),
    size: int = Query(20, ge=1, le=200),
    from_: int = Query(0, ge=0, alias="from"),
) -> Dict[str, Any]:
    """Pesquisa as publicações do CIRE já indexadas."""
    res = cire_service.search(
        q=q,
        referencia=referencia,
        processo=processo,
        nif=nif,
        tribunal=tribunal,
        tribunal_comarca=tribunal_comarca,
        tipo=tipo,
        ato=ato,
        especie=especie,
        insolvente=insolvente,
        papel=papel,
        data_from=data_from,
        data_to=data_to,
        has_documento=has_documento,
        size=size,
        from_=from_,
    )
    if res.get("error"):
        raise HTTPException(status_code=502, detail=res["error"])
    return res


@router.get("/intervenientes/{nif}")
def cire_interveniente(
    nif: str,
    size: int = Query(100, ge=1, le=200),
    from_: int = Query(0, ge=0, alias="from"),
) -> Dict[str, Any]:
    """Publicações em que o NIF/NIPC indicado é interveniente (qualquer papel)."""
    res = cire_service.interveniente(nif, size=size, from_=from_)
    if res.get("error"):
        raise HTTPException(status_code=502, detail=res["error"])
    return res


# --- Grafo das insolvências (rede de entidades, comarcas, tipos, tempo) ---

@router.get("/graph/dimensions")
def cire_graph_dimensions_endpoint() -> Dict[str, Any]:
    """Dimensões, métricas e receitas disponíveis para o grafo do CIRE."""
    return cire_graph_dimensions()


@router.get("/graph")
def cire_graph(
    dimension_a: str = Query(
        ...,
        description="Dimensão dos nós (ex.: insolvente, administrador, credor, comarca, tipo, mes)",
    ),
    dimension_b: Optional[str] = Query(
        None,
        description="Dimensão das arestas. Igual a `dimension_a` cria uma rede de co-ocorrência "
        "(ex.: credores que partilham processos); omisso devolve apenas nós.",
    ),
    metric: str = Query("publicacoes", pattern="^(publicacoes|mencoes)$"),
    mode: str = Query(
        "auto",
        pattern="^(auto|exato|amostra)$",
        description="`exato` usa agregações (sem amostragem) nas dimensões planas; nos restantes "
        "casos percorre as publicações até ao teto do servidor.",
    ),
    q: Optional[str] = Query(None, description="Texto livre (interveniente, tribunal, processo, ato)"),
    tipo: Optional[str] = Query(None, description="Insolvência | PER | PEAP | PEVE"),
    especie: Optional[str] = Query(None, description="Espécie do processo"),
    ato: Optional[str] = Query(None, description="Ato publicado"),
    comarca: Optional[str] = Query(None, description="Comarca (exato)"),
    tribunal: Optional[str] = Query(None, description="Tribunal (texto parcial)"),
    papel: Optional[str] = Query(None, description="Restringe às publicações com este papel de interveniente"),
    nif: Optional[str] = Query(None, description="Restringe às publicações com este NIF/NIPC"),
    data_from: Optional[str] = Query(None, description="Data de publicação mínima (AAAA-MM-DD)"),
    data_to: Optional[str] = Query(None, description="Data de publicação máxima (AAAA-MM-DD)"),
    has_documento: Optional[bool] = Query(None, description="Só publicações com documento associado"),
    min_count: int = Query(1, ge=1, le=1000, description="Publicações mínimas para um nó ser incluído"),
    limit: int = Query(60, ge=0, le=10_000, description="Nós a manter (0 = todos)"),
    edge_limit: int = Query(400, ge=0, le=30_000, description="Arestas a manter (0 = todas)"),
    sample: int = Query(
        20_000, ge=0, le=300_000,
        description="Publicações analisadas na varredura (0 = todas até ao teto do servidor)",
    ),
) -> Dict[str, Any]:
    """Constrói o grafo das insolvências e revitalizações a partir do índice `finance_cire`.

    Cada nó é uma entidade, tribunal, comarca, tipo de processo, ato ou período; cada
    aresta liga dois valores que co-ocorrem na mesma publicação (ou liga duas dimensões
    distintas, ex.: administrador da insolvência → insolvente).
    """
    result = build_cire_graph(
        dimension_a=dimension_a,
        dimension_b=dimension_b,
        metric=metric,
        mode=mode,
        q=q,
        tipo=tipo,
        especie=especie,
        ato=ato,
        comarca=comarca,
        tribunal=tribunal,
        papel=papel,
        nif=nif,
        data_from=data_from,
        data_to=data_to,
        has_documento=has_documento,
        min_count=min_count,
        limit=limit,
        edge_limit=edge_limit,
        sample=sample,
    )
    if result.get("error"):
        raise HTTPException(status_code=502, detail=result["error"])
    return result


@router.get("/coverage")
def cire_coverage() -> Dict[str, Any]:
    """Janelas/dias já recolhidos — para a UI avisar antes de repetir a recolha."""
    return cire_service.coverage()


@router.get("/runs")
def cire_runs(limit: int = Query(50, ge=1, le=200)) -> Dict[str, Any]:
    """Recolhas gravadas em `data/cire/runs` (com a contagem no índice)."""
    items = cire_service.runs_with_index_counts(limit=limit)
    return {"items": items, "total": len(items), "directory": str(cire_service.RUNS_DIR)}


@router.get("/runs/{run_id}")
def cire_run_detail(run_id: str, with_items: bool = Query(False)) -> Dict[str, Any]:
    """Resumo de uma recolha (e, opcionalmente, os itens gravados no JSON)."""
    try:
        meta_info = cire_service.load_run_meta(run_id)
        if not meta_info:
            payload = cire_service.load_run(run_id)
            meta_info = {"run_id": run_id, "collected": payload.get("count", 0)}
        if with_items:
            payload = cire_service.load_run(run_id)
            meta_info = {**meta_info, "criteria_source": payload.get("criteria"), "items": payload.get("items", [])}
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return meta_info


@router.get("/jobs")
def cire_jobs(_session: Session) -> Dict[str, Any]:
    """Recolhas em curso e recentes (mais recentes primeiro)."""
    with _lock:
        jobs = sorted(_jobs.values(), key=lambda j: j.get("created_at", ""), reverse=True)
    return {"jobs": jobs[:MAX_JOBS]}


@router.get("/jobs/{job_id}")
def cire_job(job_id: str, _session: Session) -> Dict[str, Any]:
    """Progresso de uma recolha."""
    with _lock:
        job = _jobs.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Recolha não encontrada")
    return job


# ------------------------------------------------------------------ escrita
@router.post("/collect")
def cire_collect(req: CireCollectRequest, session: Session) -> Dict[str, Any]:
    """Arranca a recolha em segundo plano: grava o JSON e (se `index`) importa.

    A gravação em `data/cire/runs` é **sempre** feita antes de qualquer
    indexação, para que a recolha possa ser inspecionada e reimportada.
    """
    if bool(req.desde) != bool(req.ate):
        raise HTTPException(status_code=422, detail="Indique as duas datas (início e fim) ou nenhuma.")
    if req.nome and req.nif:
        raise HTTPException(status_code=422, detail="Escolha pesquisa por NIF/NIPC ou por designação, não ambas.")

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

    threading.Thread(target=_run_collect, args=(job_id, req), name=f"cire-{job_id}", daemon=True).start()
    return job


@router.post("/jobs/{job_id}/stop")
def cire_job_stop(job_id: str, _session: Session) -> Dict[str, Any]:
    """Pede a paragem de uma recolha em curso (a página atual termina primeiro)."""
    with _lock:
        job = _jobs.get(job_id)
        if not job:
            raise HTTPException(status_code=404, detail="Recolha não encontrada")
        job["stop_requested"] = True
        job["stage"] = "a parar"
        job["updated_at"] = datetime.now(timezone.utc).isoformat()
    return job


@router.post("/ingest")
def cire_ingest(req: CireIngestRequest, _session: Session) -> Dict[str, Any]:
    """Importa para o Elasticsearch uma recolha gravada em JSON (ou itens avulsos)."""
    items = req.items
    run_id = req.run_id
    if items and req.save_json:
        run_id = run_id or cire_service._new_run_id(None, None, None, None)  # noqa: SLF001
        payload = {
            "run_id": run_id,
            "source": "citius_cire",
            "criteria": {"origem": "ingest"},
            "collected_at": datetime.now(timezone.utc).isoformat(),
            "count": len(items),
            "items": items,
        }
        meta_info = {
            "run_id": run_id,
            "source": "citius_cire",
            "criteria": {"origem": "ingest"},
            "collected": len(items),
            "created_at": datetime.now(timezone.utc).isoformat(),
            "index": "finance_cire",
            "indexed": 0,
        }
        cire_service.save_run(payload, meta_info)
    try:
        res = cire_service.ingest_run(
            run_id=run_id, items=items, update_existing=req.update_existing
        )
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    if res.get("error"):
        raise HTTPException(status_code=502, detail=res["error"])
    return res


@router.delete("/runs/{run_id}")
def cire_run_delete(run_id: str, _session: Session) -> Dict[str, Any]:
    """Apaga os ficheiros (JSON e resumo) de uma recolha gravada."""
    res = cire_service.delete_run(run_id)
    if not res.get("removed"):
        raise HTTPException(status_code=404, detail=f"Recolha «{run_id}» não encontrada")
    return res
