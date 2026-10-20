"""Rotas do módulo **ESG** (`/esg/*`).

O módulo responde a três perguntas, com um número que se pode explicar:

- **onde está a empresa** (score global e por pilar, cobertura e confiança);
- **como evoluiu e como se compara** (série de 3 anos e benchmark de setor e
  dimensão);
- **como está a carteira de fornecedores** (distribuição por nível ESG e sinais).

Endpoints:

- `GET  /esg/meta`                          — cartão do modelo, fontes, setores, CPV e catálogo
- `GET  /esg/status`                        — índices, contagens e últimas execuções
- `GET  /esg/pesquisa`                      — pesquisa de empresas com score ESG
- `GET  /esg/sugestoes`                     — sugestões (nome/NIF) para a caixa de pesquisa
- `GET  /esg/ranking`                       — ranking por score, pilar, setor, dimensão e ano
- `GET  /esg/ranking.csv`                   — exportação do ranking em CSV
- `GET  /esg/analitica`                     — painel agregado (médias, distribuições e destaques)
- `GET  /esg/empresa/{pais}/{nif}`          — dossiê ESG da empresa
- `GET  /esg/empresa/{pais}/{nif}/historico`— série de 3 anos + benchmark
- `GET  /esg/empresa/{pais}/{nif}/fornecedores` — carteira de fornecedores do comprador
- `GET  /esg/empresa/{pais}/{nif}/indicadores`  — indicadores declarados por ano/fonte
- `POST /esg/carteira/analise`              — analisa uma carteira de fornecedores indicada
- `POST /esg/indicadores`                   — ingere indicadores de um relatório        (sessão)
- `POST /esg/calcular`                      — calcula e indexa um lote de empresas      (sessão)

A leitura é pública, como nos restantes módulos; a ingestão de indicadores e o
cálculo em lote exigem sessão (e, pela matriz de permissões, escrita no módulo
`esg`, reservada a administradores e gestores de plataforma).
"""
from __future__ import annotations

import logging
from typing import Annotated, Any, Dict, List, Optional, Union

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from pydantic import BaseModel, Field
from starlette.concurrency import run_in_threadpool

from api import esg_service as service
from api.auth_routes import CurrentSession, require_session

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/esg", tags=["esg"])

Session = Annotated[CurrentSession, Depends(require_session)]

PAIS_PATTERN = "^(PT|ES|pt|es)$"
NIVEL_PATTERN = "^(lider|avancado|intermedio|inicial|fraco)$"
DIMENSAO_PATTERN = "^(sem_dados|micro|pequena|media|grande)$"
SETOR_PATTERN = "^[A-Ua-u]$"
PILAR_PATTERN = "^(e|s|g)$"
ORDENAR_PATTERN = "^(relevancia|score|score_asc|pior|e|s|g|valor|contratos|nome|nome_asc)$"


class IndicadorItem(BaseModel):
    codigo: str = Field(..., description="Código do catálogo (ex.: `e_emissoes_scope1`)")
    valor: float = Field(..., description="Valor numérico na unidade do catálogo")


class IndicadoresPayload(BaseModel):
    """Indicadores de um relatório de sustentabilidade (um ano e uma fonte)."""

    nif: str = Field(..., description="NIF/NIPC da empresa")
    nome: Optional[str] = Field(None, description="Nome, quando o cadastro ainda não o tem")
    pais: str = Field("PT", description="PT ou ES")
    ano: int = Field(..., ge=2000, le=2100, description="Ano do relatório")
    fonte: str = Field("relatorios_sustentabilidade", description="Identificador da fonte")
    url: Optional[str] = Field(None, description="Ligação para o relatório")
    verificacao: str = Field("declarada", description="`declarada` ou `externa`")
    origem: Optional[str] = Field(None, description="Como os indicadores foram obtidos")
    indicadores: Union[Dict[str, float], List[IndicadorItem]] = Field(..., description="Código → valor, ou lista de itens")
    recalcular: bool = Field(True, description="Recalcular o score da empresa depois de guardar")


