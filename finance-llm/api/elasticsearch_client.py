"""Cliente Elasticsearch para ingestão e pesquisa de dados financeiros.

Índices utilizados:
- finance_prices: histórico de preços de ações (OHLCV) por ticker.
- finance_news: notícias/sociais de ações por ticker.

Ambos suportam pesquisa por ticker, data e texto.
"""
import json
import os
import re
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from elasticsearch import Elasticsearch
from elasticsearch.helpers import bulk

ROOT = Path(__file__).resolve().parents[1]

# Índice único para contratos públicos normalizados
CONTRACTS_INDEX = "finance_contracts"


def _get_es_url() -> str:
    return os.getenv("ELASTICSEARCH_URL", "http://127.0.0.1:9200")


def get_es_client() -> Optional[Elasticsearch]:
    """Devolve cliente Elasticsearch ou None se não estiver disponível."""
    try:
        es = Elasticsearch([_get_es_url()], request_timeout=30)
        if not es.ping():
            return None
        return es
    except Exception:
        return None


def ensure_indices(es: Optional[Elasticsearch] = None) -> bool:
    """Cria/atualiza os índices necessários, caso ainda não existam."""
    client = es or get_es_client()
    if not client:
        return False

    prices_mappings = {
        "properties": {
            "ticker": {"type": "keyword"},
            "date": {"type": "date"},
            "open": {"type": "float"},
            "high": {"type": "float"},
            "low": {"type": "float"},
            "close": {"type": "float"},
            "volume": {"type": "long"},
            "period": {"type": "keyword"},
            "ingested_at": {"type": "date"},
        }
    }

    news_mappings = {
        "properties": {
            "ticker": {"type": "keyword"},
            "title": {"type": "text"},
            "summary": {"type": "text"},
            "publisher": {"type": "keyword"},
            "published": {"type": "date"},
            "url": {"type": "keyword"},
            "source": {"type": "keyword"},
            "ingested_at": {"type": "date"},
            "analyzed_at": {"type": "date"},
            "sentiment": {"type": "keyword"},
            "language": {"type": "keyword"},
            "translated_title": {"type": "text"},
            "translated_summary": {"type": "text"},
            "summary_pt": {"type": "text"},
            "topics": {"type": "keyword"},
            "entities": {
                "type": "nested",
                "properties": {
                    "name": {"type": "keyword"},
                    "type": {"type": "keyword"},
                },
            },
        }
    }

    sentiment_mappings = {
        "properties": {
            "ticker": {"type": "keyword"},
            "date": {"type": "date"},
            "news_count": {"type": "integer"},
            "sentiment_mean": {"type": "float"},
            "sentiment_std": {"type": "float"},
            "positive_count": {"type": "integer"},
            "negative_count": {"type": "integer"},
            "positive_ratio": {"type": "float"},
            "negative_ratio": {"type": "float"},
            "updated_at": {"type": "date"},
        }
    }

    macro_mappings = {
        "properties": {
            "name": {"type": "keyword"},
            "date": {"type": "date"},
            "value": {"type": "float"},
            "updated_at": {"type": "date"},
        }
    }

    earnings_mappings = {
        "properties": {
            "ticker": {"type": "keyword"},
            "date": {"type": "date"},
            "eps_estimate": {"type": "float"},
            "reported_eps": {"type": "float"},
            "surprise_pct": {"type": "float"},
            "updated_at": {"type": "date"},
        }
    }

    contracts_mappings = {
        "properties": {
            "idcontrato": {"type": "keyword"},
            "nAnuncio": {"type": "keyword"},
            "TipoAnuncio": {"type": "keyword"},
            "idINCM": {"type": "keyword"},
            "tipoContrato": {"type": "keyword"},
            "idprocedimento": {"type": "keyword"},
            "tipoprocedimento": {"type": "text"},
            "objectoContrato": {"type": "text"},
            "descContrato": {"type": "text"},
            "adjudicantes": {
                "type": "nested",
                "properties": {
                    "raw": {"type": "keyword"},
                    "parsed": {
                        "type": "nested",
                        "properties": {
                            "nif": {"type": "keyword"},
                            "nome": {"type": "text"},
                        },
                    },
                },
            },
            "adjudicatarios": {
                "type": "nested",
                "properties": {
                    "raw": {"type": "keyword"},
                    "parsed": {
                        "type": "nested",
                        "properties": {
                            "nif": {"type": "keyword"},
                            "nome": {"type": "text"},
                        },
                    },
                },
            },
            "dataPublicacao": {"type": "date", "format": "yyyy-MM-dd||yyyy/MM/dd HH:mm:ss||epoch_millis"},
            "dataCelebracaoContrato": {"type": "date", "format": "yyyy-MM-dd||yyyy/MM/dd HH:mm:ss||epoch_millis"},
            "dataDecisaoAdjudicacao": {"type": "date", "format": "yyyy-MM-dd||yyyy/MM/dd HH:mm:ss||epoch_millis"},
            "dataFechoContrato": {"type": "date", "format": "yyyy-MM-dd||yyyy/MM/dd HH:mm:ss||epoch_millis"},
            "precoContratual": {"type": "float"},
            "cpv": {
                "type": "nested",
                "properties": {
                    "code": {"type": "keyword"},
                    "description": {"type": "text"},
                },
            },
            "prazoExecucao": {"type": "float"},
            "localExecucao": {"type": "keyword"},
            "fundamentacao": {"type": "text"},
            "ProcedimentoCentralizado": {"type": "keyword"},
            "numAcordoQuadro": {"type": "keyword"},
            "DescrAcordoQuadro": {"type": "text"},
            "precoBaseProcedimento": {"type": "float"},
            "PrecoTotalEfetivo": {"type": "float"},
            "regime": {"type": "text"},
            "justifNReducEscrContrato": {"type": "text"},
            "tipoFimContrato": {"type": "keyword"},
            "CritMateriais": {"type": "keyword"},
            "concorrentes": {"type": "text"},
            "linkPecasProc": {"type": "keyword"},
            "Observacoes": {"type": "text"},
            "ContratEcologico": {"type": "keyword"},
            "Ano": {"type": "integer"},
            "fundamentAjusteDireto": {"type": "text"},
            "adjudicatarioPMEs": {"type": "keyword"},
            "NUTs": {"type": "keyword"},
            "Lotes": {"type": "text"},
            "TipoCriterioAdjudicacao": {"type": "keyword"},
            "ingested_at": {"type": "date"},
            "search_text": {"type": "text"},
            "entities": {
                "type": "nested",
                "properties": {
                    "name": {"type": "text"},
                    "type": {"type": "keyword"},
                    "nif": {"type": "keyword"},
                    "code": {"type": "keyword"},
                },
            },
        }
    }

    for name, mappings in [
        ("finance_prices", prices_mappings),
        ("finance_news", news_mappings),
        ("finance_sentiment_daily", sentiment_mappings),
        ("finance_macro", macro_mappings),
        ("finance_earnings", earnings_mappings),
        (CONTRACTS_INDEX, contracts_mappings),
    ]:
        if not client.indices.exists(index=name):
            client.indices.create(
                index=name,
                body={"mappings": mappings, "settings": {"number_of_shards": 1, "number_of_replicas": 0}},
            )
        else:
            # Garante que todos os campos esperados existem; Elasticsearch não permite alterar mapeamentos.
            pass
    return True


def _today() -> str:
    return datetime.utcnow().isoformat()


def index_price_points(ticker: str, points: List[Dict[str, Any]], period: str = "1y", es: Optional[Elasticsearch] = None) -> Dict[str, Any]:
    """Indexa pontos de preço no Elasticsearch.

    Args:
        ticker: símbolo normalizado do ticker.
        points: lista de dicts com date, open, high, low, close, volume.
        period: período de onde os dados vieram.
        es: cliente Elasticsearch opcional.

    Returns:
        dict com ticker, indexed_count, total_points.
    """
    client = es or get_es_client()
    if not client:
        return {"ticker": ticker, "error": "Elasticsearch indisponível", "indexed_count": 0}

    ensure_indices(client)
    ticker = ticker.upper()
    actions = []
    for p in points:
        doc = {
            "_op_type": "index",
            "_index": "finance_prices",
            "_id": f"{ticker}-{p.get('date')}",
            "ticker": ticker,
            "date": p.get("date"),
            "open": _as_float(p.get("open")),
            "high": _as_float(p.get("high")),
            "low": _as_float(p.get("low")),
            "close": _as_float(p.get("close")),
            "volume": _as_int(p.get("volume")),
            "period": period,
            "ingested_at": _today(),
        }
        actions.append(doc)

    if not actions:
        return {"ticker": ticker, "indexed_count": 0, "total_points": 0}

    try:
        success, errors = bulk(client, actions, raise_on_error=False, refresh=True)
        return {"ticker": ticker, "indexed_count": success, "total_points": len(actions), "errors": len(errors)}
    except Exception as e:
        return {"ticker": ticker, "error": str(e), "indexed_count": 0, "total_points": len(actions)}


def index_news_items(ticker: str, items: List[Dict[str, Any]], es: Optional[Elasticsearch] = None) -> Dict[str, Any]:
    """Indexa notícias no Elasticsearch.

    Args:
        ticker: símbolo normalizado do ticker.
        items: lista de notícias com title, summary, publisher, published, url.
        es: cliente Elasticsearch opcional.

    Returns:
        dict com ticker, indexed_count, total_items.
    """
    client = es or get_es_client()
    if not client:
        return {"ticker": ticker, "error": "Elasticsearch indisponível", "indexed_count": 0}

    ensure_indices(client)
    ticker = ticker.upper()
    actions = []
    for i, item in enumerate(items):
        published = item.get("published") or item.get("pubDate")
        if published and isinstance(published, datetime):
            published = published.isoformat()
        doc_id = f"{ticker}-{_news_id(item, i)}"
        doc = {
            "_op_type": "index",
            "_index": "finance_news",
            "_id": doc_id,
            "ticker": ticker,
            "title": item.get("title") or item.get("summary"),
            "summary": item.get("summary") or item.get("title"),
            "publisher": item.get("publisher") or item.get("provider"),
            "published": published,
            "url": item.get("url") or item.get("link"),
            "source": item.get("source", "yfinance"),
            "ingested_at": _today(),
        }
        actions.append(doc)

    if not actions:
        return {"ticker": ticker, "indexed_count": 0, "total_items": 0}

    try:
        success, errors = bulk(client, actions, raise_on_error=False, refresh=True)
        return {"ticker": ticker, "indexed_count": success, "total_items": len(actions), "errors": len(errors)}
    except Exception as e:
        return {"ticker": ticker, "error": str(e), "indexed_count": 0, "total_items": len(actions)}


