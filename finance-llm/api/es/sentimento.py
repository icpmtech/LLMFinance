"""Sentimento diário por ticker.

Módulo do pacote :mod:`api.es` — ver `api/elasticsearch_client.py`,
que continua a expor a API pública (os coletores/serviços importam de lá).
"""
import logging
from typing import Any, Dict, List, Optional

from elasticsearch import Elasticsearch
from api.es.core import get_es_client
from api.es.mappings import ensure_indices

logger = logging.getLogger(__name__)




# ---------------------------------------------------------------------------
# Sentimento diário de mercado — índice `finance_sentiment_daily`
# ---------------------------------------------------------------------------
SENTIMENT_DAILY_INDEX = "finance_sentiment_daily"




def index_sentiment_daily(rows: List[Dict[str, Any]], es: Optional[Elasticsearch] = None) -> Dict[str, Any]:
    """Grava/atualiza o sentimento diário por ticker (idempotente).

    O `_id` do documento é `ticker|data`, pelo que reconstruir o mesmo dia
    **atualiza** o documento em vez de o duplicar: reprocessar é seguro.
    """
    client = es or get_es_client()
    if not client:
        return {"error": "Elasticsearch indisponível", "indexed": 0}
    ensure_indices(client)
    bulk_body: List[Dict[str, Any]] = []
    total = 0
    for row in rows or []:
        ticker = str(row.get("ticker") or "").strip().upper()
        day = str(row.get("date") or "").strip()[:10]
        if not ticker or not day:
            continue
        document = {key: value for key, value in row.items() if key != "_id"}
        document["ticker"] = ticker
        document["date"] = day
        bulk_body.append({"index": {"_index": SENTIMENT_DAILY_INDEX, "_id": f"{ticker}|{day}"}})
        bulk_body.append(document)
        total += 1
    if not bulk_body:
        return {"indexed": 0, "errors": 0, "total": 0}
    try:
        response = client.bulk(body=bulk_body, refresh=True)
    except Exception as exc:  # pragma: no cover - depende do Elasticsearch
        return {"error": str(exc), "indexed": 0, "errors": total, "total": total}
    errors = sum(1 for item in response.get("items", []) if (item.get("index") or {}).get("error"))
    return {"indexed": total - errors, "errors": errors, "total": total}




def search_sentiment_daily(
    ticker: Optional[str] = None,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    size: int = 3000,
    es: Optional[Elasticsearch] = None,
) -> Dict[str, Any]:
    """Lê o sentimento diário guardado (por ticker e/ou intervalo de datas)."""
    client = es or get_es_client()
    if not client:
        return {"error": "Elasticsearch indisponível", "total": 0, "items": []}
    must: List[Dict[str, Any]] = []
    if ticker:
        must.append({"term": {"ticker": str(ticker).strip().upper()}})
    window: Dict[str, str] = {}
    if start_date:
        window["gte"] = str(start_date)[:10]
    if end_date:
        window["lte"] = str(end_date)[:10]
    query: Dict[str, Any] = {"bool": {"must": must or [{"match_all": {}}]}}
    if window:
        query["bool"]["filter"] = [{"range": {"date": window}}]
    try:
        response = client.search(
            index=SENTIMENT_DAILY_INDEX,
            body={
                "query": query,
                "size": max(1, min(int(size), 10000)),
                "sort": [{"date": {"order": "asc"}}, {"ticker": {"order": "asc"}}],
                "track_total_hits": True,
            },
        )
    except Exception as exc:
        return {"error": str(exc), "total": 0, "items": []}
    total = response.get("hits", {}).get("total", 0)
    total_value = total.get("value", 0) if isinstance(total, dict) else total
    return {
        "total": int(total_value or 0),
        "items": [hit.get("_source") or {} for hit in response.get("hits", {}).get("hits", [])],
    }




def list_news_tickers(es: Optional[Elasticsearch] = None) -> Dict[str, Any]:
    """Tickers com notícias indexadas em `finance_news` (com contagem)."""
    client = es or get_es_client()
    if not client:
        return {"error": "Elasticsearch indisponível", "total": 0, "items": []}
    try:
        response = client.search(
            index="finance_news",
            body={
                "size": 0,
                "track_total_hits": True,
                "aggs": {"tickers": {"terms": {"field": "ticker", "size": 500}}},
            },
        )
    except Exception as exc:
        return {"error": str(exc), "total": 0, "items": []}
    total = response.get("hits", {}).get("total", 0)
    total_value = total.get("value", 0) if isinstance(total, dict) else total
    items = [
        {"ticker": bucket.get("key"), "news": int(bucket.get("doc_count") or 0)}
        for bucket in response.get("aggregations", {}).get("tickers", {}).get("buckets", [])
    ]
    return {"total": int(total_value or 0), "items": items}




def list_sentiment_daily_tickers(es: Optional[Elasticsearch] = None) -> Dict[str, Any]:
    """Tickers com sentimento diário guardado (nº de dias, primeira e última data)."""
    client = es or get_es_client()
    if not client:
        return {"error": "Elasticsearch indisponível", "total": 0, "items": []}
    try:
        response = client.search(
            index=SENTIMENT_DAILY_INDEX,
            body={
                "size": 0,
                "track_total_hits": True,
                "aggs": {
                    "tickers": {
                        "terms": {"field": "ticker", "size": 500},
                        "aggs": {
                            "first": {"min": {"field": "date", "format": "yyyy-MM-dd"}},
                            "last": {"max": {"field": "date", "format": "yyyy-MM-dd"}},
                            "news": {"sum": {"field": "news_count"}},
                        },
                    }
                },
            },
        )
    except Exception as exc:
        return {"error": str(exc), "total": 0, "items": []}
    total = response.get("hits", {}).get("total", 0)
    total_value = total.get("value", 0) if isinstance(total, dict) else total
    items = [
        {
            "ticker": bucket.get("key"),
            "days": bucket.get("doc_count", 0),
            "first_date": (bucket.get("first") or {}).get("value_as_string"),
            "last_date": (bucket.get("last") or {}).get("value_as_string"),
            "news": int((bucket.get("news") or {}).get("value") or 0),
        }
        for bucket in response.get("aggregations", {}).get("tickers", {}).get("buckets", [])
    ]
    return {"total": int(total_value or 0), "items": items}




def delete_sentiment_daily(
    ticker: Optional[str] = None,
    dates: Optional[List[str]] = None,
    es: Optional[Elasticsearch] = None,
) -> Dict[str, Any]:
    """Apaga o sentimento diário (de um ticker, de dias concretos ou de todos).

    Com `dates`, apaga apenas esses dias (é o que permite limpar dias obsoletos da
    série sem tocar no resto).
    """
    client = es or get_es_client()
    if not client:
        return {"error": "Elasticsearch indisponível"}
    ensure_indices(client)
    must: List[Dict[str, Any]] = []
    if ticker:
        must.append({"term": {"ticker": str(ticker).strip().upper()}})
    if dates:
        must.append({"terms": {"date": [str(day)[:10] for day in dates if day]}})
    query: Dict[str, Any] = {"bool": {"must": must}} if must else {"match_all": {}}
    try:
        response = client.delete_by_query(index=SENTIMENT_DAILY_INDEX, body={"query": query}, refresh=True, conflicts="proceed")
        return {"ok": True, "deleted": response.get("deleted", 0)}
    except Exception as exc:
        return {"error": str(exc)}
