"""Benchmarks: definições, itens e comparações.

Módulo do pacote :mod:`api.es` — ver `api/elasticsearch_client.py`,
que continua a expor a API pública (os coletores/serviços importam de lá).
"""
import logging
from typing import Any, Dict, Iterable, List, Optional

from elasticsearch import Elasticsearch
from elasticsearch.helpers import bulk
from api.es.core import _safe_slug, get_es_client
from api.es.mappings import _missing_mapping_fields

logger = logging.getLogger(__name__)




# --------------------------------------------------------------------------
# Benchmarks de produtos (módulo `/benchmarks`)
#
# Os benchmarks comparam **o mesmo produto em vários sites**. As definições
# vivem em `finance_benchmarks` (uma linha por benchmark) e as ofertas
# recolhidas em `finance_bench_<slug>` — um índice **próprio por benchmark**,
# criado quando o benchmark é criado e apagado quando ele é apagado.
# --------------------------------------------------------------------------
BENCHMARKS_INDEX = "finance_benchmarks"


BENCHMARK_INDEX_PREFIX = "finance_bench_"



#: Campos que o módulo reserva nos itens (o resto do que a loja devolver vai
#: para `extra`, um `flattened`, para não perder informação nem forçar mapping).
_BENCHMARK_ITEM_FIELDS = (
    "product_key",
    "product_name",
    "brand",
    "category",
    "sku",
    "ean",
    "unit",
    "store_id",
    "store_name",
    "url",
    "image",
    "availability",
    "currency",
    "in_stock",
)




def benchmarks_mappings() -> Dict[str, Any]:
    """Mapping do índice de definições de benchmarks."""
    return {
        "properties": {
            "slug": {"type": "keyword"},
            "name": {"type": "text", "fields": {"keyword": {"type": "keyword", "ignore_above": 256}}},
            "description": {"type": "text"},
            "category": {"type": "keyword"},
            "unit": {"type": "keyword"},
            "currency": {"type": "keyword"},
            "tags": {"type": "keyword"},
            "public": {"type": "boolean"},
            "active": {"type": "boolean"},
            # Chave lógica do produto dentro do benchmark (define o que é
            # «o mesmo produto» entre lojas): ean | sku | nome | url
            "match_on": {"type": "keyword"},
            # Ligação entre os campos do benchmark e os campos extraídos pela recolha
            "field_map": {"type": "flattened"},
            "stores": {
                "type": "nested",
                "properties": {
                    "id": {"type": "keyword"},
                    "name": {"type": "keyword"},
                    "url": {"type": "keyword", "ignore_above": 1024},
                    "source_id": {"type": "keyword"},
                    "enabled": {"type": "boolean"},
                    "template_id": {"type": "keyword"},
                },
            },
            "cms_page_id": {"type": "keyword"},
            "public_path": {"type": "keyword"},
            "public_at": {"type": "date"},
            "created_at": {"type": "date"},
            "updated_at": {"type": "date"},
            "created_by": {"type": "keyword"},
            "last_run": {"type": "flattened"},
        }
    }




def benchmark_items_mappings() -> Dict[str, Any]:
    """Mapping de um índice de ofertas (um por benchmark)."""
    return {
        "properties": {
            "benchmark": {"type": "keyword"},
            "product_key": {"type": "keyword"},
            "product_name": {"type": "text", "fields": {"keyword": {"type": "keyword", "ignore_above": 512}}},
            "description": {"type": "text"},
            "brand": {"type": "keyword"},
            "category": {"type": "keyword"},
            "garment_type": {"type": "keyword"},
            "sku": {"type": "keyword"},
            "ean": {"type": "keyword"},
            "store_id": {"type": "keyword"},
            "store_name": {"type": "keyword"},
            "url": {"type": "keyword", "ignore_above": 1024},
            "image": {"type": "keyword", "ignore_above": 1024},
            "availability": {"type": "keyword"},
            "in_stock": {"type": "boolean"},
            "currency": {"type": "keyword"},
            "price": {"type": "float"},
            "price_original": {"type": "float"},
            "discount_pct": {"type": "float"},
            "rating": {"type": "float"},
            "reviews": {"type": "integer"},
            "source_id": {"type": "keyword"},
            "run_id": {"type": "keyword"},
            "collected_at": {"type": "date"},
            "extra": {"type": "flattened"},
        }
    }