def _news_id(item: Dict[str, Any], index: int) -> str:
    """Gera ID estável para uma notícia baseada no URL ou no conteúdo."""
    import hashlib
    url = item.get("url") or item.get("link") or ""
    if url:
        return hashlib.md5(url.encode("utf-8")).hexdigest()[:20]
    content = (item.get("title") or "") + (item.get("summary") or "") + str(index)
    return hashlib.md5(content.encode("utf-8")).hexdigest()[:20]


def search_prices(
    ticker: str,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    size: int = 1000,
    es: Optional[Elasticsearch] = None,
) -> Dict[str, Any]:
    """Pesquisa preços de um ticker por intervalo de datas."""
    client = es or get_es_client()
    if not client:
        return {"ticker": ticker, "error": "Elasticsearch indisponível", "points": []}

    query: Dict[str, Any] = {"bool": {"must": [{"term": {"ticker": ticker.upper()}}]}}
    range_filter = {}
    if start_date:
        range_filter["gte"] = start_date
    if end_date:
        range_filter["lte"] = end_date
    if range_filter:
        query["bool"]["filter"] = [{"range": {"date": range_filter}}]

    try:
        resp = client.search(
            index="finance_prices",
            body={
                "query": query,
                "sort": [{"date": {"order": "asc"}}],
                "size": size,
            },
        )
        points = [hit["_source"] for hit in resp["hits"]["hits"]]
        return {
            "ticker": ticker.upper(),
            "total": resp["hits"]["total"]["value"],
            "points": points,
            "start_date": start_date,
            "end_date": end_date,
        }
    except Exception as e:
        return {"ticker": ticker.upper(), "error": str(e), "points": []}


def search_news(
    ticker: str,
    q: Optional[str] = None,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    size: int = 50,
    es: Optional[Elasticsearch] = None,
) -> Dict[str, Any]:
    """Pesquisa notícias por ticker e texto opcional."""
    client = es or get_es_client()
    if not client:
        return {"ticker": ticker, "error": "Elasticsearch indisponível", "items": []}

    must: List[Dict[str, Any]] = [{"term": {"ticker": ticker.upper()}}]
    if q:
        must.append({
            "multi_match": {
                "query": q,
                "fields": ["title^2", "summary", "publisher"],
                "type": "best_fields",
            }
        })

    query: Dict[str, Any] = {"bool": {"must": must}}
    range_filter = {}
    if start_date:
        range_filter["gte"] = start_date
    if end_date:
        range_filter["lte"] = end_date
    if range_filter:
        query["bool"]["filter"] = [{"range": {"published": range_filter}}]

    try:
        resp = client.search(
            index="finance_news",
            body={
                "query": query,
                "sort": [{"published": {"order": "desc"}}, "_score"],
                "size": size,
            },
        )
        items = [hit["_source"] for hit in resp["hits"]["hits"]]
        return {
            "ticker": ticker.upper(),
            "total": resp["hits"]["total"]["value"],
            "items": items,
        }
    except Exception as e:
        return {"ticker": ticker.upper(), "error": str(e), "items": []}


def index_analyzed_news_items(
    ticker: str,
    items: List[Dict[str, Any]],
    analyses: List[Any],
    es: Optional[Elasticsearch] = None,
) -> Dict[str, Any]:
    """Indexa notícias enriquecidas com análise NLP no Elasticsearch."""
    client = es or get_es_client()
    if not client:
        return {"ticker": ticker, "error": "Elasticsearch indisponível", "indexed_count": 0}

    ensure_indices(client)
    ticker = ticker.upper()
    actions = []
    now = _today()
    for i, (item, analysis) in enumerate(zip(items, analyses)):
        published = item.get("published") or item.get("pubDate")
        if published and isinstance(published, datetime):
            published = published.isoformat()
        doc_id = f"{ticker}-{_news_id(item, i)}"
        doc = {
            "_op_type": "index",
            "_index": "finance_news",
            "_id": doc_id,
            "ticker": ticker,
            "title": item.get("title") or item.get("summary"),
            "summary": item.get("summary") or item.get("title"),
            "publisher": item.get("publisher") or item.get("provider"),
            "published": published,
            "url": item.get("url") or item.get("link"),
            "source": item.get("source", "yfinance"),
            "ingested_at": now,
            "analyzed_at": now,
            "sentiment": analysis.sentiment,
            "language": analysis.language,
            "translated_title": analysis.translated_title,
            "translated_summary": analysis.translated_summary,
            "summary_pt": analysis.summary_pt,
            "topics": analysis.topics,
            "entities": analysis.entities,
        }
        actions.append(doc)

    if not actions:
        return {"ticker": ticker, "indexed_count": 0, "total_items": 0}

    try:
        success, errors = bulk(client, actions, raise_on_error=False, refresh=True)
        return {"ticker": ticker, "indexed_count": success, "total_items": len(actions), "errors": len(errors)}
    except Exception as e:
        return {"ticker": ticker, "error": str(e), "indexed_count": 0, "total_items": len(actions)}


def fetch_news_for_analysis(
    ticker: str,
    q: Optional[str] = None,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    size: int = 100,
    es: Optional[Elasticsearch] = None,
) -> List[Dict[str, Any]]:
    """Recupera notícias indexadas para serem (re)analisadas."""
    result = search_news(ticker, q, start_date, end_date, size, es)
    return result.get("items", [])


def save_news_graph(
    ticker: str,
    graph: Dict[str, Any],
    es: Optional[Elasticsearch] = None,
) -> Dict[str, Any]:
    """Persiste grafo de notícias/entidades num índice dedicado."""
    client = es or get_es_client()
    if not client:
        return {"ticker": ticker, "error": "Elasticsearch indisponível"}

    graph_mappings = {
        "properties": {
            "ticker": {"type": "keyword"},
            "graph_type": {"type": "keyword"},
            "nodes": {"type": "object"},
            "edges": {"type": "object"},
            "created_at": {"type": "date"},
        }
    }
    if not client.indices.exists(index="finance_graphs"):
        client.indices.create(
            index="finance_graphs",
            body={"mappings": graph_mappings, "settings": {"number_of_shards": 1, "number_of_replicas": 0}},
        )

    try:
        client.index(
            index="finance_graphs",
            id=f"{ticker.upper()}-news",
            body={
                "ticker": ticker.upper(),
                "graph_type": "news_entities",
                "nodes": graph.get("nodes", []),
                "edges": graph.get("edges", []),
                "created_at": _today(),
            },
        )
        return {"ticker": ticker.upper(), "saved": True, "node_count": len(graph.get("nodes", [])), "edge_count": len(graph.get("edges", []))}
    except Exception as e:
        return {"ticker": ticker.upper(), "error": str(e)}


def load_news_graph(ticker: str, es: Optional[Elasticsearch] = None) -> Optional[Dict[str, Any]]:
    """Carrega grafo de notícias/entidades persistido."""
    client = es or get_es_client()
    if not client:
        return None
    try:
        resp = client.get(index="finance_graphs", id=f"{ticker.upper()}-news")
        return resp.get("_source")
    except Exception:
        return None


def search_all_tickers(
    q: str,
    from_: int = 0,
    size: int = 50,
    source: Optional[str] = None,
    sentiment: Optional[str] = None,
    topic: Optional[str] = None,
    es: Optional[Elasticsearch] = None,
) -> Dict[str, Any]:
    """Pesquisa notícias de todos os tickers por texto, com filtros e paginação."""
    client = es or get_es_client()
    if not client:
        return {"error": "Elasticsearch indisponível", "items": []}

    must = {
        "multi_match": {
            "query": q,
            "fields": ["ticker^3", "title^2", "summary", "publisher"],
            "type": "best_fields",
        }
    }
    filters = []
    if source:
        filters.append({"wildcard": {"publisher": f"*{source.lower()}*"}})
    if sentiment:
        filters.append({"term": {"sentiment": sentiment.lower()}})
    if topic:
        filters.append({"wildcard": {"topics": f"*{topic.lower()}*"}})

    query: Dict[str, Any] = {"bool": {"must": [must], "filter": filters}}

    try:
        resp = client.search(
            index="finance_news",
            body={
                "query": query,
                "sort": [{"published": {"order": "desc"}}, "_score"],
                "from": from_,
                "size": size,
                "track_scores": True,
                "track_total_hits": True,
            },
        )
        items = []
        for hit in resp["hits"]["hits"]:
            source = hit["_source"]
            source["score"] = hit.get("_score")
            items.append(source)
        return {"total": resp["hits"]["total"]["value"], "items": items}
    except Exception as e:
        return {"error": str(e), "items": []}


