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
- `GET  /remuneracoes/eleitos/nomes`     — quem foi eleito (Mapa Oficial da CNE) e o que a fonte não traz
- `GET  /remuneracoes/pessoas`           — quem foi eleito, onde e quanto recebe (todas as pessoas)
- `GET  /remuneracoes/camaras`           — os edifícios das câmaras, com foto e créditos
- `GET  /remuneracoes/municipios`        — brasão, data de criação, eleitores e abono de cada município
- `GET  /remuneracoes/eleitos/executivo` — cobertura dos nomes do executivo (sites dos municípios)
- `GET  /remuneracoes/simular`           — quanto vale um território com N eleitores
- `POST /remuneracoes/refresh`           — recolher do MAI, georreferenciar e reindexar
- `POST /remuneracoes/eleitos/recolher`  — recolher os eleitos e reindexar
- `POST /remuneracoes/eleitos/nomes/recolher` — recolher os nomes do Mapa Oficial da CNE
- `POST /remuneracoes/camaras/recolher`  — recolher as câmaras municipais (fotos)
- `POST /remuneracoes/municipios/recolher` — recolher os brasões e as datas de criação
- `POST /remuneracoes/eleitos/executivo` — importar os nomes do executivo de um município
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


class ExecutivoMembro(BaseModel):
    nome: str
    cargo: Optional[str] = Field(None, description="`Presidente`, `Vice-Presidente` ou `Vereador`")
    partido: Optional[str] = Field(None, description="Filiação declarada pelo município")
    atribuicoes: Optional[str] = Field(None, description="Pelouros, tal como o município os escreve")
    url: Optional[str] = Field(None, description="Página do eleito no site do município")


