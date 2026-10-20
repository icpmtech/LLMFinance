"""Rotas do módulo **Entidade para a Transparência** (`/entidade-transparencia/*`).

A EPT publica as declarações únicas dos titulares de cargos políticos e altos
cargos públicos. O módulo recolhe o catálogo e as declarações, indexa-os em
`finance_ept_*` e serve a pesquisa pela cascata da própria plataforma —
**entidade → cargo → nome do titular** — com ligação à ficha do político no
PessoasIQ.

Endpoints:

- `GET  /entidade-transparencia/meta`          — proveniência, pastas, índices e endpoints
- `GET  /entidade-transparencia/stats`         — volumetria indexada/em disco
- `GET  /entidade-transparencia/entidades`     — catálogo de entidades
- `GET  /entidade-transparencia/cargos`        — cargos (filtrados pela entidade/titular/órgão)
- `GET  /entidade-transparencia/orgaos`        — órgãos (filtrados)
- `GET  /entidade-transparencia/titulares`     — titulares (filtrados ou pesquisa por nome)
- `POST /entidade-transparencia/recolher`      — recolha em segundo plano
- `POST /entidade-transparencia/indexar`       — indexação do que está em disco
- `GET  /entidade-transparencia/jobs[/{id}]`   — progresso dos trabalhos
- `GET  /entidade-transparencia/titular/{id}`  — ficha do titular + declarações + pessoa
- `GET  /entidade-transparencia/declaracoes`   — pesquisa de declarações
- `GET  /entidade-transparencia/declaracoes/{id}` — declaração completa (secções e interesses)
- `GET  /entidade-transparencia/pessoa/{nif}`  — declarações ligadas a uma pessoa do PessoasIQ
- `GET  /entidade-transparencia/export.csv`    — exportação da pesquisa
- `POST /entidade-transparencia/exportar`      — grava um `.json` por entidade
- `GET  /entidade-transparencia/exportar/indice` — índice dos `.json` por entidade
- `GET  /entidade-transparencia/entidades/{id}/export.json` — `.json` de uma entidade
- `GET  /entidade-transparencia/validar`       — último relatório de validação
- `POST /entidade-transparencia/validar`       — valida catálogo, cascata e detalhes
"""
from __future__ import annotations

import json
import logging
from typing import Annotated, Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import FileResponse, Response
from pydantic import BaseModel, Field

from api import entidade_transparencia_service as ept
from api.auth_routes import CurrentSession, optional_session, require_session
from collectors.entidade_transparencia import normalize_name

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/entidade-transparencia", tags=["entidade-transparencia"])

Session = Annotated[CurrentSession, Depends(require_session)]
ReadSession = Annotated[CurrentSession, Depends(optional_session)]


def _spa_para_browser(request: Request) -> Optional[Response]:
    """Devolve a SPA quando o pedido vem de um browser (deep link), senão `None`.

    O endereço da ficha do titular é o mesmo para a API e para a página: o
    `fetch` do frontend (e qualquer cliente HTTP) pede JSON; um browser a abrir
    o link diretamente envia `Accept: text/html` e recebe a aplicação, que
    volta a pedir a ficha por JSON. Sem isto, clicar num resultado abria um
    JSON em vez da ficha.

    O `import` é local porque `api.main` importa este módulo.
    """
    aceita = request.headers.get("accept") or ""
    if "text/html" not in aceita:
        return None
    from api.main import spa_page_response

    return spa_page_response(str(request.url.path))


class EptRecolherRequest(BaseModel):
    """O que recolher (a cascata é opcional: entidade → cargo → titular)."""

    entidade_id: Optional[str] = Field(None, description="Entidade da cascata (id da EPT)")
    cargo_id: Optional[str] = Field(None, description="Cargo da cascata (id da EPT)")
    orgao_id: Optional[str] = Field(None, description="Órgão da cascata (id da EPT)")
    titular_id: Optional[str] = Field(None, description="Titular único (id da EPT)")
    limite_titulares: Optional[int] = Field(None, ge=1, description="Máximo de titulares a percorrer")
    limite_declaracoes: Optional[int] = Field(
        None, ge=1, description="Máximo de declarações por titular (útil para uma amostra)"
    )
    pausa: Optional[float] = Field(None, ge=0, le=10, description="Pausa entre pedidos, em segundos")
    forcar: bool = Field(False, description="Reler o que já está em disco/indexado")
    indexar: bool = Field(False, description="Indexar no Elasticsearch no fim da recolha")


