"""Rotas das peças do procedimento da Vortal (`/vortal/*`).

Descarga das peças para disco e indexação no Elasticsearch:

- Leitura pública: `GET /vortal/meta`, `/vortal/estado`, `/vortal/aviso`,
  `/vortal/pecas`, `/vortal/pesquisa`, `/vortal/avisos`, `/vortal/periodos`,
  `/vortal/periodo`.
- Escrita (exige sessão): `POST /vortal/recolha`, `POST /vortal/indexar`,
  `POST /vortal/lote`, `DELETE /vortal/aviso/{uid}`.

As ligações das peças estão publicadas nos contratos (`contratos.linkPecasProc`),
pelo que `POST /vortal/lote` recolhe por **mês e ano** — em lotes, sem colar
URLs.

O token do aviso é público (vem do URL da página de peças do procedimento); a
recolha escreve em disco (`data/vortal/<uid>/`) e, se pedido, no índice
`finance_vortal_pecas`.
"""
from __future__ import annotations

from typing import Annotated, Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from api import vortal_service as vortal
from api.admin_routes import require_admin
from api.auth_routes import CurrentSession, require_session

router = APIRouter(prefix="/vortal", tags=["vortal"])

Session = Annotated[CurrentSession, Depends(require_session)]
Admin = Annotated[CurrentSession, Depends(require_admin)]


# ------------------------------------------------------------------ modelos
class RecolhaRequest(BaseModel):
    """Recolha de peças: um ou mais avisos (URL público, UID ou token)."""

    urls: List[str] = Field(..., min_length=1, description="URLs da página de peças, URLs do aviso ou UIDs")
    indexar: bool = Field(True, description="Indexar no Elasticsearch depois de descarregar")
    extrair: bool = Field(True, description="Extrair o texto das peças (PDF/DOCX/XLSX/XML)")
    forcar: bool = Field(False, description="Voltar a descarregar mesmo que o ficheiro já exista")
    idioma: str = Field("pt-PT", max_length=10)


class IndexarRequest(BaseModel):
    """Indexação do que já está em disco."""

    uid: Optional[str] = Field(None, description="Aviso a indexar (por omissão, todos os que estão em disco)")
    recriar: bool = Field(False, description="Apagar o índice antes de indexar")


class LoteRequest(BaseModel):
    """Recolha em lote: um mês (ou um ano inteiro) do índice de contratos."""

    ano: int = Field(..., ge=2000, le=2100, description="Ano de publicação dos contratos")
    mes: Optional[int] = Field(None, ge=1, le=12, description="Mês (por omissão, o ano inteiro)")
    lote: int = Field(vortal.LOTE_PADRAO, ge=1, le=vortal.LOTE_MAXIMO, description="Avisos por lote")
    lotes: int = Field(1, ge=1, le=vortal.LOTES_POR_VEZ, description="Quantos lotes correr nesta chamada")
    indexar: bool = Field(True, description="Indexar no Elasticsearch depois de descarregar")
    extrair: bool = Field(True, description="Extrair o texto das peças (PDF/DOCX/XLSX/XML)")
    forcar: bool = Field(False, description="Voltar a descarregar mesmo que o aviso já esteja em disco")
    saltar_em_disco: Optional[bool] = Field(
        None,
        description="Só avisos ainda não recolhidos (por omissão, sim; com `forcar` não)",
    )
    escanear: int = Field(
        vortal.ESCANEAR_PADRAO,
        ge=100,
        le=vortal.ESCANEAR_MAXIMO,
        description="Contratos a ler do índice para montar a lista do período",
    )
    idioma: str = Field("pt-PT", max_length=10)


# ------------------------------------------------------------------ metadados
@router.get("/meta", summary="Metamodelo: endpoints públicos usados, índice, tipos e limites")
def vortal_meta() -> Dict[str, Any]:
    return vortal.meta()


@router.get("/estado", summary="O que está em disco e o que está indexado")
def vortal_estado() -> Dict[str, Any]:
    return vortal.estado()


@router.get("/avisos", summary="Avisos já recolhidos para disco (pelos manifestos)")
def vortal_avisos() -> Dict[str, Any]:
    avisos = vortal.listar_avisos_em_disco()
    return {
        "total": len(avisos),
        "itens": [
            {
                "uid": aviso.get("uid"),
                "token": aviso.get("token"),
                "url_aviso": aviso.get("url_aviso"),
                "recolhido_em": aviso.get("recolhido_em"),
                "totais": aviso.get("totais"),
                "pasta": aviso.get("pasta"),
            }
            for aviso in avisos
        ],
    }


@router.get("/aviso", summary="Resolve um aviso (token/URL/UID) e lista as peças sem descarregar")
def vortal_aviso(
    url: str = Query(..., description="URL da página de peças, URL do aviso ou token"),
    idioma: str = Query("pt-PT", max_length=10),
) -> Dict[str, Any]:
    token = vortal.token_de_url(url)
    uid = vortal.uid_de_url(url)
    informacao: Dict[str, Any] = {}
    if token:
        try:
            informacao = vortal.informacao_aviso(token, idioma=idioma)
        except Exception as erro:  # noqa: BLE001
            raise HTTPException(status_code=502, detail=f"a Vortal não respondeu: {erro}") from erro
        uid = informacao.get("uid") or uid
    if not uid:
        raise HTTPException(status_code=422, detail="não foi possível determinar o aviso a partir do URL/token")
    try:
        pecas = vortal.documentos_do_aviso(str(uid))
    except Exception as erro:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=f"falhou a leitura das peças: {erro}") from erro
    return {
        "uid": uid,
        "token": token,
        "url_aviso": informacao.get("url_aviso"),
        "publicado": informacao.get("publicado"),
        "pecas": pecas,
        "total": len(pecas),
        "em_disco": bool(vortal.ler_manifesto(str(uid))),
    }


