"""Rotas de portfólio financeiro (`/portfolio/*`).

Todas as respostas usam dados reais: Yahoo Finance para cotações, histórico e
métricas; notícias do índice finance_news do Elasticsearch (com fallback Yahoo).
"""
from __future__ import annotations

import logging
from typing import Annotated, Any, Dict, List, Literal, Optional, Tuple

from fastapi import APIRouter, Body, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from elasticsearch import ApiError
from elastic_transport import TransportError

from api.auth_routes import CurrentSession, optional_session
from api import portfolio_service, portfolio_store, portfolio_forecast_store, portfolio_intraday

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/portfolio", tags=["portfolio"])

Session = Annotated[Optional[CurrentSession], Depends(optional_session)]


# ---------------------------------------------------------------------------
# Modelos de pedido
# ---------------------------------------------------------------------------
class PortfolioRequest(BaseModel):
    tickers: Optional[List[str]] = Field(None, description="Tickers da carteira.")
    weights: Optional[List[float]] = Field(None, description="Pesos da carteira (mesma ordem dos tickers).")
    portfolio_id: Optional[str] = Field(None, description="Carteira guardada do utilizador a usar como escopo.")
    watchlist_id: Optional[str] = Field(None, description="Watchlist do utilizador a usar como escopo.")


class ForecastRequest(BaseModel):
    tickers: Optional[List[str]] = Field(None, description="Tickers a prever.")
    weights: Optional[List[float]] = Field(None)
    portfolio_id: Optional[str] = Field(None)
    watchlist_id: Optional[str] = Field(None)
    future_days: int = Field(30, ge=1, le=90, description="Número de observações futuras na escala selecionada.")
    use_sentiment: bool = Field(False)
    arima_mode: Literal["auto", "manual"] = "auto"
    arima_p: int = Field(1, ge=0, le=3)
    arima_d: int = Field(0, ge=0, le=1)
    arima_q: int = Field(1, ge=0, le=3)
    backtest_days: int = Field(20, ge=5, le=60, description="Observações concluídas reservadas para backtest.")
    interval: Literal["1m", "1h", "1d", "1wk", "1mo"] = "1d"
    train_window: int = Field(252, ge=60, le=1000)
    prepost: bool = True
    include_news: bool = True


class OptimizeRequest(BaseModel):
    tickers: Optional[List[str]] = Field(None)
    weights: Optional[List[float]] = Field(None)
    portfolio_id: Optional[str] = Field(None)
    watchlist_id: Optional[str] = Field(None)
    objective: str = Field("sharpe", description="sharpe | return | risk | resilience")


# ---------------------------------------------------------------------------
# Escopo: tickers/pesos explícitos, ou os da carteira/watchlist do utilizador
# ---------------------------------------------------------------------------
def _resolve_scope(
    *,
    tickers: Optional[List[str]],
    weights: Optional[List[float]],
    portfolio_id: Optional[str],
    watchlist_id: Optional[str],
    session: Optional[CurrentSession],
) -> Dict[str, Any]:
    """Resolve a origem dos dados: pedido expl?cito, carteira, watchlist ou default.

    As carteiras e watchlists vivem no ?ndice Elasticsearch de cada conta, por
    isso s? se resolvem quando h? sess?o. Sem sess?o (ou sem correspond?ncia) o
    servi?o usa a carteira de demonstra??o.
    """
    if tickers:
        return {"tickers": tickers, "weights": weights, "positions": None, "cash": 0.0, "meta": {"source": "request"}}

    user_id = str(session.user.id) if session else ""
    if user_id and portfolio_id:
        scope = portfolio_store.portfolio_scope(user_id, portfolio_id)
        if scope:
            portfolio = scope["portfolio"]
            return {
                "tickers": scope["tickers"],
                "weights": scope["weights"],
                "positions": portfolio["tickers"],
                "cash": float(portfolio.get("cash") or 0.0),
                "meta": {
                    "source": "portfolio",
                    "portfolio_id": portfolio["id"],
                    "portfolio_name": portfolio["name"],
                    "currency": portfolio.get("currency"),
                    "cash": portfolio.get("cash"),
                },
            }
    if user_id and watchlist_id:
        scope = portfolio_store.watchlist_scope(user_id, watchlist_id)
        if scope:
            watchlist = scope["watchlist"]
            return {
                "tickers": scope["tickers"],
                "weights": scope["weights"],
                "positions": None,
                "cash": 0.0,
                "meta": {
                    "source": "watchlist",
                    "watchlist_id": watchlist["id"],
                    "watchlist_name": watchlist["name"],
                },
            }
    return {"tickers": None, "weights": None, "positions": None, "cash": 0.0, "meta": {"source": "default"}}


