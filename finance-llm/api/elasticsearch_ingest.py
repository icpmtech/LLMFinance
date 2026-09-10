"""Funções de ingestão de preços e notícias para Elasticsearch usando yfinance."""
from concurrent.futures import ThreadPoolExecutor
from typing import Dict, List, Optional

import pandas as pd
from fastapi import HTTPException

from api.elasticsearch_client import (
    get_es_client,
    index_news_items,
    index_price_points,
)
from api.models import (
    ElasticIngestNewsResponse,
    ElasticIngestPricesResponse,
    ElasticSearchNewsResponse,
    ElasticSearchPricesResponse,
    ElasticStatus,
)
from api.tools import get_news, get_stock_history

_executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="es_ingest_")


def _run_in_thread(fn, *args):
    """Executa função bloqueante num thread separado."""
    import asyncio
    loop = asyncio.get_running_loop()
    return loop.run_in_executor(_executor, fn, *args)


async def ingest_ticker_prices(
    ticker: str,
    period: str = "1y",
    interval: str = "1d",
) -> ElasticIngestPricesResponse:
    """Obtém e indexa histórico de preços de um ticker."""
    history = await _run_in_thread(get_stock_history, ticker, period, interval)
    if isinstance(history, dict) and "error" in history:
        raise HTTPException(status_code=404, detail=history["error"])

    if isinstance(history, pd.DataFrame):
        points = history.replace({pd.NA: None}).to_dict(orient="records")
    elif isinstance(history, dict):
        points = history.get("data", [])
    else:
        points = list(history)
    if not points:
        return ElasticIngestPricesResponse(ticker=ticker, indexed_count=0, total_points=0)

    es = get_es_client()
    result = index_price_points(ticker, points, period=period, es=es)
    return ElasticIngestPricesResponse(
        ticker=result["ticker"],
        indexed_count=result.get("indexed_count", 0),
        total_points=result.get("total_points", 0),
        period=period,
        interval=interval,
        message="Preços indexados com sucesso" if not result.get("error") else None,
        error=result.get("error"),
    )


async def ingest_ticker_news(
    ticker: str,
    backend: str = "gpt2",
    auto_analyze: bool = True,
) -> ElasticIngestNewsResponse:
    """Obtém e indexa notícias de um ticker.

    Se auto_analyze=True, as notícias são imediatamente analisadas com NLP
    (sentimento, tradução PT, entidades, tópicos) e o grafo de entidades é
    reconstruído e persistido.
    """
    news = await _run_in_thread(get_news, ticker)
    if isinstance(news, dict) and "error" in news:
        raise HTTPException(status_code=404, detail=news["error"])

    items = news.get("news", []) if isinstance(news, dict) else list(news)
    if not items:
        return ElasticIngestNewsResponse(ticker=ticker, indexed_count=0, total_items=0)

    es = get_es_client()
    result = index_news_items(ticker, items, es=es)

    analyzed_count = 0
    graph_error = None
    if auto_analyze and result.get("indexed_count", 0) and not result.get("error"):
        try:
            from api.elasticsearch_client import (
                fetch_news_for_analysis,
                index_analyzed_news_items,
                save_news_graph,
            )
            from api.news_nlp import analyze_news_batch, build_news_entity_graph

            batch = [
                {"title": it.get("title", ""), "summary": it.get("summary", ""), "ticker": ticker}
                for it in items
            ]
            analyses = await _run_in_thread(analyze_news_batch, batch, backend, ticker)
            analyzed = index_analyzed_news_items(ticker, items, analyses, es=es)
            analyzed_count = analyzed.get("indexed_count", 0)

            analyzed_items = fetch_news_for_analysis(ticker, size=200, es=es)
            graph = build_news_entity_graph(ticker, analyzed_items)
            save_news_graph(ticker, graph, es=es)
        except Exception as exc:
            graph_error = str(exc)

    message = f"Notícias indexadas com sucesso"
    if auto_analyze and analyzed_count:
        message += f" e {analyzed_count} analisadas"
    if graph_error:
        message += " (grafo: erro)"

    return ElasticIngestNewsResponse(
        ticker=result["ticker"],
        indexed_count=result.get("indexed_count", 0),
        total_items=result.get("total_items", 0),
        analyzed_count=analyzed_count if analyzed_count else None,
        message=message if not result.get("error") else None,
        error=result.get("error") or graph_error,
    )


async def ingest_ticker_all(
    ticker: str,
    period: str = "1y",
    interval: str = "1d",
) -> Dict[str, object]:
    """Obtém e indexa preços e notícias de um ticker."""
    prices = await ingest_ticker_prices(ticker, period, interval)
    news = await ingest_ticker_news(ticker)
    return {
        "ticker": ticker.upper(),
        "prices": prices,
        "news": news,
    }


async def search_ticker_prices(
    ticker: str,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    size: int = 1000,
) -> ElasticSearchPricesResponse:
    from api.elasticsearch_client import search_prices

    es = get_es_client()
    result = search_prices(ticker, start_date, end_date, size, es=es)
    return ElasticSearchPricesResponse(
        ticker=result.get("ticker", ticker.upper()),
        total=result.get("total", 0),
        points=result.get("points", []),
        start_date=start_date,
        end_date=end_date,
        error=result.get("error"),
    )


async def search_ticker_news(
    ticker: str,
    q: Optional[str] = None,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    size: int = 50,
) -> ElasticSearchNewsResponse:
    from api.elasticsearch_client import search_news

    es = get_es_client()
    result = search_news(ticker, q, start_date, end_date, size, es=es)
    return ElasticSearchNewsResponse(
        ticker=result.get("ticker", ticker.upper()),
        total=result.get("total", 0),
        items=result.get("items", []),
        query=q,
        error=result.get("error"),
    )


def get_elastic_status() -> ElasticStatus:
    """Devolve estado de ligação ao Elasticsearch."""
    es = get_es_client()
    if not es:
        return ElasticStatus(available=False, message="Elasticsearch indisponível")
    try:
        info = es.info()
        return ElasticStatus(
            available=True,
            version=info.get("version", {}).get("number"),
            cluster_name=info.get("cluster_name"),
            message="Elasticsearch disponível",
        )
    except Exception as e:
        return ElasticStatus(available=False, message=str(e))
