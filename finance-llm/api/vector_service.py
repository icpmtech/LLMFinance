"""Serviço de vector search no Elasticsearch.

Gera embeddings com sentence-transformers e armazena-os em campos `dense_vector`
no Elasticsearch para permitir pesquisa semântica (kNN) híbrida com BM25.
"""
from __future__ import annotations

import asyncio
import logging
import threading
from functools import lru_cache
from typing import Any, Dict, List, Optional, Sequence

from api.elasticsearch_client import CONTRACTS_INDEX, ENTITIES_INDEX, get_es_client

logger = logging.getLogger(__name__)

DEFAULT_MODEL_NAME = "sentence-transformers/all-MiniLM-L6-v2"
EMBEDDING_DIM = 384  # all-MiniLM-L6-v2

# Quantos candidatos o kNN examina por pesquisa, em múltiplos do `k` pedido.
# Valores altos melhoram a recordação e custam tempo: 10× é generoso, 3-4× chega.
NUM_CANDIDATES_FACTOR = 4

# Cache global do modelo de embeddings (reutiliza lógica do RAG).
_embed_model_cache: dict = {}
_embed_model_lock = threading.Lock()


def _get_embedding_model(model_name: str = DEFAULT_MODEL_NAME):
    """Devolve modelo sentence-transformers em cache."""
    cached = _embed_model_cache.get(model_name)
    if cached is not None:
        return cached
    try:
        from sentence_transformers import SentenceTransformer  # type: ignore
    except Exception as exc:
        raise RuntimeError("sentence-transformers não está instalado.") from exc
    with _embed_model_lock:
        if model_name not in _embed_model_cache:
            _embed_model_cache[model_name] = SentenceTransformer(model_name)
    return _embed_model_cache[model_name]


def _normalize_text(text: Any) -> str:
    """Texto seguro para embedding."""
    if text is None:
        return ""
    text = str(text).strip()
    # Remove múltiplos espaços.
    return " ".join(text.split())


def _contract_text(doc: Dict[str, Any]) -> str:
    """Concatena campos textuais de um contrato para embedding."""
    parts = [
        doc.get("objectoContrato", ""),
        doc.get("descContrato", ""),
        doc.get("fundamentacao", ""),
        doc.get("search_text", ""),
    ]
    # Nomes das partes.
    for party_kind in ("adjudicantes", "adjudicatarios"):
        for party in doc.get(party_kind, {}).get("parsed", []) or []:
            parts.append(party.get("nome", ""))
    # CPV descriptions.
    for cpv in doc.get("cpv", []) or []:
        parts.append(cpv.get("description", ""))
    return _normalize_text(". ".join(p for p in parts if p))


def _entity_text(doc: Dict[str, Any]) -> str:
    """Texto representativo de uma entidade."""
    parts = [doc.get("name", ""), doc.get("country", "")]
    return _normalize_text(". ".join(p for p in parts if p))


def _ensure_embedding_mapping(index: str, dim: int = EMBEDDING_DIM) -> bool:
    """Adiciona o campo `embedding` dense_vector ao índice se necessário."""
    es = get_es_client()
    if not es:
        return False
    try:
        mapping = es.indices.get_mapping(index=index)
        props = mapping.get(index, {}).get("mappings", {}).get("properties", {})
        if "embedding" in props:
            return True
        es.indices.put_mapping(
            index=index,
            body={
                "properties": {
                    "embedding": {
                        "type": "dense_vector",
                        "dims": dim,
                        "index": True,
                        "similarity": "cosine",
                    }
                }
            },
        )
        logger.info("Vector mapping added to %s", index)
        return True
    except Exception as e:
        logger.error("Failed to ensure vector mapping on %s: %s", index, e)
        return False


def ensure_vector_indices() -> Dict[str, bool]:
    """Garante que os índices de contratos e entidades têm campo embedding."""
    return {
        CONTRACTS_INDEX: _ensure_embedding_mapping(CONTRACTS_INDEX),
        ENTITIES_INDEX: _ensure_embedding_mapping(ENTITIES_INDEX),
    }


def _encode_texts(texts: Sequence[str], model_name: str = DEFAULT_MODEL_NAME) -> List[List[float]]:
    """Codifica uma lista de textos em embeddings normalizados."""
    model = _get_embedding_model(model_name)
    # Filtra textos vazios e devolve embedding nulo para eles.
    non_empty = [t for t in texts]
    if not non_empty:
        return []
    embeddings = model.encode(
        list(non_empty),
        convert_to_numpy=True,
        normalize_embeddings=True,
        show_progress_bar=False,
    )
    return [emb.tolist() for emb in embeddings]


