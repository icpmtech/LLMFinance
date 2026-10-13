"""Rotas FastAPI do módulo **Remunerações dos Eleitos Locais** (`/remuneracoes/*`).

Duas metades que se cruzam:

- a **tabela oficial** dos abonos (Lei n.º 11/96), por escalão de eleitores,
  regime, cargo e modalidade — `GET /remuneracoes/tabelas`;
- o **território** — quantos eleitores inscritos tem cada concelho e freguesia
  (recenseamento do MAI) e o polígono para o mapa — `GET /remuneracoes/mapa`,
  `GET /remuneracoes/concelhos`, `GET /remuneracoes/freguesias`.

Juntas dão o que interessa a cada município: `GET /remuneracoes/concelhos/{id}`
devolve os eleitores do concelho, o escalão em que cai, os abonos que lhe
correspondem, quem foi eleito em 2025 (presidente da câmara e vereadores por
partido) e a mesma conta para cada uma das suas freguesias.

- `GET  /remuneracoes/meta`              — de onde vêm os dados e o que já está lido
- `GET  /remuneracoes/stats`             — volumetria (territórios, eleitores, cobertura do mapa)
- `GET  /remuneracoes/tabelas`           — a tabela de abonos (por ano e nível)
- `GET  /remuneracoes/escaloes`          — escalões de eleitores de um nível
- `GET  /remuneracoes/concelhos`         — concelhos com eleitores, escalão e abono
- `GET  /remuneracoes/concelhos/{id}`    — ficha do concelho e das suas freguesias
- `GET  /remuneracoes/freguesias`        — pesquisa de freguesias
- `GET  /remuneracoes/mapa`              — coordenadas + eleitores + abono (mapa OSM)
- `GET  /remuneracoes/eleitos`           — presidentes de câmara e vereadores eleitos em 2025
- `GET  /remuneracoes/simular`           — quanto vale um território com N eleitores
- `POST /remuneracoes/refresh`           — recolher do MAI, georreferenciar e reindexar
- `POST /remuneracoes/eleitos/recolher`  — recolher os eleitos e reindexar
- `POST /remuneracoes/reindex`           — reindexar sem recolher
- `POST /remuneracoes/tabelas/import`    — importar/substituir uma tabela (ex.: municípios)
"""
from __future__ import annotations

from typing import Annotated, Any, Dict, List, Optional

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field

from api import remuneracoes_service as remuneracoes
from api.auth_routes import CurrentSession, optional_session

router = APIRouter(prefix="/remuneracoes", tags=["remuneracoes"])

Session = Annotated[CurrentSession, Depends(optional_session)]


class EscalaoItem(BaseModel):
    id: str
    designacao: str
    ordem: Optional[int] = None
    min_eleitores: Optional[int] = None
    max_eleitores: Optional[int] = None
    percentagem_pr: Optional[float] = None
    inferido: Optional[bool] = None


class RubricaItem(BaseModel):
    id: str
    regime: str = ""
    grupo: str = ""
    cargo: str = ""
    modalidade: str = ""
    natureza: str = ""
    percentagens: Optional[Dict[str, Optional[float]]] = None
    valores: Dict[str, Optional[float]] = Field(default_factory=dict)


class TabelaImportRequest(BaseModel):
    ano: int
    nivel: str = Field(description="`municipio` ou `freguesia`")
    titulo: str = ""
    estado: str = "importada"
    nota: Optional[str] = None
    escaloes: List[EscalaoItem]
    rubricas: List[RubricaItem] = Field(default_factory=list)


