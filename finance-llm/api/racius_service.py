"""Pesquisa no diretório de empresas do Racius (índice `finance_racius`).

O módulo de recolha do IQ OS grava as fichas das empresas num índice próprio
(ver `sink_index` na fonte `racius-diretorio`): além do `finance_scraped`, onde
os campos variáveis vivem num `flattened`, cada empresa fica com **campos de
topo tipados** (`concelho`, `distrito`, `forma_juridica`, `capital_social_eur`…),
que é o que permite facetas e filtros. Este serviço é a leitura desse índice —
usa-o a página de pesquisa do diretório.
"""
from __future__ import annotations

import logging
from typing import Any, Dict, Iterable, List, Optional

from api.elasticsearch_client import get_es_client, search_directory

logger = logging.getLogger(__name__)

INDEX = "finance_racius"
SOURCE_ID = "racius-diretorio"
SOURCE_NAME = "Racius · Diretório de empresas (PT)"

#: Campos com faceta (dropdowns da página).
FACET_FIELDS: tuple = ("distrito", "concelho", "forma_juridica")

#: Campos ordenados numa lista: um resultado é uma empresa, não uma notícia.
LIST_FIELDS: tuple = (
    "nome",
    "nif",
    "concelho",
    "distrito",
    "forma_juridica",
    "capital_social_eur",
    "morada",
    "atividade",
    "cae",
    "url",
    "ficha",
    "scraped_at",
)

#: Relevância: o nome da empresa manda, depois o NIF e a morada.
SEARCH_FIELDS: tuple = (
    "nome^4",
    "nif^2",
    "morada^2",
    "atividade",
    "acerca",
    "localizacao",
    "data.*",
)

SORT_OPTIONS: tuple = ("relevance", "nome", "capital", "recent", "oldest")


def available() -> bool:
    """Indica se o índice do diretório já existe (recolha feita)."""
    client = get_es_client()
    if not client:
        return False
    try:
        return bool(client.indices.exists(index=INDEX))
    except Exception as exc:  # noqa: BLE001 — a página mostra «sem dados»
        logger.debug("Índice %s indisponível: %s", INDEX, exc)
        return False


def _item(source: Dict[str, Any]) -> Dict[str, Any]:
    """Reduz o documento aos campos que a página mostra (ordem estável)."""
    item: Dict[str, Any] = {}
    for name in LIST_FIELDS:
        if source.get(name) not in (None, "", [], {}):
            item[name] = source[name]
    item["source_id"] = source.get("source_id") or SOURCE_ID
    item["source_name"] = source.get("source_name") or SOURCE_NAME
    return item


def search(
    *,
    q: Optional[str] = None,
    distrito: Optional[str] = None,
    concelho: Optional[str] = None,
    forma_juridica: Optional[str] = None,
    cae: Optional[str] = None,
    min_capital: Optional[float] = None,
    max_capital: Optional[float] = None,
    sort: str = "relevance",
    size: int = 20,
    offset: int = 0,
    facets: Iterable[str] = FACET_FIELDS,
    facet_size: int = 25,
) -> Dict[str, Any]:
    """Pesquisa empresas por texto + filtros, com facetas para os dropdowns."""
    if sort not in SORT_OPTIONS:
        sort = "relevance"
    result = search_directory(
        INDEX,
        q=q,
        filters={
            "distrito": distrito,
            "concelho": concelho,
            "forma_juridica": forma_juridica,
            "cae": cae,
        },
        min_capital=min_capital,
        max_capital=max_capital,
        sort=sort,
        size=size,
        offset=offset,
        facet_fields=facets,
        facet_size=facet_size,
        search_fields=SEARCH_FIELDS,
    )
    if result.get("error"):
        return {"error": result["error"], "total": 0, "items": [], "facets": {}}
    result["items"] = [_item(item) for item in result.get("items") or []]
    return result


def meta() -> Dict[str, Any]:
    """Total de empresas e opções dos filtros (sem depender de uma pesquisa)."""
    client = get_es_client()
    if not client:
        return {"available": False, "total": 0, "facets": {}, "facets_order": list(FACET_FIELDS)}
    try:
        if not client.indices.exists(index=INDEX):
            return {"available": False, "total": 0, "facets": {}, "facets_order": list(FACET_FIELDS)}
        count = client.count(index=INDEX).get("count", 0)
    except Exception as exc:  # noqa: BLE001
        return {"available": False, "total": 0, "facets": {}, "error": str(exc), "facets_order": list(FACET_FIELDS)}

    buckets: Dict[str, List[Dict[str, Any]]] = {}
    empty = search_directory(INDEX, size=0, facet_fields=FACET_FIELDS, facet_size=50)
    buckets = empty.get("facets") or {}
    return {
        "available": bool(count),
        "total": int(count),
        "source_id": SOURCE_ID,
        "source_name": SOURCE_NAME,
        "facets": buckets,
        "facets_order": list(FACET_FIELDS),
        "sort_options": list(SORT_OPTIONS),
    }