async def _encode_texts_async(texts: Sequence[str], model_name: str = DEFAULT_MODEL_NAME) -> List[List[float]]:
    """Versão async de _encode_texts; corre o modelo num thread pool."""
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, _encode_texts, texts, model_name)


# Campos que os `text_fn` precisam de ler. Pedir o documento inteiro num índice de
# milhões de contratos multiplica o tráfego e a memória sem necessidade.
_SOURCE_FIELDS: Dict[str, List[str]] = {
    CONTRACTS_INDEX: [
        "objectoContrato",
        "descContrato",
        "fundamentacao",
        "search_text",
        "adjudicantes",
        "adjudicatarios",
        "cpv",
    ],
    ENTITIES_INDEX: ["name", "country"],
}


def _fetch_missing_embeddings(index: str, text_fn, batch_size: int = 64):
    """Yield batches de (doc_id, text) para documentos sem embedding."""
    es = get_es_client()
    if not es:
        return
    scroll_id: Optional[str] = None
    try:
        resp = es.search(
            index=index,
            body={
                "query": {"bool": {"must_not": {"exists": {"field": "embedding"}}}},
                "_source": _SOURCE_FIELDS.get(index, True),
                "stored_fields": [],
                "size": batch_size,
            },
            scroll="5m",
        )
        scroll_id = resp.get("_scroll_id")
        while scroll_id and resp["hits"]["hits"]:
            hits = resp["hits"]["hits"]
            batch = []
            for hit in hits:
                source = hit.get("_source", {})
                text = text_fn(source)
                if text:
                    batch.append((hit["_id"], text))
            if batch:
                yield batch
            resp = es.scroll(scroll_id=scroll_id, scroll="5m")
            scroll_id = resp.get("_scroll_id")
    except Exception as e:
        logger.error("Error fetching missing embeddings from %s: %s", index, e)
    finally:
        if scroll_id:
            try:
                es.clear_scroll(scroll_id=scroll_id)
            except Exception:  # pragma: no cover - limpeza best-effort
                pass


def index_missing_embeddings(
    index: str,
    batch_size: int = 64,
    max_docs: Optional[int] = None,
    model_name: str = DEFAULT_MODEL_NAME,
) -> Dict[str, Any]:
    """Indexa embeddings para documentos que ainda não têm (síncrono)."""
    es = get_es_client()
    if not es or not _ensure_embedding_mapping(index):
        return {"error": "Elasticsearch indisponível ou mapping falhou"}

    text_fn = _contract_text if index == CONTRACTS_INDEX else _entity_text
    total_indexed = 0
    total_errors = 0
    batches = 0

    for batch in _fetch_missing_embeddings(index, text_fn, batch_size=batch_size):
        if max_docs and total_indexed >= max_docs:
            break
        if not batch:
            continue
        doc_ids, texts = zip(*batch)
        try:
            embeddings = _encode_texts(texts, model_name=model_name)
        except Exception as e:
            logger.error("Embedding encode failed: %s", e)
            total_errors += len(batch)
            continue
        bulk_body = []
        for doc_id, embedding in zip(doc_ids, embeddings):
            bulk_body.append({"update": {"_index": index, "_id": doc_id}})
            bulk_body.append({"doc": {"embedding": embedding}})
        try:
            resp = es.bulk(body=bulk_body, refresh=False)
            errors = resp.get("errors", True)
            if errors:
                for item in resp.get("items", []):
                    if item.get("update", {}).get("error"):
                        total_errors += 1
                        logger.warning("Embedding index error: %s", item["update"]["error"])
            else:
                total_indexed += len(doc_ids)
            batches += 1
            if batches % 10 == 0:
                logger.info("Indexed %d embeddings in %s", total_indexed, index)
        except Exception as e:
            logger.error("Bulk embedding index failed: %s", e)
            total_errors += len(batch)

    try:
        es.indices.refresh(index=index)
    except Exception:
        pass

    return {
        "index": index,
        "indexed": total_indexed,
        "errors": total_errors,
        "batches": batches,
    }


