"""Rotas do módulo **Administração Central** (`/administracao-central/*`).

Serve o índice das entidades do Setor Institucional das Administrações Públicas
(edição anual do INE, SEC 2010) e cruza-o com os contratos públicos do portal
BASE para mostrar, por entidade e por subsetor, os contratos adjudicados e as
empresas adjudicatárias.

- `GET  /administracao-central/meta`                — fonte, ficheiros e volumetria do índice
- `GET  /administracao-central/subsetores`          — subsetores indexados e cobertura das ligações
- `GET  /administracao-central/entidades`           — pesquisa da lista de entidades
- `GET  /administracao-central/entidades/{id}`      — ficha da entidade (contratos, adjudicatárias, CPV)
- `GET  /administracao-central/entidades/{id}/contratos` — contratos adjudicados por uma entidade
- `GET  /administracao-central/contratos`           — pesquisa de contratos do setor
- `GET  /administracao-central/analiticas`          — painel do setor (volume, valor, rankings)
- `GET  /administracao-central/export.csv`          — exportação da pesquisa de entidades
- `POST /administracao-central/reindexar`           — relê o PDF e refaz as ligações aos contratos
"""
from __future__ import annotations

import logging
from typing import Annotated, Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import Response
from pydantic import BaseModel, Field

from api import administracao_central_service as administracao_central
from api.auth_routes import CurrentSession, optional_session, require_session

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/administracao-central", tags=["administracao-central"])

Session = Annotated[CurrentSession, Depends(require_session)]
ReadSession = Annotated[CurrentSession, Depends(optional_session)]


class ReindexarRequest(BaseModel):
    """Opções da reconstrução do índice a partir do PDF da fonte."""

    usar_contratos: bool = Field(
        True, description="Ligar as entidades aos NIF do índice de contratos (requer Elasticsearch)"
    )


class Entidade(BaseModel):
    """Entidade do setor institucional, com a ligação ao cadastro de contratos."""

    id: str
    nome: str
    slug: str
    subsetor: str
    subsetor_nome: str
    nif: Optional[str] = None
    nome_contratos: Optional[str] = None
    ligacao: str = Field(..., description="exato | nome | prefixo | sigla | forte | manual | nenhuma")
    ligacao_confianca: float = 0.0
    contratos: int = 0
    valor: float = 0.0
    ano_min: Optional[int] = None
    ano_max: Optional[int] = None


class EntidadesResponse(BaseModel):
    query: Optional[str] = None
    subsetor: str = "all"
    ordenar: str = "valor"
    total: int = 0
    from_: int = Field(0, alias="from")
    size: int = 25
    items: List[Entidade] = []
    error: Optional[str] = None

    model_config = {"populate_by_name": True}


@router.get("/meta")
def administracao_central_meta(session: ReadSession = None) -> Dict[str, Any]:
    """Fonte (PDF do INE), ficheiros em disco e cobertura das ligações a NIF."""
    return administracao_central.meta()


@router.get("/subsetores")
def administracao_central_subsetores(session: ReadSession = None) -> Dict[str, Any]:
    """Subsetores indexados (SEC 2010) e quantas entidades ficaram ligadas a um NIF."""
    dados = administracao_central.meta()
    return {
        "fonte": dados.get("fonte"),
        "subsetor_omissao": dados.get("subsetor_omissao"),
        "items": dados.get("subsetores") or [],
        "total": dados.get("total", 0),
        "ligadas": dados.get("ligadas", 0),
        "indice_em_falta": dados.get("indice_em_falta", False),
    }


@router.get("/entidades", response_model=EntidadesResponse)
def administracao_central_entidades(
    q: Optional[str] = Query(None, description="Texto a procurar no nome da entidade, no nome usado nos contratos ou no NIF"),
    subsetor: Optional[str] = Query(None, description="Subsetor SEC 2010 (por omissão, todos os indexados)"),
    ligacao: Optional[str] = Query(
        None,
        pattern="^(com_nif|sem_nif|com_contratos)$",
        description="Filtrar por tipo de ligação ao cadastro de contratos",
    ),
    ordenar: str = Query("valor", pattern="^(nome|nome_desc|contratos|valor|subsetor)$"),
    size: int = Query(25, ge=1, le=500),
    from_: int = Query(0, ge=0, alias="from"),
    session: ReadSession = None,
) -> EntidadesResponse:
    """Pesquisa o índice de entidades do setor (nome, subsetor e ligação a NIF)."""
    resultado = administracao_central.pesquisar(
        q=q, subsetor=subsetor, ligacao=ligacao, ordenar=ordenar, tamanho=size, desde=from_
    )
    return EntidadesResponse(**resultado)


@router.get("/entidades/{identificador}")
def administracao_central_entidade(
    identificador: str,
    top: int = Query(15, ge=1, le=100, description="Quantas adjudicatárias, CPV e contratos recentes mostrar"),
    session: ReadSession = None,
) -> Dict[str, Any]:
    """Ficha da entidade: contratos adjudicados, quem lhe vendeu e o que comprou."""
    ficha = administracao_central.ficha_entidade(identificador, tamanho=top)
    if ficha.get("error") == "Entidade não encontrada":
        raise HTTPException(status_code=404, detail="Entidade não encontrada.")
    return ficha


