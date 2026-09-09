"""Backend FastAPI para a Chat UI do FinanceLLM."""
import json
from pathlib import Path
from typing import Annotated, List

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, StreamingResponse

from api.models import (
    ActionsResponse,
    AddTickerRequest,
    AddTickerResponse,
    CalendarResponse,
    ChatMessage,
    ChatRequest,
    ChatResponse,
    ElasticDeleteResponse,
    ElasticIngestNewsResponse,
    ElasticIngestPricesResponse,
    ElasticIngestRequest,
    ElasticSearchNewsResponse,
    ElasticSearchPricesResponse,
    ElasticStatus,
    ElasticTickerListResponse,
    FinancialsResponse,
    ForecastPoint,
    ForecastRequest,
    ForecastResponse,
    ForecastSeries,
    HistoryPoint,
    HoldersResponse,
    NewsItem,
    NewsResponse,
    OptionsResponse,
    RecommendationsResponse,
    SecFiling,
    SecFilingsResponse,
    SustainabilityResponse,
    TechnicalExplanation,
    TechnicalPoint,
    TechnicalResponse,
    TickerHistoryResponse,
    TickerInfoResponse,
    TickerSearchResponse,
    YahooSearchResult,
)
from api.agent import run_chat, stream_chat
from api.elasticsearch_ingest import (
    get_elastic_status,
    ingest_ticker_all,
    ingest_ticker_news,
    ingest_ticker_prices,
    search_ticker_news,
    search_ticker_prices,
)
from api.tools import (
    _normalize_ticker,
    add_ticker,
    get_actions,
    get_calendar,
    get_financials,
    get_holders,
    get_news,
    get_options,
    get_recommendations,
    get_sec_filings_yahoo,
    get_stock_history,
    get_stock_info,
    get_sustainability,
    get_technical_indicators,
    explain_technical_indicators,
    yahoo_search,
)
from forecasting.arima_model import run_full_pipeline


from api.rag_routes import router as rag_router


ROOT = Path(__file__).resolve().parents[1]
FORECAST_DIR = ROOT / "data" / "forecasting"

app = FastAPI(
    title="FinanceLLM API",
    version="0.4.0",
    description="API de chat, previsão de séries temporais e RAG FinanceLLM (GPT-2, Mistral e BloombergGPT-style).",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["*"],
)

app.include_router(rag_router)


@app.get("/")
def read_root():
    return {
        "status": "ok",
        "service": "FinanceLLM API",
        "models": ["gpt2", "mistral", "bloomberg"],
        "features": ["chat", "forecast", "rag", "elasticsearch"],
        "rag_model": None,
    }


@app.get("/health")
def health():
    return {"status": "healthy", "models": ["gpt2", "mistral", "bloomberg"], "features": ["chat", "forecast", "rag", "elasticsearch"]}


@app.post("/chat", response_model=ChatResponse)
def chat(req: ChatRequest, backend: str = Query("gpt2", pattern="^(gpt2|mistral)$")):
    result = run_chat(req.messages, backend=backend)
    return ChatResponse(
        message=result["message"],
        sources=result["sources"],
        tools=result["tools"],
    )


@app.post("/chat/stream")
def chat_stream_post(req: ChatRequest, backend: str = Query("gpt2", pattern="^(gpt2|mistral)$")):
    return StreamingResponse(
        stream_chat(req.messages, backend=backend),
        media_type="text/event-stream",
    )


@app.get("/chat/stream")
def chat_stream_get(_payload: Annotated[str, Query(...)], backend: str = Query("gpt2", pattern="^(gpt2|mistral)$")):
    payload = json.loads(_payload)
    req = ChatRequest(**payload)
    return StreamingResponse(
        stream_chat(req.messages, backend=backend),
        media_type="text/event-stream",
    )


@app.get("/tickers")
def list_tickers(query: str = Query("", min_length=0)):
    """Devolve lista de tickers conhecidos, com filtro opcional."""
    tickers_path = ROOT / "data" / "tickers_extended.json"
    tickers = json.loads(tickers_path.read_text(encoding="utf-8")) if tickers_path.exists() else []
    q = query.strip().upper()
    if q:
        tickers = [t for t in tickers if q in t.upper()]
    return {"tickers": tickers}