class EptIndexarRequest(BaseModel):
    """O que indexar."""

    forcar: bool = Field(False, description="Reindexar mesmo o que já está indexado")


class EptExportarRequest(BaseModel):
    """Exportação de um `.json` por entidade."""

    entidades: Optional[List[str]] = Field(
        None, description="Ids das entidades a exportar (por omissão, todas)"
    )


class EptValidarRequest(BaseModel):
    """Validação do catálogo e dos detalhes contra a plataforma da EPT."""

    limite_titulares: Optional[int] = Field(
        0,
        ge=0,
        description="Quantos titulares validar (0 = nenhum, por omissão; reparte a amostra pelo catálogo)",
    )
    limite_declaracoes: Optional[int] = Field(
        None, ge=1, description="Quantas declarações validar (por omissão, todas as que estão em disco)"
    )
    pausa: Optional[float] = Field(None, ge=0, le=10, description="Pausa entre pedidos, em segundos")


@router.get("/meta")
def ept_meta(session: ReadSession = None) -> Dict[str, Any]:
    """Proveniência, pastas, índice e endpoints externos usados pelo módulo."""
    return ept.meta()


@router.get("/stats")
def ept_stats(session: ReadSession = None) -> Dict[str, Any]:
    """Quantos titulares, titularidades e declarações estão em índice/disco."""
    return ept.stats()


@router.get("/entidades")
def ept_entidades(
    q: Optional[str] = Query(None, description="Filtro por nome da entidade"),
    forcar: bool = Query(False, description="Voltar a ler o catálogo na EPT"),
    limite: int = Query(10000, ge=1, le=10000),
    session: ReadSession = None,
) -> Dict[str, Any]:
    """Entidades/órgãos — o primeiro passo da cascata."""
    try:
        itens: List[Dict[str, Any]] = ept.entidades(forcar=forcar)
    except Exception as exc:  # noqa: BLE001 - sem rede, o catálogo em cache serve
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    if q:
        alvo = normalize_name(q)
        itens = [item for item in itens if alvo in normalize_name(item.get("nome"))]
    return {"total": len(itens), "items": itens[:limite]}


@router.get("/entidades/{entidade_id}/export.json")
def ept_entidade_export(entidade_id: str, session: ReadSession = None) -> FileResponse:
    """Descarrega o `.json` de uma entidade (gera-o se ainda não existir)."""
    caminho = ept.entidades_json_dir() / f"{entidade_id}.json"
    if not caminho.exists():
        try:
            ept.exportar_entidades_json([entidade_id])
        except Exception as exc:  # noqa: BLE001
            raise HTTPException(status_code=502, detail=str(exc)) from exc
    if not caminho.exists():
        raise HTTPException(status_code=404, detail="Entidade sem dados exportados.")
    return FileResponse(
        str(caminho),
        media_type="application/json; charset=utf-8",
        filename=f"entidade-transparencia-{entidade_id}.json",
    )


@router.get("/exportar/indice")
def ept_exportar_indice(session: ReadSession = None) -> Dict[str, Any]:
    """Índice dos `.json` por entidade (quais existem e o que contêm)."""
    destino = ept.entidades_json_dir()
    indice = destino / "_index.json"
    if not indice.exists():
        try:
            ept.exportar_entidades_json()
        except Exception as exc:  # noqa: BLE001
            raise HTTPException(status_code=502, detail=str(exc)) from exc
    if not indice.exists():
        raise HTTPException(status_code=404, detail="Ainda não há exportação por entidade.")
    return json.loads(indice.read_text(encoding="utf-8"))


@router.get("/cargos")
def ept_cargos(
    entidade_id: Optional[str] = Query(None, description="Id da entidade (passo 1)"),
    titular_id: Optional[str] = Query(None, description="Id do titular"),
    orgao_id: Optional[str] = Query(None, description="Id do órgão"),
    q: Optional[str] = Query(None, description="Filtro por nome do cargo"),
    forcar: bool = Query(False),
    limite: int = Query(2000, ge=1, le=10000),
    session: ReadSession = None,
) -> Dict[str, Any]:
    """Cargos — o segundo passo da cascata."""
    try:
        itens = ept.cargos(
            entidade_id=entidade_id,
            titular_id=titular_id,
            orgao_id=orgao_id,
            forcar=forcar,
        )
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    if q:
        alvo = normalize_name(q)
        itens = [item for item in itens if alvo in normalize_name(item.get("nome"))]
    return {"total": len(itens), "items": itens[:limite], "entidade_id": entidade_id}


