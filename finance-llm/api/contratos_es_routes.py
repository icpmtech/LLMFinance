"""Rotas dos contratos públicos de Espanha (`/contracts-es/*`) — PLACSP.

Segue o desenho dos restantes módulos: **leitura pública**, **escrita com sessão**.
O índice Elasticsearch (`contratos_es`) é alimentado por `collectors/contratos_es.py`
a partir dos ZIPs/ATOM de `data/contratos-espanha`.

- `GET  /contracts-es/status`             — volumetria indexada (total, anos, fontes)
- `GET  /contracts-es/meta`               — ZIPs disponíveis, JSONL locais e listas de códigos CODICE
- `POST /contracts-es/search`             — pesquisa com filtros e facetas
- `GET  /contracts-es/autocomplete?q=`    — sugestões (órgãos, adjudicatários, CPV)
- `GET  /contracts-es/entities?q=&kind=`  — entidades (órgãos adjudicantes e empresas adjudicatárias)
- `GET  /contracts-es/{doc_id}`           — detalhe de um contrato
- `POST /contracts-es/import`             — importar um ano (normaliza e indexa)   (sessão)
- `GET  /contracts-es/imports`            — importações em curso/recentes
- `GET  /contracts-es/import/{job_id}`    — progresso de uma importação
"""
from __future__ import annotations

import threading
import uuid
from datetime import datetime, timezone
from typing import Annotated, Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from api.models import ContractAnalyticsResponse

from api.auth_routes import CurrentSession, require_session
from api.elasticsearch_client import (
    CONTRATOS_ES_FONTES,
    contratos_es_autocomplete,
    contratos_es_status,
    contratos_es_years_available,
    get_contrato_es,
    get_contratos_es_analytics,
    search_contratos_es,
    search_contratos_es_entities,
)

router = APIRouter(prefix="/contracts-es", tags=["contratos-es"])

Session = Annotated[CurrentSession, Depends(require_session)]

MAX_JOBS = 20


# ------------------------------------------------------------------- modelos
class ContratoEsSearchRequest(BaseModel):
    """Filtros da pesquisa de contratos de Espanha (todos opcionais)."""

    q: Optional[str] = None
    ano: Optional[int] = None
    fonte: Optional[str] = Field(None, description="licitaciones | menores")
    tipo: Optional[str] = Field(None, description="Código CODICE (ex.: 2) ou rótulo (ex.: Servicios)")
    estado: Optional[str] = Field(None, description="Código (PUB/ADJ/RES…) ou rótulo")
    procedimiento: Optional[str] = None
    organo: Optional[str] = None
    organismo_id: Optional[str] = Field(None, description="Código DIR3 do órgão")
    adjudicatario: Optional[str] = None
    adjudicatario_nif: Optional[str] = None
    localidad: Optional[str] = None
    nuts: Optional[str] = None
    cpv_code: Optional[str] = None
    min_value: Optional[float] = None
    max_value: Optional[float] = None
    start_date: Optional[str] = None
    end_date: Optional[str] = None
    date_field: Optional[str] = Field(None, description="fecha_publicacion | fecha_adjudicacion | fecha_actualizacion")
    solo_menores: Optional[bool] = None
    size: int = Field(20, ge=1, le=100)
    from_: int = Field(0, ge=0, alias="from")
    sort_by: Optional[str] = None
    sort_order: Optional[str] = None


class ContratoEsImportRequest(BaseModel):
    """Importação de um ano do PLACSP (normaliza para JSONL e indexa)."""

    fonte: str = Field("licitaciones", description="licitaciones | menores | ambos")
    ano: int = Field(..., description="Ano do ZIP a importar")
    limit: Optional[int] = Field(None, description="Limite de documentos (amostra)")
    index: bool = Field(True, description="Indexar no Elasticsearch depois de normalizar")
    force: bool = Field(False, description="Reprocessar mesmo que o JSONL já exista")


# ------------------------------------------------------------------- importações
_jobs: Dict[str, Dict[str, Any]] = {}
_lock = threading.Lock()


def _job_update(job_id: str, **fields: Any) -> None:
    with _lock:
        job = _jobs.get(job_id)
        if job:
            job.update(fields)
            job["updated_at"] = datetime.now(timezone.utc).isoformat()


