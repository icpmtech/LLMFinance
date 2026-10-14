"""Rotas FastAPI do módulo **Remunerações da Administração Pública**.

O modelo é o quadro consolidado que a DGAEP publica todos os anos (*Sistema
Remuneratório da Administração Pública*): a Tabela Remuneratória Única, as
carreiras e categorias com as suas posições remuneratórias, os cargos dirigentes
e a base legal de cada carreira. As rotas leem o modelo de `data/remuneracoes-ap`
(o mesmo que a plataforma mostra e o simulador usa):

- `GET  /remuneracoes-ap/meta`         — de onde vêm os dados, anos recolhidos e metamodelo
- `GET  /remuneracoes-ap/stats`        — volumetria do ano (níveis, carreiras, dirigentes)
- `GET  /remuneracoes-ap/anos`         — anos com modelo em disco
- `GET  /remuneracoes-ap/parametros`   — BRAP do ano (nível 5) e os seus limites
- `GET  /remuneracoes-ap/niveis`       — Tabela Remuneratória Única (nível → valor mensal)
- `GET  /remuneracoes-ap/serie`        — a TRU ano a ano, para ver a evolução de cada nível
- `GET  /remuneracoes-ap/seccoes`      — secções de carreiras do ano (gerais, especiais, …)
- `GET  /remuneracoes-ap/carreiras`    — carreiras/categorias e as suas posições remuneratórias
- `GET  /remuneracoes-ap/dirigentes`   — cargos dirigentes e equiparados
- `GET  /remuneracoes-ap/notas`        — notas da DGAEP por secção
- `GET  /remuneracoes-ap/base-legal`   — base legal por carreira e grau
- `GET  /remuneracoes-ap/pesquisa`     — pesquisa no quadro indexado (por ano, tipo e texto)
- `GET  /remuneracoes-ap/simular`      — quanto vale uma posição (mensal e no ano)
- `POST /remuneracoes-ap/refresh`      — descarregar os PDF da DGAEP, ler e gravar o modelo (exige sessão)
- `POST /remuneracoes-ap/indexar`      — indexar o modelo que já está em disco (exige sessão)
"""
from __future__ import annotations

from typing import Annotated, Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query

from api import remuneracoes_ap_service as ap
from api.auth_routes import CurrentSession, optional_session

router = APIRouter(prefix="/remuneracoes-ap", tags=["remuneracoes-ap"])

Session = Annotated[CurrentSession, Depends(optional_session)]


def _escritor(session: Any) -> str:
    """Quem está a pedir a recolha (a sessão é obrigatória para escrever)."""
    if session is None or not getattr(session, "user", None):
        raise HTTPException(status_code=401, detail="Sessão necessária para recolher ou indexar.")
    utilizador = session.user
    return str(getattr(utilizador, "email", None) or getattr(utilizador, "id", None) or "desconhecido")


@router.get("/meta", summary="Proveniência, anos recolhidos e metamodelo do módulo")
def remuneracoes_ap_meta() -> Dict[str, Any]:
    return ap.meta()


@router.get("/stats", summary="Volumetria do modelo de um ano")
def remuneracoes_ap_stats(ano: Optional[int] = Query(None, description="Ano do quadro (por omissão, o mais recente).")) -> Dict[str, Any]:
    return ap.stats(ano)


@router.get("/anos", summary="Anos com modelo recolhido")
def remuneracoes_ap_anos() -> Dict[str, Any]:
    anos = ap.anos_disponiveis()
    return {
        "anos": anos,
        "ano": anos[0] if anos else None,
        "ficheiros": {str(chave): valor for chave, valor in sorted(ap.FICHEIROS.items(), reverse=True)},
        "fonte": ap.FONTE,
        "fonte_url": ap.FONTE_URL,
    }


@router.get("/parametros", summary="BRAP do ano (nível 5) e limites da tabela")
def remuneracoes_ap_parametros(ano: Optional[int] = Query(None)) -> Dict[str, Any]:
    parametros = ap.parametros_do_ano(ano)
    if not parametros:
        raise HTTPException(status_code=404, detail="Sem modelo recolhido para esse ano.")
    return parametros