class ExecutivoImportRequest(BaseModel):
    """Os nomes do executivo de um município, lidos do site da câmara."""

    concelho: str
    fonte: Optional[str] = None
    fonte_url: Optional[str] = None
    consultado_em: Optional[str] = None
    membros: List[ExecutivoMembro]


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
        "municipios": {
            "fonte": (remuneracoes.municipios() or {}).get("fonte"),
            "fonte_url": (remuneracoes.municipios() or {}).get("fonte_url"),
            "fonte_imagens": (remuneracoes.municipios() or {}).get("fonte_imagens"),
            "recolhido_em": (remuneracoes.municipios() or {}).get("recolhido_em"),
        },
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
    municipio: Optional[str] = Query(
        None, description="Nome do município (Lisboa e Porto têm escalão próprio na tabela)"
    ),
    session: Session = None,
) -> Dict[str, Any]:
    return {
        "nivel": nivel,
        "eleitores": eleitores,
        **remuneracoes.resumo_territorio(nivel, eleitores, municipio),
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


@router.get("/eleitos/executivo", summary="Cobertura dos nomes do executivo municipal")
def remuneracoes_cobertura_executivo(session: Session = None) -> Dict[str, Any]:
    return remuneracoes.cobertura_executivo()


@router.get("/eleitos/nomes", summary="Nomes dos eleitos (Mapa Oficial da CNE) e cobertura")
def remuneracoes_nomes_eleitos(
    freguesia: Optional[str] = Query(None, description="Ficha dos eleitos de uma freguesia (id)"),
    session: Session = None,
) -> Dict[str, Any]:
    if freguesia:
        detalhe = remuneracoes.eleitos_freguesia(freguesia)
        return detalhe or {"error": "Freguesia sem eleitos transcritos", "freguesia": freguesia}
    nomes = remuneracoes.nomes_eleitos()
    freguesias_doc = nomes.get("freguesias") or {}
    return {
        "fonte": nomes.get("fonte"),
        "fonte_url": nomes.get("fonte_url"),
        "fonte_pagina": nomes.get("fonte_pagina"),
        "eleicao": nomes.get("eleicao"),
        "recolhido_em": nomes.get("cached_at"),
        "nota": nomes.get("nota"),
        "municipios": {
            "total": nomes.get("total_concelhos"),
            "com_presidente": nomes.get("total_com_presidente"),
            "total_vereadores": nomes.get("total_vereadores"),
        },
        "freguesias": {
            "total": freguesias_doc.get("total"),
            "com_presidente": freguesias_doc.get("com_presidente"),
            "total_sem_correspondencia": freguesias_doc.get("total_sem_correspondencia"),
            "sem_correspondencia": freguesias_doc.get("sem_correspondencia"),
        },
        # O que a fonte oficial não traz, dito por palavras: mandatos sem nome no
        # mapa (lacunas) e nomes em que as duas fontes divergem (divergências).
        "lacunas": nomes.get("lacunas"),
        "divergencias": nomes.get("divergencias"),
        "sem_correspondencia": nomes.get("sem_correspondencia"),
    }


@router.get("/pessoas", summary="Quem foi eleito, onde e quanto recebe")
def remuneracoes_pessoas(
    q: Optional[str] = Query(None, description="Nome, município, freguesia ou partido"),
    distrito: Optional[str] = Query(None),
    concelho: Optional[str] = Query(None),
    cargo: Optional[str] = Query(None, description="`presidente`, `vereador`, `presidente_junta`, `assembleia_freguesia`"),
    partido: Optional[str] = Query(None, description="Sigla da candidatura"),
    nivel: Optional[str] = Query(None, description="`municipio` ou `freguesia`"),
    page: int = Query(1, ge=1),
    size: int = Query(50, ge=1, le=500),
    session: Session = None,
) -> Dict[str, Any]:
    return remuneracoes.listar_pessoas(
        q=q, distrito=distrito, concelho=concelho, cargo=cargo, partido=partido,
        nivel=nivel, page=page, size=size,
    )


@router.get("/camaras", summary="Câmaras municipais (edifício, foto e créditos)")
def remuneracoes_camaras(
    q: Optional[str] = Query(None, description="Designação ou município"),
    distrito: Optional[str] = Query(None),
    apenas_com_foto: bool = Query(False, description="Só as que têm fotografia"),
    session: Session = None,
) -> Dict[str, Any]:
    return remuneracoes.listar_camaras(q=q, distrito=distrito, apenas_com_foto=apenas_com_foto)


@router.get("/municipios", summary="Municípios: brasão, data de criação, eleitores e abono")
def remuneracoes_municipios(
    q: Optional[str] = Query(None, description="Município, distrito ou código de três letras"),
    distrito: Optional[str] = Query(None),
    apenas_com_brasao: bool = Query(False, description="Só os que têm brasão"),
    ordem: str = Query("nome", description="`nome`, `criacao` (mais antigos primeiro) ou `populacao`"),
    session: Session = None,
) -> Dict[str, Any]:
    return remuneracoes.listar_municipios(
        q=q, distrito=distrito, apenas_com_brasao=apenas_com_brasao, ordem=ordem
    )


@router.post("/municipios/recolher", summary="Recolher os brasões e as datas de criação")
def remuneracoes_recolher_municipios(
    forcar: bool = Query(False, description="Voltar a ler a lista da Wikipédia"),
    reindexar: bool = Query(True),
    session: Session = None,
) -> Dict[str, Any]:
    dados = remuneracoes.municipios(forcar=forcar)
    saida: Dict[str, Any] = {
        "recolhido_em": dados.get("recolhido_em"),
        "fonte": dados.get("fonte"),
        "total": len(dados.get("municipios") or []),
        "com_brasao": dados.get("com_brasao"),
        "com_credito": dados.get("com_credito"),
        "com_data_criacao": dados.get("com_data_criacao"),
        "erro": dados.get("erro"),
    }
    if reindexar:
        saida["indexado"] = remuneracoes.indexar()
    return saida


@router.post("/eleitos/nomes/recolher", summary="Recolher os nomes dos eleitos do Mapa Oficial da CNE")
def remuneracoes_recolher_nomes(
    forcar: bool = Query(False, description="Voltar a descarregar o mapa oficial"),
    reindexar: bool = Query(True),
    session: Session = None,
) -> Dict[str, Any]:
    dados = remuneracoes.collect_eleitos_nomes(forcar=forcar)
    freguesias_doc = dados.get("freguesias") or {}
    saida: Dict[str, Any] = {
        "recolhido_em": dados.get("cached_at"),
        "municipios": {
            "total": dados.get("total_concelhos"),
            "com_presidente": dados.get("total_com_presidente"),
            "total_vereadores": dados.get("total_vereadores"),
        },
        "freguesias": {
            "total": freguesias_doc.get("total"),
            "com_presidente": freguesias_doc.get("com_presidente"),
        },
        "lacunas": dados.get("lacunas"),
        "divergencias": dados.get("divergencias"),
    }
    if reindexar:
        saida["indexado"] = remuneracoes.indexar()
    return saida


@router.post("/camaras/recolher", summary="Recolher as câmaras municipais (fotos do Commons)")
def remuneracoes_recolher_camaras(
    forcar: bool = Query(False),
    reindexar: bool = Query(True),
    session: Session = None,
) -> Dict[str, Any]:
    dados = remuneracoes.camaras(forcar=forcar)
    saida: Dict[str, Any] = {
        "recolhido_em": dados.get("recolhido_em"),
        "total_edificios": len(dados.get("camaras") or []),
        "com_foto": sum(1 for c in dados.get("camaras") or [] if c.get("imagem")),
        "com_coordenadas": sum(1 for c in dados.get("camaras") or [] if c.get("lat") is not None),
    }
    if reindexar:
        saida["indexado"] = remuneracoes.indexar()
    return saida


@router.post("/eleitos/executivo", summary="Importar os nomes do executivo de um município")
def remuneracoes_importar_executivo(
    payload: ExecutivoImportRequest,
    session: Session = None,
) -> Dict[str, Any]:
    return remuneracoes.importar_executivo(payload.model_dump())


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