# ------------------------------------------------------------------- recolha
@router.post("/recolha", summary="Descarregar as peças para disco e (opcionalmente) indexar (exige sessão)")
def vortal_recolha(pedido: RecolhaRequest, session: Session = None) -> Dict[str, Any]:
    resultado = vortal.recolher(
        pedido.urls,
        indexar=pedido.indexar,
        extrair=pedido.extrair,
        forcar=pedido.forcar,
        idioma=pedido.idioma,
    )
    vortal.registar_recolha(resultado, autor=getattr(session.user, "email", None), tipo="recolha", urls=pedido.urls)
    if resultado.get("avisos") == 0 and resultado.get("erros"):
        raise HTTPException(status_code=502, detail="; ".join(resultado["erros"][:3]))
    return resultado


@router.post("/lote", summary="Recolher e indexar, em lotes, os avisos Vortal de um mês/ano (exige sessão)")
def vortal_lote(pedido: LoteRequest, session: Session = None) -> Dict[str, Any]:
    resultado = vortal.recolher_lote(
        ano=pedido.ano,
        mes=pedido.mes,
        lote=pedido.lote,
        lotes=pedido.lotes,
        indexar=pedido.indexar,
        extrair=pedido.extrair,
        forcar=pedido.forcar,
        saltar_em_disco=pedido.saltar_em_disco,
        idioma=pedido.idioma,
        escanear=pedido.escanear,
    )
    vortal.registar_recolha(
        resultado,
        autor=getattr(session.user, "email", None),
        tipo="lote",
        urls=[f"{pedido.ano}-{pedido.mes or 'ano'}"],
    )
    if not resultado.get("ok"):
        raise HTTPException(status_code=502, detail=str(resultado.get("erro") or "recolha em lote falhou"))
    return resultado


@router.post("/indexar", summary="Indexar no Elasticsearch o que já está em disco (exige sessão)")
def vortal_indexar(pedido: IndexarRequest, session: Session = None) -> Dict[str, Any]:
    resultado = vortal.indexar_em_disco(uid=pedido.uid)
    if pedido.recriar:
        resultado["recriar"] = True
    vortal.registar_recolha(
        {"avisos": resultado.get("avisos") or 0, "pecas": resultado.get("indexados") or 0, "indice": resultado},
        autor=getattr(session.user, "email", None),
        tipo="indexacao",
        urls=[pedido.uid] if pedido.uid else [],
    )
    return resultado


# ------------------------------------------------------------------ períodos
@router.get("/periodos", summary="Anos e meses com avisos Vortal publicados (para escolher o lote)")
def vortal_periodos() -> Dict[str, Any]:
    return vortal.periodos()


@router.get("/periodo", summary="O que há num mês/ano: avisos, o que já está em disco e o que falta")
def vortal_periodo(
    ano: int = Query(..., ge=2000, le=2100, description="Ano de publicação dos contratos"),
    mes: Optional[int] = Query(None, ge=1, le=12, description="Mês (por omissão, o ano inteiro)"),
    limite: int = Query(20, ge=1, le=200),
    escanear: int = Query(vortal.ESCANEAR_PADRAO, ge=100, le=vortal.ESCANEAR_MAXIMO),
) -> Dict[str, Any]:
    return vortal.avisos_do_periodo(ano=ano, mes=mes, limite=limite, escanear=escanear)


# ------------------------------------------------------------------ consulta
@router.get("/pecas", summary="Peças indexadas (por aviso ou todas)")
def vortal_pecas(
    uid: Optional[str] = Query(None, description="UID do aviso"),
    limite: int = Query(50, ge=1, le=200),
) -> Dict[str, Any]:
    return vortal.listar_pecas(uid=uid, limite=limite)


@router.get("/pesquisa", summary="Pesquisa no texto das peças recolhidas")
def vortal_pesquisa(
    q: str = Query(..., min_length=2),
    uid: Optional[str] = Query(None),
    limite: int = Query(25, ge=1, le=100),
) -> Dict[str, Any]:
    return vortal.pesquisar(q, uid=uid, limite=limite)


@router.delete("/aviso/{uid}", summary="Remover um aviso do índice (e do disco, se pedido) — exige sessão")
def vortal_apagar(
    uid: str,
    disco: bool = Query(False, description="Apagar também os ficheiros em disco"),
    session: Session = None,
) -> Dict[str, Any]:
    resultado = vortal.apagar_aviso(uid, apagar_disco=disco)
    vortal.registar_recolha(
        {"avisos": 1 if resultado.get("ok") else 0, "pecas": resultado.get("apagados") or 0},
        autor=getattr(session.user, "email", None),
        tipo="remocao",
        urls=[uid],
    )
    return resultado


# --------------------------------------------------------------- administração
@router.get("/admin/monitorizacao", summary="Monitorização do módulo (só administradores)")
def vortal_admin_monitorizacao(limite: int = Query(20, ge=1, le=100), session: Admin = None) -> Dict[str, Any]:
    return vortal.monitorizacao(limite=limite)


@router.get("/admin/recolhas", summary="Histórico de recolhas e indexações (só administradores)")
def vortal_admin_recolhas(limite: int = Query(20, ge=1, le=100), session: Admin = None) -> Dict[str, Any]:
    return {"itens": vortal.historico_recolhas(limite=limite)}


@router.get("/admin/indice", summary="Estado do índice das peças no Elasticsearch (só administradores)")
def vortal_admin_indice(session: Admin = None) -> Dict[str, Any]:
    estado = vortal.estado()
    return {"indice": estado.get("indice"), "disco": estado.get("disco")}
