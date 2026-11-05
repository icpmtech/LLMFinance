"""Rotas de portfólio financeiro (`/portfolio/*`).

Todas as respostas usam dados reais: Yahoo Finance para cotações, histórico e
métricas; notícias do índice finance_news do Elasticsearch (com fallback Yahoo).
"""
from __future__ import annotations

from typing import Annotated, Any, Dict, List, Optional

from fastapi import APIRouter, Body, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from api.auth_routes import CurrentSession, optional_session
from api import portfolio_service

router = APIRouter(prefix="/portfolio", tags=["portfolio"])

Session = Annotated[Optional[CurrentSession], Depends(optional_session)]


# ---------------------------------------------------------------------------
# Modelos de pedido
# ---------------------------------------------------------------------------
class PortfolioRequest(BaseModel):
    tickers: Optional[List[str]] = Field(None, description="Tickers da carteira.")
    weights: Optional[List[float]] = Field(None, description="Pesos da carteira (mesma ordem dos tickers).")


class ForecastRequest(BaseModel):
    tickers: Optional[List[str]] = Field(None, description="Tickers a prever.")
    future_days: int = Field(30, ge=1, le=90)
    use_sentiment: bool = Field(False)


class OptimizeRequest(BaseModel):
    tickers: Optional[List[str]] = Field(None)
    weights: Optional[List[float]] = Field(None)
    objective: str = Field("sharpe", description="sharpe | return | risk | resilience")


# ---------------------------------------------------------------------------
# Rotas
# ---------------------------------------------------------------------------
@router.get("/meta", summary="Metadados e carteira default do módulo de portfólio")
def portfolio_meta() -> Dict[str, Any]:
    """Fonte, ressalva e carteira default."""
    default = portfolio_service._load_default_portfolio()
    return {
        "source": "Yahoo Finance",
        "news_source": "Elasticsearch finance_news (fallback Yahoo Finance)",
        "currency_default": "USD",
        "cache_ttl_seconds": portfolio_service.CACHE_TTL_SECONDS,
        "default_tickers": [p["ticker"] for p in default],
        "default_weights": [p.get("weight", 1.0) for p in default],
    }


@router.post("/summary", summary="Sumário de carteira com cotações e notícias")
def portfolio_summary(
    body: PortfolioRequest = Body(default_factory=PortfolioRequest),
) -> Dict[str, Any]:
    return portfolio_service.portfolio_summary(tickers=body.tickers, weights=body.weights)


@router.post("/reporting", summary="Dados agregados para relatórios de carteira")
def portfolio_reporting(
    body: PortfolioRequest = Body(default_factory=PortfolioRequest),
) -> Dict[str, Any]:
    return portfolio_service.portfolio_reporting(tickers=body.tickers, weights=body.weights)


@router.post("/forecast", summary="Previsões ARIMA de preço para os tickers")
def portfolio_forecast(
    body: ForecastRequest = Body(default_factory=ForecastRequest),
) -> Dict[str, Any]:
    return portfolio_service.portfolio_forecast(
        tickers=body.tickers,
        future_days=body.future_days,
        use_sentiment=body.use_sentiment,
    )


@router.post("/resilience", summary="Otimização de carteira para resiliência / Sharpe")
def portfolio_resilience(
    body: OptimizeRequest = Body(default_factory=OptimizeRequest),
) -> Dict[str, Any]:
    objective = body.objective
    if objective not in {"sharpe", "return", "risk", "resilience"}:
        raise HTTPException(status_code=422, detail="objective deve ser sharpe, return, risk ou resilience")
    return portfolio_service.portfolio_optimize(
        tickers=body.tickers,
        weights=body.weights,
        objective=objective,
    )


@router.post("/attribution", summary="Análise de attribution Brinson por setor")
def portfolio_attribution(
    body: PortfolioRequest = Body(default_factory=PortfolioRequest),
) -> Dict[str, Any]:
    return portfolio_service.portfolio_attribution(tickers=body.tickers, weights=body.weights)


@router.post("/risk", summary="Métricas de risco, VaR, beta e factor exposures")
def portfolio_risk(
    body: PortfolioRequest = Body(default_factory=PortfolioRequest),
) -> Dict[str, Any]:
    return portfolio_service.portfolio_risk(tickers=body.tickers, weights=body.weights)


@router.get("/ticker/{ticker}/info", summary="Informação detalhada de um ticker")
def ticker_info(ticker: str) -> Dict[str, Any]:
    info = portfolio_service._fetch_info(ticker)
    quote = portfolio_service._fetch_live_quote(ticker)
    info.update(
        {
            "price": portfolio_service._safe_float(quote.get("price"), info.get("price")),
            "change_pct": portfolio_service._safe_float(quote.get("change_pct")),
            "volume": portfolio_service._safe_float(quote.get("volume")),
            "previous_close": portfolio_service._safe_float(quote.get("previous_close")),
        }
    )
    return info


@router.get("/ticker/{ticker}/history", summary="Histórico de preços de um ticker")
def ticker_history(
    ticker: str,
    period: str = Query("1y", description="Período do Yahoo (1mo, 3mo, 6mo, 1y, 2y, 5y)"),
    interval: str = Query("1d", description="Intervalo (1d, 1wk, 1mo)"),
) -> Dict[str, Any]:
    df = portfolio_service._fetch_history(ticker, period=period, interval=interval)
    if df.empty:
        return {"ticker": ticker.upper(), "period": period, "points": [], "error": "Sem dados"}
    points = []
    for _, row in df.iterrows():
        points.append(
            {
                "date": row["Date"].isoformat() if hasattr(row["Date"], "isoformat") else str(row["Date"]),
                "open": portfolio_service._safe_float(row.get("Open")),
                "high": portfolio_service._safe_float(row.get("High")),
                "low": portfolio_service._safe_float(row.get("Low")),
                "close": portfolio_service._safe_float(row.get("Close")),
                "volume": portfolio_service._safe_float(row.get("Volume")),
            }
        )
    return {"ticker": ticker.upper(), "period": period, "points": points}
