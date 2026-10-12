"""Rotas do módulo **Partidos políticos e as suas contas** (`/partidos/*`).

Junta as duas fontes oficiais do financiamento partidário português:

- **Tribunal Constitucional — Financiamento Partidário** (`contas_eleicoes-partidos`):
  por ano, as *contas anuais* de cada partido, as *listas de ações e meios* de
  propaganda política, os *relatórios* da ECFP, os *acórdãos* e as *decisões*;
- **CNE — Partidos Políticos**: o registo oficial (denominação, sigla, data de
  inscrição, inscritos/extintos, sítio, símbolo e descrição).

Endpoints:

- `GET  /partidos/meta`             — pastas, anos, o que está lido e indexado
- `GET  /partidos/anos`             — anos publicados pelo TC e o que está em disco
- `GET  /partidos/fontes`           — as fontes do módulo e as secções do TC
- `GET  /partidos/ficheiros`        — páginas, PDF e JSONL em disco
- `POST /partidos/recolher`         — recolhe páginas + PDF + CNE para JSONL (segundo plano)
- `POST /partidos/indexar`          — indexa os JSONL em `finance_partidos` (segundo plano)
- `GET  /partidos/jobs[/{id}]`      — progresso dos trabalhos
- `GET  /partidos/resumo`           — painel: por ano, por secção e top partidos
- `GET  /partidos/search`           — pesquisa (texto, ano, secção, partido, cumprimento)
- `GET  /partidos/registo`          — registo oficial dos partidos (CNE), com pesquisa
- `GET  /partidos/partido/{termo}`  — ficha do partido: registo da CNE + contas por ano
- `GET  /partidos/partido/{termo}/pessoas` — pessoas do PessoasIQ ligadas ao partido
- `GET  /partidos/pessoa/{nif}`     — a pessoa e o partido dela, com as contas do partido
- `GET  /partidos/amostra/{ano}`    — amostra lida do disco (funciona sem Elasticsearch)
- `GET  /partidos/documento/pdf`    — o PDF guardado (ano + ficheiro), sem sair da pasta
- `GET  /partidos/export.csv`       — exportação da pesquisa
"""
from __future__ import annotations

import logging
from typing import Annotated, Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import FileResponse, Response
from pydantic import BaseModel, Field

from api import partidos_service as partidos
from api.auth_routes import CurrentSession, optional_session, require_session

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/partidos", tags=["partidos"])

Session = Annotated[CurrentSession, Depends(require_session)]
ReadSession = Annotated[CurrentSession, Depends(optional_session)]


class PartidosRecolherRequest(BaseModel):
    """O que recolher das duas fontes."""

    anos: Optional[List[int]] = Field(None, description="Anos do TC a recolher (por omissão, todos os publicados)")
    secoes: Optional[List[str]] = Field(
        None,
        description=(
            "Secções a recolher (`contas_anuais`, `lista_acoes`, `relatorios_ecfp`, "
            "`acordaos`, `decisoes_ecfp`); por omissão, todas"
        ),
    )
    com_pdf: bool = Field(
        True,
        description="Descarregar os PDF e extrair-lhes o texto (mais lento; sem isto fica só o metadados e as ligações)",
    )
    com_cne: bool = Field(True, description="Recolher também o registo oficial dos partidos (CNE)")
    forcar: bool = Field(False, description="Reler/descarregar mesmo o que já está em disco")
    indexar: bool = Field(False, description="Indexar no Elasticsearch no fim da recolha")


class PartidosIndexarRequest(BaseModel):
    """O que indexar."""

    anos: Optional[List[int]] = Field(None, description="Anos a indexar (por omissão, todos os lidos)")
    forcar: bool = Field(False, description="Reindexar mesmo o que já está indexado")


@router.get("/meta")
def partidos_meta(session: ReadSession = None) -> Dict[str, Any]:
    """Pasta dos dados, anos recolhidos, volumetria em disco e índices usados."""
    return partidos.meta()


