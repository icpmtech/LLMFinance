"""Rotas da **Descoberta de pessoas** (`/descoberta/pessoas/*`).

Dão-se uma ou várias empresas (NIF ou nome) e o painel devolve **quem** está
ligado a elas: cargos societários, capital, papéis nos processos do CIRE,
a rede de cada pessoa para fora das empresas pedidas e — quando há mais do
que uma empresa — quem as liga.

- `GET  /descoberta/pessoas/meta`             — fontes, classes de cargo e limites
- `GET  /descoberta/pessoas/resolver`         — resolve um nome/NIF na empresa certa
- `GET  /descoberta/pessoas/descobrir`        — descobre as pessoas das empresas (query)
- `POST /descoberta/pessoas/descobrir`        — igual, com as empresas no corpo
- `GET  /descoberta/pessoas/pessoa/{nif}`     — ficha da pessoa em todo o universo

O trabalho está em `api.descoberta_pessoas` (orquestra `elasticsearch_client`,
`cire_service` e `devedores_service`); aqui só se expõe o resultado.
"""
from __future__ import annotations

import logging
from typing import Annotated, Any, Dict, List, Optional

from fastapi import APIRouter, Body, Depends, HTTPException, Query
from fastapi.concurrency import run_in_threadpool

from api import descoberta_pessoas as service
from api import descoberta_service as empresas_service
from api.auth_routes import CurrentSession, optional_session

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/descoberta/pessoas", tags=["descoberta"])

Session = Annotated[Optional[CurrentSession], Depends(optional_session)]

MAX_EMPRESAS = service.MAX_EMPRESAS


def _lista(valor: Any) -> List[str]:
    """Aceita uma lista ou um texto com vírgulas/pontos e vírgulas."""
    if valor is None:
        return []
    if isinstance(valor, (list, tuple, set)):
        itens = [str(parte).strip() for parte in valor]
    else:
        itens = [parte.strip() for parte in str(valor).replace(";", ",").split(",")]
    return [item for item in itens if item]


def _pais(valor: Optional[str]) -> str:
    codigo = str(valor or service.PAIS_DEFAULT).strip().upper()
    if codigo not in service.PAISES_SUPORTADOS:
        raise HTTPException(
            status_code=422,
            detail=f"País não suportado: {codigo or '(vazio)'}. Use um de: {', '.join(service.PAISES_SUPORTADOS)}.",
        )
    return codigo


def _max_empresas(valor: Any) -> int:
    try:
        limite = int(valor) if valor not in (None, "") else MAX_EMPRESAS
    except (TypeError, ValueError) as exc:
        raise HTTPException(status_code=422, detail="`max_empresas` tem de ser um número.") from exc
    if limite < service.MIN_EMPRESAS or limite > MAX_EMPRESAS:
        raise HTTPException(
            status_code=422,
            detail=f"`max_empresas` tem de estar entre {service.MIN_EMPRESAS} e {MAX_EMPRESAS}.",
        )
    return limite


async def _descobrir(payload: Dict[str, Any]) -> Dict[str, Any]:
    """Valida o pedido e devolve o painel (ou 422 com a razão)."""
    try:
        return await run_in_threadpool(
            service.descobrir,
            nifs=_lista(payload.get("nifs") or payload.get("empresas")),
            nomes=_lista(payload.get("nomes")),
            pais=_pais(payload.get("pais")),
            max_empresas=_max_empresas(payload.get("max_empresas")),
            fontes=_lista(payload.get("fontes")) or None,
            incluir_grafo=bool(payload.get("incluir_grafo", True)),
            incluir_devedores=bool(payload.get("incluir_devedores", True)),
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("/meta", summary="Fontes e limites da descoberta de pessoas")
def descoberta_pessoas_meta(session: Session = None) -> Dict[str, Any]:
    """Catálogo de fontes, classes de cargo e limites do painel."""
    return service.meta()


@router.get("/resolver", summary="Resolve um nome ou NIF na empresa certa")
def descoberta_pessoas_resolver(
    q: Annotated[str, Query(min_length=2, max_length=200)],
    size: Annotated[int, Query(ge=1, le=20)] = 8,
    session: Session = None,
) -> Dict[str, Any]:
    """A mesma resolução do painel de empresas — o ponto de partida do pedido."""
    return empresas_service.resolver(q, size=size)


@router.get("/descobrir", summary="Descobre as pessoas ligadas às empresas (query)")
async def descoberta_pessoas_descobrir_get(
    nifs: Annotated[Optional[str], Query(description="NIFs separados por vírgulas")] = None,
    nomes: Annotated[Optional[str], Query(description="Nomes separados por vírgulas")] = None,
    pais: Annotated[str, Query(pattern="^[A-Za-z]{2}$")] = service.PAIS_DEFAULT,
    max_empresas: Annotated[int, Query(ge=service.MIN_EMPRESAS, le=MAX_EMPRESAS)] = MAX_EMPRESAS,
    fontes: Annotated[Optional[str], Query(description="Fontes separadas por vírgulas")] = None,
    incluir_grafo: bool = True,
    incluir_devedores: bool = True,
    session: Session = None,
) -> Dict[str, Any]:
    """Pessoas com cargos nas empresas indicadas, com evidência, grafo e atenção."""
    return await _descobrir(
        {
            "nifs": nifs,
            "nomes": nomes,
            "pais": pais,
            "max_empresas": max_empresas,
            "fontes": fontes,
            "incluir_grafo": incluir_grafo,
            "incluir_devedores": incluir_devedores,
        }
    )


@router.post("/descobrir", summary="Descobre as pessoas ligadas às empresas (corpo JSON)")
async def descoberta_pessoas_descobrir_post(payload: Dict[str, Any] = Body(default_factory=dict)) -> Dict[str, Any]:
    """Igual a `GET /descoberta/pessoas/descobrir`, com as empresas no corpo.

    O corpo aceita `empresas` (ou `nifs`) e `nomes` (lista ou texto com vírgulas),
    `pais`, `max_empresas`, `fontes`, `incluir_grafo` e `incluir_devedores`.
    """
    return await _descobrir(payload or {})


@router.get("/pessoa/{nif}", summary="Ficha de uma pessoa em todo o universo")
async def descoberta_pessoas_ficha(
    nif: str,
    empresas: Annotated[Optional[str], Query(description="NIFs do pedido, separados por vírgulas")] = None,
    session: Session = None,
) -> Dict[str, Any]:
    """Todos os cargos da pessoa, marcando os das empresas do pedido."""
    resultado = await run_in_threadpool(service.ficha, nif, empresas=_lista(empresas) or None)
    if resultado.get("erro") and not resultado.get("encontrada"):
        raise HTTPException(status_code=404, detail=resultado["erro"])
    return resultado