def autocomplete_suggestions(q: str, size: int = 12, es: Optional[Elasticsearch] = None) -> Dict[str, Any]:
    """Gera sugestões de autocomplete a partir de tickers, títulos, publishers e tópicos indexados."""
    client = es or get_es_client()
    if not client:
        return {"error": "Elasticsearch indisponível", "suggestions": []}

    q = q.strip()
    if not q:
        return {"suggestions": []}

    lower_q = q.lower()
    upper_q = q.upper()

    try:
        resp = client.search(
            index="finance_news",
            body={
                "size": 0,
                "query": {
                    "bool": {
                        "should": [
                            {"wildcard": {"ticker": f"{upper_q}*"}},
                            {"match_phrase_prefix": {"title": q}},
                            {"wildcard": {"publisher": f"*{lower_q}*"}},
                            {"wildcard": {"topics": f"*{lower_q}*"}},
                        ],
                        "minimum_should_match": 1,
                    }
                },
                "aggs": {
                    "tickers": {
                        "terms": {
                            "field": "ticker",
                            "size": 5,
                            "include": f"{upper_q}.*",
                            "order": {"_count": "desc"},
                        }
                    },
                    "publishers": {
                        "terms": {
                            "field": "publisher",
                            "size": 5,
                            "include": f".*{lower_q}.*",
                            "order": {"_count": "desc"},
                        }
                    },
                    "topics": {
                        "terms": {
                            "field": "topics",
                            "size": 5,
                            "include": f".*{lower_q}.*",
                            "order": {"_count": "desc"},
                        }
                    },
                    "title_hits": {
                        "terms": {
                            "field": "title.keyword",
                            "size": 5,
                            "include": f".*{lower_q}.*",
                            "order": {"_count": "desc"},
                        }
                    },
                },
            },
        )

        suggestions = []
        seen = set()

        for bucket in resp["aggregations"]["tickers"]["buckets"]:
            text = bucket["key"]
            if text not in seen:
                seen.add(text)
                suggestions.append({"text": text, "type": "ticker", "count": bucket["doc_count"]})

        for bucket in resp["aggregations"]["publishers"]["buckets"]:
            text = bucket["key"]
            if text and text not in seen:
                seen.add(text)
                suggestions.append({"text": text, "type": "publisher", "count": bucket["doc_count"]})

        for bucket in resp["aggregations"]["topics"]["buckets"]:
            text = bucket["key"]
            if text and text not in seen:
                seen.add(text)
                suggestions.append({"text": text, "type": "topic", "count": bucket["doc_count"]})

        for bucket in resp["aggregations"]["title_hits"]["buckets"]:
            text = bucket["key"]
            if text and text not in seen:
                seen.add(text)
                suggestions.append({"text": text, "type": "title", "count": bucket["doc_count"]})

        suggestions = suggestions[:size]
        return {"suggestions": suggestions}
    except Exception as e:
        return {"error": str(e), "suggestions": []}


def delete_ticker_data(ticker: str, es: Optional[Elasticsearch] = None) -> Dict[str, Any]:
    """Apaga todos os dados de preços e notícias de um ticker."""
    client = es or get_es_client()
    if not client:
        return {"ticker": ticker, "error": "Elasticsearch indisponível"}

    ticker = ticker.upper()
    try:
        prices_resp = client.delete_by_query(
            index="finance_prices",
            body={"query": {"term": {"ticker": ticker}}},
        )
        news_resp = client.delete_by_query(
            index="finance_news",
            body={"query": {"term": {"ticker": ticker}}},
        )
        return {
            "ticker": ticker,
            "prices_deleted": prices_resp.get("deleted", 0),
            "news_deleted": news_resp.get("deleted", 0),
        }
    except Exception as e:
        return {"ticker": ticker, "error": str(e)}


def list_indexed_tickers(es: Optional[Elasticsearch] = None) -> List[str]:
    """Devolve a lista de tickers que já têm dados indexados."""
    client = es or get_es_client()
    if not client:
        return []

    try:
        resp = client.search(
            index="finance_prices",
            body={
                "size": 0,
                "aggs": {"tickers": {"terms": {"field": "ticker", "size": 1000}}},
            },
        )
        return [bucket["key"] for bucket in resp["aggregations"]["tickers"]["buckets"]]
    except Exception:
        return []


def _as_float(value: Any) -> Optional[float]:
    if value is None:
        return None
    try:
        return float(value)
    except (ValueError, TypeError):
        return None


def _as_int(value: Any) -> Optional[int]:
    if value is None:
        return None
    try:
        return int(float(value))
    except (ValueError, TypeError):
        return None


# --- Contratos públicos ---

def index_contracts(
    docs: List[Dict[str, Any]],
    es: Optional[Elasticsearch] = None,
) -> Dict[str, Any]:
    """Indexa documentos de contratos no índice finance_contracts."""
    client = es or get_es_client()
    if not client:
        return {"error": "Elasticsearch indisponível", "indexed_count": 0}

    ensure_indices(client)
    actions = []
    for doc in docs:
        doc_id = str(doc.get("idcontrato") or doc.get("idprocedimento"))
        actions.append({
            "_op_type": "index",
            "_index": CONTRACTS_INDEX,
            "_id": doc_id,
            **doc,
        })

    if not actions:
        return {"indexed_count": 0, "total": 0}

    try:
        success, errors = bulk(client, actions, raise_on_error=False, refresh=True)
        return {"indexed_count": success, "total": len(actions), "errors": len(errors)}
    except Exception as e:
        return {"error": str(e), "indexed_count": 0, "total": len(actions)}


def bulk_index_contracts_from_jsonl(
    jsonl_path: Path,
    chunk_size: int = 1000,
    max_records: Optional[int] = None,
    es: Optional[Elasticsearch] = None,
) -> Dict[str, Any]:
    """Indexa um ficheiro JSONL de contratos em chunks."""
    client = es or get_es_client()
    if not client:
        return {"error": "Elasticsearch indisponível", "indexed_count": 0}

    ensure_indices(client)
    total = 0
    success_total = 0
    error_total = 0
    chunk: List[Dict[str, Any]] = []

    try:
        resolved_path = Path(jsonl_path) if not isinstance(jsonl_path, Path) else jsonl_path
        print(f"[bulk_index_contracts] path={resolved_path} exists={resolved_path.exists()} chunk_size={chunk_size} max_records={max_records}")
        with open(resolved_path, "r", encoding="utf-8") as fh:
            for line in fh:
                if max_records and total >= max_records:
                    print(f"[bulk_index_contracts] max_records reached {total}")
                    break
                try:
                    doc = json.loads(line)
                except Exception:
                    continue
                chunk.append(doc)
                total += 1
                if len(chunk) >= chunk_size:
                    res = index_contracts(chunk, client)
                    print(f"[bulk_index_contracts] chunk indexed={res.get('indexed_count')} errors={res.get('errors')} error={res.get('error')}")
                    success_total += res.get("indexed_count", 0)
                    error_total += res.get("errors", 0) or (0 if not res.get("error") else len(chunk))
                    chunk = []
        if chunk:
            res = index_contracts(chunk, client)
            print(f"[bulk_index_contracts] final chunk indexed={res.get('indexed_count')} errors={res.get('errors')} error={res.get('error')}")
            success_total += res.get("indexed_count", 0)
            error_total += res.get("errors", 0) or (0 if not res.get("error") else len(chunk))
        print(f"[bulk_index_contracts] done total={total} success={success_total} errors={error_total}")
        return {"indexed_count": success_total, "total": total, "errors": error_total}
    except Exception as e:
        print(f"[bulk_index_contracts] exception {e}")
        return {"error": str(e), "indexed_count": success_total, "total": total}


def _contract_to_flat_dict(source: Dict[str, Any]) -> Dict[str, Any]:
    """Converte documento de contrato num dicionário plano para exportação."""
    def party_str(parties: Any) -> str:
        if not parties:
            return ""
        if isinstance(parties, dict):
            parties = [parties]
        names = []
        for p in parties:
            parsed = p.get("parsed") if isinstance(p, dict) else None
            if isinstance(parsed, list):
                names.extend([x.get("nome", "") for x in parsed if x.get("nome")])
            raw = p.get("raw") if isinstance(p, dict) else None
            if isinstance(raw, list):
                names.extend([str(r) for r in raw])
            elif isinstance(raw, str):
                names.append(raw)
        return "; ".join(names)

    def nif_str(parties: Any) -> str:
        if not parties:
            return ""
        if isinstance(parties, dict):
            parties = [parties]
        nifs = []
        for p in parties:
            parsed = p.get("parsed") if isinstance(p, dict) else None
            if isinstance(parsed, list):
                nifs.extend([x.get("nif", "") for x in parsed if x.get("nif")])
        return "; ".join(nifs)

    def cpv_str(cpv: Any) -> str:
        if not cpv:
            return ""
        if isinstance(cpv, dict):
            cpv = [cpv]
        return "; ".join([f"{x.get('code','')} {x.get('description','')}".strip() for x in cpv])

    return {
        "idcontrato": source.get("idcontrato"),
        "nAnuncio": source.get("nAnuncio"),
        "tipoContrato": source.get("tipoContrato"),
        "tipoprocedimento": source.get("tipoprocedimento"),
        "objectoContrato": source.get("objectoContrato"),
        "descContrato": source.get("descContrato"),
        "adjudicante": party_str(source.get("adjudicantes")),
        "nif_adjudicante": nif_str(source.get("adjudicantes")),
        "adjudicatario": party_str(source.get("adjudicatarios")),
        "nif_adjudicatario": nif_str(source.get("adjudicatarios")),
        "dataPublicacao": source.get("dataPublicacao"),
        "dataCelebracaoContrato": source.get("dataCelebracaoContrato"),
        "precoContratual": source.get("precoContratual"),
        "PrecoTotalEfetivo": source.get("PrecoTotalEfetivo"),
        "precoBaseProcedimento": source.get("precoBaseProcedimento"),
        "cpv": cpv_str(source.get("cpv")),
        "localExecucao": source.get("localExecucao"),
        "Ano": source.get("Ano"),
        "NUTs": source.get("NUTs"),
        "regime": source.get("regime"),
    }


