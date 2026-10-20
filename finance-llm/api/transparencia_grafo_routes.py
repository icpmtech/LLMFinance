"""Rotas do módulo **Grafo da Transparência** (`/transparencia-grafo/*`).

O módulo transforma as declarações únicas da Entidade para a Transparência numa
rede de **pessoas, cargos, entidades públicas e empresas**, com a sede das
empresas geocodificada para o mapa.

Endpoints:

- `GET  /transparencia-grafo/meta`        — proveniência, ficheiros, índices, tipos e relações
- `GET  /transparencia-grafo/stats`       — volumetria em disco e no índice
- `GET  /transparencia-grafo/dimensoes`   — tipos de nó, relações e filtros para a UI
- `GET  /transparencia-grafo/grafo`       — subgrafo filtrado (nós + arestas)
- `GET  /transparencia-grafo/nos/{id}`    — ficha do nó e vizinhos
- `GET  /transparencia-grafo/empresas`    — empresas/entidades com sede e coordenadas
- `GET  /transparencia-grafo/mapa`        — pontos e agregados por concelho
- `GET  /transparencia-grafo/export.csv`  — exportação da lista ou do grafo
- `POST /transparencia-grafo/construir`   — constrói o grafo (segundo plano)
- `POST /transparencia-grafo/indexar`     — indexa o grafo em disco (segundo plano)
- `GET  /transparencia-grafo/jobs[/{id}]` — progresso dos trabalhos
"""
from __future__ import annotations

from typing import Annotated, Any, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from pydantic import BaseModel, Field

from api import transparencia_grafo_service as svc
from api.auth_routes import CurrentSession, optional_session, require_session

router = APIRouter(prefix="/transparencia-grafo", tags=["transparencia-grafo"])

Session = Annotated[CurrentSession, Depends(require_session)]
ReadSession = Annotated[CurrentSession, Depends(optional_session)]


class ConstruirRequest(BaseModel):
    """Como construir o grafo a partir das declarações em disco."""

    forcar: bool = Field(False, description="Reconstruir mesmo que o manifesto esteja atualizado")
    indexar: bool = Field(True, description="Indexar no Elasticsearch no fim")
    limite_declaracoes: Optional[int] = Field(
        None, ge=1, description="Máximo de declarações a ler (útil para uma amostra)"
    )


@router.get("/meta")
def grafo_meta(session: ReadSession = None) -> Dict[str, Any]:
    """Proveniência, ficheiros, índices, tipos de nó e relações."""
    return svc.meta()


@router.get("/stats")
def grafo_stats(session: ReadSession = None) -> Dict[str, Any]:
    """Volumetria do grafo em disco e no índice."""
    return svc.stats()


@router.get("/dimensoes")
def grafo_dimensoes() -> Dict[str, Any]:
    """Tipos de nó, relações e precisões geográficas para os filtros da UI."""
    return {
        "tipos": svc.TIPOS_NO,
        "relacoes": svc.RELACOES,
        "precisoes": svc.meta().get("precisoes") or {},
        "metricas": {"ligacoes": "Ligações (grau do nó)"},
    }


@router.get("/grafo")
def grafo(
    tipo: Optional[str] = Query(None, description="Tipos de nó separados por vírgula (pessoa,cargo,entidade,empresa)"),
    relacao: Optional[str] = Query(None, description="Relações separadas por vírgula (EXERCE,CARGO_EM,ATIVIDADE,PARTICIPACAO,BENEFICIO,SERVICO)"),
    q: Optional[str] = Query(None, description="Pesquisa por nome, NIF ou concelho"),
    ano: Optional[int] = Query(None, ge=1900, le=2100, description="Ano em que o nó aparece"),
    nif: Optional[str] = Query(None, description="NIF/NIPC exato"),
    foco: Optional[str] = Query(None, description="Id do nó a expandir (ex.: empresa:500000000)"),
    profundidade: int = Query(1, ge=1, le=3, description="Saltos a partir do nó em foco"),
    min_peso: int = Query(1, ge=1, le=10_000, description="Peso mínimo da aresta"),
    limit: int = Query(80, ge=0, le=500, description="Nós a manter (0 = todos)"),
    edge_limit: int = Query(400, ge=0, le=20_000, description="Arestas a manter (0 = todas)"),
) -> Dict[str, Any]:
    """Constrói o subgrafo pedido.

    Sem filtros devolve os nós mais ligados, equilibrados por tipo. Com `foco`
    devolve a vizinhança do nó; com `tipo`/`relacao`/`q`/`ano` filtra a rede.
    """
    return svc.grafo(
        tipo=tipo,
        relacao=relacao,
        q=q,
        ano=ano,
        nif=nif,
        foco=foco,
        profundidade=profundidade,
        min_peso=min_peso,
        limit=limit,
        edge_limit=edge_limit,
    )