@router.get("/niveis", summary="Tabela Remuneratória Única do ano")
def remuneracoes_ap_niveis(
    ano: Optional[int] = Query(None),
    minimo: Optional[int] = Query(None, ge=1, le=115, description="Nível mínimo."),
    maximo: Optional[int] = Query(None, ge=1, le=115, description="Nível máximo."),
    com_valor: bool = Query(False, description="Só os níveis com valor publicado."),
) -> Dict[str, Any]:
    alvo = ap.ano_de_referencia(ano)
    if not alvo:
        raise HTTPException(status_code=404, detail="Sem modelo recolhido para esse ano.")
    itens = [
        item
        for item in ap.niveis(alvo, com_valor=com_valor)
        if (minimo is None or item["nivel"] >= minimo) and (maximo is None or item["nivel"] <= maximo)
    ]
    return {
        "ano": alvo,
        "total": len(itens),
        "itens": itens,
        "parametros": ap.parametros_do_ano(alvo),
        "notas": (ap.ler_modelo(alvo) or {}).get("tru_notas") or [],
    }


@router.get("/serie", summary="A TRU ano a ano (evolução de cada nível)")
def remuneracoes_ap_serie(
    inicio: int = Query(5, ge=1, le=115, description="Primeiro nível da série."),
    fim: Optional[int] = Query(None, ge=1, le=115, description="Último nível da série."),
) -> Dict[str, Any]:
    anos = ap.anos_disponiveis()
    return {"anos": anos, "itens": ap.serie_dos_niveis(inicio, fim)}


@router.get("/seccoes", summary="Secções de carreiras do ano")
def remuneracoes_ap_seccoes(ano: Optional[int] = Query(None)) -> Dict[str, Any]:
    alvo = ap.ano_de_referencia(ano)
    if not alvo:
        raise HTTPException(status_code=404, detail="Sem modelo recolhido para esse ano.")
    return {"ano": alvo, "itens": ap.secao_carreiras(alvo)}


@router.get("/carreiras", summary="Carreiras/categorias e posições remuneratórias")
def remuneracoes_ap_carreiras(
    ano: Optional[int] = Query(None),
    q: Optional[str] = Query(None, description="Texto a procurar na carreira ou na categoria."),
    seccao: Optional[str] = Query(None, description="Secção do quadro (ex.: `Carreiras Gerais`)."),
    size: int = Query(40, ge=1, le=500),
    page: int = Query(1, ge=1),
) -> Dict[str, Any]:
    alvo = ap.ano_de_referencia(ano)
    if not alvo:
        raise HTTPException(status_code=404, detail="Sem modelo recolhido para esse ano.")
    itens = ap.carreiras(alvo, q=q, seccao=seccao)
    inicio = (page - 1) * size
    return {
        "ano": alvo,
        "total": len(itens),
        "page": page,
        "size": size,
        "itens": itens[inicio : inicio + size],
    }


@router.get("/dirigentes", summary="Cargos dirigentes e equiparados")
def remuneracoes_ap_dirigentes(
    ano: Optional[int] = Query(None),
    q: Optional[str] = Query(None, description="Texto a procurar no âmbito, no serviço ou no cargo."),
    ambito: Optional[str] = Query(None, description="Âmbito (ex.: `DIRIGENTES – ADMINISTRAÇÃO LOCAL`)."),
) -> Dict[str, Any]:
    alvo = ap.ano_de_referencia(ano)
    if not alvo:
        raise HTTPException(status_code=404, detail="Sem modelo recolhido para esse ano.")
    itens = ap.dirigentes(alvo, q=q, ambito=ambito)
    return {
        "ano": alvo,
        "total": len(itens),
        "itens": itens,
        "ambitos": sorted({str(item.get("ambito")) for item in ap.dirigentes(alvo) if item.get("ambito")}),
    }


@router.get("/notas", summary="Notas da DGAEP por secção")
def remuneracoes_ap_notas(
    ano: Optional[int] = Query(None),
    seccao: Optional[str] = Query(None, description="Secção das notas."),
) -> Dict[str, Any]:
    alvo = ap.ano_de_referencia(ano)
    if not alvo:
        raise HTTPException(status_code=404, detail="Sem modelo recolhido para esse ano.")
    itens = ap.notas_da_seccao(alvo, seccao)
    return {"ano": alvo, "total": len(itens), "itens": itens}