@router.get("/orgaos")
def ept_orgaos(
    entidade_id: Optional[str] = Query(None),
    cargo_id: Optional[str] = Query(None),
    titular_id: Optional[str] = Query(None),
    q: Optional[str] = Query(None),
    forcar: bool = Query(False),
    limite: int = Query(2000, ge=1, le=10000),
    session: ReadSession = None,
) -> Dict[str, Any]:
    """Órgãos — filtro auxiliar da cascata."""
    try:
        itens = ept.orgaos(
            entidade_id=entidade_id,
            cargo_id=cargo_id,
            titular_id=titular_id,
            forcar=forcar,
        )
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    if q:
        alvo = normalize_name(q)
        itens = [item for item in itens if alvo in normalize_name(item.get("nome"))]
    return {"total": len(itens), "items": itens[:limite]}


@router.get("/titulares")
def ept_titulares(
    entidade_id: Optional[str] = Query(None, description="Entidade escolhida (passo 1)"),
    cargo_id: Optional[str] = Query(None, description="Cargo escolhido (passo 2)"),
    orgao_id: Optional[str] = Query(None),
    q: Optional[str] = Query(None, description="Nome do titular (passo 3)"),
    page: int = Query(1, ge=1),
    size: int = Query(30, ge=1, le=5000),
    forcar: bool = Query(False),
    session: ReadSession = None,
) -> Dict[str, Any]:
    """Titulares — o terceiro passo da cascata (ou pesquisa por nome)."""
    try:
        if any((entidade_id, cargo_id, orgao_id)):
            itens = ept.titulares(
                entidade_id=entidade_id,
                cargo_id=cargo_id,
                orgao_id=orgao_id,
                q=q,
                forcar=forcar,
                limite=100_000,
            )
            total = len(itens)
            inicio = (page - 1) * size
            return {"total": total, "page": page, "size": size, "items": itens[inicio : inicio + size], "fonte": "ept"}
        if q:
            resultado = ept.search_titulares(q=q, page=page, size=size)
            if not resultado.get("items"):
                # Ainda sem índice: o catálogo da EPT (em cache) serve de recurso.
                catalogo = ept.titulares(q=q, limite=100_000)
                total = len(catalogo)
                inicio = (page - 1) * size
                resultado = {
                    "total": total,
                    "page": page,
                    "size": size,
                    "items": catalogo[inicio : inicio + size],
                    "fonte": "ept",
                }
        else:
            itens = ept.titulares(limite=100_000)
            total = len(itens)
            inicio = (page - 1) * size
            resultado = {"total": total, "page": page, "size": size, "items": itens[inicio : inicio + size], "fonte": "ept"}
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return resultado


@router.post("/recolher")
def ept_recolher(payload: EptRecolherRequest | None = None, session: Session = None) -> Dict[str, Any]:
    """Recolhe catálogo + declarações em segundo plano (retoma o que já existe)."""
    dados = (payload or EptRecolherRequest()).model_dump()
    return ept.start_job("recolher", dados)


@router.post("/indexar")
def ept_indexar(payload: EptIndexarRequest | None = None, session: Session = None) -> Dict[str, Any]:
    """Indexa em `finance_ept_*` o que já está em disco (segundo plano)."""
    dados = (payload or EptIndexarRequest()).model_dump()
    return ept.start_job("indexar", dados)


@router.post("/exportar")
def ept_exportar(payload: EptExportarRequest | None = None, session: Session = None) -> Dict[str, Any]:
    """Gera um `.json` por entidade em `data/entidade-transparencia/entidades`."""
    dados = (payload or EptExportarRequest()).model_dump()
    return ept.start_job("exportar", dados)


@router.get("/validar")
def ept_validacao(session: ReadSession = None) -> Dict[str, Any]:
    """Último relatório de validação (catálogo, cascata e detalhes vs EPT)."""
    relatorio = ept.ler_validacao()
    if relatorio is None:
        raise HTTPException(
            status_code=404,
            detail="Ainda não há validação. Corre POST /entidade-transparencia/validar.",
        )
    return relatorio


@router.post("/validar")
def ept_validar(payload: EptValidarRequest | None = None, session: Session = None) -> Dict[str, Any]:
    """Valida entidades, cargos, nomes de titulares e detalhes em segundo plano.

    A cascata completa (entidade × cargo × titular) é comparada com a listagem
    de titularidades da plataforma; os detalhes são validados por amostra.
    """
    dados = (payload or EptValidarRequest()).model_dump()
    return ept.start_job("validar", dados)


