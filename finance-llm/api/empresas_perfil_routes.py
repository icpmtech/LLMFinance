"""Rotas do módulo **Sites e logótipos das empresas** (`/empresas/perfil/*`).

Dá marca às empresas que aparecem no benchmark: o site oficial e o logótipo,
para o grafo do comprador, as tabelas e as fichas mostrarem a empresa e não só
o nome. O trabalho pesado (pesquisa web, validação por HTTP, arbitragem por IA e
extracção do logótipo) está em `api.empresas_perfil`; aqui só se expõe o
resultado.

- `GET  /empresas/perfil`              — perfis em cache de vários NIF (leitura rápida)
- `POST /empresas/perfil/resolver`     — resolve site + logótipo de até 12 empresas (sessão)
- `GET  /empresas/perfil/stats`        — cobertura do módulo (painel)
- `GET  /empresas/perfil/lista`        — perfis conhecidos (backoffice)
- `GET  /empresas/perfil/config`       — configuração (pesquisa, IA, validade)
- `POST /empresas/perfil/config`       — actualiza a configuração (sessão)
- `GET  /empresas/perfil/{chave}`      — um perfil (NIF ou nome)
- `GET  /empresas/perfil/{chave}/logo` — imagem do logótipo (PNG/SVG)
- `POST /empresas/perfil/{chave}/site` — corrigir o site à mão (sessão)
- `DELETE /empresas/perfil/{chave}`    — esquecer o perfil (sessão)

A rota do **logótipo não pede sessão**: é consumida por `<img src>`, que não
envia o cabeçalho `Authorization`. Só devolve imagens já guardadas no servidor.
"""
from __future__ import annotations

import logging
from typing import Annotated, Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import FileResponse, Response
from pydantic import BaseModel, Field

from api import empresas_perfil as perfil
from api.auth_routes import require_session

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/empresas/perfil", tags=["empresas-perfil"])

_TIPOS = {
    ".png": "image/png",
    ".svg": "image/svg+xml",
    ".webp": "image/webp",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".gif": "image/gif",
    ".ico": "image/x-icon",
}


class PerfilAlvo(BaseModel):
    """Empresa a identificar (site e logótipo)."""

    nif: Optional[str] = Field(None, description="NIF/DIR3/SIRET da empresa")
    nome: Optional[str] = Field(None, description="Nome, usado quando não há NIF")
    pais: Optional[str] = Field(None, description="`pt`, `es` ou `fr` (por omissão, o do pedido)")


class ResolverRequest(BaseModel):
    """Pedido de resolução de sites e logótipos."""

    alvos: List[PerfilAlvo] = Field(..., description="Empresas a resolver (máx. 12 por pedido)")
    pais: str = Field("pt", description="País por omissão: `pt`, `es` ou `fr`")
    usar_ia: bool = Field(True, description="Deixar a IA arbitrar entre candidatos duvidosos")
    forcar: bool = Field(False, description="Ignorar a cache e procurar de novo")
    provider: Optional[str] = Field(None, description="Fornecedor de IA a usar (opcional)")
    modelo: Optional[str] = Field(None, description="Modelo de IA a usar (opcional)")


class SiteManual(BaseModel):
    """Correcção manual do site de uma empresa."""

    site: str = Field(..., description="URL do site oficial")
    nome: Optional[str] = Field(None, description="Nome da empresa (se o perfil ainda não existir)")


class ConfigRequest(BaseModel):
    """Configuração do módulo (backoffice)."""

    usar_pesquisa: Optional[bool] = Field(None, description="Procurar candidatos na web")
    usar_ia: Optional[bool] = Field(None, description="Usar a IA para arbitrar dúvidas")
    dias_validade: Optional[int] = Field(None, description="Dias que um perfil se considera fresco")
    paralelo: Optional[int] = Field(None, description="Empresas resolvidas em paralelo")
    max_lote: Optional[int] = Field(None, description="Teto de empresas por pedido")


def _ids(texto: Optional[str]) -> List[str]:
    return [parte.strip() for parte in str(texto or "").replace(";", ",").split(",") if parte.strip()]


@router.get("", summary="Perfis (site e logótipo) já conhecidos de vários NIF")
def perfis_conhecidos(
    nifs: Annotated[str, Query(description="NIF/DIR3/SIRET separados por vírgula")],
) -> Dict[str, Any]:
    """Leitura **só da cache** — é o que o grafo pede ao abrir a análise."""
    identificadores = _ids(nifs)[:60]
    itens: Dict[str, Any] = {}
    for identificador in identificadores:
        encontrado = perfil.obter(identificador)
        if encontrado:
            itens[identificador] = encontrado
    return {
        "perfis": itens,
        "encontrados": len(itens),
        "em_falta": [i for i in identificadores if i not in itens],
        "stats": perfil.stats(),
    }