def export_contracts_to_excel(
    q: Optional[str] = None,
    year: Optional[int] = None,
    entity: Optional[str] = None,
    nif: Optional[str] = None,
    cpv_code: Optional[str] = None,
    min_price: Optional[float] = None,
    max_price: Optional[float] = None,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    max_records: int = 10000,
    es: Optional[Elasticsearch] = None,
) -> bytes:
    """Exporta contratos filtrados para Excel (bytes)."""
    try:
        import openpyxl
        from openpyxl.styles import Font
    except ImportError as e:
        raise RuntimeError("openpyxl não instalado") from e

    client = es or get_es_client()
    if not client:
        raise RuntimeError("Elasticsearch indisponível")

    query = _build_contract_query(q, year, entity, nif, cpv_code, min_price, max_price, start_date, end_date)
    resp = client.search(
        index=CONTRACTS_INDEX,
        body={
            "query": query,
            "sort": [{"dataPublicacao": {"order": "desc"}}, "_score"],
            "size": min(max_records, 10000),
            "track_scores": False,
        },
    )

    rows = [_contract_to_flat_dict(hit["_source"]) for hit in resp["hits"]["hits"]]
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Contratos"
    headers = list(rows[0].keys()) if rows else [
        "idcontrato", "nAnuncio", "tipoContrato", "tipoprocedimento", "objectoContrato",
        "descContrato", "adjudicante", "nif_adjudicante", "adjudicatario", "nif_adjudicatario",
        "dataPublicacao", "dataCelebracaoContrato", "precoContratual", "PrecoTotalEfetivo",
        "precoBaseProcedimento", "cpv", "localExecucao", "Ano", "NUTs", "regime",
    ]
    ws.append(headers)
    for cell in ws[1]:
        cell.font = Font(bold=True)
    def value_to_excel(v: Any) -> Any:
        if isinstance(v, (list, dict)):
            return json.dumps(v, ensure_ascii=False)
        return v

    for row in rows:
        ws.append([value_to_excel(row.get(h)) for h in headers])
    for column in ws.columns:
        max_length = 0
        column_letter = column[0].column_letter
        for cell in column:
            try:
                val_len = len(str(cell.value))
                if val_len > max_length:
                    max_length = val_length
            except Exception:
                pass
        ws.column_dimensions[column_letter].width = min(max_length + 2, 60)

    from io import BytesIO
    buf = BytesIO()
    wb.save(buf)
    buf.seek(0)
    return buf.read()


def export_contracts_to_pdf(
    q: Optional[str] = None,
    year: Optional[int] = None,
    entity: Optional[str] = None,
    nif: Optional[str] = None,
    cpv_code: Optional[str] = None,
    min_price: Optional[float] = None,
    max_price: Optional[float] = None,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    max_records: int = 500,
    es: Optional[Elasticsearch] = None,
) -> bytes:
    """Exporta contratos filtrados para PDF (bytes)."""
    try:
        from reportlab.lib import colors
        from reportlab.lib.pagesizes import A4, landscape
        from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
        from reportlab.lib.styles import getSampleStyleSheet
    except ImportError as e:
        raise RuntimeError("reportlab não instalado") from e

    client = es or get_es_client()
    if not client:
        raise RuntimeError("Elasticsearch indisponível")

    query = _build_contract_query(q, year, entity, nif, cpv_code, min_price, max_price, start_date, end_date)
    resp = client.search(
        index=CONTRACTS_INDEX,
        body={
            "query": query,
            "sort": [{"dataPublicacao": {"order": "desc"}}, "_score"],
            "size": min(max_records, 1000),
            "track_scores": False,
        },
    )

    rows = [_contract_to_flat_dict(hit["_source"]) for hit in resp["hits"]["hits"]]
    headers = ["ID", "Ano", "Tipo", "Objecto", "Adjudicante", "Adjudicatário", "Valor", "Publicação"]
    data = [headers]
    for r in rows:
        data.append([
            str(r.get("idcontrato") or ""),
            str(r.get("Ano") or ""),
            str(r.get("tipoContrato") or ""),
            str(r.get("objectoContrato") or "")[:80],
            str(r.get("adjudicante") or "")[:50],
            str(r.get("adjudicatario") or "")[:50],
            f"{r.get('precoContratual') or 0:.2f} €",
            str(r.get("dataPublicacao") or ""),
        ])

    from io import BytesIO
    buf = BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=landscape(A4), rightMargin=20, leftMargin=20, topMargin=20, bottomMargin=20)
    elements = []
    styles = getSampleStyleSheet()
    elements.append(Paragraph("Relatório de Contratos Públicos", styles["Title"]))
    elements.append(Paragraph(f"Total exportado: {len(rows)} contratos", styles["Normal"]))
    elements.append(Spacer(1, 12))
    table = Table(data, repeatRows=1)
    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#10a37f")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.whitesmoke),
        ("ALIGN", (0, 0), (-1, -1), "LEFT"),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, 0), 9),
        ("BOTTOMPADDING", (0, 0), (-1, 0), 8),
        ("BACKGROUND", (0, 1), (-1, -1), colors.HexColor("#f8f9fa")),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
        ("FONTSIZE", (0, 1), (-1, -1), 8),
        ("WORDWRAP", (0, 0), (-1, -1), True),
    ]))
    elements.append(table)
    doc.build(elements)
    buf.seek(0)
    return buf.read()


def search_contracts(
    q: Optional[str] = None,
    year: Optional[int] = None,
    entity: Optional[str] = None,
    nif: Optional[str] = None,
    counterparty_nif: Optional[str] = None,
    region: Optional[str] = None,
    cpv_code: Optional[str] = None,
    min_price: Optional[float] = None,
    max_price: Optional[float] = None,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    size: int = 20,
    from_: int = 0,
    es: Optional[Elasticsearch] = None,
) -> Dict[str, Any]:
    """Pesquisa contratos por texto, entidades, datas e valores."""
    client = es or get_es_client()
    if not client:
        return {"error": "Elasticsearch indisponível", "items": []}

    query = _build_contract_query(q, year, entity, nif, counterparty_nif, region, cpv_code, min_price, max_price, start_date, end_date)

    try:
        resp = client.search(
            index=CONTRACTS_INDEX,
            body={
                "query": query,
                "sort": [{"dataPublicacao": {"order": "desc"}}, "_score"],
                "from": from_,
                "size": size,
                "track_scores": True,
                "track_total_hits": True,
            },
        )
        items = []
        for hit in resp["hits"]["hits"]:
            source = hit["_source"]
            source["score"] = hit.get("_score")
            source["doc_id"] = hit.get("_id")
            items.append(source)
        return {
            "query": q,
            "total": resp["hits"]["total"]["value"],
            "items": items,
            "from": from_,
            "size": size,
        }
    except Exception as e:
        return {"error": str(e), "items": []}


def contracts_autocomplete(
    q: str,
    size: int = 12,
    es: Optional[Elasticsearch] = None,
) -> Dict[str, Any]:
    """Sugestões de autocomplete para entidades e CPV."""
    client = es or get_es_client()
    if not client:
        return {"error": "Elasticsearch indisponível", "suggestions": []}

    q = q.strip()
    if not q:
        return {"suggestions": []}

    lower_q = q.lower()

    try:
        resp = client.search(
            index=CONTRACTS_INDEX,
            body={
                "size": 0,
                "query": {
                    "bool": {
                        "should": [
                            {"match_phrase_prefix": {"objectoContrato": q}},
                            {"match_phrase_prefix": {"descContrato": q}},
                            {
                                "bool": {
                                    "should": [
                                        {
                                            "nested": {
                                                "path": "adjudicantes.parsed",
                                                "query": {"match_phrase_prefix": {"adjudicantes.parsed.nome": q}},
                                            }
                                        },
                                        {
                                            "nested": {
                                                "path": "adjudicatarios.parsed",
                                                "query": {"match_phrase_prefix": {"adjudicatarios.parsed.nome": q}},
                                            }
                                        },
                                    ],
                                    "minimum_should_match": 1,
                                }
                            },
                        ],
                        "minimum_should_match": 1,
                    }
                },
                "aggs": {
                    "adjudicantes": {
                        "nested": {"path": "adjudicantes.parsed"},
                        "aggs": {
                            "names": {
                                "terms": {
                                    "field": "adjudicantes.parsed.nome.keyword",
                                    "size": size,
                                    "include": f".*{lower_q}.*",
                                    "order": {"_count": "desc"},
                                }
                            }
                        }
                    },
                    "adjudicatarios": {
                        "nested": {"path": "adjudicatarios.parsed"},
                        "aggs": {
                            "names": {
                                "terms": {
                                    "field": "adjudicatarios.parsed.nome.keyword",
                                    "size": size,
                                    "include": f".*{lower_q}.*",
                                    "order": {"_count": "desc"},
                                }
                            }
                        }
                    },
                    "cpv_codes": {
                        "nested": {"path": "cpv"},
                        "aggs": {
                            "codes": {
                                "terms": {
                                    "field": "cpv.code",
                                    "size": 5,
                                    "include": f"{lower_q}.*",
                                    "order": {"_count": "desc"},
                                }
                            }
                        }
                    },
                },
            },
        )

        suggestions = []
        seen = set()
        for agg_key in ("adjudicantes", "adjudicatarios"):
            for bucket in resp["aggregations"][agg_key]["names"]["buckets"]:
                text = bucket["key"]
                if text and text not in seen:
                    seen.add(text)
                    suggestions.append({"text": text, "type": "entity", "count": bucket["doc_count"]})
        for bucket in resp["aggregations"]["cpv_codes"]["codes"]["buckets"]:
            text = bucket["key"]
            if text and text not in seen:
                seen.add(text)
                suggestions.append({"text": text, "type": "cpv", "count": bucket["doc_count"]})

        return {"suggestions": suggestions[:size]}
    except Exception as e:
        return {"error": str(e), "suggestions": []}