def benchmark_items_index(slug: str) -> str:
    """Nome do índice de ofertas de um benchmark (`finance_bench_<slug>`)."""
    return f"{BENCHMARK_INDEX_PREFIX}{_safe_slug(slug)}"




def ensure_benchmarks_index(client: Optional[Elasticsearch] = None) -> bool:
    """Garante o índice das definições de benchmarks."""
    cliente = client or get_es_client()
    if not cliente:
        return False
    try:
        if not cliente.indices.exists(index=BENCHMARKS_INDEX):
            cliente.indices.create(
                index=BENCHMARKS_INDEX,
                settings={"number_of_shards": 1, "number_of_replicas": 0},
                mappings=benchmarks_mappings(),
            )
        return True
    except Exception as exc:  # noqa: BLE001
        logger.warning("Não foi possível garantir o índice %s: %s", BENCHMARKS_INDEX, exc)
        return False




def ensure_benchmark_items_index(slug: str, *, client: Optional[Elasticsearch] = None) -> bool:
    """Garante o índice de ofertas **de um benchmark** (um índice por benchmark)."""
    cliente = client or get_es_client()
    if not cliente:
        return False
    indice = benchmark_items_index(slug)
    try:
        if not cliente.indices.exists(index=indice):
            cliente.indices.create(
                index=indice,
                settings={"number_of_shards": 1, "number_of_replicas": 0},
                mappings=benchmark_items_mappings(),
            )
        else:
            # Campos novos (`garment_type`, por exemplo) entram nos índices que já
            # existem: sem isto, um estudo antigo só passaria a ter as colunas
            # novas depois de recriado — e recriá-lo apagava as ofertas.
            mappings = benchmark_items_mappings()
            try:
                existente = cliente.indices.get_mapping(index=indice)[indice]["mappings"].get("properties", {})
                em_falta = _missing_mapping_fields(existente, mappings.get("properties") or {})
                if em_falta:
                    cliente.indices.put_mapping(index=indice, body={"properties": em_falta})
            except Exception as exc:  # noqa: BLE001
                logger.debug("put_mapping ignorado para %s: %s", indice, exc)
        return True
    except Exception as exc:  # noqa: BLE001
        logger.warning("Não foi possível garantir o índice %s: %s", indice, exc)
        return False




def save_benchmark_definition(doc: Dict[str, Any], *, es: Optional[Elasticsearch] = None) -> Dict[str, Any]:
    """Guarda (cria/actualiza) a definição de um benchmark, por `slug`."""
    client = es or get_es_client()
    if not client:
        return {"error": "Elasticsearch indisponível"}
    if not ensure_benchmarks_index(client):
        return {"error": "Índice de benchmarks indisponível"}
    slug = str(doc.get("slug") or "").strip()
    if not slug:
        return {"error": "Slug em falta"}
    # O `slug` é o identificador lógico (URL, definição, ofertas) e mantém os
    # hífenes; o `_safe_slug` só serve para **nome de índice** (`finance_bench_*`),
    # que não aceita alguns caracteres.
    corpo = {**doc, "slug": slug}
    try:
        client.index(index=BENCHMARKS_INDEX, id=_safe_slug(slug), document=corpo, refresh=True)
    except Exception as exc:  # noqa: BLE001
        return {"error": str(exc)}
    return corpo




def get_benchmark_definition(slug: str, *, es: Optional[Elasticsearch] = None) -> Optional[Dict[str, Any]]:
    """Definição de um benchmark (ou `None`)."""
    client = es or get_es_client()
    if not client:
        return None
    if not ensure_benchmarks_index(client):
        return None
    try:
        resp = client.get(index=BENCHMARKS_INDEX, id=_safe_slug(slug))
    except Exception:  # noqa: BLE001 - não encontrado é o caso normal
        return None
    return dict(resp.get("_source") or {})