@app.post("/forecast", response_model=ForecastResponse)
def forecast(req: ForecastRequest):
    """Executa o pipeline ARIMA para o ticker pedido e devolve previsões + séries."""
    try:
        order = tuple(int(x) for x in req.order.split(","))
    except Exception:
        raise HTTPException(status_code=400, detail="Ordem ARIMA inválida. Use o formato p,d,q (ex: 2,1,2).")

    ticker = _normalize_ticker(req.ticker)
    try:
        info = get_stock_info(ticker)
        result = run_full_pipeline(
            ticker=ticker,
            period=req.period,
            order=order,
            train_ratio=req.train_ratio,
            future_steps=req.future_days,
            save_plot=True,
        )
        data = result.to_dict()
        forecast_points = [
            ForecastPoint(date=f["date"], price=f["price"], lower=f.get("lower"), upper=f.get("upper"))
            for f in data["forecast"]
        ]
        series = [ForecastSeries(date=s["date"], value=s["value"], type=s["type"]) for s in data["series"]]
        plot_url = None
        if result.plot_path:
            plot_url = f"/forecast/plot/{result.plot_path.name}"
        return ForecastResponse(
            ticker=ticker,
            order=result.order,
            train_days=data["train_days"],
            test_days=data["test_days"],
            rmse=result.rmse,
            mape=result.mape,
            ljung_box_pvalue=result.ljung_box_pvalue,
            last_train_date=data["last_train_date"],
            last_test_date=data["last_test_date"],
            currency=info.get("currency", "USD"),
            company_name=info.get("name", ticker),
            forecast=forecast_points,
            series=series,
            plot_url=plot_url,
            plot_path=str(result.plot_path) if result.plot_path else None,
            model_summary=result.model_summary,
            explanation=result.generate_explanation(
                currency=info.get("currency", "USD"),
                company_name=info.get("name", ticker),
            ),
        )
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Erro ao gerar previsão para {ticker}: {exc}")


@app.get("/forecast/plot/{filename}")
def forecast_plot(filename: str):
    """Serve o gráfico de previsão gerado."""
    path = FORECAST_DIR / filename
    if not path.exists() or not path.is_file():
        raise HTTPException(status_code=404, detail="Gráfico não encontrado.")
    return FileResponse(path, media_type="image/png")


@app.get("/tickers/search/yahoo", response_model=TickerSearchResponse)
def yahoo_ticker_search(query: str = Query(..., min_length=1, description="Termo a pesquisar no Yahoo Finance")):
    """Pesquisa tickers/empresas diretamente no Yahoo Finance."""
    results = yahoo_search(query, max_results=12)
    return TickerSearchResponse(
        query=query,
        tickers=[r["symbol"] for r in results],
        yahoo_results=[YahooSearchResult(**r) for r in results],
    )


@app.get("/tickers/{ticker}/info", response_model=TickerInfoResponse)
def ticker_info(ticker: str):
    """Devolve informação fundamental de um ticker."""
    ticker = _normalize_ticker(ticker)
    info = get_stock_info(ticker)
    if info.get("error"):
        raise HTTPException(status_code=502, detail=f"Erro ao obter info de {ticker}: {info['error']}")
    return TickerInfoResponse(
        ticker=ticker,
        name=info.get("name"),
        currency=info.get("currency"),
        price=info.get("price"),
        market_cap=info.get("market_cap"),
        pe=info.get("pe"),
        eps=info.get("eps"),
        dividend_yield=info.get("dividend_yield"),
        sector=info.get("sector"),
        industry=info.get("industry"),
        website=info.get("website"),
        country=info.get("country"),
        employees=info.get("employees"),
        summary=info.get("summary"),
        exchange=info.get("exchange"),
        quote_type=info.get("quote_type"),
        beta=info.get("beta"),
        target_mean_price=info.get("target_mean_price"),
        target_high_price=info.get("target_high_price"),
        target_low_price=info.get("target_low_price"),
        recommendation=info.get("recommendation"),
        recommendation_mean=info.get("recommendation_mean"),
        number_of_analysts=info.get("number_of_analysts"),
        roe=info.get("roe"),
        kpis=info.get("kpis", {}),
    )


@app.get("/tickers/{ticker}/history", response_model=TickerHistoryResponse)
def ticker_history(
    ticker: str,
    period: str = Query("1y", pattern="^(1mo|3mo|6mo|1y|2y|5y|10y|max)$"),
):
    """Devolve histórico de preços de um ticker."""
    import pandas as pd

    ticker = _normalize_ticker(ticker)
    df = get_stock_history(ticker, period=period)
    if df.empty:
        raise HTTPException(status_code=404, detail=f"Sem histórico para {ticker} no período {period}.")
    # Normalizar colunas
    cols = {c.lower(): c for c in df.columns}
    points = []
    for _, row in df.iterrows():
        date = row.get("Date")
        if pd.isna(date):
            continue
        if hasattr(date, "strftime"):
            date = date.strftime("%Y-%m-%d")
        else:
            date = str(date)[:10]
        points.append(
            HistoryPoint(
                date=date,
                open=float(row[cols.get("open", "Open")]) if not pd.isna(row.get(cols.get("open", "Open"))) else None,
                high=float(row[cols.get("high", "High")]) if not pd.isna(row.get(cols.get("high", "High"))) else None,
                low=float(row[cols.get("low", "Low")]) if not pd.isna(row.get(cols.get("low", "Low"))) else None,
                close=float(row[cols.get("close", "Close")]) if not pd.isna(row.get(cols.get("close", "Close"))) else None,
                volume=float(row[cols.get("volume", "Volume")]) if not pd.isna(row.get(cols.get("volume", "Volume"))) else None,
            )
        )
    return TickerHistoryResponse(ticker=ticker, period=period, points=points)


