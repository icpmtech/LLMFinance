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

#: Definição das opções do módulo (a «página de configuração»). O que aqui se
#: escolhe é o que a sonda usa por omissão, para não se repetir a escolha em cada
#: loja.
CONFIG_SLUG = "__config__"
CONFIG_FIELDS: Dict[str, Any] = {
    "fetcher": "dynamic",
    "use_ai": True,
    "provider": "",
    "model": "",
    "hint": "produtos com preço, imagem e descrição",
    "limite_por_loja": 200,
    "pausa_segundos": 2.0,
    "respeitar_robots": True,
    "moeda": "EUR",
    "categoria_padrao": "Informática",
}

#: Valores aceites em campos fechados.
FETCHERS_VALIDOS = ("http", "dynamic", "stealth")


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
    # O fetcher também pode vir no topo da loja (é assim que a sonda o devolve).
    if raw.get("fetcher") and isinstance(loja.get("scraper"), dict) and not loja["scraper"].get("fetcher"):
        loja["scraper"] = {**loja["scraper"], "fetcher": str(raw["fetcher"])}
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
# Configuração do módulo
# ---------------------------------------------------------------------------
def _normalizar_configuracao(bruto: Dict[str, Any], existente: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Valida as opções do módulo, mantendo o que já estava quando vier vazio."""
    atual = {**CONFIG_FIELDS, **(existente or {})}
    dados = bruto if isinstance(bruto, dict) else {}

    def texto(chave: str, limite: int = 200) -> str:
        if chave in dados and dados.get(chave) is not None:
            return str(dados.get(chave)).strip()[:limite]
        return str(atual.get(chave) or "")[:limite]

    def booleano(chave: str) -> bool:
        if chave in dados:
            return bool(dados.get(chave))
        return bool(atual.get(chave))

    def numero(chave: str, minimo: float, maximo: float) -> float:
        try:
            valor = float(dados.get(chave, atual.get(chave)))
        except (TypeError, ValueError):
            valor = float(CONFIG_FIELDS[chave])
        return max(minimo, min(maximo, valor))

    fetcher = texto("fetcher", 20).lower() or "dynamic"
    if fetcher not in FETCHERS_VALIDOS:
        fetcher = "dynamic"
    config = {
        "fetcher": fetcher,
        "use_ai": booleano("use_ai"),
        "provider": texto("provider", 40),
        "model": texto("model", 80),
        "hint": texto("hint", 300),
        "limite_por_loja": int(numero("limite_por_loja", 1, 5000)),
        "pausa_segundos": round(numero("pausa_segundos", 0, 60), 2),
        "respeitar_robots": booleano("respeitar_robots"),
        "moeda": (texto("moeda", 3) or "EUR").upper(),
        "categoria_padrao": texto("categoria_padrao", 60),
        "updated_at": _agora(),
    }
    return config


def obter_configuracao() -> Dict[str, Any]:
    """Opções do módulo (com os valores por omissão já preenchidos)."""
    guardada = esc.get_benchmark_definition(CONFIG_SLUG) or {}
    return _normalizar_configuracao(guardada, guardada)


def guardar_configuracao(payload: Dict[str, Any], *, autor: str = "") -> Dict[str, Any]:
    """Guarda as opções do módulo."""
    existente = esc.get_benchmark_definition(CONFIG_SLUG) or {}
    config = _normalizar_configuracao(payload, existente)
    config["slug"] = CONFIG_SLUG
    config["name"] = "Configuração do módulo de benchmarks"
    config["config"] = True
    config["created_by"] = existente.get("created_by") or autor
    esc.save_benchmark_definition(config)
    return {k: v for k, v in config.items() if k not in ("slug", "name", "config")}


# ---------------------------------------------------------------------------
# CRUD
# ---------------------------------------------------------------------------
def listar() -> List[Dict[str, Any]]:
    """Todos os benchmarks (mais recentes primeiro), com a volumetria de cada um."""
    benchmarks = [b for b in esc.list_benchmark_definitions() if not b.get("config")]
    for benchmark in benchmarks:
        benchmark["stats"] = _stats_rapidas(benchmark.get("slug"))
    return benchmarks


def _stats_rapidas(slug: Optional[str]) -> Dict[str, Any]:
    """Nº de ofertas/produtos/lojas e preços, sem varrer o índice todo."""
    vazio = {"offers": 0, "products": 0, "stores": 0, "avg_price": None, "price_min": None, "price_max": None}
    client = esc.get_es_client()
    if not client or not slug:
        return vazio
    indice = esc.benchmark_items_index(slug)
    try:
        if not client.indices.exists(index=indice):
            return vazio
        resp = client.search(
            index=indice,
            body={
                "size": 0,
                "aggs": {
                    "produtos": {"cardinality": {"field": "product_key"}},
                    "lojas": {"cardinality": {"field": "store_id"}},
                    # O preço médio já esteve só na análise; o cartão da lista
                    # mostrava «preço médio —» para sempre, mesmo com 48 ofertas
                    # com preço. Uma `stats` traz média/mínimo/máximo de graça.
                    "precos": {"stats": {"field": "price"}},
                },
            },
        )
    except Exception:  # noqa: BLE001
        return vazio
    aggs = resp.get("aggregations") or {}
    precos = aggs.get("precos") or {}
    media = precos.get("avg")
    return {
        "offers": int(((resp.get("hits") or {}).get("total") or {}).get("value") or 0),
        "products": int((aggs.get("produtos") or {}).get("value") or 0),
        "stores": int((aggs.get("lojas") or {}).get("value") or 0),
        "avg_price": round(float(media), 2) if media is not None else None,
        "price_min": precos.get("min"),
        "price_max": precos.get("max"),
    }


def obter(slug: str) -> Optional[Dict[str, Any]]:
    """Definição de um benchmark, com a volumetria."""
    if slug == CONFIG_SLUG:
        return None
    benchmark = esc.get_benchmark_definition(slug)
    if not benchmark or benchmark.get("config"):
        return None
    benchmark["stats"] = _stats_rapidas(benchmark.get("slug"))
    return benchmark


def guardar_loja(slug: str, loja: Dict[str, Any]) -> Dict[str, Any]:
    """Cria ou **substitui** uma loja num benchmark existente.

    É o que a sonda usa para pôr os seletores que acabou de validar na loja certa
    (por `id`), sem tocar nas outras nem no resto da definição.
    """
    benchmark = obter(slug)
    if not benchmark:
        raise ValueError(f"Benchmark «{slug}» não encontrado.")
    nova = normalize_store(loja)
    lojas = [l for l in (benchmark.get("stores") or []) if str(l.get("id")) != str(nova["id"])]
    lojas.append(nova)
    return atualizar(slug, {**benchmark, "stores": lojas}, autor=str(benchmark.get("created_by") or ""))


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
    if slug == CONFIG_SLUG:
        raise ValueError("O documento de configuração não é um estudo.")
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