def list_benchmark_definitions(*, es: Optional[Elasticsearch] = None) -> List[Dict[str, Any]]:
    """Todos os benchmarks, mais recentes primeiro."""
    client = es or get_es_client()
    if not client:
        return []
    if not ensure_benchmarks_index(client):
        return []
    try:
        resp = client.search(
            index=BENCHMARKS_INDEX,
            body={"size": 200, "query": {"match_all": {}}, "sort": [{"updated_at": {"order": "desc"}}]},
        )
    except Exception:  # noqa: BLE001
        return []
    return [dict(hit.get("_source") or {}) for hit in (resp.get("hits") or {}).get("hits") or []]




def delete_benchmark_definition(slug: str, *, es: Optional[Elasticsearch] = None) -> bool:
    """Apaga a definição de um benchmark."""
    client = es or get_es_client()
    if not client:
        return False
    try:
        client.delete(index=BENCHMARKS_INDEX, id=_safe_slug(slug), refresh=True)
        return True
    except Exception:  # noqa: BLE001 - já não existia
        return False




def index_benchmark_items(slug: str, items: Iterable[Dict[str, Any]], *, es: Optional[Elasticsearch] = None) -> Dict[str, Any]:
    """Indexa as ofertas recolhidas no índice **próprio** do benchmark.

    O `_id` é ``<loja>|<item_id>``, por isso repetir uma recolha actualiza a
    oferta em vez de a duplicar.
    """
    client = es or get_es_client()
    if not client:
        return {"error": "Elasticsearch indisponível", "indexed": 0, "errors": 0}
    if not ensure_benchmark_items_index(slug, client=client):
        return {"error": "Índice do benchmark indisponível", "indexed": 0, "errors": 0}
    indice = benchmark_items_index(slug)
    acoes: List[Dict[str, Any]] = []
    for item in items or []:
        doc = {k: v for k, v in item.items() if k not in ("item_id",)}
        identificador = str(item.get("item_id") or doc.get("url") or doc.get("product_key") or "").strip()
        if not identificador:
            continue
        doc["benchmark"] = slug
        acoes.append({"_index": indice, "_id": f"{doc.get('store_id') or 'loja'}|{identificador}", "_source": doc})
    if not acoes:
        return {"indexed": 0, "errors": 0, "index": indice}
    sucesso, erros = bulk(client, acoes, raise_on_error=False, stats_only=False, refresh=True)
    return {"indexed": int(sucesso), "errors": len(erros or []), "index": indice}




def delete_benchmark_items(
    slug: str,
    *,
    store_id: Optional[str] = None,
    es: Optional[Elasticsearch] = None,
) -> Dict[str, Any]:
    """Limpa as ofertas de um benchmark (todas, ou só as de uma loja)."""
    client = es or get_es_client()
    if not client:
        return {"error": "Elasticsearch indisponível"}
    indice = benchmark_items_index(slug)
    try:
        if not client.indices.exists(index=indice):
            return {"deleted": 0, "index": indice}
        corpo: Dict[str, Any] = {"match_all": {}} if not store_id else {"term": {"store_id": store_id}}
        resp = client.delete_by_query(index=indice, body={"query": corpo}, refresh=True, conflicts="proceed")
        return {"deleted": int(resp.get("deleted") or 0), "index": indice}
    except Exception as exc:  # noqa: BLE001
        return {"error": str(exc), "index": indice}




def drop_benchmark_index(slug: str, *, es: Optional[Elasticsearch] = None) -> bool:
    """Apaga o índice de ofertas de um benchmark (ao apagar o benchmark)."""
    client = es or get_es_client()
    if not client:
        return False
    try:
        client.indices.delete(index=benchmark_items_index(slug), ignore_unavailable=True)
        return True
    except Exception:  # noqa: BLE001
        return False