async def index_missing_embeddings_async(
    index: str,
    batch_size: int = 64,
    max_docs: Optional[int] = None,
    model_name: str = DEFAULT_MODEL_NAME,
    progress_callback: Optional[callable] = None,
) -> Dict[str, Any]:
    """Indexa embeddings de forma assíncrona, devolvendo o controlo entre batches."""
    es = get_es_client()
    if not es or not _ensure_embedding_mapping(index):
        return {"error": "Elasticsearch indisponível ou mapping falhou"}

    text_fn = _contract_text if index == CONTRACTS_INDEX else _entity_text
    total_indexed = 0
    total_errors = 0
    batches = 0

    for batch in _fetch_missing_embeddings(index, text_fn, batch_size=batch_size):
        if max_docs and total_indexed >= max_docs:
            break
        if not batch:
            continue
        doc_ids, texts = zip(*batch)
        try:
            embeddings = await _encode_texts_async(texts, model_name=model_name)
        except Exception as e:
            logger.error("Embedding encode failed: %s", e)
            total_errors += len(batch)
            continue
        bulk_body = []
        for doc_id, embedding in zip(doc_ids, embeddings):
            bulk_body.append({"update": {"_index": index, "_id": doc_id}})
            bulk_body.append({"doc": {"embedding": embedding}})
        try:
            resp = es.bulk(body=bulk_body, refresh=False)
            errors = resp.get("errors", True)
            if errors:
                for item in resp.get("items", []):
                    if item.get("update", {}).get("error"):
                        total_errors += 1
                        logger.warning("Embedding index error: %s", item["update"]["error"])
            else:
                total_indexed += len(doc_ids)
            batches += 1
            if batches % 10 == 0:
                logger.info("Indexed %d embeddings in %s", total_indexed, index)
                if progress_callback:
                    try:
                        progress_callback(total_indexed, total_errors)
                    except Exception:
                        pass
        except Exception as e:
            logger.error("Bulk embedding index failed: %s", e)
            total_errors += len(batch)

        # cede controlo ao loop de eventos a cada batch para não bloquear outras requests.
        await asyncio.sleep(0)

    try:
        es.indices.refresh(index=index)
    except Exception:
        pass

    return {
        "index": index,
        "indexed": total_indexed,
        "errors": total_errors,
        "batches": batches,
    }


@lru_cache(maxsize=512)
def _query_embedding(query: str, model_name: str = DEFAULT_MODEL_NAME) -> tuple:
    """Embedding de uma consulta, em cache.

    O `vector_search` é chamado **uma vez por âmbito** com a mesma consulta: sem
    isto, a mesma frase era codificada duas ou três vezes por pergunta. A chave
    inclui o modelo porque mudar de modelo muda o espaço vetorial.
    """
    vetores = _encode_texts([_normalize_text(query)], model_name=model_name)
    return tuple(vetores[0]) if vetores else ()


def vector_search(
    index: str,
    query: str,
    top_k: int = 20,
    filters: Optional[Dict[str, Any]] = None,
    min_score: float = 0.0,
    model_name: str = DEFAULT_MODEL_NAME,
    num_candidates_factor: int = NUM_CANDIDATES_FACTOR,
) -> Dict[str, Any]:
    """Pesquisa semântica kNN no Elasticsearch com filtros opcionais."""
    es = get_es_client()
    if not es:
        return {"error": "Elasticsearch indisponível", "items": []}

    embedding = list(_query_embedding(query, model_name))
    if not embedding:
        return {"error": "Não foi possível gerar embedding", "items": []}

    knn_query: Dict[str, Any] = {
        "field": "embedding",
        "query_vector": embedding,
        "k": top_k,
        # Candidatos examinados por pesquisa. Era `top_k * 10` (500 com
        # `per_source=50`): no HNSW, 3-4× o `k` já dá a mesma qualidade com muito
        # menos trabalho. Ajustável por parâmetro (ver NUM_CANDIDATES_FACTOR).
        "num_candidates": max(top_k * max(1, num_candidates_factor), 50),
    }

    bool_filter = []
    if filters:
        for key, value in filters.items():
            if value is None:
                continue
            if key == "year":
                bool_filter.append({"term": {"Ano": value}})
            elif key == "year_from":
                bool_filter.append({"range": {"Ano": {"gte": value}}})
            elif key == "year_to":
                bool_filter.append({"range": {"Ano": {"lte": value}}})
            elif key == "district":
                # localExecucao é keyword; faz match para abranger variantes.
                bool_filter.append({"match": {"localExecucao": value}})
            elif key == "nif":
                bool_filter.append(
                    {"nested": {"path": "adjudicatarios.parsed", "query": {"term": {"adjudicatarios.parsed.nif": value}}}}
                )
            elif key == "cpv_code":
                bool_filter.append(
                    {"nested": {"path": "cpv", "query": {"term": {"cpv.code": value}}}}
                )
            elif key == "region":
                bool_filter.append({"match": {"localExecucao": value}})

    body: Dict[str, Any] = {
        "knn": knn_query,
        "_source": True,
        "size": top_k,
    }
    if bool_filter:
        body["query"] = {"bool": {"filter": bool_filter}}

    try:
        resp = es.search(index=index, body=body)
    except Exception as e:
        return {"error": str(e), "items": []}

    items = []
    for hit in resp["hits"]["hits"]:
        source = hit["_source"]
        source["doc_id"] = hit["_id"]
        source["vector_score"] = hit.get("_score", 0.0)
        if source["vector_score"] >= min_score:
            items.append(source)

    return {
        "query": query,
        "total": resp["hits"]["total"]["value"],
        "items": items,
        "size": top_k,
    }