def _with_scope(result: Dict[str, Any], scope: Dict[str, Any]) -> Dict[str, Any]:
    result["scope"] = scope
    return result


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
    session: Session,
    body: PortfolioRequest = Body(default_factory=PortfolioRequest),
) -> Dict[str, Any]:
    resolved = _resolve_scope(
        tickers=body.tickers,
        weights=body.weights,
        portfolio_id=body.portfolio_id,
        watchlist_id=body.watchlist_id,
        session=session,
    )
    return _with_scope(
        portfolio_service.portfolio_summary(
            tickers=resolved["tickers"],
            weights=resolved["weights"],
            positions=resolved["positions"],
            cash=resolved["cash"],
            currency=resolved["meta"].get("currency"),
        ),
        resolved["meta"],
    )


@router.post("/timeseries", summary="Séries normalizadas e métricas de risco para gráficos")
def portfolio_timeseries(
    session: Session,
    body: PortfolioRequest = Body(default_factory=PortfolioRequest),
) -> Dict[str, Any]:
    """Todos os ativos do escopo num só pedido (performance + risco)."""
    resolved = _resolve_scope(
        tickers=body.tickers,
        weights=body.weights,
        portfolio_id=body.portfolio_id,
        watchlist_id=body.watchlist_id,
        session=session,
    )
    return _with_scope(
        portfolio_service.portfolio_timeseries(
            tickers=resolved["tickers"],
            weights=resolved["weights"],
        ),
        resolved["meta"],
    )


@router.post("/reporting", summary="Dados agregados para relatórios de carteira")
def portfolio_reporting(
    session: Session,
    body: PortfolioRequest = Body(default_factory=PortfolioRequest),
) -> Dict[str, Any]:
    resolved = _resolve_scope(
        tickers=body.tickers,
        weights=body.weights,
        portfolio_id=body.portfolio_id,
        watchlist_id=body.watchlist_id,
        session=session,
    )
    return _with_scope(
        portfolio_service.portfolio_reporting(
            tickers=resolved["tickers"],
            weights=resolved["weights"],
            positions=resolved["positions"],
            cash=resolved["cash"],
            currency=resolved["meta"].get("currency"),
        ),
        resolved["meta"],
    )


@router.post("/forecast", summary="Previsões ARIMA de preço para os tickers")
def portfolio_forecast(
    session: Session,
    body: ForecastRequest = Body(default_factory=ForecastRequest),
) -> Dict[str, Any]:
    storage_scope = _forecast_storage_scope(session, body.portfolio_id, body.watchlist_id)
    resolved = _resolve_scope(
        tickers=body.tickers,
        weights=body.weights,
        portfolio_id=body.portfolio_id,
        watchlist_id=body.watchlist_id,
        session=session,
    )
    result = _with_scope(
        portfolio_service.portfolio_forecast(
            tickers=resolved["tickers"],
            future_days=body.future_days,
            use_sentiment=body.use_sentiment,
            arima_mode=body.arima_mode,
            arima_order=(body.arima_p, body.arima_d, body.arima_q),
            backtest_days=body.backtest_days,
            interval=body.interval,
            train_window=body.train_window,
            prepost=body.prepost,
            include_news=body.include_news,
        ),
        resolved["meta"],
    )
    for forecast in result["forecasts"]:
        if forecast.get("error"):
            continue
        if session is None:
            forecast["persistence"] = {"error": "Inicie sessao para guardar simulacoes no Elasticsearch."}
            continue
        try:
            forecast["persistence"] = portfolio_forecast_store.record_forecast(
                str(session.user.id), storage_scope, forecast,
                {key: value for key, value in body.model_dump().items()
                 if key not in {"tickers", "weights", "portfolio_id", "watchlist_id", "include_news", "use_sentiment"}},
            )
        except (ApiError, TransportError, RuntimeError, ValueError) as exc:
            logger.exception("Falha ao guardar previsao de %s", forecast["ticker"])
            forecast["persistence"] = {"error": f"Nao foi possivel guardar/ler a simulacao: {exc}"}
    return result


def _forecast_storage_scope(
    session: Optional[CurrentSession], portfolio_id: Optional[str], watchlist_id: Optional[str],
) -> str:
    if portfolio_id and watchlist_id:
        raise HTTPException(status_code=422, detail="Escolha carteira ou watchlist, nao ambas.")
    if portfolio_id or watchlist_id:
        if session is None:
            raise HTTPException(status_code=401, detail="Sessao necessaria para este escopo.")
        user_id = str(session.user.id)
        if portfolio_id:
            if portfolio_store.get_portfolio(user_id, portfolio_id) is None:
                raise HTTPException(status_code=404, detail="Carteira nao encontrada.")
            return f"portfolio:{portfolio_id}"
        if portfolio_store.watchlist_scope(user_id, watchlist_id) is None:
            raise HTTPException(status_code=404, detail="Watchlist nao encontrada.")
        return f"watchlist:{watchlist_id}"
    return "default"