@router.get("/meta", summary="Proveniência dos dados e volumetria da tabela")
def remuneracoes_meta(session: Session = None) -> Dict[str, Any]:
    fonte = remuneracoes.abonos().get("fonte") or {}
    dados = remuneracoes.territorios()
    geo = remuneracoes.geo()
    return {
        "recolhido_em": dados.get("cached_at"),
        "fonte_territorios": dados.get("fonte"),
        "fonte_territorios_url": dados.get("fonte_url"),
        "eleicao": dados.get("eleicao"),
        "fonte_geo": geo.get("fonte"),
        "fonte_geo_url": geo.get("fonte_url"),
        "licenca_geo": geo.get("licenca"),
        "tabela": {
            "documento": fonte.get("documento"),
            "ficheiro": fonte.get("ficheiro"),
            "base_legal": fonte.get("base_legal"),
            "atualizacao": fonte.get("atualizacao"),
            "unidade": fonte.get("unidade"),
            "referencias": remuneracoes.abonos().get("referencias") or {},
        },
        "niveis": [t.get("nivel") for t in remuneracoes.abonos().get("tabelas") or []],
    }


@router.get("/stats", summary="Volumetria do que está recolhido")
def remuneracoes_stats(session: Session = None) -> Dict[str, Any]:
    return remuneracoes.stats()


@router.get("/tabelas", summary="Tabela de abonos dos eleitos locais")
def remuneracoes_tabelas(
    nivel: Optional[str] = Query(None, description="`municipio` ou `freguesia`"),
    ano: Optional[int] = Query(None, description="Ano da tabela"),
    session: Session = None,
) -> Dict[str, Any]:
    tabelas = remuneracoes.tabelas(nivel=nivel, ano=ano)
    return {
        "total": len(tabelas),
        "fonte": remuneracoes.abonos().get("fonte") or {},
        "referencias": remuneracoes.abonos().get("referencias") or {},
        "tabelas": tabelas,
    }


@router.get("/escaloes", summary="Escalões de eleitores de um nível")
def remuneracoes_escaloes(
    nivel: str = Query("freguesia", description="`municipio` ou `freguesia`"),
    ano: Optional[int] = Query(None),
    session: Session = None,
) -> Dict[str, Any]:
    tabela = remuneracoes.tabela(nivel, ano) or {}
    return {
        "nivel": nivel,
        "ano": tabela.get("ano"),
        "titulo": tabela.get("titulo"),
        "estado": tabela.get("estado"),
        "total": len(tabela.get("escaloes") or []),
        "escaloes": tabela.get("escaloes") or [],
    }


@router.get("/concelhos", summary="Concelhos com eleitores, escalão e abonos")
def remuneracoes_concelhos(
    q: Optional[str] = Query(None, description="Nome do concelho ou distrito"),
    distrito: Optional[str] = Query(None, description="Distrito (substring)"),
    min_eleitores: Optional[int] = Query(None, ge=0, description="Mínimo de eleitores inscritos"),
    max_eleitores: Optional[int] = Query(None, ge=0, description="Máximo de eleitores inscritos"),
    page: int = Query(1, ge=1),
    size: int = Query(50, ge=1, le=500),
    session: Session = None,
) -> Dict[str, Any]:
    return remuneracoes.listar_concelhos(
        q=q,
        distrito=distrito,
        min_eleitores=min_eleitores,
        max_eleitores=max_eleitores,
        page=page,
        size=size,
    )


@router.get("/concelhos/{concelho}", summary="Ficha de um concelho e das suas freguesias")
def remuneracoes_concelho_detail(concelho: str, session: Session = None) -> Dict[str, Any]:
    return remuneracoes.concelho_detail(concelho)


@router.get("/freguesias", summary="Freguesias com eleitores, escalão e abonos")
def remuneracoes_freguesias(
    q: Optional[str] = Query(None, description="Nome da freguesia"),
    concelho: Optional[str] = Query(None, description="Concelho (substring)"),
    distrito: Optional[str] = Query(None, description="Distrito (substring)"),
    escalao_id: Optional[str] = Query(None, description="Filtrar por escalão de eleitores"),
    page: int = Query(1, ge=1),
    size: int = Query(100, ge=1, le=1000),
    session: Session = None,
) -> Dict[str, Any]:
    return remuneracoes.freguesias(
        q=q,
        concelho=concelho,
        distrito=distrito,
        escalao_id=escalao_id,
        page=page,
        size=size,
    )