def contracts_status(es: Optional[Elasticsearch] = None) -> Dict[str, Any]:
    """Devolve contagem total de contratos indexados e anos conhecidos."""
    client = es or get_es_client()
    if not client:
        return {"error": "Elasticsearch indisponível", "total": 0, "years": []}

    ensure_indices(client)
    try:
        total = client.count(index=CONTRACTS_INDEX).get("count", 0)
        resp = client.search(
            index=CONTRACTS_INDEX,
            body={
                "size": 0,
                "aggs": {"years": {"terms": {"field": "Ano", "size": 50, "order": {"_key": "desc"}}}},
            },
        )
        years = [int(bucket["key"]) for bucket in resp["aggregations"]["years"]["buckets"]]
        return {"total": total, "years": years}
    except Exception as e:
        return {"error": str(e), "total": 0, "years": []}


def contract_years_available() -> List[int]:
    """Anos de contratos com JSONL normalizado disponível."""
    years = []
    if not (ROOT / "data" / "processed" / "contratos").exists():
        return years
    for path in sorted((ROOT / "data" / "processed" / "contratos").glob("contratos_*.jsonl")):
        m = re.search(r"(\d{4})", path.stem)
        if m:
            years.append(int(m.group(1)))
    return sorted(years)


def _build_contract_query(
    q: Optional[str] = None,
    year: Optional[int] = None,
    entity: Optional[str] = None,
    nif: Optional[str] = None,
    counterparty_nif: Optional[str] = None,
    region: Optional[str] = None,
    cpv_code: Optional[str] = None,
    min_price: Optional[float] = None,
    max_price: Optional[float] = None,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
) -> Dict[str, Any]:
    must: List[Dict[str, Any]] = []
    filters: List[Dict[str, Any]] = []

    if q:
        must.append({
            "multi_match": {
                "query": q,
                "fields": [
                    "objectoContrato^3",
                    "descContrato^2",
                    "search_text",
                    "adjudicantes.parsed.nome",
                    "adjudicatarios.parsed.nome",
                    "cpv.description",
                    "localExecucao",
                ],
                "type": "best_fields",
            }
        })

    if year:
        filters.append({"term": {"Ano": year}})
    if entity:
        filters.append({
            "bool": {
                "should": [
                    {
                        "nested": {
                            "path": "adjudicantes.parsed",
                            "query": {"match": {"adjudicantes.parsed.nome": entity}},
                        }
                    },
                    {
                        "nested": {
                            "path": "adjudicatarios.parsed",
                            "query": {"match": {"adjudicatarios.parsed.nome": entity}},
                        }
                    },
                ],
                "minimum_should_match": 1,
            }
        })
    if nif and not counterparty_nif:
        filters.append({
            "bool": {
                "should": [
                    {
                        "nested": {
                            "path": "adjudicantes.parsed",
                            "query": {"term": {"adjudicantes.parsed.nif": nif}},
                        }
                    },
                    {
                        "nested": {
                            "path": "adjudicatarios.parsed",
                            "query": {"term": {"adjudicatarios.parsed.nif": nif}},
                        }
                    },
                ],
                "minimum_should_match": 1,
            }
        })
    elif nif and counterparty_nif:
        filters.append({
            "bool": {
                "must": [
                    {
                        "nested": {
                            "path": "adjudicantes.parsed",
                            "query": {"term": {"adjudicantes.parsed.nif": nif}},
                        }
                    },
                    {
                        "nested": {
                            "path": "adjudicatarios.parsed",
                            "query": {"term": {"adjudicatarios.parsed.nif": counterparty_nif}},
                        }
                    },
                ]
            }
        })
    if region:
        filters.append(_region_filter(region))
    if cpv_code:
        filters.append({
            "nested": {
                "path": "cpv",
                "query": {"wildcard": {"cpv.code": f"{cpv_code}*"}},
            }
        })

    price_range = {}
    if min_price is not None:
        price_range["gte"] = min_price
    if max_price is not None:
        price_range["lte"] = max_price
    if price_range:
        filters.append({
            "bool": {
                "should": [
                    {"range": {"precoContratual": price_range}},
                    {"range": {"PrecoTotalEfetivo": price_range}},
                ],
                "minimum_should_match": 1,
            }
        })

    date_range = {}
    if start_date:
        date_range["gte"] = start_date
    if end_date:
        date_range["lte"] = end_date
    if date_range:
        filters.append({
            "bool": {
                "should": [
                    {"range": {"dataPublicacao": date_range}},
                    {"range": {"dataCelebracaoContrato": date_range}},
                ],
                "minimum_should_match": 1,
            }
        })

    if not must and not filters:
        return {"match_all": {}}

    query: Dict[str, Any] = {"bool": {}}
    if must:
        query["bool"]["must"] = must
    if filters:
        query["bool"]["filter"] = filters
    return query


def get_contract_analytics(
    q: Optional[str] = None,
    year: Optional[int] = None,
    entity: Optional[str] = None,
    nif: Optional[str] = None,
    cpv_code: Optional[str] = None,
    min_price: Optional[float] = None,
    max_price: Optional[float] = None,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    top_entities: int = 8,
    top_cpv: int = 8,
    value_buckets: int = 7,
    es: Optional[Elasticsearch] = None,
) -> Dict[str, Any]:
    """Devolve agregações analíticas para o dashboard de contratos."""
    client = es or get_es_client()
    if not client:
        return {"error": "Elasticsearch indisponível"}

    base_query = _build_contract_query(q, year, entity, nif, cpv_code, min_price, max_price, start_date, end_date)

    try:
        resp = client.search(
            index=CONTRACTS_INDEX,
            body={
                "size": 0,
                "track_total_hits": True,
                "query": base_query,
                "aggs": {
                    "total_value": {"sum": {"field": "precoContratual"}},
                    "avg_value": {"avg": {"field": "precoContratual"}},
                    "max_value": {"max": {"field": "precoContratual"}},
                    "by_year": {
                        "terms": {"field": "Ano", "size": 50, "order": {"_key": "desc"}}
                    },
                    "by_month": {
                        "date_histogram": {
                            "field": "dataPublicacao",
                            "calendar_interval": "month",
                            "format": "yyyy-MM",
                            "min_doc_count": 1,
                        }
                    },
                    "value_distribution": {
                        "histogram": {
                            "field": "precoContratual",
                            "interval": 50000,
                            "min_doc_count": 1,
                        }
                    },
                    "top_adjudicantes": {
                        "nested": {"path": "adjudicantes"},
                        "aggs": {
                            "names": {
                                "terms": {
                                    "field": "adjudicantes.raw",
                                    "size": top_entities,
                                    "order": {"total_value": "desc"},
                                },
                                "aggs": {
                                    "total_value": {
                                        "reverse_nested": {},
                                        "aggs": {"value": {"sum": {"field": "precoContratual"}}},
                                    }
                                },
                            }
                        },
                    },
                    "top_adjudicatarios": {
                        "nested": {"path": "adjudicatarios"},
                        "aggs": {
                            "names": {
                                "terms": {
                                    "field": "adjudicatarios.raw",
                                    "size": top_entities,
                                    "order": {"total_value": "desc"},
                                },
                                "aggs": {
                                    "total_value": {
                                        "reverse_nested": {},
                                        "aggs": {"value": {"sum": {"field": "precoContratual"}}},
                                    }
                                },
                            }
                        },
                    },
                    "top_cpv": {
                        "nested": {"path": "cpv"},
                        "aggs": {
                            "codes": {
                                "terms": {
                                    "field": "cpv.code",
                                    "size": top_cpv,
                                    "order": {"_count": "desc"},
                                },
                                "aggs": {
                                    "description": {
                                        "terms": {"field": "cpv.description.keyword", "size": 1}
                                    },
                                    "total_value": {
                                        "reverse_nested": {},
                                        "aggs": {"value": {"sum": {"field": "precoContratual"}}},
                                    },
                                },
                            }
                        },
                    },
                    "procedure_types": {
                        "terms": {"field": "tipoprocedimento.keyword", "size": 20, "missing": "N/A"}
                    },
                    "contract_types": {
                        "terms": {"field": "tipoContrato.keyword", "size": 20, "missing": "N/A"}
                    },
                },
            },
        )

        aggs = resp["aggregations"]

        def fmt_money(v):
            return round(v, 2) if v is not None else None

        entity_rows: List[Dict[str, Any]] = []
        seen_entities: set = set()
        for agg_key in ("top_adjudicantes", "top_adjudicatarios"):
            for b in aggs.get(agg_key, {}).get("names", {}).get("buckets", []):
                key = b["key"]
                if not key or key in seen_entities:
                    continue
                seen_entities.add(key)
                total_value_obj = b.get("total_value", {})
                value = total_value_obj.get("value", {}).get("value") if isinstance(total_value_obj.get("value"), dict) else total_value_obj.get("value")
                entity_rows.append({
                    "key": key,
                    "count": b["doc_count"],
                    "total_value": fmt_money(value),
                    "description": "",
                })
        entity_rows.sort(key=lambda x: (x.get("total_value") or 0, x.get("count") or 0), reverse=True)
        entity_rows = entity_rows[:top_entities]

        cpv_rows = []
        for b in aggs.get("top_cpv", {}).get("codes", {}).get("buckets", []):
            desc_buckets = b.get("description", {}).get("buckets", [])
            desc = desc_buckets[0].get("key", "") if desc_buckets else ""
            total_value_obj = b.get("total_value", {})
            value = total_value_obj.get("value", {}).get("value") if isinstance(total_value_obj.get("value"), dict) else total_value_obj.get("value")
            cpv_rows.append({
                "key": b["key"],
                "count": b["doc_count"],
                "total_value": fmt_money(value),
                "description": desc,
            })

        return {
            "total_contracts": resp["hits"]["total"]["value"],
            "total_value": fmt_money(aggs["total_value"].get("value")),
            "avg_value": fmt_money(aggs["avg_value"].get("value")),
            "max_value": fmt_money(aggs["max_value"].get("value")),
            "by_year": [{"key": str(b["key"]), "count": b["doc_count"]} for b in aggs["by_year"]["buckets"]],
            "by_month": [{"key": b["key_as_string"], "count": b["doc_count"]} for b in aggs["by_month"]["buckets"]],
            "value_distribution": [{"key": f"{int(b['key'])} - {int(b['key']) + 50000}", "count": b["doc_count"]} for b in aggs["value_distribution"]["buckets"][:value_buckets]],
            "top_entities": entity_rows,
            "top_cpv": cpv_rows,
            "procedure_types": [{"key": b["key"], "count": b["doc_count"]} for b in aggs["procedure_types"]["buckets"]],
            "contract_types": [{"key": b["key"], "count": b["doc_count"]} for b in aggs["contract_types"]["buckets"]],
            "year": year,
        }
    except Exception as e:
        return {"error": str(e)}