class LotePayload(BaseModel):
    """Cálculo em lote (por NIFs explícitos ou pela carteira do cadastro)."""

    nifs: List[str] = Field(default_factory=list, description="NIFs a calcular (se vazio, usa o cadastro)")
    pais: str = Field("PT", description="PT ou ES")
    limite: int = Field(50, ge=1, le=500, description="Máximo de empresas")
    min_contratos: int = Field(1, ge=0, description="Mínimo de contratos no cadastro")
    anos: int = Field(3, ge=1, le=5, description="Anos de histórico")
    max_contratos: int = Field(600, ge=50, le=1_000, description="Contratos lidos por empresa")


class CarteiraPayload(BaseModel):
    """Carteira de fornecedores indicada por NIF e/ou nome."""

    nifs: List[str] = Field(default_factory=list)
    nomes: List[str] = Field(default_factory=list)
    pais: str = Field("PT", description="PT ou ES")
    calcular_em_falta: bool = Field(True, description="Calcular quem ainda não tem fotografia ESG")


def _validar_pais(pais: Optional[str]) -> None:
    if pais and service.pais_codigo(pais) not in ("PT", "ES"):
        raise HTTPException(status_code=400, detail=f"país desconhecido: {pais} (use PT ou ES)")


def _ou_erro(payload: Dict[str, Any]) -> Dict[str, Any]:
    """Converte o erro do motor numa resposta HTTP adequada."""
    erro = str(payload.get("error") or "")
    if not erro:
        return payload
    if "Elasticsearch" in erro:
        raise HTTPException(status_code=503, detail=erro)
    if "Indique" in erro or "inválid" in erro or "desconhecido" in erro or "deve ser" in erro or "Nenhum" in erro:
        raise HTTPException(status_code=400, detail=erro)
    raise HTTPException(status_code=404, detail=erro)


@router.get("/meta", summary="Cartão do modelo ESG, fontes, setores, CPV e catálogo de indicadores")
def esg_meta() -> Dict[str, Any]:
    """Explica o número: pilares, pesos, limiares, faixas, dimensões e fontes."""
    return service.meta()


@router.get("/status", summary="Estado do módulo ESG (índices, contagens e execuções)")
def esg_status() -> Dict[str, Any]:
    """Índices `finance_esg_*`, última fotografia e últimas execuções."""
    return service.status()


@router.get("/pesquisa", summary="Pesquisar empresas com score ESG")
async def esg_pesquisa(
    q: str = Query(..., min_length=2, description="Nome, marca ou NIF da empresa"),
    pais: Optional[str] = Query(None, pattern=PAIS_PATTERN, description="Filtrar por país"),
    setor: Optional[str] = Query(None, pattern=SETOR_PATTERN, description="Secção CAE (A–U)"),
    dimensao: Optional[str] = Query(None, pattern=DIMENSAO_PATTERN, description="Dimensão da carteira"),
    nivel: Optional[str] = Query(None, pattern=NIVEL_PATTERN, description="Faixa do score"),
    ordenar: str = Query("relevancia", pattern=ORDENAR_PATTERN, description="relevancia | score | e | s | g | valor | contratos | nome"),
    pilar: Optional[str] = Query(None, pattern=PILAR_PATTERN, description="Ordenar por um pilar"),
    size: int = Query(10, ge=1, le=30, description="Empresas por pedido"),
    from_: int = Query(0, ge=0, le=500, alias="from"),
    incluir_nao_indexadas: bool = Query(True, description="Calcular ao vivo as empresas ainda sem fotografia"),
) -> Dict[str, Any]:
    """No índice ESG; se não houver fotografia, resolve no cadastro e calcula.

    A primeira consulta a uma empresa custa mais (lê contratos, CAE, CIRE e
    indicadores); fica guardada para as seguintes.
    """
    _validar_pais(pais)
    return _ou_erro(
        await run_in_threadpool(
            service.pesquisa,
            q,
            pais=pais,
            setor=setor,
            dimensao=dimensao,
            nivel=nivel,
            ordenar=ordenar,
            pilar=pilar,
            size=size,
            from_=from_,
            incluir_nao_indexadas=incluir_nao_indexadas,
        )
    )