@router.get("/mapa", summary="Coordenadas, eleitores e abonos por território")
def remuneracoes_mapa(
    nivel: str = Query("municipio", description="`municipio` (os 308 concelhos) ou `freguesia`"),
    distrito: Optional[str] = Query(None, description="Distrito (substring)"),
    concelho: Optional[str] = Query(None, description="Concelho (só com `nivel=freguesia`)"),
    q: Optional[str] = Query(None, description="Nome do território (substring)"),
    session: Session = None,
) -> Dict[str, Any]:
    return remuneracoes.mapa(nivel=nivel, distrito=distrito, concelho=concelho, q=q)


@router.get("/simular", summary="Abonos de um território com N eleitores")
def remuneracoes_simular(
    eleitores: int = Query(..., ge=0, description="Número de eleitores inscritos"),
    nivel: str = Query("freguesia", description="`municipio` ou `freguesia`"),
    session: Session = None,
) -> Dict[str, Any]:
    return {
        "nivel": nivel,
        "eleitores": eleitores,
        **remuneracoes.resumo_territorio(nivel, eleitores),
    }


@router.get("/eleitos", summary="Presidentes de câmara e vereadores eleitos (2025)")
def remuneracoes_eleitos(
    distrito: Optional[str] = Query(None, description="Distrito (substring)"),
    q: Optional[str] = Query(None, description="Nome do concelho ou do presidente (substring)"),
    partido: Optional[str] = Query(None, description="Sigla do partido que elegeu o presidente"),
    page: int = Query(1, ge=1),
    size: int = Query(50, ge=1, le=308),
    session: Session = None,
) -> Dict[str, Any]:
    return remuneracoes.listar_eleitos(
        distrito=distrito, q=q, partido=partido, page=page, size=size
    )


@router.post("/eleitos/recolher", summary="Recolher os eleitos do MAI e reindexar")
def remuneracoes_recolher_eleitos(
    forcar: bool = Query(False, description="Pedir tudo outra vez, em vez de só o que falta"),
    reindexar: bool = Query(True, description="Indexar no Elasticsearch depois de recolher"),
    session: Session = None,
) -> Dict[str, Any]:
    resultado = remuneracoes.collect_eleitos(forcar=forcar)
    saida: Dict[str, Any] = {
        "recolhido_em": resultado.get("cached_at"),
        "total_concelhos": resultado.get("total_concelhos"),
        "total_com_presidente": resultado.get("total_com_presidente"),
    }
    if reindexar:
        saida["indexado"] = remuneracoes.indexar()
    return saida


@router.post("/refresh", summary="Recolher de novo do MAI e reindexar")
def remuneracoes_refresh(
    incluir_freguesias: bool = Query(True, description="Recolher também as ~3259 freguesias"),
    reindexar: bool = Query(True, description="Indexar no Elasticsearch depois de recolher"),
    forcar: bool = Query(False, description="Pedir tudo outra vez, em vez de só o que falta"),
    incluir_eleitos: bool = Query(True, description="Recolher também os eleitos de 2025"),
    session: Session = None,
) -> Dict[str, Any]:
    return remuneracoes.refresh(
        incluir_freguesias=incluir_freguesias,
        reindexar=reindexar,
        forcar=forcar,
        incluir_eleitos=incluir_eleitos,
    )


@router.post("/reindex", summary="Indexar no Elasticsearch sem recolher dados novos")
def remuneracoes_reindex(session: Session = None) -> Dict[str, Any]:
    return remuneracoes.indexar()


@router.post("/tabelas/import", summary="Importar/substituir uma tabela de abonos")
def remuneracoes_importar_tabela(
    payload: TabelaImportRequest,
    session: Session = None,
) -> Dict[str, Any]:
    return remuneracoes.importar_tabela(payload.model_dump())