# --- Diretório de empresas (entidades) ---

def _entity_lookup_by_nif_query(nif: str) -> Dict[str, Any]:
    """Devolve uma query nested que procura uma entidade por NIF em ambos os papéis."""
    return {
        "bool": {
            "should": [
                {"nested": {"path": "adjudicantes.parsed", "query": {"term": {"adjudicantes.parsed.nif": nif}}}},
                {"nested": {"path": "adjudicatarios.parsed", "query": {"term": {"adjudicatarios.parsed.nif": nif}}}},
            ],
            "minimum_should_match": 1,
        }
    }


def get_company_by_nif(
    nif: str,
    es: Optional[Elasticsearch] = None,
) -> Dict[str, Any]:
    """Devolve resumo de uma entidade específica pelo NIF.

    Faz uma pesquisa nested com agregações por papel, devolvendo a estrutura
    CompanySummary (nif, name, total_value, adjudicante/adjudicatario, etc.).
    """
    client = es or get_es_client()
    if not client:
        return {"error": "Elasticsearch indisponível"}

    ensure_indices(client)

    try:
        resp = client.search(
            index=CONTRACTS_INDEX,
            body={
                "size": 0,
                "query": _entity_lookup_by_nif_query(nif),
                "aggs": {
                    "adjudicantes": {
                        "nested": {"path": "adjudicantes.parsed"},
                        "aggs": {
                            "filtered": {
                                "filter": {"term": {"adjudicantes.parsed.nif": nif}},
                                "aggs": {
                                    "name": {"top_hits": {"size": 1, "_source": ["adjudicantes.parsed.nome"]}},
                                    "total_value": {
                                        "reverse_nested": {},
                                        "aggs": {"value": {"sum": {"field": "precoContratual"}}},
                                    },
                                    "years": {
                                        "reverse_nested": {},
                                        "aggs": {"stats": {"stats": {"field": "Ano"}}},
                                    },
                                    "count": {"reverse_nested": {}},
                                },
                            }
                        },
                    },
                    "adjudicatarios": {
                        "nested": {"path": "adjudicatarios.parsed"},
                        "aggs": {
                            "filtered": {
                                "filter": {"term": {"adjudicatarios.parsed.nif": nif}},
                                "aggs": {
                                    "name": {"top_hits": {"size": 1, "_source": ["adjudicatarios.parsed.nome"]}},
                                    "total_value": {
                                        "reverse_nested": {},
                                        "aggs": {"value": {"sum": {"field": "precoContratual"}}},
                                    },
                                    "years": {
                                        "reverse_nested": {},
                                        "aggs": {"stats": {"stats": {"field": "Ano"}}},
                                    },
                                    "count": {"reverse_nested": {}},
                                },
                            }
                        },
                    },
                },
            },
        )

        aggs = resp["aggregations"]

        def fmt_money(v):
            return round(v, 2) if v is not None else None

        def build_role_summary(agg_key: str) -> Optional[Dict[str, Any]]:
            bucket = aggs.get(agg_key, {}).get("filtered", {})
            doc_count = bucket.get("doc_count", 0)
            if not doc_count:
                return None
            name_hits = bucket.get("name", {}).get("hits", {}).get("hits", [])
            name_from_hit: Optional[str] = None
            if name_hits:
                src = name_hits[0].get("_source", {})
                if isinstance(src, dict):
                    name_from_hit = src.get("nome")
            total_value_obj = bucket.get("total_value", {})
            value = total_value_obj.get("value", {}).get("value") if isinstance(total_value_obj.get("value"), dict) else total_value_obj.get("value")
            years_stats = bucket.get("years", {}).get("stats", {})
            first_year = years_stats.get("min")
            last_year = years_stats.get("max")
            return {
                "contracts_count": doc_count,
                "total_value": fmt_money(value) or 0.0,
                "avg_value": fmt_money(value / doc_count) if value and doc_count else None,
                "first_year": int(first_year) if first_year is not None else None,
                "last_year": int(last_year) if last_year is not None else None,
                "name": name_from_hit,
            }

        adjudicante = build_role_summary("adjudicantes")
        adjudicatario = build_role_summary("adjudicatarios")
        contracts_total = (adjudicante["contracts_count"] if adjudicante else 0) + (adjudicatario["contracts_count"] if adjudicatario else 0)
        total_value = (adjudicante["total_value"] if adjudicante else 0.0) + (adjudicatario["total_value"] if adjudicatario else 0.0)

        # Escolhe o nome mais comum entre os papéis
        names: List[str] = []
        for key in ("adjudicantes", "adjudicatarios"):
            role_summary = adjudicante if key == "adjudicantes" else adjudicatario
            if role_summary and role_summary.get("name"):
                names.append(role_summary["name"])
        name = names[0] if names else nif

        return {
            "nif": nif,
            "name": name,
            "normalized_name": name,
            "contracts_total": contracts_total,
            "total_value": fmt_money(total_value) or 0.0,
            "adjudicante": adjudicante,
            "adjudicatario": adjudicatario,
        }
    except Exception as e:
        return {"error": str(e)}


def _company_role_filter(role: Optional[str]) -> Optional[List[Dict[str, Any]]]:
    """Devolve filtro de caminho nested conforme o papel pretendido."""
    if role == "adjudicante":
        return [{"nested": {"path": "adjudicantes.parsed", "query": {"exists": {"field": "adjudicantes.parsed.nif"}}}}]
    if role == "adjudicatario":
        return [{"nested": {"path": "adjudicatarios.parsed", "query": {"exists": {"field": "adjudicatarios.parsed.nif"}}}}]
    return None


def _company_name_query(q: Optional[str]) -> Optional[Dict[str, Any]]:
    """Query de texto para nome ou NIF de empresa em qualquer um dos papéis."""
    if not q:
        return None
    q_clean = q.strip()
    if not q_clean:
        return None
    should_clauses: List[Dict[str, Any]] = []
    for role_path in ("adjudicantes", "adjudicatarios"):
        should_clauses.append(
            {
                "nested": {
                    "path": f"{role_path}.parsed",
                    "query": {"match": {f"{role_path}.parsed.nome": {"query": q_clean, "operator": "and"}}},
                }
            }
        )
        should_clauses.append(
            {
                "nested": {
                    "path": f"{role_path}.parsed",
                    "query": {"term": {f"{role_path}.parsed.nif": q_clean}},
                }
            }
        )
    return {
        "bool": {
            "should": should_clauses,
            "minimum_should_match": 1,
        }
    }