@router.get("/entidades/{identificador}/contratos")
def administracao_central_contratos_da_entidade(
    identificador: str,
    q: Optional[str] = Query(None, description="Texto no objeto do contrato"),
    ano: Optional[int] = Query(None),
    adjudicatario: Optional[str] = Query(None, description="Nome da adjudicatária"),
    cpv: Optional[str] = Query(None, description="Código CPV (prefixo ou código completo)"),
    size: int = Query(20, ge=1, le=200),
    from_: int = Query(0, ge=0, alias="from"),
    session: ReadSession = None,
) -> Dict[str, Any]:
    """Contratos em que a entidade é adjudicante."""
    item = administracao_central.entidade(identificador)
    if not item:
        raise HTTPException(status_code=404, detail="Entidade não encontrada.")
    if not item.get("nif"):
        return {
            "query": q,
            "total": 0,
            "items": [],
            "from": from_,
            "size": size,
            "aviso": "Entidade sem NIF ligado nos contratos do portal BASE.",
        }
    resultado = administracao_central.contratos(
        nif=item["nif"], q=q, ano=ano, adjudicatario=adjudicatario, cpv=cpv, tamanho=size, desde=from_
    )
    if resultado.get("error"):
        raise HTTPException(status_code=502, detail=resultado["error"])
    return resultado


@router.get("/contratos")
def administracao_central_contratos(
    q: Optional[str] = Query(None, description="Texto livre (objeto, descrição, entidades)"),
    subsetor: Optional[str] = Query(None, description="Limita às entidades de um subsetor"),
    ano: Optional[int] = Query(None),
    entidade: Optional[str] = Query(None, description="Nome da entidade adjudicante"),
    adjudicatario: Optional[str] = Query(None, description="Nome da adjudicatária"),
    cpv: Optional[str] = Query(None, description="Código CPV (prefixo ou código completo)"),
    preco_min: Optional[float] = Query(None, description="Valor mínimo do contrato (€)"),
    preco_max: Optional[float] = Query(None, description="Valor máximo do contrato (€)"),
    size: int = Query(20, ge=1, le=200),
    from_: int = Query(0, ge=0, alias="from"),
    session: ReadSession = None,
) -> Dict[str, Any]:
    """Pesquisa os contratos adjudicados pelas entidades do setor."""
    resultado = administracao_central.contratos(
        subsetor=subsetor,
        q=q,
        ano=ano,
        entidade=entidade,
        adjudicatario=adjudicatario,
        cpv=cpv,
        preco_min=preco_min,
        preco_max=preco_max,
        tamanho=size,
        desde=from_,
    )
    if resultado.get("error"):
        raise HTTPException(status_code=502, detail=resultado["error"])
    return resultado


@router.get("/analiticas")
def administracao_central_analiticas(
    subsetor: Optional[str] = Query(None, description="Subsetor SEC 2010 (por omissão, todos)"),
    ano: Optional[int] = Query(None, description="Ano dos contratos"),
    nif: Optional[str] = Query(None, description="Restringe a uma entidade (NIF)"),
    q: Optional[str] = Query(None, description="Texto livre nos contratos"),
    top: int = Query(20, ge=1, le=100, description="Tamanho dos rankings"),
    forcar: bool = Query(False, description="Ignora a cache das agregações"),
    session: ReadSession = None,
) -> Dict[str, Any]:
    """Painel do setor: volume e valor dos contratos, anos, entidades, adjudicatárias e CPV."""
    resultado = administracao_central.agregacoes(subsetor, ano=ano, q=q, nif=nif, top=top, forcar=forcar)
    if resultado.get("error"):
        raise HTTPException(status_code=502, detail=resultado["error"])
    return resultado


@router.get("/export.csv")
def administracao_central_export(
    q: Optional[str] = Query(None),
    subsetor: Optional[str] = Query(None),
    session: ReadSession = None,
) -> Response:
    """CSV com as entidades do índice e os totais de contrato ligados a cada uma."""
    return Response(
        content=administracao_central.exportar_csv(subsetor=subsetor, q=q),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": 'attachment; filename="administracao-central.csv"'},
    )


@router.post("/reindexar")
def administracao_central_reindexar(
    payload: ReindexarRequest | None = None, session: Session = None
) -> Dict[str, Any]:
    """Relê o PDF do INE e refaz as ligações nome→NIF a partir do índice de contratos."""
    opcoes = payload or ReindexarRequest()
    try:
        indice = administracao_central.reconstruir(usar_contratos=opcoes.usar_contratos)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return {
        "total": indice["total"],
        "ligadas": indice["ligadas"],
        "subsetores": indice["subsetores"],
        "gerado_em": indice.get("gerado_em"),
        "ficheiro": str(administracao_central.INDICE),
    }