@router.get("/base-legal", summary="Base legal por carreira e grau")
def remuneracoes_ap_base_legal(
    ano: Optional[int] = Query(None),
    q: Optional[str] = Query(None, description="Texto a procurar na carreira ou na legislação."),
) -> Dict[str, Any]:
    alvo = ap.ano_de_referencia(ano)
    if not alvo:
        raise HTTPException(status_code=404, detail="Sem modelo recolhido para esse ano.")
    tabelas = ap.base_legal(alvo, q=q)
    return {
        "ano": alvo,
        "total": sum(len(tabela.get("linhas") or []) for tabela in tabelas),
        "tabelas": tabelas,
    }


@router.get("/pesquisa", summary="Pesquisa no quadro indexado (níveis, posições e dirigentes)")
def remuneracoes_ap_pesquisa(
    q: Optional[str] = Query(None, description="Texto (carreira, categoria, cargo, âmbito)."),
    ano: Optional[int] = Query(None),
    tipo: Optional[str] = Query(None, description="`nivel`, `posicao` ou `dirigente`."),
    nivel: Optional[int] = Query(None, ge=1, le=115),
    remuneracao_minima: Optional[float] = Query(None, ge=0),
    remuneracao_maxima: Optional[float] = Query(None, ge=0),
    size: int = Query(40, ge=1, le=200),
    page: int = Query(1, ge=1),
) -> Dict[str, Any]:
    from api.elasticsearch_client import search_remuneracoes_ap

    return search_remuneracoes_ap(
        q=q,
        ano=ano,
        tipo=tipo,
        nivel=nivel,
        remuneracao_minima=remuneracao_minima,
        remuneracao_maxima=remuneracao_maxima,
        size=size,
        page=page,
    )


@router.get("/simular", summary="Quanto vale uma posição (mensal e no ano)")
def remuneracoes_ap_simular(
    ano: Optional[int] = Query(None),
    nivel: Optional[int] = Query(None, ge=1, le=115, description="Nível da TRU."),
    carreira: Optional[str] = Query(None, description="Carreira (ex.: `Técnico superior`)."),
    categoria: Optional[str] = Query(None, description="Categoria dentro da carreira."),
    posicao: Optional[str] = Query(None, description="Posição remuneratória (ex.: `1`, `7-A`)."),
    cargo: Optional[str] = Query(None, description="Cargo dirigente (ex.: `Reitor`, `Diretor-geral`)."),
    ambito: Optional[str] = Query(None, description="Âmbito do cargo dirigente."),
    grupo: Optional[str] = Query(None, description="Grupo/serviço do cargo dirigente."),
    indice: Optional[int] = Query(None, description="Índice do cargo dirigente."),
    pagamentos: int = Query(ap.PAGAMENTOS_POR_ANO, ge=1, le=14, description="Pagamentos por ano (12 + subsídios)."),
) -> Dict[str, Any]:
    resultado = ap.simular(
        ano=ano,
        nivel=nivel,
        carreira=carreira,
        categoria=categoria,
        posicao=posicao,
        cargo=cargo,
        ambito=ambito,
        grupo=grupo,
        indice=indice,
        pagamentos=pagamentos,
    )
    if resultado.get("error"):
        raise HTTPException(status_code=404, detail=resultado["error"])
    return resultado


@router.post("/refresh", summary="Recolher os PDF da DGAEP e gravar o modelo (exige sessão)")
def remuneracoes_ap_refresh(
    anos: Optional[List[int]] = Query(None, description="Anos a recolher (por omissão, todos os publicados)."),
    forcar: bool = Query(False, description="Voltar a descarregar os PDF e reler."),
    indexar: bool = Query(True, description="Indexar o modelo no Elasticsearch no fim."),
    session: Session = None,
) -> Dict[str, Any]:
    autor = _escritor(session)
    resultado = ap.recolher(anos=anos, forcar=forcar)
    saida: Dict[str, Any] = {**resultado, "autor": autor}
    if indexar:
        saida["indexado"] = ap.indexar()
    return saida


@router.post("/indexar", summary="Indexar o modelo que já está em disco (exige sessão)")
def remuneracoes_ap_indexar(session: Session = None) -> Dict[str, Any]:
    autor = _escritor(session)
    return {"autor": autor, "indexado": ap.indexar(), "anos": ap.anos_disponiveis()}
