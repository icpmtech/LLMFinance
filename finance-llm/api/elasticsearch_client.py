"""Cliente Elasticsearch para ingestão e pesquisa de dados financeiros.

Índices utilizados:
- finance_prices: histórico de preços de ações (OHLCV) por ticker.
- finance_news: notícias/sociais de ações por ticker.

Ambos suportam pesquisa por ticker, data e texto.
"""
import os
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


def search_all_tickers(q: str, size: int = 50, es: Optional[Elasticsearch] = None) -> Dict[str, Any]:
    """Pesquisa notícias de todos os tickers por texto."""
    client = es or get_es_client()
    if not client:
        return {"error": "Elasticsearch indisponível", "items": []}

    query = {
        "multi_match": {
            "query": q,
            "fields": ["ticker^3", "title^2", "summary", "publisher"],
            "type": "best_fields",
        }
    }

    try:
        resp = client.search(
            index="finance_news",
            body={
                "query": query,
                "sort": [{"published": {"order": "desc"}}, "_score"],
                "size": size,
                "track_scores": True,
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
                            {"match_phrase_prefix": {"publisher": q}},
                            {"match_phrase_prefix": {"topics": q}},
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
        with open(jsonl_path, "r", encoding="utf-8") as fh:
            for line in fh:
                if max_records and total >= max_records:
                    break
                try:
                    doc = json.loads(line)
                except Exception:
                    continue
                chunk.append(doc)
                total += 1
                if len(chunk) >= chunk_size:
                    res = index_contracts(chunk, client)
                    success_total += res.get("indexed_count", 0)
                    error_total += res.get("errors", 0) or (0 if not res.get("error") else len(chunk))
                    chunk = []
        if chunk:
            res = index_contracts(chunk, client)
            success_total += res.get("indexed_count", 0)
            error_total += res.get("errors", 0) or (0 if not res.get("error") else len(chunk))
        return {"indexed_count": success_total, "total": total, "errors": error_total}
    except Exception as e:
        return {"error": str(e), "indexed_count": success_total, "total": total}


def search_contracts(
    q: Optional[str] = None,
    year: Optional[int] = None,
    entity: Optional[str] = None,
    nif: Optional[str] = None,
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

    query: Dict[str, Any] = {"bool": {"must": [], "filter": []}}
    must = query["bool"]["must"]
    filters = query["bool"]["filter"]

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
    else:
        must.append({"match_all": {}})

    if year:
        filters.append({"term": {"Ano": year}})
    if entity:
        filters.append({
            "nested": {
                "path": "entities",
                "query": {
                    "match": {"entities.name": entity},
                },
            }
        })
    if nif:
        filters.append({
            "nested": {
                "path": "entities",
                "query": {
                    "term": {"entities.nif": nif},
                },
            }
        })
    if cpv_code:
        filters.append({
            "nested": {
                "path": "cpv",
                "query": {
                    "wildcard": {"cpv.code": f"{cpv_code}*"},
                },
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

    try:
        resp = client.search(
            index=CONTRACTS_INDEX,
            body={
                "query": query,
                "sort": [{"dataPublicacao": {"order": "desc"}}, "_score"],
                "from": from_,
                "size": size,
                "track_scores": True,
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
                                "nested": {
                                    "path": "entities",
                                    "query": {"match_phrase_prefix": {"entities.name": q}},
                                }
                            },
                        ],
                        "minimum_should_match": 1,
                    }
                },
                "aggs": {
                    "entities": {
                        "nested": {"path": "entities"},
                        "aggs": {
                            "names": {
                                "terms": {
                                    "field": "entities.name.keyword",
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
        for bucket in resp["aggregations"]["entities"]["names"]["buckets"]:
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
        return {"error": str(e), "available": available, "indexed": []}