@app.get("/tickers/{ticker}/financials", response_model=FinancialsResponse)
def ticker_financials(ticker: str):
    """Devolve demonstrações financeiras anuais (income statement, balance sheet, cash flow)."""
    ticker = _normalize_ticker(ticker)
    data = get_financials(ticker)
    if data.get("error"):
        raise HTTPException(status_code=502, detail=f"Erro ao obter financials de {ticker}: {data['error']}")
    return FinancialsResponse(
        ticker=ticker,
        income_statement=data.get("income_statement", {}),
        balance_sheet=data.get("balance_sheet", {}),
        cash_flow=data.get("cash_flow", {}),
        quarterly_income_statement=data.get("quarterly_income_statement", {}),
        quarterly_balance_sheet=data.get("quarterly_balance_sheet", {}),
        quarterly_cash_flow=data.get("quarterly_cash_flow", {}),
    )


@app.get("/tickers/{ticker}/sec-filings", response_model=SecFilingsResponse)
def ticker_sec_filings(ticker: str, days: int = Query(365, ge=30, le=3650)):
    """Devolve os SEC filings publicados no Yahoo Finance para o ticker."""
    ticker = _normalize_ticker(ticker)
    filings = get_sec_filings_yahoo(ticker, max_age_days=days)
    return SecFilingsResponse(
        ticker=ticker,
        filings=[SecFiling(**f) for f in filings],
    )


@app.post("/tickers/add", response_model=AddTickerResponse)
def add_new_ticker(req: AddTickerRequest):
    """Adiciona um ticker à lista local, validando-o contra o Yahoo Finance."""
    result = add_ticker(req.ticker)
    return AddTickerResponse(**result)


@app.get("/tickers/{ticker}/holders", response_model=HoldersResponse)
def ticker_holders(ticker: str):
    ticker = _normalize_ticker(ticker)
    data = get_holders(ticker)
    return HoldersResponse(**data)


@app.get("/tickers/{ticker}/sustainability", response_model=SustainabilityResponse)
def ticker_sustainability(ticker: str):
    ticker = _normalize_ticker(ticker)
    data = get_sustainability(ticker)
    return SustainabilityResponse(**data)


@app.get("/tickers/{ticker}/recommendations", response_model=RecommendationsResponse)
def ticker_recommendations(ticker: str):
    ticker = _normalize_ticker(ticker)
    data = get_recommendations(ticker)
    return RecommendationsResponse(**data)


@app.get("/tickers/{ticker}/calendar", response_model=CalendarResponse)
def ticker_calendar(ticker: str):
    ticker = _normalize_ticker(ticker)
    data = get_calendar(ticker)
    return CalendarResponse(**data)


@app.get("/tickers/{ticker}/news", response_model=NewsResponse)
def ticker_news(ticker: str, max_items: int = Query(10, ge=1, le=50)):
    ticker = _normalize_ticker(ticker)
    data = get_news(ticker, max_items=max_items)
    return NewsResponse(news=[NewsItem(**n) for n in data.get("news", [])], **{k: v for k, v in data.items() if k != "news"})


@app.get("/tickers/{ticker}/options", response_model=OptionsResponse)
def ticker_options(ticker: str):
    ticker = _normalize_ticker(ticker)
    data = get_options(ticker)
    return OptionsResponse(**data)


@app.get("/tickers/{ticker}/actions", response_model=ActionsResponse)
def ticker_actions(ticker: str):
    ticker = _normalize_ticker(ticker)
    data = get_actions(ticker)
    return ActionsResponse(**data)


@app.get("/tickers/{ticker}/technical", response_model=TechnicalResponse)
def ticker_technical(ticker: str, period: str = Query("1y", pattern="^(1mo|3mo|6mo|1y|2y|5y|10y|max)$")):
    """Devolve indicadores técnicos calculados a partir do histórico de preços."""
    ticker = _normalize_ticker(ticker)
    data = get_technical_indicators(ticker, period=period)
    if data.get("error"):
        raise HTTPException(status_code=502, detail=f"Erro ao calcular indicadores para {ticker}: {data['error']}")
    keys = [
        "price", "volume", "sma20", "sma50", "sma200", "ema12", "ema26",
        "rsi14", "macd", "macd_signal", "macd_histogram", "bb_upper", "bb_middle",
        "bb_lower", "atr14", "obv",
    ]
    points = []
    dates = data.get("dates", [])
    for i, d in enumerate(dates):
        kwargs = {"date": d}
        for k in keys:
            kwargs[k] = data.get(k, [])[i] if i < len(data.get(k, [])) else None
        points.append(TechnicalPoint(**kwargs))
    return TechnicalResponse(ticker=ticker, period=period, points=points)