def benchmark_store_stats(slug: str, *, es: Optional[Elasticsearch] = None) -> List[Dict[str, Any]]:
    """Volumetria e preço por loja — a base do ranking de competitividade."""
    client = es or get_es_client()
    if not client:
        return []
    indice = benchmark_items_index(slug)
    try:
        if not client.indices.exists(index=indice):
            return []
        resp = client.search(
            index=indice,
            body={
                "size": 0,
                "query": {"match_all": {}},
                "aggs": {
                    "lojas": {
                        "terms": {"field": "store_id", "size": 100},
                        "aggs": {
                            "nome": {"terms": {"field": "store_name", "size": 1}},
                            "preco": {"stats": {"field": "price"}},
                            "produtos": {"cardinality": {"field": "product_key"}},
                            "em_stock": {"filter": {"term": {"in_stock": True}}},
                        },
                    }
                },
            },
        )
    except Exception:  # noqa: BLE001
        return []
    lojas: List[Dict[str, Any]] = []
    for balde in ((resp.get("aggregations") or {}).get("lojas") or {}).get("buckets") or []:
        preco = balde.get("preco") or {}
        nome = ((balde.get("nome") or {}).get("buckets") or [{}])[0].get("key")
        lojas.append(
            {
                "store_id": balde.get("key"),
                "store_name": nome or balde.get("key"),
                "ofertas": balde.get("doc_count"),
                "produtos": balde.get("produtos", {}).get("value"),
                "em_stock": (balde.get("em_stock") or {}).get("doc_count"),
                "preco_min": preco.get("min"),
                "preco_max": preco.get("max"),
                "preco_medio": round(preco.get("avg"), 2) if preco.get("avg") is not None else None,
            }
        )
    lojas.sort(key=lambda item: item.get("preco_medio") or 0)
    return lojas




def benchmark_garment_stats(slug: str, *, es: Optional[Elasticsearch] = None) -> List[Dict[str, Any]]:
    """Preço por **tipo de peça** — o resumo que compara marcas diferentes.

    O produto a produto só é comparável quando as lojas vendem o mesmo artigo;
    por tipo de peça (`Camisolas`, `Calças`, `Vestidos`…) já se pode comparar o
    preço médio de cada loja, mesmo que sejam peças de marcas distintas.
    """
    client = es or get_es_client()
    if not client:
        return []
    indice = benchmark_items_index(slug)
    try:
        if not client.indices.exists(index=indice):
            return []
        resp = client.search(
            index=indice,
            body={
                "size": 0,
                "query": {"match_all": {}},
                "aggs": {
                    "tipos": {
                        "terms": {"field": "garment_type", "size": 40, "order": {"_count": "desc"}},
                        "aggs": {
                            "preco": {"stats": {"field": "price"}},
                            "lojas": {"cardinality": {"field": "store_id"}},
                            "mais_barata": {
                                "terms": {"field": "store_name", "size": 1, "order": {"minimo": "asc"}},
                                "aggs": {"minimo": {"min": {"field": "price"}}},
                            },
                        },
                    }
                },
            },
        )
    except Exception:  # noqa: BLE001
        return []
    tipos: List[Dict[str, Any]] = []
    for balde in ((resp.get("aggregations") or {}).get("tipos") or {}).get("buckets") or []:
        preco = balde.get("preco") or {}
        barata = ((balde.get("mais_barata") or {}).get("buckets") or [{}])[0]
        tipos.append(
            {
                "garment_type": balde.get("key"),
                "offers": balde.get("doc_count"),
                "stores": int(balde.get("lojas", {}).get("value") or 0),
                "price_min": round(preco["min"], 2) if preco.get("min") is not None else None,
                "price_max": round(preco["max"], 2) if preco.get("max") is not None else None,
                "price_avg": round(preco["avg"], 2) if preco.get("avg") is not None else None,
                "cheapest_store": barata.get("key"),
                "cheapest_price": round((barata.get("minimo") or {}).get("value"), 2)
                if (barata.get("minimo") or {}).get("value") is not None
                else None,
            }
        )
    return tipos