def search_companies(
    q: Optional[str] = None,
    role: Optional[str] = "all",
    region: Optional[str] = None,
    min_contracts: int = 1,
    min_value: Optional[float] = None,
    max_value: Optional[float] = None,
    year: Optional[int] = None,
    size: int = 20,
    from_: int = 0,
    es: Optional[Elasticsearch] = None,
) -> Dict[str, Any]:
    """Pesquisa entidades únicas derivadas dos contratos indexados.

    Utiliza duas agregações nested por NIF (adjudicantes/adjudicatarios) e depois
    combina os resultados em memória para devolver uma lista paginada de empresas.
    """
    client = es or get_es_client()
    if not client:
        return {"error": "Elasticsearch indisponível", "total": 0, "items": []}

    ensure_indices(client)

    base_filters: List[Dict[str, Any]] = []
    if year:
        base_filters.append({"term": {"Ano": year}})
    if region:
        base_filters.append(_region_filter(region))
    role_filter = _company_role_filter(role)
    if role_filter:
        base_filters.extend(role_filter)

    name_query = _company_name_query(q)

    base_query: Dict[str, Any] = {"bool": {}}
    if base_filters:
        base_query["bool"]["filter"] = base_filters
    if name_query:
        base_query["bool"]["must"] = name_query
    if not base_query["bool"]:
        base_query = {"match_all": {}}

    try:
        resp = client.search(
            index=CONTRACTS_INDEX,
            body={
                "size": 0,
                "query": base_query,
                "aggs": {
                    "adjudicantes": {
                        "nested": {"path": "adjudicantes.parsed"},
                        "aggs": {
                            "by_nif": {
                                "terms": {
                                    "field": "adjudicantes.parsed.nif",
                                    "size": 2000,
                                    "order": {"total_value": "desc"},
                                },
                                "aggs": {
                                    "name": {
                                        "top_hits": {"size": 1, "_source": ["adjudicantes.parsed.nome"]}
                                    },
                                    "total_value": {
                                        "reverse_nested": {},
                                        "aggs": {"value": {"sum": {"field": "precoContratual"}}},
                                    },
                                    "years": {
                                        "reverse_nested": {},
                                        "aggs": {"stats": {"stats": {"field": "Ano"}}},
                                    },
                                },
                            }
                        },
                    },
                    "adjudicatarios": {
                        "nested": {"path": "adjudicatarios.parsed"},
                        "aggs": {
                            "by_nif": {
                                "terms": {
                                    "field": "adjudicatarios.parsed.nif",
                                    "size": 2000,
                                    "order": {"total_value": "desc"},
                                },
                                "aggs": {
                                    "name": {
                                        "top_hits": {"size": 1, "_source": ["adjudicatarios.parsed.nome"]}
                                    },
                                    "total_value": {
                                        "reverse_nested": {},
                                        "aggs": {"value": {"sum": {"field": "precoContratual"}}},
                                    },
                                    "years": {
                                        "reverse_nested": {},
                                        "aggs": {"stats": {"stats": {"field": "Ano"}}},
                                    },
                                },
                            }
                        },
                    },
                },
            },
        )

        companies: Dict[str, Dict[str, Any]] = {}

        def fmt_money(v):
            return round(v, 2) if v is not None else None

        for agg_key in ("adjudicantes", "adjudicatarios"):
            role_name = "adjudicante" if agg_key == "adjudicantes" else "adjudicatario"
            for b in resp["aggregations"][agg_key]["by_nif"]["buckets"]:
                nif = b["key"]
                name_hits = b.get("name", {}).get("hits", {}).get("hits", [])
                name = nif or "Nome desconhecido"
                if name_hits:
                    src = name_hits[0].get("_source", {})
                    if isinstance(src, dict):
                        name = src.get("nome") or name
                total_value_obj = b.get("total_value", {})
                value = total_value_obj.get("value", {}).get("value") if isinstance(total_value_obj.get("value"), dict) else total_value_obj.get("value")
                total_value = value or 0.0
                years_stats = b.get("years", {}).get("stats", {})
                first_year = years_stats.get("min")
                last_year = years_stats.get("max")
                count = b["doc_count"]

                if count < min_contracts:
                    continue
                if min_value is not None and total_value < min_value:
                    continue
                if max_value is not None and total_value > max_value:
                    continue

                if nif and nif not in companies:
                    companies[nif] = {
                        "nif": nif,
                        "name": name,
                        "normalized_name": name,
                        "contracts_total": 0,
                        "total_value": 0.0,
                        "adjudicante": None,
                        "adjudicatario": None,
                    }
                if not nif:
                    key = f"__no_nif__{name.lower().strip()}"
                    if key not in companies:
                        companies[key] = {
                            "nif": None,
                            "name": name,
                            "normalized_name": name,
                            "contracts_total": 0,
                            "total_value": 0.0,
                            "adjudicante": None,
                            "adjudicatario": None,
                        }

                entry = companies[nif if nif else key]
                role_summary = {
                    "contracts_count": count,
                    "total_value": fmt_money(total_value) or 0.0,
                    "avg_value": fmt_money(total_value / count) if count else None,
                    "first_year": int(first_year) if first_year is not None else None,
                    "last_year": int(last_year) if last_year is not None else None,
                }
                entry[role_name] = role_summary
                entry["contracts_total"] = (entry["contracts_total"] or 0) + count
                entry["total_value"] = (entry["total_value"] or 0.0) + total_value

        items = sorted(companies.values(), key=lambda x: (x.get("total_value") or 0, x.get("contracts_total") or 0), reverse=True)
        total = len(items)
        page = items[from_: from_ + size]
        for it in page:
            it["total_value"] = fmt_money(it["total_value"]) or 0.0

        return {
            "query": q,
            "total": total,
            "items": page,
            "from": from_,
            "size": size,
        }
    except Exception as e:
        return {"query": q, "total": 0, "items": [], "error": str(e)}


def get_company_contracts(
    nif: Optional[str] = None,
    name: Optional[str] = None,
    role: Optional[str] = "all",
    size: int = 20,
    from_: int = 0,
    es: Optional[Elasticsearch] = None,
) -> Dict[str, Any]:
    """Devolve contratos onde a entidade aparece como adjudicante/adjudicatário."""
    client = es or get_es_client()
    if not client:
        return {"error": "Elasticsearch indisponível", "total": 0, "items": []}

    should: List[Dict[str, Any]] = []
    if nif:
        if role in ("all", "adjudicante", None):
            should.append({
                "nested": {
                    "path": "adjudicantes.parsed",
                    "query": {"term": {"adjudicantes.parsed.nif": nif}},
                }
            })
        if role in ("all", "adjudicatario", None):
            should.append({
                "nested": {
                    "path": "adjudicatarios.parsed",
                    "query": {"term": {"adjudicatarios.parsed.nif": nif}},
                }
            })
    if name:
        if role in ("all", "adjudicante", None):
            should.append({
                "nested": {
                    "path": "adjudicantes.parsed",
                    "query": {"match": {"adjudicantes.parsed.nome": name}},
                }
            })
        if role in ("all", "adjudicatario", None):
            should.append({
                "nested": {
                    "path": "adjudicatarios.parsed",
                    "query": {"match": {"adjudicatarios.parsed.nome": name}},
                }
            })

    if not should:
        return {"error": "É necessário indicar NIF ou nome", "total": 0, "items": []}

    query = {
        "bool": {
            "should": should,
            "minimum_should_match": 1,
        }
    }

    try:
        resp = client.search(
            index=CONTRACTS_INDEX,
            body={
                "size": size,
                "from": from_,
                "query": query,
                "sort": [{"dataPublicacao": {"order": "desc"}}, "_score"],
                "track_total_hits": True,
            },
        )
        items = []
        for hit in resp["hits"]["hits"]:
            src = hit["_source"]
            src["doc_id"] = hit["_id"]
            src["score"] = hit.get("_score")
            items.append(src)

        return {
            "nif": nif,
            "name": name,
            "role": role,
            "total": resp["hits"]["total"]["value"],
            "items": items,
            "from": from_,
            "size": size,
        }
    except Exception as e:
        return {"error": str(e), "total": 0, "items": []}


def get_company_analytics(
    nif: Optional[str] = None,
    name: Optional[str] = None,
    role: Optional[str] = "all",
    year: Optional[int] = None,
    es: Optional[Elasticsearch] = None,
) -> Dict[str, Any]:
    """Devolve analytics para uma empresa específica."""
    client = es or get_es_client()
    if not client:
        return {"error": "Elasticsearch indisponível"}

    should: List[Dict[str, Any]] = []
    if nif:
        if role in ("all", "adjudicante", None):
            should.append({
                "nested": {
                    "path": "adjudicantes.parsed",
                    "query": {"term": {"adjudicantes.parsed.nif": nif}},
                }
            })
        if role in ("all", "adjudicatario", None):
            should.append({
                "nested": {
                    "path": "adjudicatarios.parsed",
                    "query": {"term": {"adjudicatarios.parsed.nif": nif}},
                }
            })
    if name:
        if role in ("all", "adjudicante", None):
            should.append({
                "nested": {
                    "path": "adjudicantes.parsed",
                    "query": {"match": {"adjudicantes.parsed.nome": name}},
                }
            })
        if role in ("all", "adjudicatario", None):
            should.append({
                "nested": {
                    "path": "adjudicatarios.parsed",
                    "query": {"match": {"adjudicatarios.parsed.nome": name}},
                }
            })

    if not should:
        return {"error": "É necessário indicar NIF ou nome"}

    filters: List[Dict[str, Any]] = []
    if year:
        filters.append({"term": {"Ano": year}})

    query = {"bool": {"should": should, "minimum_should_match": 1}}
    if filters:
        query["bool"]["filter"] = filters

    try:
        resp = client.search(
            index=CONTRACTS_INDEX,
            body={
                "size": 0,
                "query": query,
                "aggs": {
                    "total_value": {"sum": {"field": "precoContratual"}},
                    "avg_value": {"avg": {"field": "precoContratual"}},
                    "max_value": {"max": {"field": "precoContratual"}},
                    "by_year": {"terms": {"field": "Ano", "size": 50, "order": {"_key": "desc"}}},
                    "by_month": {
                        "date_histogram": {
                            "field": "dataPublicacao",
                            "calendar_interval": "month",
                            "format": "yyyy-MM",
                            "min_doc_count": 1,
                        }
                    },
                    "by_cpv": {
                        "nested": {"path": "cpv"},
                        "aggs": {
                            "codes": {
                                "terms": {"field": "cpv.code", "size": 10, "order": {"total_value": "desc"}},
                                "aggs": {
                                    "description": {"terms": {"field": "cpv.description.keyword", "size": 1}},
                                    "total_value": {
                                        "reverse_nested": {},
                                        "aggs": {"value": {"sum": {"field": "precoContratual"}}},
                                    },
                                },
                            }
                        },
                    },
                    "top_partners": {
                        "nested": {"path": "adjudicatarios.parsed"},
                        "aggs": {
                            "by_nif": {
                                "terms": {"field": "adjudicatarios.parsed.nif", "size": 8, "order": {"total_value": "desc"}},
                                "aggs": {
                                    "name": {"top_hits": {"size": 1, "_source": ["adjudicatarios.parsed.nome"]}},
                                    "total_value": {
                                        "reverse_nested": {},
                                        "aggs": {"value": {"sum": {"field": "precoContratual"}}},
                                    },
                                },
                            }
                        },
                    },
                    "procedure_types": {
                        "terms": {"field": "tipoprocedimento.keyword", "size": 20, "missing": "N/A"}
                    },
                    "contract_types": {
                        "terms": {"field": "tipoContrato.keyword", "size": 20, "missing": "N/A"}
                    },
                    "by_value_range": {
                        "histogram": {"field": "precoContratual", "interval": 25000, "min_doc_count": 1}
                    },
                },
            },
        )

        aggs = resp["aggregations"]

        def fmt_money(v):
            return round(v, 2) if v is not None else None

        def extract_value(total_value_obj):
            if isinstance(total_value_obj.get("value"), dict):
                return total_value_obj["value"].get("value")
            return total_value_obj.get("value")

        cpv_rows = []
        for b in aggs.get("by_cpv", {}).get("codes", {}).get("buckets", []):
            desc_buckets = b.get("description", {}).get("buckets", [])
            cpv_rows.append({
                "key": b["key"],
                "count": b["doc_count"],
                "total_value": fmt_money(extract_value(b.get("total_value", {}))),
                "description": desc_buckets[0].get("key", "") if desc_buckets else "",
            })

        partner_rows = []
        for b in aggs.get("top_partners", {}).get("by_nif", {}).get("buckets", []):
            if b["key"] == nif:
                continue
            partner_name_hits = b.get("name", {}).get("hits", {}).get("hits", [])
            partner_name = ""
            if partner_name_hits:
                partner_src = partner_name_hits[0].get("_source", {})
                if isinstance(partner_src, dict):
                    partner_name = partner_src.get("nome", "")
            partner_rows.append({
                "key": b["key"],
                "count": b["doc_count"],
                "total_value": fmt_money(extract_value(b.get("total_value", {}))),
                "description": partner_name,
            })

        company_summary = None
        if nif:
            company_summary = get_company_by_nif(nif, es=client)
            if "error" in company_summary:
                company_summary = None

        return {
            "company": company_summary,
            "total_contracts": resp["hits"]["total"]["value"],
            "total_value": fmt_money(aggs["total_value"].get("value")),
            "avg_value": fmt_money(aggs["avg_value"].get("value")),
            "max_value": fmt_money(aggs["max_value"].get("value")),
            "by_year": [{"key": str(b["key"]), "count": b["doc_count"]} for b in aggs["by_year"]["buckets"]],
            "by_month": [{"key": b["key_as_string"], "count": b["doc_count"]} for b in aggs["by_month"]["buckets"]],
            "by_cpv": cpv_rows,
            "top_partners": partner_rows,
            "by_procedure_type": [{"key": b["key"], "count": b["doc_count"]} for b in aggs["procedure_types"]["buckets"]],
            "by_contract_type": [{"key": b["key"], "count": b["doc_count"]} for b in aggs["contract_types"]["buckets"]],
            "by_value_range": [{"key": f"{int(b['key'])} - {int(b['key']) + 25000}", "count": b["doc_count"]} for b in aggs["by_value_range"]["buckets"][:10]],
            "year": year,
        }
    except Exception as e:
        return {"error": str(e)}


