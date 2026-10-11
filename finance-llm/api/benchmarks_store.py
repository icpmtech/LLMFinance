"""Definições dos **benchmarks de produtos** (módulo `/benchmarks`).

Um benchmark é um estudo de preços: o mesmo produto comparado em várias lojas
online. Cada benchmark tem

- uma definição (nome, categoria, moeda, chave de comparação e a lista de lojas);
- **o seu próprio índice no Elasticsearch** (`finance_bench_<slug>`), criado no
  momento em que o benchmark é criado e apagado com ele — é isso que permite
  pesquisar e publicar cada benchmark como se fosse um módulo independente;
- a possibilidade de ser publicado como página pública no site (CMS).

As definições vivem em `finance_benchmarks`; a persistência em Elasticsearch é
feita pelo `elasticsearch_client` (nenhum estado em memória, para sobreviver a
reinícios e a várias réplicas do backend).
"""
from __future__ import annotations

import logging
import re
import unicodedata
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from api import elasticsearch_client as esc

logger = logging.getLogger(__name__)

#: Chaves aceites para decidir o que é «o mesmo produto» entre lojas.
MATCH_KEYS = ("ean", "sku", "nome", "url")

#: Campos do benchmark que podem ser ligados a um campo extraído pela recolha.
#: Sem `field_map` o serviço procura por nomes conhecidos (preço, marca, …).
FIELD_MAP_KEYS = (
    "price",
    "price_original",
    "product_name",
    "description",
    "brand",
    "category",
    "ean",
    "sku",
    "url",
    "image",
    "availability",
)

#: Campos que cada loja pode trazer na definição.
STORE_FIELDS = ("id", "name", "url", "enabled", "source_id", "template_id", "scraper", "tags")


def _agora() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def slugify(texto: str) -> str:
    """`Preços de portáteis!` → `precos-de-portateis` (usável em URL e índice)."""
    base = unicodedata.normalize("NFKD", str(texto or ""))
    base = "".join(ch for ch in base if not unicodedata.combining(ch)).lower()
    base = re.sub(r"[^a-z0-9]+", "-", base).strip("-")
    return base[:60] or "benchmark"


def _id_loja(nome: str, url: str = "") -> str:
    """Identificador estável de uma loja dentro do benchmark."""
    base = slugify(nome)
    if base and base != "benchmark":
        return base
    return slugify(url.split("//")[-1].split("/")[0]) or "loja"