def hybrid_search_contracts(
    query: str,
    top_k: int = 20,
    filters: Optional[Dict[str, Any]] = None,
    vector_weight: float = 0.5,
    text_weight: float = 0.5,
    model_name: str = DEFAULT_MODEL_NAME,
) -> Dict[str, Any]:
    """Pesquisa híbrida: BM25 sobre search_text + kNN sobre embedding.

    Combina os dois conjuntos de resultados com RRF simples
    (Reciprocal Rank Fusion) porque os scores de BM25 e coseno
    não são comparáveis diretamente.
    """
    # Recolha vector search.
    vector_res = vector_search(
        CONTRACTS_INDEX,
        query,
        top_k=top_k * 3,
        filters=filters,
        model_name=model_name,
    )
    if "error" in vector_res:
        return vector_res

    # Recolha texto (BM25).
    text_query = {"bool": {"must": {"multi_match": {"query": query, "fields": ["objectoContrato^3", "descContrato^2", "search_text", "fundamentacao"]}}}}
    if filters:
        bool_filter = []
        for key, value in filters.items():
            if value is None:
                continue
            if key == "year":
                bool_filter.append({"term": {"Ano": value}})
            elif key == "year_from":
                bool_filter.append({"range": {"Ano": {"gte": value}}})
            elif key == "year_to":
                bool_filter.append({"range": {"Ano": {"lte": value}}})
            elif key in ("district", "region"):
                bool_filter.append({"match": {"localExecucao": value}})
            elif key == "nif":
                bool_filter.append(
                    {"nested": {"path": "adjudicatarios.parsed", "query": {"term": {"adjudicatarios.parsed.nif": value}}}}
                )
            elif key == "cpv_code":
                bool_filter.append(
                    {"nested": {"path": "cpv", "query": {"term": {"cpv.code": value}}}}
                )
        if bool_filter:
            text_query["bool"]["filter"] = bool_filter

    es = get_es_client()
    text_items = []
    if es:
        try:
            resp = es.search(
                index=CONTRACTS_INDEX,
                body={"query": text_query, "size": top_k * 3, "track_total_hits": True},
            )
            for hit in resp["hits"]["hits"]:
                source = hit["_source"]
                source["doc_id"] = hit["_id"]
                source["text_score"] = hit.get("_score", 0.0)
                text_items.append(source)
        except Exception as e:
            logger.error("Text search failed: %s", e)

    # RRF fusion: score = sum(1/(k+rank)) com k=60.
    RRF_K = 60
    fused: Dict[str, Dict[str, Any]] = {}
    for rank, item in enumerate(vector_res.get("items", [])):
        doc_id = item.get("doc_id")
        fused[doc_id] = {"item": item, "score": 1.0 / (RRF_K + rank + 1)}
    for rank, item in enumerate(text_items):
        doc_id = item.get("doc_id")
        if doc_id in fused:
            fused[doc_id]["score"] += 1.0 / (RRF_K + rank + 1)
        else:
            fused[doc_id] = {"item": item, "score": 1.0 / (RRF_K + rank + 1)}

    ranked = sorted(fused.values(), key=lambda x: x["score"], reverse=True)[:top_k]
    return {
        "query": query,
        "total": len(fused),
        "items": [x["item"] for x in ranked],
        "size": top_k,
        "vector_hits": len(vector_res.get("items", [])),
        "text_hits": len(text_items),
    }


def vector_search_status() -> Dict[str, Any]:
    """Devolve estatísticas de embeddings indexados."""
    es = get_es_client()
    if not es:
        return {"error": "Elasticsearch indisponível"}
    try:
        stats = {}
        for index in (CONTRACTS_INDEX, ENTITIES_INDEX):
            total = es.count(index=index).get("count", 0)
            with_embedding = es.count(
                index=index,
                body={"query": {"exists": {"field": "embedding"}}},
            ).get("count", 0)
            stats[index] = {"total": total, "with_embedding": with_embedding, "missing": total - with_embedding}
        return {"status": "ok", "indices": stats}
    except Exception as e:
        return {"error": str(e)}
