"""Rotas do módulo **Deteção de padrões** (`/padroes/*`).

Responde à pergunta «o que é atípico na contratação pública, em quem e com que
relações?» cruzando contratos (PT/ES), empresas, cargos, insolvências e notícias.

- `GET /padroes/meta`                      — padrões, algoritmos, fontes e parâmetros
- `GET /padroes/analysis`                  — análise completa (KPIs, CPV, anomalias, entidades, rede, modelo)
- `GET /padroes/anomalies`                 — só os contratos sinalizados (filtros por score/detetor)
- `GET /padroes/entities`                  — só as empresas/entidades com score
- `GET /padroes/relations`                 — grafo de relações, laços e concentração
- `GET /padroes/news`                      — menções em notícias das entidades sinalizadas
- `GET /padroes/entity/{nif}`              — dossiê de uma entidade (contratos, sinais, cargos, CIRE, notícias)
- `POST /padroes/cache/clear`              — limpar a cache de análises            (sessão)

A leitura é pública (como nos restantes módulos); só a manutenção da cache exige
sessão. Um `refresh=true` na análise também exige sessão, porque reconstrói tudo.
"""
from __future__ import annotations

import logging
from typing import Annotated, Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query

from api import padroes_service as service
from api.auth_routes import CurrentSession, optional_session, require_session

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/padroes", tags=["padroes"])

Session = Annotated[CurrentSession, Depends(require_session)]

PAIS_PATTERN = "^(PT|ES|pt|es)$"


def _analysis(
    pais: str,
    ano_from: Optional[int],
    ano_to: Optional[int],
    cpv: Optional[str],
    per_year: int,
    contamination: float,
    seed: int,
    refresh: bool,
) -> Dict[str, Any]:
    payload = service.analyze(
        pais=pais,
        ano_from=ano_from,
        ano_to=ano_to,
        cpv=cpv,
        per_year=per_year,
        contamination=contamination,
        seed=seed,
        use_cache=not refresh,
    )
    if payload.get("error") and payload.get("paises") is None and "país desconhecido" in str(payload.get("error")):
        raise HTTPException(status_code=400, detail=payload["error"])
    return payload


@router.get("/meta", summary="Catálogo de padrões, algoritmos e fontes")
def padroes_meta() -> Dict[str, Any]:
    """O que o motor sabe procurar, com que algoritmos e sobre que índices."""
    return service.meta()


@router.get("/analysis", summary="Análise completa de padrões")
def padroes_analysis(
    pais: str = Query("PT", pattern=PAIS_PATTERN, description="PT (Portal BASE) ou ES (PLACSP)"),
    ano_from: Optional[int] = Query(None, ge=1900, le=2100, description="Ano mínimo (omissão: todos)"),
    ano_to: Optional[int] = Query(None, ge=1900, le=2100, description="Ano máximo (omissão: atual)"),
    cpv: Optional[str] = Query(None, max_length=12, description="Prefixo de CPV (ex.: «45» obras)"),
    per_year: int = Query(service.SAMPLE_PER_YEAR_DEFAULT, ge=100, le=5000, description="Contratos lidos por ano"),
    contamination: float = Query(0.02, ge=0.005, le=0.2, description="Proporção esperada de anomalias"),
    seed: int = Query(42, ge=0, le=10_000, description="Semente (reprodutibilidade)"),
    refresh: bool = Query(False, description="Ignorar a cache e recalcular (exige sessão)"),
    session: Optional[CurrentSession] = Depends(optional_session),
) -> Dict[str, Any]:
    """Corre (ou reutiliza da cache) a análise não supervisionada + supervisionada."""
    if refresh and session is None:
        raise HTTPException(status_code=401, detail="Recalcular a análise exige sessão.")
    return _analysis(pais, ano_from, ano_to, cpv, per_year, contamination, seed, refresh)


@router.get("/anomalies", summary="Contratos sinalizados")
def padroes_anomalies(
    pais: str = Query("PT", pattern=PAIS_PATTERN),
    ano_from: Optional[int] = Query(None, ge=1900, le=2100),
    ano_to: Optional[int] = Query(None, ge=1900, le=2100),
    cpv: Optional[str] = Query(None, max_length=12),
    per_year: int = Query(service.SAMPLE_PER_YEAR_DEFAULT, ge=100, le=5000),
    contamination: float = Query(0.02, ge=0.005, le=0.2),
    seed: int = Query(42, ge=0, le=10_000),
    min_score: float = Query(0.0, ge=0.0, le=1.0, description="Score mínimo de consenso"),
    detector: Optional[str] = Query(None, description="isolation_forest | lof | kmeans | one_class_svm"),
    padrao: Optional[str] = Query(None, description="Filtrar por padrão (ex.: aditivo_valor)"),
    limit: int = Query(100, ge=1, le=400),
) -> Dict[str, Any]:
    """Contratos com score alto e pelo menos dois detetores de acordo."""
    payload = _analysis(pais, ano_from, ano_to, cpv, per_year, contamination, seed, False)
    if payload.get("error"):
        return payload
    items: List[Dict[str, Any]] = payload.get("anomalias") or []
    if min_score > 0:
        items = [item for item in items if (item.get("score") or 0) >= min_score]
    if detector:
        items = [item for item in items if detector in (item.get("detetores") or [])]
    if padrao:
        items = [item for item in items if any(r.get("padrao") == padrao for r in item.get("razoes") or [])]
    return {
        "pais": payload.get("pais"),
        "total": len(items),
        "limiar_consenso": (payload.get("deteccao") or {}).get("limiar_consenso"),
        "algoritmos": (payload.get("deteccao") or {}).get("algoritmos"),
        "items": items[:limit],
        "overview": payload.get("overview"),
    }