@router.get("/anos")
def partidos_anos(refrescar: bool = Query(False, description="Voltar a ler a lista de anos na página do TC")) -> Dict[str, Any]:
    """Anos com página própria no TC e o que já está recolhido."""
    try:
        disponiveis = partidos.anos_disponiveis(refrescar=refrescar)
    except Exception as exc:  # noqa: BLE001 - sem rede, o que está em disco serve
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    manifesto = partidos.read_manifest()
    recolhidos = manifesto.get("anos") or {}
    linhas = []
    for ano in disponiveis:
        entrada = recolhidos.get(str(ano)) or {}
        linhas.append(
            {
                "ano": ano,
                "url": partidos.TC_ANO_URL.format(ano=ano),
                "recolhido": bool(entrada),
                "itens": entrada.get("itens"),
                "documentos": entrada.get("documentos"),
                "partidos": entrada.get("partidos"),
                "com_texto": entrada.get("com_texto"),
                "digitalizados": entrada.get("digitalizados"),
                "indexados": entrada.get("indexados"),
                "recolhido_em": entrada.get("recolhido_em"),
            }
        )
    return {"total": len(disponiveis), "minimo": partidos.TC_ANO_MINIMO, "anos": sorted(linhas, key=lambda linha: -linha["ano"])}


@router.get("/fontes")
def partidos_fontes(session: ReadSession = None) -> Dict[str, Any]:
    """As fontes do módulo (TC e CNE), o que cada uma dá e as secções da página anual."""
    return partidos.fontes()


@router.get("/ficheiros")
def partidos_ficheiros(session: ReadSession = None) -> Dict[str, Any]:
    """Páginas, PDF e JSONL guardados na pasta do módulo."""
    return partidos.ficheiros()


@router.post("/recolher")
def partidos_recolher(payload: PartidosRecolherRequest | None = None, session: Session = None) -> Dict[str, Any]:
    """Recolhe páginas anuais do TC, PDF e registo da CNE para JSONL (segundo plano)."""
    dados = (payload or PartidosRecolherRequest()).model_dump()
    return partidos.start_job("recolher", dados)


@router.post("/indexar")
def partidos_indexar(payload: PartidosIndexarRequest | None = None, session: Session = None) -> Dict[str, Any]:
    """Indexa os JSONL já lidos no Elasticsearch (segundo plano)."""
    dados = (payload or PartidosIndexarRequest()).model_dump()
    return partidos.start_job("indexar", dados)


@router.get("/jobs")
def partidos_jobs(session: ReadSession = None) -> Dict[str, Any]:
    """Trabalhos de recolha e indexação (mais recentes primeiro)."""
    return partidos.list_jobs()