def benchmark_product_comparison(
    slug: str,
    *,
    q: Optional[str] = None,
    store_id: Optional[str] = None,
    order: str = "dispersao",
    size: int = 50,
    from_: int = 0,
    min_stores: int = 2,
    es: Optional[Elasticsearch] = None,
) -> Dict[str, Any]:
    """Compara **o mesmo produto entre lojas**: melhor preço, dispersão e lojas.

    Agrega por `product_key` e, em cada produto, calcula o mínimo, o máximo, a
    média e as lojas onde aparece. A ordenação (dispersão, poupança, nº de
    lojas ou nome) é feita em Python sobre os baldes, porque depende de valores
    calculados — o Elasticsearch só devolve os candidatos.
    """
    client = es or get_es_client()
    if not client:
        return {"error": "Elasticsearch indisponível", "items": [], "total": 0}
    indice = benchmark_items_index(slug)
    try:
        if not client.indices.exists(index=indice):
            return {"items": [], "total": 0, "index": indice, "stores": []}
    except Exception as exc:  # noqa: BLE001
        return {"error": str(exc), "items": [], "total": 0}

    filtros: List[Dict[str, Any]] = []
    if store_id:
        filtros.append({"term": {"store_id": store_id}})
    if q:
        filtros.append(
            {
                "multi_match": {
                    "query": q,
                    "fields": ["product_name^3", "brand^2", "sku", "ean", "category"],
                    "type": "best_fields",
                    "fuzziness": "AUTO",
                }
            }
        )
    corpo: Dict[str, Any] = {
        "size": 0,
        "query": {"bool": {"filter": filtros}} if filtros else {"match_all": {}},
        "aggs": {
            "produtos": {
                # Ordenado pelo preço máximo do produto (o balde maior primeiro):
                # o cliente mostra primeiro onde há mais amplitude de preço.
                "terms": {"field": "product_key", "size": 1000, "order": {"preco.max": "desc"}},
                "aggs": {
                    "nome": {"terms": {"field": "product_name.keyword", "size": 1}},
                    "marca": {"terms": {"field": "brand", "size": 1}},
                    "preco": {"stats": {"field": "price"}},
                    "lojas": {"cardinality": {"field": "store_id"}},
                    "melhor": {
                        "top_hits": {
                            "size": 1,
                            "sort": [{"price": {"order": "asc"}}],
                            "_source": [
                                "store_id",
                                "store_name",
                                "price",
                                "url",
                                "image",
                                "description",
                                "availability",
                                "currency",
                                "in_stock",
                            ],
                        }
                    },
                    "ofertas": {
                        "top_hits": {
                            "size": 50,
                            "sort": [{"price": {"order": "asc"}}],
                            "_source": [
                                "store_id",
                                "store_name",
                                "price",
                                "url",
                                "image",
                                "description",
                                "availability",
                                "currency",
                                "in_stock",
                                "discount_pct",
                            ],
                        }
                    },
                },
            }
        },
    }
    try:
        resp = client.search(index=indice, body=corpo)
    except Exception as exc:  # noqa: BLE001
        return {"error": str(exc), "items": [], "total": 0}

    produtos: List[Dict[str, Any]] = []
    for balde in ((resp.get("aggregations") or {}).get("produtos") or {}).get("buckets") or []:
        preco = balde.get("preco") or {}
        minimo = preco.get("min")
        maximo = preco.get("max")
        media = preco.get("avg")
        lojas = int(balde.get("lojas", {}).get("value") or 0)
        if lojas < max(1, int(min_stores)):
            continue
        melhor = ((balde.get("melhor") or {}).get("hits") or {}).get("hits") or [{}]
        ofertas = [
            dict(hit.get("_source") or {})
            for hit in (((balde.get("ofertas") or {}).get("hits") or {}).get("hits") or [])
        ]
        nome = ((balde.get("nome") or {}).get("buckets") or [{}])[0].get("key")
        marca = ((balde.get("marca") or {}).get("buckets") or [{}])[0].get("key")
        dispersao = round(100.0 * (maximo - minimo) / media, 2) if media else None
        produtos.append(
            {
                "product_key": balde.get("key"),
                "product_name": nome or balde.get("key"),
                "brand": marca,
                "offers": balde.get("doc_count"),
                "stores": lojas,
                "price_min": minimo,
                "price_max": maximo,
                "price_avg": round(media, 2) if media is not None else None,
                "spread_pct": dispersao,
                "saving_abs": round(maximo - minimo, 2) if minimo is not None and maximo is not None else None,
                "best": dict(melhor[0].get("_source") or {}) if melhor else {},
                "all_offers": ofertas,
            }
        )

    chaves = {
        "dispersao": lambda item: -(item.get("spread_pct") or 0),
        "poupanca": lambda item: -(item.get("saving_abs") or 0),
        "lojas": lambda item: -int(item.get("stores") or 0),
        "preco": lambda item: item.get("price_min") if item.get("price_min") is not None else 0,
        "nome": lambda item: str(item.get("product_name") or "").lower(),
    }
    produtos.sort(key=chaves.get(order, chaves["dispersao"]))
    total = len(produtos)
    inicio = max(0, int(from_))
    return {
        "index": indice,
        "items": produtos[inicio : inicio + max(1, min(int(size), 200))],
        "total": total,
        "order": order,
    }