@app.get("/tickers/{ticker}/technical/explain", response_model=TechnicalExplanation)
def ticker_technical_explain(ticker: str, period: str = Query("1y", pattern="^(1mo|3mo|6mo|1y|2y|5y|10y|max)$")):
    """Gera um resumo textual simples do que cada painel técnico indica."""
    ticker = _normalize_ticker(ticker)
    data = get_technical_indicators(ticker, period=period)
    if data.get("error"):
        raise HTTPException(status_code=502, detail=f"Erro ao calcular indicadores para {ticker}: {data['error']}")
    explanation = explain_technical_indicators(data)
    return TechnicalExplanation(ticker=ticker, period=period, **explanation)


@app.get("/elastic/status", response_model=ElasticStatus)
def elastic_status():
    """Devolve o estado de ligação ao Elasticsearch."""
    return get_elastic_status()


@app.post("/elastic/ingest/prices/{ticker}", response_model=ElasticIngestPricesResponse)
async def elastic_ingest_prices(
    ticker: str,
    period: str = Query("1y", pattern="^(1mo|3mo|6mo|1y|2y|5y|10y|max)$"),
    interval: str = Query("1d", pattern="^(1d|1wk|1mo)$"),
):
    """Obtém histórico de preços via yfinance e indexa no Elasticsearch."""
    ticker = _normalize_ticker(ticker)
    return await ingest_ticker_prices(ticker, period=period, interval=interval)


@app.post("/elastic/ingest/news/{ticker}", response_model=ElasticIngestNewsResponse)
async def elastic_ingest_news(ticker: str):
    """Obtém notícias via yfinance e indexa no Elasticsearch."""
    ticker = _normalize_ticker(ticker)
    return await ingest_ticker_news(ticker)


@app.post("/elastic/ingest/{ticker}")
async def elastic_ingest_ticker(
    ticker: str,
    req: ElasticIngestRequest = ElasticIngestRequest(),
):
    """Indexa preços e notícias de um ticker no Elasticsearch."""
    ticker = _normalize_ticker(ticker)
    return await ingest_ticker_all(ticker, period=req.period, interval=req.interval)


@app.get("/elastic/search/prices/{ticker}", response_model=ElasticSearchPricesResponse)
def elastic_search_prices(
    ticker: str,
    start_date: str = Query(None, description="Data inicial (YYYY-MM-DD)"),
    end_date: str = Query(None, description="Data final (YYYY-MM-DD)"),
    size: int = Query(1000, ge=1, le=10000),
):
    """Pesquisa preços indexados por ticker e intervalo de datas."""
    ticker = _normalize_ticker(ticker)
    return search_ticker_prices(ticker, start_date=start_date, end_date=end_date, size=size)


@app.get("/elastic/search/news/{ticker}", response_model=ElasticSearchNewsResponse)
def elastic_search_news(
    ticker: str,
    q: str = Query(None, description="Termo de pesquisa no título/resumo"),
    start_date: str = Query(None, description="Data inicial (YYYY-MM-DD)"),
    end_date: str = Query(None, description="Data final (YYYY-MM-DD)"),
    size: int = Query(50, ge=1, le=500),
):
    """Pesquisa notícias indexadas por ticker e texto."""
    ticker = _normalize_ticker(ticker)
    return search_ticker_news(ticker, q=q, start_date=start_date, end_date=end_date, size=size)


@app.get("/elastic/tickers", response_model=ElasticTickerListResponse)
def elastic_list_tickers():
    """Lista os tickers com dados de preços indexados no Elasticsearch."""
    from api.elasticsearch_client import list_indexed_tickers
    return ElasticTickerListResponse(tickers=list_indexed_tickers())


@app.delete("/elastic/tickers/{ticker}", response_model=ElasticDeleteResponse)
def elastic_delete_ticker(ticker: str):
    """Apaga todos os dados de preços e notícias de um ticker no Elasticsearch."""
    from api.elasticsearch_client import delete_ticker_data
    ticker = _normalize_ticker(ticker)
    result = delete_ticker_data(ticker)
    return ElasticDeleteResponse(
        ticker=result.get("ticker", ticker),
        prices_deleted=result.get("prices_deleted"),
        news_deleted=result.get("news_deleted"),
        error=result.get("error"),
    )