@router.get("/jobs/{job_id}")
def partidos_job(job_id: str, session: ReadSession = None) -> Dict[str, Any]:
    """Estado de um trabalho."""
    job = partidos.job_status(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Trabalho não encontrado.")
    return job


@router.get("/resumo")
def partidos_resumo(
    ano: Optional[List[int]] = Query(None, description="Anos a considerar (repetível; por omissão, todos)"),
    session: ReadSession = None,
) -> Dict[str, Any]:
    """Painel do módulo: por ano, por secção, top partidos e cumprimento."""
    resultado = partidos.resumo(anos=ano)
    if resultado.get("error"):
        raise HTTPException(status_code=503, detail=str(resultado["error"]))
    return resultado


@router.get("/search")
def partidos_search(
    q: Optional[str] = Query(None, description="Texto livre (partido, sigla, título da secção, texto do PDF)"),
    ano: Optional[int] = Query(None, description="Ano da página do TC"),
    secao: Optional[str] = Query(
        None, description="contas_anuais | lista_acoes | relatorios_ecfp | acordaos | decisoes_ecfp"
    ),
    partido: Optional[str] = Query(None, description="Chave, sigla ou nome do partido"),
    sigla: Optional[str] = Query(None, description="Sigla exata (como o TC a publica)"),
    entregou: Optional[bool] = Query(None, description="Só o que foi entregue (`true`) ou o que falta (`false`)"),
    com_documento: Optional[bool] = Query(None, description="Só as entradas com documento publicado"),
    digitalizado: Optional[bool] = Query(None, description="Só os PDF que são digitalizações (sem texto extraível)"),
    sort: str = Query("relevancia", pattern="^(relevancia|ano|partido|secao|paginas)$"),
    order: str = Query("desc", pattern="^(asc|desc)$"),
    page: int = Query(1, ge=1),
    size: int = Query(25, ge=1, le=200),
    session: ReadSession = None,
) -> Dict[str, Any]:
    """Pesquisa os documentos das contas, com facetas (ano, secção, partido) e indicadores."""
    resultado = partidos.search(
        q=q,
        ano=ano,
        secao=secao,
        partido=partido,
        sigla=sigla,
        entregou=entregou,
        com_documento=com_documento,
        digitalizado=digitalizado,
        sort=sort,
        order=order,
        page=page,
        size=size,
    )
    if resultado.get("error"):
        raise HTTPException(status_code=503, detail=str(resultado["error"]))
    return resultado


@router.get("/registo")
def partidos_registo(
    q: Optional[str] = Query(None, description="Nome ou sigla do partido"),
    situacao: Optional[str] = Query(None, pattern="^(inscrito|extinto)$", description="inscrito | extinto"),
    page: int = Query(1, ge=1),
    size: int = Query(50, ge=1, le=200),
    session: ReadSession = None,
) -> Dict[str, Any]:
    """Registo oficial dos partidos na CNE (inscritos e extintos)."""
    resultado = partidos.listar_registo(q=q, situacao=situacao, page=page, size=size)
    if resultado.get("error"):
        raise HTTPException(status_code=503, detail=str(resultado["error"]))
    return resultado


@router.get("/partido/{termo}")
def partidos_partido(
    termo: str,
    size: int = Query(400, ge=1, le=1000),
    session: ReadSession = None,
) -> Dict[str, Any]:
    """Ficha do partido: o registo da CNE e todas as contas publicadas pela ECFP, ano a ano."""
    resultado = partidos.por_partido(termo, size=size)
    if resultado.get("error"):
        raise HTTPException(status_code=503, detail=str(resultado["error"]))
    if not resultado.get("encontrado"):
        raise HTTPException(status_code=404, detail="Sem contas indexadas para este partido (faça a recolha ou corrija a sigla).")
    return resultado


@router.get("/partido/{termo}/pessoas")
def partidos_partido_pessoas(
    termo: str,
    size: int = Query(60, ge=1, le=200),
    session: ReadSession = None,
) -> Dict[str, Any]:
    """Pessoas indexadas no PessoasIQ com este partido (deputados e políticos)."""
    resultado = partidos.pessoas_do_partido(termo, size=size)
    if resultado.get("error"):
        raise HTTPException(status_code=503, detail=str(resultado["error"]))
    return resultado


@router.get("/pessoa/{nif}")
def partidos_pessoa(nif: str, session: ReadSession = None) -> Dict[str, Any]:
    """A pessoa (PessoasIQ) e o partido dela, com as contas desse partido."""
    resultado = partidos.pessoa_e_partido(nif)
    if resultado.get("error"):
        raise HTTPException(status_code=404, detail=str(resultado["error"]))
    return resultado


@router.get("/amostra/{ano}")
def partidos_amostra(
    ano: int,
    limit_items: int = Query(50, ge=1, le=500),
    session: ReadSession = None,
) -> Dict[str, Any]:
    """Amostra das entradas lidas de um ano (não precisa do Elasticsearch)."""
    return partidos.amostra(ano, limite=limit_items)


@router.get("/documento/pdf")
def partidos_documento_pdf(
    ano: int = Query(..., description="Ano da página do TC"),
    ficheiro: str = Query(..., description="Nome do ficheiro, como o TC o publica"),
    download: bool = Query(False, description="Forçar o descarregamento em vez de abrir no browser"),
    session: ReadSession = None,
) -> FileResponse:
    """Serve o PDF guardado no módulo (o browser pode abri-lo sem voltar ao TC)."""
    try:
        caminho = partidos.caminho_documento(ano, ficheiro)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if not caminho.exists():
        raise HTTPException(status_code=404, detail="Documento não encontrado no módulo (faça a recolha com PDF).")
    return FileResponse(
        caminho,
        media_type="application/pdf",
        filename=ficheiro if download else None,
        content_disposition_type="attachment" if download else "inline",
    )


@router.get("/export.csv")
def partidos_export(
    q: Optional[str] = Query(None),
    ano: Optional[int] = Query(None),
    secao: Optional[str] = Query(None),
    partido: Optional[str] = Query(None),
    sigla: Optional[str] = Query(None),
    entregou: Optional[bool] = Query(None),
    maximo: int = Query(50_000, ge=1, le=200_000, description="Máximo de registos exportados"),
    session: ReadSession = None,
) -> Response:
    """Exporta em CSV (delimitador `;`) o resultado da pesquisa."""
    try:
        conteudo = partidos.csv_bytes(
            maximo=maximo,
            q=q,
            ano=ano,
            secao=secao,
            partido=partido,
            sigla=sigla,
            entregou=entregou,
        )
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return Response(
        content=conteudo,
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": 'attachment; filename="partidos.csv"'},
    )