def list_contract_years(es: Optional[Elasticsearch] = None) -> Dict[str, Any]:
    """Devolve anos disponíveis e total indexado por ano."""
    client = es or get_es_client()
    available = contract_years_available()
    if not client:
        return {"available": available, "indexed": []}
    try:
        resp = client.search(
            index=CONTRACTS_INDEX,
            body={
                "size": 0,
                "aggs": {
                    "by_year": {
                        "terms": {"field": "Ano", "size": 50, "order": {"_key": "desc"}},
                    }
                },
            },
        )
        indexed = [{"year": int(bucket["key"]), "count": bucket["doc_count"]} for bucket in resp["aggregations"]["by_year"]["buckets"]]
        return {"available": available, "indexed": indexed}
    except Exception as e:
        return {"available": available, "indexed": [], "error": str(e)}


def get_contract_by_id(idcontrato: str, es: Optional[Elasticsearch] = None) -> Dict[str, Any]:
    """Devolve um contrato pelo identificador publicado no portal."""
    client = es or get_es_client()
    if not client:
        return {"error": "Elasticsearch indisponível"}
    try:
        response = client.search(
            index=CONTRACTS_INDEX,
            body={"size": 1, "query": {"term": {"idcontrato": idcontrato}}},
        )
        hits = response.get("hits", {}).get("hits", [])
        if not hits:
            return {"error": "Contrato não encontrado", "status_code": 404}
        source = dict(hits[0].get("_source", {}))
        source["doc_id"] = hits[0].get("_id")
        return source
    except Exception as exc:
        return {"error": str(exc)}


def get_contract_regional_analytics(year: Optional[int] = None, size: int = 30, es: Optional[Elasticsearch] = None) -> Dict[str, Any]:
    """Agrega volume e valor contratual por NUTS."""
    client = es or get_es_client()
    if not client:
        return {"error": "Elasticsearch indisponível", "regions": []}
    query: Dict[str, Any] = {"match_all": {}}
    if year:
        query = {"term": {"Ano": year}}
    try:
        response = client.search(
            index=CONTRACTS_INDEX,
            body={
                "track_total_hits": True,
                "size": 0,
                "query": query,
                "aggs": {
                    "regions": {
                        "terms": {"field": "NUTs", "size": size, "missing": "Não especificado"},
                        "aggs": {"total_value": {"sum": {"field": "precoContratual"}}},
                    },
                    "total_value": {"sum": {"field": "precoContratual"}},
                },
            },
        )
        aggs = response.get("aggregations", {})
        return {
            "total_contracts": response.get("hits", {}).get("total", {}).get("value", 0),
            "total_value": aggs.get("total_value", {}).get("value"),
            "regions": [
                {"key": bucket["key"], "count": bucket["doc_count"], "total_value": bucket.get("total_value", {}).get("value")}
                for bucket in aggs.get("regions", {}).get("buckets", [])
            ],
        }
    except Exception as exc:
        return {"error": str(exc), "regions": []}


def _region_filter(region: Optional[str] = None) -> Dict[str, Any]:
    """Filtro de região. Aceita código curto (ex: PT11A) ou string completa NUTS.

    ES armazena NUTs como strings completas (ex: "PT11A - Área Metropolitana do Porto"),
    por isso usamos wildcard/prefixo quando a região fornecida não contém o separador.
    """
    if not region:
        return None
    if " - " in region:
        return {"term": {"NUTs": region}}
    return {"wildcard": {"NUTs": f"{region}*"}}


def _match_pair_query(nif: Optional[str] = None, counterparty_nif: Optional[str] = None) -> Optional[Dict[str, Any]]:
    """Returns nested must query for adjudicante/adjudicatario pair when both provided."""
    if nif and counterparty_nif:
        return {
            "bool": {
                "must": [
                    {
                        "nested": {
                            "path": "adjudicantes.parsed",
                            "query": {"term": {"adjudicantes.parsed.nif": nif}},
                        }
                    },
                    {
                        "nested": {
                            "path": "adjudicatarios.parsed",
                            "query": {"term": {"adjudicatarios.parsed.nif": counterparty_nif}},
                        }
                    },
                ]
            }
        }
    return None


def get_contract_relationships(
    limit: int = 1000,
    region: Optional[str] = None,
    nif: Optional[str] = None,
    counterparty_nif: Optional[str] = None,
    role: Optional[str] = "all",
    es: Optional[Elasticsearch] = None,
) -> Dict[str, Any]:
    """Constrói relações adjudicante -> adjudicatário a partir dos contratos recentes."""
    client = es or get_es_client()
    if not client:
        return {"error": "Elasticsearch indisponível", "relations": []}
    filters: List[Dict[str, Any]] = []
    if region:
        filters.append(_region_filter(region))
    pair_query = _match_pair_query(nif, counterparty_nif)
    if pair_query:
        filters.append(pair_query)
    elif nif:
        # Include any contract where this NIF appears (adjudicante or adjudicatario)
        filters.append({
            "bool": {
                "should": [
                    {"nested": {"path": "adjudicantes.parsed", "query": {"term": {"adjudicantes.parsed.nif": nif}}}},
                    {"nested": {"path": "adjudicatarios.parsed", "query": {"term": {"adjudicatarios.parsed.nif": nif}}}},
                ],
                "minimum_should_match": 1,
            }
        })
    query: Dict[str, Any] = {"bool": {"filter": filters}} if filters else {"match_all": {}}
    try:
        response = client.search(
            index=CONTRACTS_INDEX,
            body={
                "size": limit,
                "_source": ["adjudicantes.parsed", "adjudicatarios.parsed", "precoContratual", "Ano"],
                "query": query,
                "sort": [{"Ano": {"order": "desc", "unmapped_type": "integer"}}],
            },
        )
        pairs: Dict[str, Dict[str, Any]] = {}
        for hit in response.get("hits", {}).get("hits", []):
            source = hit.get("_source", {})
            buyers = source.get("adjudicantes", {}).get("parsed", [])
            suppliers = source.get("adjudicatarios", {}).get("parsed", [])
            value = source.get("precoContratual") or 0
            for buyer in buyers:
                for supplier in suppliers:
                    buyer_id = buyer.get("nif") or buyer.get("nome")
                    supplier_id = supplier.get("nif") or supplier.get("nome")
                    if not buyer_id or not supplier_id:
                        continue
                    # Apply role filter after the fact when only one NIF provided
                    if nif and not pair_query:
                        if role == "adjudicante" and buyer_id != nif:
                            continue
                        if role == "adjudicatario" and supplier_id != nif:
                            continue
                    key = f"{buyer_id}|{supplier_id}"
                    pair = pairs.setdefault(key, {
                        "source": buyer_id, "source_name": buyer.get("nome") or buyer_id,
                        "target": supplier_id, "target_name": supplier.get("nome") or supplier_id,
                        "count": 0, "total_value": 0.0,
                    })
                    pair["count"] += 1
                    pair["total_value"] += value
        relations = sorted(pairs.values(), key=lambda item: item["total_value"], reverse=True)[:100]
        for relation in relations:
            relation["total_value"] = round(relation["total_value"], 2)
        return {"relations": relations}
    except Exception as exc:
        return {"error": str(exc), "relations": []}


def get_contract_network(
    limit: int = 500,
    region: Optional[str] = None,
    nif: Optional[str] = None,
    role: Optional[str] = "all",
    es: Optional[Elasticsearch] = None,
) -> Dict[str, Any]:
    """Devolve nós e ligações para uma visualização de rede de entidades."""
    result = get_contract_relationships(limit=limit, region=region, nif=nif, role=role, es=es)
    if result.get("error"):
        return result
    nodes: Dict[str, Dict[str, Any]] = {}
    edges = []
    for relation in result.get("relations", []):
        for node_id, name, node_type in (
            (relation["source"], relation["source_name"], "adjudicante"),
            (relation["target"], relation["target_name"], "adjudicatario"),
        ):
            nodes.setdefault(node_id, {"id": node_id, "label": name, "type": node_type})
        edges.append({"source": relation["source"], "target": relation["target"], "count": relation["count"], "value": relation["total_value"]})
    return {"nodes": list(nodes.values()), "edges": edges}