@router.get("/sugestoes", summary="Sugestões de empresas para a caixa de pesquisa")
def esg_sugestoes(
    q: str = Query(..., min_length=2, description="Nome ou NIF (mínimo 2 caracteres)"),
    size: int = Query(8, ge=1, le=20),
) -> Dict[str, Any]:
    """Sugestões do cadastro (nome, NIF, país, contratos)."""
    return service.sugestoes(q, size=size)


@router.get("/ranking", summary="Ranking ESG de empresas")
async def esg_ranking(
    pais: Optional[str] = Query(None, pattern=PAIS_PATTERN),
    setor: Optional[str] = Query(None, pattern=SETOR_PATTERN),
    dimensao: Optional[str] = Query(None, pattern=DIMENSAO_PATTERN),
    nivel: Optional[str] = Query(None, pattern=NIVEL_PATTERN),
    ano: Optional[int] = Query(None, ge=2000, le=2100),
    ordenar: str = Query("score", pattern=ORDENAR_PATTERN),
    pilar: Optional[str] = Query(None, pattern=PILAR_PATTERN),
    size: int = Query(20, ge=1, le=100),
    from_: int = Query(0, ge=0, le=5_000, alias="from"),
) -> Dict[str, Any]:
    """Ranking global, por pilar, setor, dimensão e ano, com posição."""
    _validar_pais(pais)
    return _ou_erro(
        await run_in_threadpool(
            service.ranking,
            pais=pais,
            setor=setor,
            dimensao=dimensao,
            nivel=nivel,
            ano=ano,
            ordenar=ordenar,
            pilar=pilar,
            size=size,
            from_=from_,
        )
    )


@router.get("/ranking.csv", summary="Exportar o ranking ESG em CSV")
def esg_ranking_csv(
    pais: Optional[str] = Query(None, pattern=PAIS_PATTERN),
    setor: Optional[str] = Query(None, pattern=SETOR_PATTERN),
    dimensao: Optional[str] = Query(None, pattern=DIMENSAO_PATTERN),
    nivel: Optional[str] = Query(None, pattern=NIVEL_PATTERN),
    ano: Optional[int] = Query(None, ge=2000, le=2100),
    ordenar: str = Query("score", pattern=ORDENAR_PATTERN),
    limite: int = Query(500, ge=1, le=1_000),
) -> Response:
    """CSV com posição, NIF, nome, setor, dimensão, score, pilares e cobertura."""
    _validar_pais(pais)
    conteudo = service.exportar_csv(
        pais=pais, setor=setor, dimensao=dimensao, nivel=nivel, ano=ano, ordenar=ordenar, limite=limite
    )
    return Response(
        content=conteudo,
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": 'attachment; filename="esg-ranking.csv"'},
    )


@router.get("/analitica", summary="Painel agregado do módulo ESG")
async def esg_analitica(
    pais: Optional[str] = Query(None, pattern=PAIS_PATTERN),
    setor: Optional[str] = Query(None, pattern=SETOR_PATTERN),
    dimensao: Optional[str] = Query(None, pattern=DIMENSAO_PATTERN),
    nivel: Optional[str] = Query(None, pattern=NIVEL_PATTERN),
    ano: Optional[int] = Query(None, ge=2000, le=2100),
    q: Optional[str] = Query(None, min_length=2, max_length=200),
) -> Dict[str, Any]:
    """Médias, distribuições por nível/setor/dimensão/distrito e destaques."""
    _validar_pais(pais)
    return _ou_erro(
        await run_in_threadpool(
            service.analitica, pais=pais, setor=setor, dimensao=dimensao, nivel=nivel, ano=ano, q=q
        )
    )


@router.get("/empresa/{pais}/{nif}", summary="Dossiê ESG de uma empresa")
async def esg_empresa(
    pais: str,
    nif: str,
    ano: Optional[int] = Query(None, ge=2000, le=2100, description="Ano de referência (por omissão, o último com contratos)"),
    historico_anos: int = Query(3, ge=1, le=5, description="Anos da série"),
    incluir_fornecedores: bool = Query(True, description="Incluir a carteira de fornecedores (contratos como comprador)"),
    indexar: bool = Query(True, description="Guardar/atualizar a fotografia no índice"),
) -> Dict[str, Any]:
    """Score, pilares, componentes, série de 3 anos, benchmark, indicadores e evidências."""
    _validar_pais(pais)
    return _ou_erro(
        await run_in_threadpool(
            service.empresa_detalhe,
            nif=nif,
            pais=service.pais_codigo(pais),
            ano=ano,
            historico_anos=historico_anos,
            incluir_fornecedores=incluir_fornecedores,
            indexar=indexar,
        )
    )