def _run_import(job_id: str, req: ContratoEsImportRequest) -> None:
    """Trabalhador da importação: normaliza os ZIPs do ano e indexa no Elasticsearch."""
    from collectors import contratos_es as pipeline

    try:
        fontes = list(CONTRATOS_ES_FONTES) if req.fonte == "ambos" else [req.fonte]
        targets = [
            (fonte, ano, path)
            for fonte, ano, path in pipeline.available_zips(None, [req.ano])
            if fonte in fontes
        ]
        if not targets:
            _job_update(job_id, state="error", message=f"Nenhum ZIP de {req.ano} para {req.fonte}", finished=True)
            return

        _job_update(job_id, state="running", stage="normalizar", total_targets=len(targets))
        results: List[Dict[str, Any]] = []
        for fonte, ano, zip_path in targets:
            def on_progress(info: Dict[str, Any], fonte: str = fonte) -> None:
                _job_update(
                    job_id,
                    fonte=fonte,
                    docs=info.get("count", 0),
                    atoms_done=info.get("atoms_done", 0),
                    atoms_total=info.get("atoms_total", 0),
                )

            info = pipeline.build_jsonl(
                fonte,
                ano,
                zip_path,
                limit=req.limit,
                force=req.force,
                on_progress=on_progress,
            )
            if req.index and info.get("count"):
                _job_update(job_id, stage="indexar", fonte=fonte)
                info["index"] = pipeline.index_jsonl(pipeline.jsonl_path(fonte, ano))
            results.append(info)

        total_docs = sum(r.get("count", 0) for r in results)
        total_indexed = sum((r.get("index") or {}).get("indexed_count", 0) for r in results)
        _job_update(
            job_id,
            state="done",
            stage="concluido",
            results=results,
            docs=total_docs,
            indexed=total_indexed,
            finished=True,
            message=f"{total_docs} documentos normalizados, {total_indexed} indexados",
        )
    except Exception as exc:  # noqa: BLE001 — o erro tem de chegar à UI
        _job_update(job_id, state="error", message=str(exc), finished=True)


# ------------------------------------------------------------------- leitura
@router.get("/status")
def contratos_es_status_endpoint() -> Dict[str, Any]:
    """Volumetria do índice `contratos_es`."""
    res = contratos_es_status()
    if res.get("error"):
        raise HTTPException(status_code=502, detail=res.get("error"))
    return res


@router.get("/meta")
def contratos_es_meta() -> Dict[str, Any]:
    """ZIPs disponíveis, JSONLs já normalizados e listas de códigos CODICE."""
    from collectors import contratos_es as pipeline

    zips = [
        {"fonte": fonte, "ano": ano, "zip": path.name}
        for fonte, ano, path in pipeline.available_zips()
    ]
    normalized = [
        {"fonte": fonte, "ano": ano, "jsonl": path.name}
        for fonte, ano, path in pipeline.available_zips(None, None)
        if pipeline.jsonl_path(fonte, ano).exists()
    ]
    return {
        "zips": zips,
        "normalized": normalized,
        "indexed_years": contratos_es_years_available(),
        "fontes": list(CONTRATOS_ES_FONTES),
        "codigos": {
            "tipo_contrato": pipeline.label_map("ContractCode-2.08"),
            "estado": pipeline.ESTADO_LABELS,
            "resultado": pipeline.label_map("TenderResultCode-2.09"),
            "procedimiento": pipeline.label_map("SyndicationTenderingProcessCode-2.07"),
        },
    }


@router.get("/analytics")
def contratos_es_analytics_endpoint(
    q: Optional[str] = None,
    ano: Optional[int] = None,
    fonte: Optional[str] = None,
    tipo: Optional[str] = None,
    estado: Optional[str] = None,
    procedimiento: Optional[str] = None,
    organo: Optional[str] = None,
    organismo_id: Optional[str] = None,
    adjudicatario: Optional[str] = None,
    adjudicatario_nif: Optional[str] = None,
    localidad: Optional[str] = None,
    nuts: Optional[str] = None,
    cpv_code: Optional[str] = None,
    min_value: Optional[float] = None,
    max_value: Optional[float] = None,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    date_field: Optional[str] = Query(None, description="fecha_publicacion | fecha_adjudicacion | fecha_actualizacion"),
    solo_menores: Optional[bool] = None,
) -> ContractAnalyticsResponse:
    """Agregações analíticas para o dashboard de contratos de Espanha."""
    res = get_contratos_es_analytics(
        q=q,
        ano=ano,
        fonte=fonte,
        tipo=tipo,
        estado=estado,
        procedimiento=procedimiento,
        organo=organo,
        organismo_id=organismo_id,
        adjudicatario=adjudicatario,
        adjudicatario_nif=adjudicatario_nif,
        localidad=localidad,
        nuts=nuts,
        cpv_code=cpv_code,
        min_value=min_value,
        max_value=max_value,
        start_date=start_date,
        end_date=end_date,
        date_field=date_field,
        solo_menores=solo_menores,
    )
    if res.get("error"):
        raise HTTPException(status_code=502, detail=res.get("error"))
    return ContractAnalyticsResponse(**res)