@router.get("/forecast/history", summary="Simulacoes guardadas e comparacao com precos reais")
def portfolio_forecast_history(
    session: Session,
    ticker: str = Query(..., min_length=1, max_length=32),
    interval: Literal["1m", "1h", "1d", "1wk", "1mo"] = "1d",
    prepost: bool = True,
    portfolio_id: Optional[str] = None,
    watchlist_id: Optional[str] = None,
    offset: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=100),
    kind: Literal["forecast", "backtest", "signal"] = "forecast",
    cursor: Optional[str] = Query(None, max_length=2048),
) -> Dict[str, Any]:
    if session is None:
        raise HTTPException(status_code=401, detail="Inicie sessao para consultar simulacoes.")
    storage_scope = _forecast_storage_scope(session, portfolio_id, watchlist_id)
    try:
        return portfolio_forecast_store.read_history(
            str(session.user.id), storage_scope, ticker, interval, prepost, offset, limit, kind, cursor,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except (ApiError, TransportError, RuntimeError) as exc:
        logger.exception("Falha ao consultar simulacoes de %s", ticker)
        raise HTTPException(status_code=503, detail="Elasticsearch indisponivel para consultar simulacoes.") from exc


@router.get("/forecast/intraday", summary="Pontos intradiarios observados e persistidos")
def portfolio_intraday_points(
    session: Session,
    ticker: str = Query(..., min_length=1, max_length=32, pattern=r"^[A-Za-z0-9.^=_-]+$"),
    mode: Literal["bars", "samples", "provider"] = "bars",
    prepost: bool = True,
    portfolio_id: Optional[str] = None,
    watchlist_id: Optional[str] = None,
) -> Dict[str, Any]:
    if session is None:
        raise HTTPException(status_code=401, detail="Sessao necessaria para pontos intradiarios.")
    storage_scope = _forecast_storage_scope(session, portfolio_id, watchlist_id)
    try:
        return portfolio_intraday.intraday_points(str(session.user.id), storage_scope, ticker, mode, prepost)
    except (ApiError, TransportError, RuntimeError, ValueError) as exc:
        logger.exception("Falha no feed intradiario de %s", ticker)
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@router.post("/resilience", summary="Otimização de carteira para resiliência / Sharpe")
def portfolio_resilience(
    session: Session,
    body: OptimizeRequest = Body(default_factory=OptimizeRequest),
) -> Dict[str, Any]:
    objective = body.objective
    if objective not in {"sharpe", "return", "risk", "resilience"}:
        raise HTTPException(status_code=422, detail="objective deve ser sharpe, return, risk ou resilience")
    resolved = _resolve_scope(
        tickers=body.tickers,
        weights=body.weights,
        portfolio_id=body.portfolio_id,
        watchlist_id=body.watchlist_id,
        session=session,
    )
    return _with_scope(
        portfolio_service.portfolio_optimize(
            tickers=resolved["tickers"], weights=resolved["weights"], objective=objective
        ),
        resolved["meta"],
    )


@router.post("/attribution", summary="Análise de attribution Brinson por setor")
def portfolio_attribution(
    session: Session,
    body: PortfolioRequest = Body(default_factory=PortfolioRequest),
) -> Dict[str, Any]:
    resolved = _resolve_scope(
        tickers=body.tickers,
        weights=body.weights,
        portfolio_id=body.portfolio_id,
        watchlist_id=body.watchlist_id,
        session=session,
    )
    return _with_scope(portfolio_service.portfolio_attribution(tickers=resolved["tickers"], weights=resolved["weights"]), resolved["meta"])


@router.post("/risk", summary="Métricas de risco, VaR, beta e factor exposures")
def portfolio_risk(
    session: Session,
    body: PortfolioRequest = Body(default_factory=PortfolioRequest),
) -> Dict[str, Any]:
    resolved = _resolve_scope(
        tickers=body.tickers,
        weights=body.weights,
        portfolio_id=body.portfolio_id,
        watchlist_id=body.watchlist_id,
        session=session,
    )
    return _with_scope(portfolio_service.portfolio_risk(tickers=resolved["tickers"], weights=resolved["weights"]), resolved["meta"])


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