def normalize_store(raw: Dict[str, Any], existente: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Normaliza uma loja da lista de lojas do benchmark."""
    dados = {**(existente or {}), **(raw or {})}
    nome = str(dados.get("name") or dados.get("store_name") or "").strip()
    url = str(dados.get("url") or "").strip()
    loja: Dict[str, Any] = {
        "id": str(dados.get("id") or _id_loja(nome, url)).strip(),
        "name": nome or url or "Loja sem nome",
        "url": url,
        "enabled": bool(dados.get("enabled", True)),
        "source_id": str(dados.get("source_id") or "").strip(),
        "template_id": str(dados.get("template_id") or "").strip(),
        "tags": [str(t).strip() for t in (dados.get("tags") or []) if str(t).strip()],
    }
    # Configuração de recolha própria da loja (usada quando não há `source_id`).
    if isinstance(raw.get("scraper"), dict):
        loja["scraper"] = raw["scraper"]
    elif isinstance(dados.get("scraper"), dict):
        loja["scraper"] = dados["scraper"]
    return loja


def normalize_benchmark(payload: Dict[str, Any], existente: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Valida e normaliza a definição de um benchmark.

    Levanta `ValueError` quando falta o essencial (nome e pelo menos uma loja).
    """
    dados = {**(existente or {}), **(payload or {})}
    nome = str(dados.get("name") or "").strip()
    if not nome:
        raise ValueError("Indique o nome do benchmark.")

    slug = slugify(dados.get("slug") or nome)
    if existente and existente.get("slug"):
        # O slug não muda num benchmark existente: é o id do índice e o caminho
        # público. Mudá-lo apontaria para um índice que já não existe.
        slug = str(existente["slug"])

    match_on = str(dados.get("match_on") or "nome").strip().lower()
    if match_on not in MATCH_KEYS:
        match_on = "nome"

    lojas_raw = dados.get("stores")
    if lojas_raw is None:
        lojas_raw = existente.get("stores") if existente else []
    if isinstance(lojas_raw, dict):
        lojas_raw = [lojas_raw]
    anteriores = {str(s.get("id")): s for s in (existente or {}).get("stores") or []}
    lojas: List[Dict[str, Any]] = []
    vistos: set[str] = set()
    for bruta in lojas_raw or []:
        if not isinstance(bruta, dict):
            continue
        loja = normalize_store(bruta, anteriores.get(str(bruta.get("id") or "")))
        if loja["id"] in vistos:
            continue
        vistos.add(loja["id"])
        lojas.append(loja)
    if not lojas:
        raise ValueError("Indique pelo menos uma loja (site) a comparar.")

    agora = _agora()
    mapa_bruto = dados.get("field_map") if isinstance(dados.get("field_map"), dict) else {}
    mapa = {
        chave: str(mapa_bruto.get(chave) or "").strip()
        for chave in FIELD_MAP_KEYS
        if str(mapa_bruto.get(chave) or "").strip()
    }
    return {
        "slug": slug,
        "name": nome,
        "description": str(dados.get("description") or "").strip(),
        "category": str(dados.get("category") or "").strip(),
        "unit": str(dados.get("unit") or "unidade").strip(),
        "currency": str(dados.get("currency") or "EUR").strip().upper()[:3],
        "tags": [str(t).strip() for t in (dados.get("tags") or []) if str(t).strip()],
        "public": bool(dados.get("public", False)),
        "active": bool(dados.get("active", True)),
        "match_on": match_on,
        "field_map": mapa,
        "stores": lojas,
        "cms_page_id": (existente or {}).get("cms_page_id", ""),
        "public_path": (existente or {}).get("public_path", ""),
        "public_at": (existente or {}).get("public_at"),
        "created_at": (existente or {}).get("created_at") or agora,
        "updated_at": agora,
        "created_by": (existente or {}).get("created_by") or str(dados.get("created_by") or ""),
        "last_run": (existente or {}).get("last_run") or {},
    }


# ---------------------------------------------------------------------------
# CRUD
# ---------------------------------------------------------------------------
def listar() -> List[Dict[str, Any]]:
    """Todos os benchmarks (mais recentes primeiro), com a volumetria de cada um."""
    benchmarks = esc.list_benchmark_definitions()
    for benchmark in benchmarks:
        benchmark["stats"] = _stats_rapidas(benchmark.get("slug"))
    return benchmarks


def _stats_rapidas(slug: Optional[str]) -> Dict[str, Any]:
    """Nº de ofertas/produtos/lojas sem varrer o índice todo."""
    client = esc.get_es_client()
    if not client or not slug:
        return {"offers": 0, "products": 0, "stores": 0}
    indice = esc.benchmark_items_index(slug)
    try:
        if not client.indices.exists(index=indice):
            return {"offers": 0, "products": 0, "stores": 0}
        resp = client.search(
            index=indice,
            body={
                "size": 0,
                "aggs": {
                    "produtos": {"cardinality": {"field": "product_key"}},
                    "lojas": {"cardinality": {"field": "store_id"}},
                },
            },
        )
    except Exception:  # noqa: BLE001
        return {"offers": 0, "products": 0, "stores": 0}
    aggs = resp.get("aggregations") or {}
    return {
        "offers": int(((resp.get("hits") or {}).get("total") or {}).get("value") or 0),
        "products": int((aggs.get("produtos") or {}).get("value") or 0),
        "stores": int((aggs.get("lojas") or {}).get("value") or 0),
    }


def obter(slug: str) -> Optional[Dict[str, Any]]:
    """Definição de um benchmark, com a volumetria."""
    benchmark = esc.get_benchmark_definition(slug)
    if not benchmark:
        return None
    benchmark["stats"] = _stats_rapidas(benchmark.get("slug"))
    return benchmark


def criar(payload: Dict[str, Any], *, autor: str = "") -> Dict[str, Any]:
    """Cria um benchmark e o seu índice de ofertas."""
    definicao = normalize_benchmark({**payload, "created_by": autor})
    if esc.get_benchmark_definition(definicao["slug"]):
        raise ValueError(f"Já existe um benchmark com o endereço «{definicao['slug']}».")
    guardado = esc.save_benchmark_definition(definicao)
    if guardado.get("error"):
        return guardado
    # O índice nasce com o benchmark: é o «seu índice de elastic».
    esc.ensure_benchmark_items_index(definicao["slug"])
    guardado["stats"] = _stats_rapidas(definicao["slug"])
    return guardado


def atualizar(slug: str, payload: Dict[str, Any], *, autor: str = "") -> Dict[str, Any]:
    """Actualiza a definição (as lojas podem ser substituídas)."""
    existente = esc.get_benchmark_definition(slug)
    if not existente:
        return {"error": "Benchmark não encontrado"}
    atualizado = normalize_benchmark({**payload, "created_by": autor or existente.get("created_by")}, existente)
    guardado = esc.save_benchmark_definition(atualizado)
    if guardado.get("error"):
        return guardado
    esc.ensure_benchmark_items_index(atualizado["slug"])
    guardado["stats"] = _stats_rapidas(atualizado["slug"])
    return guardado


def apagar(slug: str, *, com_dados: bool = True) -> Dict[str, Any]:
    """Apaga o benchmark (e, por omissão, o índice de ofertas dele)."""
    existente = esc.get_benchmark_definition(slug)
    if not existente:
        return {"error": "Benchmark não encontrado"}
    indice_removido = esc.drop_benchmark_index(slug) if com_dados else False
    esc.delete_benchmark_definition(slug)
    return {"slug": slug, "removed": True, "index_removed": indice_removido}


def marcar_recolha(slug: str, resumo: Dict[str, Any]) -> None:
    """Guarda o resumo da última recolha na definição (para a UI mostrar)."""
    existente = esc.get_benchmark_definition(slug)
    if not existente:
        return
    existente["last_run"] = resumo
    existente["updated_at"] = _agora()
    esc.save_benchmark_definition(existente)


def marcar_publicacao(slug: str, *, page_id: str, caminho: str, publico: bool) -> Optional[Dict[str, Any]]:
    """Marca (ou desmarca) o benchmark como público, guardando a página do CMS."""
    existente = esc.get_benchmark_definition(slug)
    if not existente:
        return None
    existente["cms_page_id"] = page_id
    existente["public_path"] = caminho
    existente["public"] = bool(publico)
    existente["public_at"] = _agora() if publico else None
    existente["updated_at"] = _agora()
    return esc.save_benchmark_definition(existente)