@router.get("/nos/{no_id}")
def grafo_no(no_id: str) -> Dict[str, Any]:
    """Ficha de um nó (pessoa, cargo, entidade ou empresa) e os seus vizinhos."""
    resultado = svc.no_detail(no_id)
    if resultado.get("error"):
        raise HTTPException(status_code=404, detail=resultado["error"])
    return resultado


@router.get("/empresas")
def grafo_empresas(
    q: Optional[str] = Query(None, description="Pesquisa por nome, NIF, concelho ou sede"),
    concelho: Optional[str] = Query(None, description="Concelho exato (como resolvido)"),
    com_geo: Optional[bool] = Query(None, description="Só com (true) ou sem (false) coordenadas"),
    tipo: str = Query("empresa", description="Tipos separados por vírgula (empresa,entidade)"),
    ordenar: str = Query("grau", pattern="^(grau|ligacoes|peso|nome)$"),
    limit: int = Query(100, ge=0, le=5_000, description="Itens por página (0 = todos)"),
    offset: int = Query(0, ge=0),
) -> Dict[str, Any]:
    """Empresas (e entidades, se pedido) com a sede, a geolocalização e as ligações."""
    return svc.empresas(
        q=q,
        concelho=concelho,
        com_geo=com_geo,
        tipo=tipo,
        limit=limit,
        offset=offset,
        ordenar=ordenar,
    )


@router.get("/concelhos/{concelho}")
def grafo_concelho(
    concelho: str,
    limite: int = Query(100, ge=1, le=1000, description="Empresas a devolver"),
    offset: int = Query(0, ge=0),
    incluir_contratacao: bool = Query(True, description="Cruzar cada NIF com a contratação pública (portal BASE)"),
) -> Dict[str, Any]:
    """Empresas de um concelho com as relações no grafo e a contratação pública."""
    resultado = svc.concelho_detalhe(
        concelho,
        limite=limite,
        offset=offset,
        incluir_contratacao=incluir_contratacao,
    )
    if resultado.get("error"):
        raise HTTPException(status_code=404, detail=resultado["error"])
    return resultado


@router.get("/mapa")
def grafo_mapa(    q: Optional[str] = Query(None, description="Pesquisa por nome, NIF ou concelho"),
    concelho: Optional[str] = Query(None, description="Restringe a um concelho"),
    tipo: str = Query("empresa", description="Tipos com sede no mapa (empresa,entidade)"),
    limite_pontos: int = Query(1500, ge=0, le=20_000, description="Pontos individuais a devolver"),
    limite_concelhos: int = Query(60, ge=0, le=500, description="Concelhos no agregado"),
    limite_sem_geo: int = Query(200, ge=0, le=1_000, description="Entidades sem coordenadas a listar"),
) -> Dict[str, Any]:
    """Mapa das empresas: pontos, agregado por concelho e lista das sem coordenadas."""
    return svc.mapa(
        q=q,
        concelho=concelho,
        tipo=tipo,
        limite_pontos=limite_pontos,
        limite_concelhos=limite_concelhos,
        limite_sem_geo=limite_sem_geo,
    )


@router.get("/export.csv")
def grafo_export(
    vista: str = Query("empresas", pattern="^(empresas|nos)$", description="Exportar empresas ou nós do grafo"),
    q: Optional[str] = Query(None),
    concelho: Optional[str] = Query(None),
    tipo: Optional[str] = Query(None, description="Empresas: tipo; nós: `no_tipo`"),
    no_tipo: Optional[str] = Query(None, description="Tipos de nó (export `nos`)"),
    com_geo: Optional[bool] = Query(None),
    limit: int = Query(50_000, ge=0, le=200_000),
) -> Response:
    """CSV (Excel) das empresas ou dos nós filtrados."""
    conteudo = svc.csv_bytes(
        vista=vista,
        q=q,
        concelho=concelho,
        tipo=tipo or "empresa",
        no_tipo=no_tipo,
        com_geo=com_geo,
        limit=limit,
    )
    nome = "transparencia-grafo-empresas.csv" if vista == "empresas" else "transparencia-grafo-nos.csv"
    return Response(
        content=conteudo,
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{nome}"'},
    )


@router.post("/construir")
def grafo_construir(payload: ConstruirRequest, session: Session = None) -> Dict[str, Any]:
    """Constrói o grafo a partir das declarações em disco (trabalho em segundo plano)."""
    return svc.start_job("construir", payload.model_dump())


@router.post("/indexar")
def grafo_indexar(session: Session = None) -> Dict[str, Any]:
    """Indexa o grafo em disco nos índices `finance_ept_grafo_*`."""
    return svc.start_job("indexar", {})


@router.get("/jobs")
def grafo_jobs(session: ReadSession = None) -> Dict[str, Any]:
    """Trabalhos de construção/indexação desta instância."""
    return svc.list_jobs()


@router.get("/jobs/{job_id}")
def grafo_job(job_id: str, session: ReadSession = None) -> Dict[str, Any]:
    """Progresso de um trabalho."""
    resultado = svc.job_status(job_id)
    if not resultado:
        raise HTTPException(status_code=404, detail="Trabalho desconhecido")
    return resultado