def benchmark_offers(
    slug: str,
    *,
    q: Optional[str] = None,
    store_id: Optional[str] = None,
    order: str = "preco",
    size: int = 50,
    from_: int = 0,
    es: Optional[Elasticsearch] = None,
) -> Dict[str, Any]:
    """Ofertas item a item (o que cada loja anuncia), com facetas e preços."""
    client = es or get_es_client()
    if not client:
        return {"error": "Elasticsearch indisponível", "items": [], "total": 0}
    indice = benchmark_items_index(slug)
    try:
        if not client.indices.exists(index=indice):
            return {"items": [], "total": 0, "index": indice}
    except Exception as exc:  # noqa: BLE001
        return {"error": str(exc), "items": [], "total": 0}

    filtros: List[Dict[str, Any]] = []
    if store_id:
        filtros.append({"term": {"store_id": store_id}})
    if q:
        filtros.append(
            {
                "multi_match": {
                    "query": q,
                    "fields": ["product_name^3", "brand^2", "sku", "ean", "category"],
                    "type": "best_fields",
                    "fuzziness": "AUTO",
                }
            }
        )
    ordenacoes = {
        "preco": [{"price": {"order": "asc"}}],
        "preco_desc": [{"price": {"order": "desc"}}],
        "recentes": [{"collected_at": {"order": "desc"}}],
        "nome": [{"product_name.keyword": {"order": "asc"}}],
        "desconto": [{"discount_pct": {"order": "desc"}}],
    }
    try:
        resp = client.search(
            index=indice,
            body={
                "size": max(1, min(int(size), 200)),
                "from": max(0, int(from_)),
                "track_total_hits": True,
                "query": {"bool": {"filter": filtros}} if filtros else {"match_all": {}},
                "sort": ordenacoes.get(order, ordenacoes["preco"]),
                "aggs": {
                    "lojas": {"terms": {"field": "store_id", "size": 100}},
                    "categorias": {"terms": {"field": "category", "size": 50}},
                    "disponibilidade": {"terms": {"field": "availability", "size": 20}},
                    "faixa": {
                        "histogram": {"field": "price", "interval": 50},
                    },
                    "preco": {"stats": {"field": "price"}},
                },
            },
        )
    except Exception as exc:  # noqa: BLE001
        return {"error": str(exc), "items": [], "total": 0}

    itens = []
    for hit in ((resp.get("hits") or {}).get("hits") or []):
        doc = dict(hit.get("_source") or {})
        doc["_id"] = hit.get("_id")
        itens.append(doc)
    aggs = resp.get("aggregations") or {}
    total = ((resp.get("hits") or {}).get("total") or {}).get("value")
    return {
        "index": indice,
        "items": itens,
        "total": total if total is not None else len(itens),
        "facets": {
            "lojas": [{"id": b.get("key"), "count": b.get("doc_count")} for b in (aggs.get("lojas") or {}).get("buckets") or []],
            "categorias": [
                {"id": b.get("key"), "count": b.get("doc_count")} for b in (aggs.get("categorias") or {}).get("buckets") or []
            ],
            "disponibilidade": [
                {"id": b.get("key"), "count": b.get("doc_count")}
                for b in (aggs.get("disponibilidade") or {}).get("buckets") or []
            ],
        },
        "stats": {
            "preco_min": (aggs.get("preco") or {}).get("min"),
            "preco_max": (aggs.get("preco") or {}).get("max"),
            "preco_medio": (aggs.get("preco") or {}).get("avg"),
        },
    }