@router.get("/stats", summary="Cobertura do módulo de sites e logótipos")
def estatisticas() -> Dict[str, Any]:
    return perfil.stats()


@router.get("/lista", summary="Perfis conhecidos (backoffice)")
def listar(
    limite: Annotated[int, Query(ge=1, le=1000)] = 200,
    so_com_site: bool = False,
) -> Dict[str, Any]:
    itens = perfil.lista(limite=limite, so_com_site=so_com_site)
    return {"items": itens, "total": len(itens), "stats": perfil.stats()}


@router.get("/config", summary="Configuração do módulo")
def ler_config() -> Dict[str, Any]:
    return perfil.config()


@router.post("/config", summary="Actualiza a configuração (sessão)")
def escrever_config(
    req: ConfigRequest,
    session: Annotated[Any, Depends(require_session)],
) -> Dict[str, Any]:
    return perfil.guardar_config(req.model_dump())


@router.post("/resolver", summary="Descobrir site e logótipo (IA + scraper)")
def resolver(
    req: ResolverRequest,
    session: Annotated[Any, Depends(require_session)],
) -> Dict[str, Any]:
    """Resolve cada empresa: candidatos na web, validação por HTTP, arbitragem
    por IA quando há dúvida e extracção do logótipo do site escolhido.

    A resposta segue a ordem pedida e inclui `site`, `logo_url`, `confianca`,
    `motivo` e os candidatos considerados (útil no backoffice).
    """
    alvos = [alvo for alvo in req.alvos if alvo.nif or alvo.nome]
    if not alvos:
        raise HTTPException(status_code=422, detail="Indique pelo menos uma empresa (NIF ou nome).")
    limite = int(perfil.config().get("max_lote") or perfil.MAX_LOTE)
    if len(alvos) > limite:
        raise HTTPException(
            status_code=422,
            detail=f"Demasiadas empresas num só pedido (máximo {limite}). Divida em lotes.",
        )
    utilizador = getattr(getattr(session, "user", None), "id", None)
    resultados = perfil.resolver_varios(
        [alvo.model_dump() for alvo in alvos],
        pais=req.pais,
        usar_ia=req.usar_ia,
        forcar=req.forcar,
        user_id=utilizador,
        provider=req.provider,
        modelo=req.modelo,
    )
    return {
        "perfis": resultados,
        "resolvidos": sum(1 for item in resultados if item.get("site")),
        "com_logo": sum(1 for item in resultados if item.get("logo_url")),
        "stats": perfil.stats(),
    }


@router.get("/{chave}", summary="Perfil de uma empresa (site e logótipo)")
def ler_perfil(
    chave: str,
    nome: Annotated[Optional[str], Query(description="Nome, quando a chave é um NIF ainda não visto")] = None,
) -> Dict[str, Any]:
    encontrado = perfil.obter(chave, nome)
    if not encontrado:
        raise HTTPException(status_code=404, detail="Sem perfil guardado para esta empresa.")
    return encontrado


@router.get("/{chave}/logo", summary="Logótipo da empresa (imagem)", response_class=FileResponse)
def obter_logo(chave: str) -> Response:
    """Imagem já guardada no servidor (não vai à rede)."""
    caminho = perfil.caminho_logo(chave)
    if not caminho:
        raise HTTPException(status_code=404, detail="Sem logótipo para esta empresa.")
    tipo = _TIPOS.get(caminho.suffix.lower(), "application/octet-stream")
    return FileResponse(
        caminho,
        media_type=tipo,
        headers={
            "Cache-Control": "public, max-age=604800",
            "Content-Disposition": f'inline; filename="{caminho.name}"',
        },
    )


@router.post("/{chave}/site", summary="Corrigir o site à mão (sessão)")
def definir_site(
    chave: str,
    req: SiteManual,
    session: Annotated[Any, Depends(require_session)],
) -> Dict[str, Any]:
    """Correcção manual: fixa o site e recolhe logo o logótipo dele."""
    try:
        return perfil.definir_site(req.nome or "", chave, req.site)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.delete("/{chave}", summary="Esquecer o perfil de uma empresa (sessão)")
def esquecer(
    chave: str,
    session: Annotated[Any, Depends(require_session)],
    com_logo: bool = True,
) -> Dict[str, Any]:
    removido = perfil.limpar(chave, com_logo=com_logo)
    return {"removido": removido, "stats": perfil.stats()}