@router.get("/empresa/{pais}/{nif}/historico", summary="Série de 3 anos e benchmark da empresa")
async def esg_empresa_historico(
    pais: str,
    nif: str,
    anos: int = Query(3, ge=1, le=5),
) -> Dict[str, Any]:
    """Evolução do score e dos pilares, com a mediana dos pares por ano."""
    _validar_pais(pais)
    return _ou_erro(
        await run_in_threadpool(service.historico_empresa, nif=nif, pais=service.pais_codigo(pais), anos=anos)
    )


@router.get("/empresa/{pais}/{nif}/fornecedores", summary="Carteira de fornecedores de um comprador")
async def esg_empresa_fornecedores(
    pais: str,
    nif: str,
    limite: int = Query(500, ge=20, le=2_000, description="Contratos como comprador lidos"),
    calcular_em_falta: bool = Query(True, description="Calcular fornecedores ainda sem fotografia ESG"),
    max_calcular: int = Query(12, ge=0, le=30, description="Máximo de fornecedores calculados no pedido"),
) -> Dict[str, Any]:
    """Distribuição dos fornecedores por nível ESG, valor imputado e sinais."""
    _validar_pais(pais)
    return _ou_erro(
        await run_in_threadpool(
            service.fornecedores_da_empresa,
            nif=nif,
            pais=service.pais_codigo(pais),
            limite=limite,
            calcular_em_falta=calcular_em_falta,
            max_calcular=max_calcular,
        )
    )


@router.get("/empresa/{pais}/{nif}/indicadores", summary="Indicadores ESG declarados da empresa")
def esg_empresa_indicadores(
    pais: str,
    nif: str,
    ano: Optional[int] = Query(None, ge=2000, le=2100),
) -> Dict[str, Any]:
    """Indicadores guardados por ano e fonte (o que a empresa publicou)."""
    _validar_pais(pais)
    return service.indicadores_empresa(nif=nif, pais=service.pais_codigo(pais), ano=ano)


@router.post("/carteira/analise", summary="Analisar uma carteira de fornecedores")
async def esg_carteira_analise(payload: CarteiraPayload) -> Dict[str, Any]:
    """Score ESG de cada fornecedor indicado, com distribuição e alertas."""
    _validar_pais(payload.pais)
    if not payload.nifs and not payload.nomes:
        raise HTTPException(status_code=400, detail="Indique pelo menos um NIF ou nome de fornecedor.")
    return _ou_erro(
        await run_in_threadpool(
            service.carteira_analise,
            nifs=payload.nifs,
            nomes=payload.nomes,
            pais=service.pais_codigo(payload.pais),
            calcular_em_falta=payload.calcular_em_falta,
        )
    )


@router.post("/indicadores", summary="Ingerir indicadores de um relatório de sustentabilidade")
async def esg_ingerir_indicadores(payload: IndicadoresPayload, session: Session) -> Dict[str, Any]:
    """Guarda os indicadores declarados, valida os códigos e recalcula a empresa."""
    _validar_pais(payload.pais)
    dados = payload.model_dump()
    dados["pais"] = service.pais_codigo(payload.pais)
    return _ou_erro(
        await run_in_threadpool(service.ingerir_indicadores, dados, user={"id": session.user.id, "email": session.user.email})
    )


@router.post("/calcular", summary="Calcular e indexar um lote de empresas")
async def esg_calcular(payload: LotePayload, session: Session) -> Dict[str, Any]:
    """Calcula o score das empresas indicadas (ou da carteira do cadastro) e indexa."""
    _validar_pais(payload.pais)
    dados = payload.model_dump()
    dados["pais"] = service.pais_codigo(payload.pais)
    return _ou_erro(
        await run_in_threadpool(service.calcular_lote, dados, user={"id": session.user.id, "email": session.user.email})
    )