@router.post("/search")
def contratos_es_search_endpoint(req: ContratoEsSearchRequest) -> Dict[str, Any]:
    """Pesquisa contratos de Espanha com filtros e facetas."""
    res = search_contratos_es(
        q=req.q,
        ano=req.ano,
        fonte=req.fonte,
        tipo=req.tipo,
        estado=req.estado,
        procedimiento=req.procedimiento,
        organo=req.organo,
        organismo_id=req.organismo_id,
        adjudicatario=req.adjudicatario,
        adjudicatario_nif=req.adjudicatario_nif,
        localidad=req.localidad,
        nuts=req.nuts,
        cpv_code=req.cpv_code,
        min_value=req.min_value,
        max_value=req.max_value,
        start_date=req.start_date,
        end_date=req.end_date,
        date_field=req.date_field,
        solo_menores=req.solo_menores,
        size=req.size,
        from_=req.from_,
        sort_by=req.sort_by,
        sort_order=req.sort_order,
    )
    if res.get("error"):
        raise HTTPException(status_code=502, detail=res.get("error"))
    return res


@router.get("/autocomplete")
def contratos_es_autocomplete_endpoint(
    q: str = Query(..., min_length=1),
    size: int = Query(10, ge=1, le=50),
) -> Dict[str, Any]:
    """Sugestões de órgãos, adjudicatários e CPV."""
    res = contratos_es_autocomplete(q=q, size=size)
    if res.get("error"):
        raise HTTPException(status_code=502, detail=res.get("error"))
    return res


@router.get("/entities")
def contratos_es_entities_endpoint(
    q: str = Query("", description="Nome (total ou parcial) do órgão ou da empresa."),
    kind: str = Query("all", description="organo | adjudicatario | all"),
    ano: Optional[int] = Query(None, description="Ano dos contratos a considerar."),
    size: int = Query(20, ge=1, le=100),
    from_: int = Query(0, ge=0, alias="from"),
) -> Dict[str, Any]:
    """Entidades de Espanha (órgãos adjudicantes e empresas adjudicatárias).

    No PLACSP cada documento é um contrato, pelo que os nomes das entidades são
    obtidos por agregação: cada item traz o número de contratos e o valor
    adjudicado somado.
    """
    only = kind if kind in ("organo", "adjudicatario") else None
    res = search_contratos_es_entities(q=q or None, kind=only, ano=ano, size=size, from_=from_)
    if res.get("error"):
        raise HTTPException(status_code=502, detail=res.get("error"))
    return res


@router.get("/imports")
def contratos_es_imports_endpoint() -> Dict[str, Any]:
    """Importações em curso e recentes (mais recentes primeiro)."""
    with _lock:
        jobs = sorted(_jobs.values(), key=lambda j: j.get("created_at", ""), reverse=True)
    return {"jobs": jobs[:MAX_JOBS]}


@router.get("/import/{job_id}")
def contratos_es_import_status_endpoint(job_id: str) -> Dict[str, Any]:
    """Progresso de uma importação."""
    with _lock:
        job = _jobs.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Importação não encontrada")
    return job


@router.post("/import")
def contratos_es_import_endpoint(req: ContratoEsImportRequest, session: Session) -> Dict[str, Any]:
    """Arranca a importação de um ano em segundo plano (normaliza e indexa)."""
    if req.fonte not in CONTRATOS_ES_FONTES and req.fonte != "ambos":
        raise HTTPException(status_code=422, detail=f"Fonte inválida: {req.fonte}")

    from collectors import contratos_es as pipeline

    if not pipeline.available_zips(None, [req.ano]):
        raise HTTPException(status_code=404, detail=f"Não existe ZIP para o ano {req.ano}")

    job_id = uuid.uuid4().hex[:12]
    job = {
        "id": job_id,
        "fonte": req.fonte,
        "ano": req.ano,
        "limit": req.limit,
        "index": req.index,
        "state": "queued",
        "stage": "em espera",
        "docs": 0,
        "indexed": 0,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "created_by": getattr(session, "user_id", None) or getattr(session, "email", None),
        "finished": False,
    }
    with _lock:
        _jobs[job_id] = job
        if len(_jobs) > MAX_JOBS:
            for old in sorted(_jobs.values(), key=lambda j: j.get("created_at", ""))[: len(_jobs) - MAX_JOBS]:
                _jobs.pop(old["id"], None)

    threading.Thread(target=_run_import, args=(job_id, req), name=f"contratos-es-{job_id}", daemon=True).start()
    return job


@router.get("/{doc_id}")
def contrato_es_detail_endpoint(doc_id: str) -> Dict[str, Any]:
    """Detalhe de um contrato de Espanha (pelo `_id` do documento no Elasticsearch)."""
    res = get_contrato_es(doc_id)
    if res.get("error"):
        raise HTTPException(status_code=404, detail=res.get("error"))
    return res