@router.get("/entities", summary="Empresas/entidades com score")
def padroes_entities(
    pais: str = Query("PT", pattern=PAIS_PATTERN),
    ano_from: Optional[int] = Query(None, ge=1900, le=2100),
    ano_to: Optional[int] = Query(None, ge=1900, le=2100),
    cpv: Optional[str] = Query(None, max_length=12),
    per_year: int = Query(service.SAMPLE_PER_YEAR_DEFAULT, ge=100, le=5000),
    contamination: float = Query(0.02, ge=0.005, le=0.2),
    seed: int = Query(42, ge=0, le=10_000),
    min_score: float = Query(0.0, ge=0.0, le=1.0),
    insolventes: bool = Query(False, description="Só entidades com processo no CIRE"),
    limit: int = Query(100, ge=1, le=300),
) -> Dict[str, Any]:
    """Ranking de adjudicatárias (LOF no espaço de features da entidade)."""
    payload = _analysis(pais, ano_from, ano_to, cpv, per_year, contamination, seed, False)
    if payload.get("error"):
        return payload
    items: List[Dict[str, Any]] = payload.get("entidades") or []
    if min_score > 0:
        items = [item for item in items if (item.get("score") or 0) >= min_score]
    if insolventes:
        items = [item for item in items if item.get("insolvente")]
    return {
        "pais": payload.get("pais"),
        "total": len(items),
        "modelo": payload.get("modelo_entidades"),
        "items": items[:limit],
    }


@router.get("/relations", summary="Rede de relações e concentração")
def padroes_relations(
    pais: str = Query("PT", pattern=PAIS_PATTERN),
    ano_from: Optional[int] = Query(None, ge=1900, le=2100),
    ano_to: Optional[int] = Query(None, ge=1900, le=2100),
    cpv: Optional[str] = Query(None, max_length=12),
    per_year: int = Query(service.SAMPLE_PER_YEAR_DEFAULT, ge=100, le=5000),
    seed: int = Query(42, ge=0, le=10_000),
) -> Dict[str, Any]:
    """Grafo adjudicante→adjudicatária, laços societários, concentração e CIRE."""
    payload = _analysis(pais, ano_from, ano_to, cpv, per_year, 0.02, seed, False)
    if payload.get("error"):
        return payload
    relations = payload.get("relacoes") or {}
    return {
        "pais": payload.get("pais"),
        "nodes": relations.get("nodes") or [],
        "edges": relations.get("edges") or [],
        "meta": relations.get("meta") or {},
        "lacos": relations.get("lacos") or [],
        "concentracao": relations.get("concentracao") or [],
        "insolventes": relations.get("insolventes") or [],
        "pessoas": relations.get("pessoas") or [],
    }


@router.get("/news", summary="Menções em notícias das entidades sinalizadas")
def padroes_news(
    pais: str = Query("PT", pattern=PAIS_PATTERN),
    ano_from: Optional[int] = Query(None, ge=1900, le=2100),
    ano_to: Optional[int] = Query(None, ge=1900, le=2100),
    cpv: Optional[str] = Query(None, max_length=12),
    per_year: int = Query(service.SAMPLE_PER_YEAR_DEFAULT, ge=100, le=5000),
    seed: int = Query(42, ge=0, le=10_000),
    limit: int = Query(8, ge=1, le=20, description="Entidades a procurar"),
) -> Dict[str, Any]:
    """Procura menções (RSS, recolha e redes sociais) das empresas mais sinalizadas."""
    payload = _analysis(pais, ano_from, ano_to, cpv, per_year, 0.02, seed, False)
    if payload.get("error"):
        return payload
    entities = [entity for entity in (payload.get("entidades") or []) if entity.get("nome") or entity.get("nif")]
    targets: List[tuple] = []
    for entity in entities[:limit]:
        name = entity.get("nome") or ""
        if len(str(name)) >= 4:
            targets.append((f"{name} ({entity.get('nif')})", name))
    if not targets:
        return {"pais": payload.get("pais"), "items": [], "procuradas": []}
    items = service.news_mentions(targets)
    return {
        "pais": payload.get("pais"),
        "procuradas": [name for _, name in targets],
        "total": len(items),
        "items": items,
    }


@router.get("/entity/{nif}", summary="Dossiê de uma entidade")
def padroes_entity(
    nif: str,
    pais: str = Query("PT", pattern=PAIS_PATTERN),
) -> Dict[str, Any]:
    """Contratos, sinais, cargos sociais, processos CIRE e notícias de uma entidade."""
    dossier = service.entity_dossier(nif, pais=pais)
    if dossier.get("error") and "Elasticsearch" in str(dossier["error"]):
        raise HTTPException(status_code=503, detail=dossier["error"])
    return dossier


@router.post("/cache/clear", summary="Limpar a cache de análises")
def padroes_cache_clear(session: Session) -> Dict[str, Any]:
    """Liberta as análises em memória (o próximo pedido recalcula)."""
    removed = service.clear_cache()
    return {"removidas": removed, "por": session.user.email}