@router.get("/jobs")
def ept_jobs(session: ReadSession = None) -> Dict[str, Any]:
    """Trabalhos de recolha/indexação (mais recentes primeiro)."""
    return ept.list_jobs()


@router.get("/jobs/{job_id}")
def ept_job(job_id: str, session: ReadSession = None) -> Dict[str, Any]:
    """Progresso de um trabalho."""
    job = ept.job_status(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Trabalho não encontrado.")
    return job


@router.get("/titular/{titular_id}")
def ept_titular(
    titular_id: str,
    request: Request,
    ao_vivo: bool = Query(
        True,
        description="Se ainda não estiver indexado, ler a ficha na EPT (mais lento)",
    ),
    limite: int = Query(100, ge=1, le=200),
    session: ReadSession = None,
) -> Any:
    """Ficha do titular: posições, declarações e ligação ao PessoasIQ."""
    pagina = _spa_para_browser(request)
    if pagina is not None:
        return pagina
    try:
        return ept.titular_detail(titular_id, ao_vivo=ao_vivo, limite=limite)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@router.post("/titular/{titular_id}/recolher")
def ept_recolher_titular(titular_id: str, session: Session = None) -> Dict[str, Any]:
    """Recolhe as declarações de um único titular (em segundo plano)."""
    return ept.start_job("recolher", {"titular_id": str(titular_id), "indexar": True, "forcar": True})


@router.get("/declaracoes")
def ept_declaracoes(
    q: Optional[str] = Query(None, description="Texto livre (titular, entidade, cargo e conteúdo)"),
    titular_id: Optional[str] = Query(None),
    titular: Optional[str] = Query(None, description="Nome do titular (frase)"),
    entidade: Optional[str] = Query(None, description="Entidade (frase)"),
    cargo: Optional[str] = Query(None, description="Cargo (frase)"),
    orgao: Optional[str] = Query(None, description="Órgão (frase)"),
    ano: Optional[int] = Query(None, ge=1900, le=2100),
    natureza: Optional[str] = Query(None, description="Inicial, Alteração, Cessação, Final, …"),
    com_interesses: Optional[bool] = Query(None, description="Só declarações com registo de interesses"),
    sort: str = Query("recent", pattern="^(recent|relevance|name|ano)$"),
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=200),
    session: ReadSession = None,
) -> Dict[str, Any]:
    """Pesquisa declarações (texto e filtros) com facetas."""
    return ept.search_declaracoes(
        q,
        titular_id=titular_id,
        titular=titular,
        entidade=entidade,
        cargo=cargo,
        orgao=orgao,
        ano=ano,
        natureza=natureza,
        com_interesses=com_interesses,
        sort=sort,
        page=page,
        size=size,
    )


@router.get("/declaracoes/{declaracao_id}")
def ept_declaracao(
    declaracao_id: str,
    incluir_raw: bool = Query(False, description="Incluir a árvore original da API"),
    session: ReadSession = None,
) -> Dict[str, Any]:
    """Declaração completa: secções normalizadas, tabelas e registo de interesses."""
    try:
        return ept.declaracao_detail(declaracao_id, incluir_raw=incluir_raw)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/pessoa/{nif}")
def ept_pessoa(nif: str, size: int = Query(100, ge=1, le=200), session: ReadSession = None) -> Dict[str, Any]:
    """Declarações da EPT ligadas a uma pessoa do PessoasIQ (por nome)."""
    resultado = ept.pessoa_declaracoes(nif, size=size)
    if resultado.get("error"):
        raise HTTPException(status_code=404, detail=resultado["error"])
    return resultado


@router.get("/export.csv")
def ept_export(
    q: Optional[str] = Query(None),
    titular_id: Optional[str] = Query(None),
    entidade: Optional[str] = Query(None),
    cargo: Optional[str] = Query(None),
    ano: Optional[int] = Query(None, ge=1900, le=2100),
    natureza: Optional[str] = Query(None),
    session: ReadSession = None,
) -> Response:
    """Exporta a pesquisa de declarações em CSV."""
    conteudo = ept.csv_bytes(
        q=q,
        titular_id=titular_id,
        entidade=entidade,
        cargo=cargo,
        ano=ano,
        natureza=natureza,
    )
    return Response(
        content=conteudo,
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": 'attachment; filename="entidade-transparencia.csv"'},
    )
