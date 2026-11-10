"""Temporal validation and daily ARIMA simulation for portfolio forecasts."""
from __future__ import annotations

import logging
import math

import numpy as np
import pandas as pd

from forecasting.arima_model import fit_arima, to_log_returns
from forecasting.market_series import future_dates, load_market_series, serialize_date
from forecasting.trading_signals import simulate_trading

logger = logging.getLogger(__name__)
Order = tuple[int, int, int]


def _fit(returns: pd.Series, order: Order):
    # Percentage-point returns avoid ill-conditioned variance estimates near zero.
    fitted = fit_arima(returns * 100, order=order)
    if not fitted.mle_retvals.get("converged", True):
        raise ValueError(f"ARIMA{order} did not converge.")
    return fitted


def _walk_forward(
    prices: pd.Series, start: int, order: Order, interval: str = "1d", train_window: int = 252,
    next_prediction: list[float] | None = None,
) -> list[dict]:
    # Each prediction precedes the state update with that day's observed return.
    initial_returns = to_log_returns(prices.iloc[:start].tail(train_window)).reset_index(drop=True)
    fitted = _fit(initial_returns, order)
    rows = []
    for index in range(start, len(prices)):
        previous = float(prices.iloc[index - 1])
        actual = float(prices.iloc[index])
        prediction = fitted.get_forecast(steps=1)
        mean = float(np.asarray(prediction.predicted_mean)[0]) / 100
        ci = np.asarray(prediction.conf_int())[0] / 100
        rows.append({
            "date": serialize_date(prices.index[index], interval),
            "actual": actual,
            "price": previous * math.exp(mean),
            "lower": previous * math.exp(float(ci[0])),
            "upper": previous * math.exp(float(ci[1])),
            "baseline": previous,
            "trend": _trend_price(prices.iloc[:index], 1),
        })
        observed_return = pd.Series(
            [100 * math.log(actual / previous)], index=[int(fitted.nobs)],
            name="log_return",
        )
        fitted = fitted.append(observed_return, refit=False)
    if next_prediction is not None:
        mean = float(np.asarray(fitted.get_forecast(steps=1).predicted_mean)[0]) / 100
        next_prediction.append(float(prices.iloc[-1]) * math.exp(mean))
    return rows


def _trend_price(prices: pd.Series, steps: int) -> float:
    recent = np.log(prices.tail(20).to_numpy(dtype=float))
    slope = float(np.polyfit(np.arange(len(recent)), recent, 1)[0])
    return float(prices.iloc[-1]) * math.exp(slope * steps)


def _metrics(rows: list[dict], key: str = "price") -> dict:
    actual = np.array([row["actual"] for row in rows])
    predicted = np.array([row[key] for row in rows])
    errors = actual - predicted
    return {
        "rmse": float(np.sqrt(np.mean(errors ** 2))),
        "mape": float(np.mean(np.abs(errors / actual)) * 100),
    }


def detect_patterns(prices: pd.Series, interval: str = "1d") -> dict:
    recent = prices.tail(60)
    returns = to_log_returns(prices)
    last = float(prices.iloc[-1])
    sma20 = float(prices.tail(20).mean())
    sma50 = float(prices.tail(50).mean())
    lows = recent[(recent < recent.shift(1)) & (recent <= recent.shift(-1))]
    highs = recent[(recent > recent.shift(1)) & (recent >= recent.shift(-1))]
    below = lows[lows <= last]
    above = highs[highs >= last]
    correlation = float(returns.tail(60).autocorr(lag=1))
    return {
        "trend": "up" if last > sma20 > sma50 else "down" if last < sma20 < sma50 else "mixed",
        "sma20": sma20,
        "sma50": sma50,
        "volatility_annual_pct": float(returns.tail(60).std() * np.sqrt({"1m": 252 * 390, "1h": 252 * 6.5, "1d": 252, "1wk": 52, "1mo": 12}[interval]) * 100),
        "autocorrelation_lag1": correlation if np.isfinite(correlation) else None,
        "support": float(below.max()) if not below.empty else None,
        "resistance": float(above.min()) if not above.empty else None,
        "window": len(recent),
        "as_of": str(prices.index[-1].date()),
    }


def simulate_portfolio_ticker(
    ticker: str,
    future_steps: int = 30,
    mode: str = "auto",
    order: Order = (1, 0, 1),
    backtest_days: int = 20,
    interval: str = "1d",
    train_window: int = 252,
    prepost: bool = True,
) -> dict:
    if mode not in {"auto", "manual"}:
        raise ValueError("mode must be auto or manual.")
    if not 1 <= future_steps <= 90 or not 5 <= backtest_days <= 60:
        raise ValueError("Invalid forecast or backtest horizon.")
    if len(order) != 3 or not (0 <= order[0] <= 3 and 0 <= order[1] <= 1 and 0 <= order[2] <= 3):
        raise ValueError("ARIMA order requires p/q in 0..3 and d in 0..1.")
    if not 60 <= train_window <= 1000:
        raise ValueError("Training window must contain 60..1000 observations.")
    market = load_market_series(ticker, interval, prepost)
    prices = market.prices
    completed = market.completed
    if len(completed) < backtest_days + 60:
        raise ValueError(f"Insufficient history: {len(completed)} completed observations; need {backtest_days + 60}.")
    if not np.isfinite(prices.to_numpy()).all() or (prices <= 0).any():
        raise ValueError("History contains invalid prices.")
    # Bound fitting cost without truncating history returned to the user.
    model_prices = completed.tail(train_window + backtest_days + 10)
    cutoff = len(model_prices) - backtest_days
    validation = []
    if mode == "auto":
        selection_prices = model_prices.iloc[:cutoff]
        for candidate in [(0, 0, 0), (1, 0, 0), (0, 0, 1), (1, 0, 1)]:
            try:
                rows = _walk_forward(selection_prices, len(selection_prices) - 10, candidate, interval, train_window)
                validation.append({"order": candidate, **_metrics(rows)})
            except (ValueError, np.linalg.LinAlgError) as exc:
                logger.warning("ARIMA candidate %s failed for %s: %s", candidate, ticker, exc)
        if not validation:
            raise ValueError("No ARIMA candidate converged in temporal validation.")
        order = min(validation, key=lambda candidate: candidate["rmse"])["order"]
    else:
        selection_prices = model_prices.iloc[:cutoff]
    selection_rows = _walk_forward(selection_prices, len(selection_prices) - 10, order, interval, train_window)
    comparison = [
        {"model": model, **_metrics(selection_rows, key)}
        for model, key in (("arima", "price"), ("last_close", "baseline"), ("trend", "trend"))
    ]
    recommended = min(comparison, key=lambda candidate: candidate["rmse"])["model"]
    next_prediction: list[float] = []
    backtest = _walk_forward(model_prices, cutoff, order, interval, train_window, next_prediction)
    metrics = _metrics(backtest)
    baseline = _metrics(backtest, "baseline")
    # Refit on every available recent observation, anchored at the latest close.
    final_prices = prices.tail(train_window)
    fitted = _fit(to_log_returns(final_prices).reset_index(drop=True), order)
    forecast_result = fitted.get_forecast(steps=future_steps)
    predicted_returns = np.asarray(forecast_result.predicted_mean) / 100
    values = float(prices.iloc[-1]) * np.exp(np.cumsum(predicted_returns))
    sigma = float(pd.Series(np.asarray(fitted.resid)).std()) / 100
    dates = future_dates(prices, future_steps, interval)
    forecast = []
    for index, (date, value) in enumerate(zip(dates, values)):
        margin = 1.96 * sigma * math.sqrt(index + 1)
        forecast.append({
            "date": serialize_date(date, interval), "price": float(value),
            "lower": float(value * math.exp(-margin)), "upper": float(value * math.exp(margin)),
            "trend": _trend_price(final_prices, index + 1),
            "recommended": float(value) if recommended == "arima" else (
                _trend_price(final_prices, index + 1) if recommended == "trend" else float(prices.iloc[-1])
            ),
        })
    if not all(np.isfinite(row[key]) for row in forecast for key in ("price", "lower", "upper")):
        raise ValueError("ARIMA produced non-finite forecast prices.")
    warnings = []
    if metrics["rmse"] >= baseline["rmse"]:
        warnings.append("O ARIMA não superou o preço da observação anterior no backtest.")
    warnings.append("Datas futuras aproximadas: não incluem feriados; as horas usam horários observados, não um calendário oficial.")
    if market.metadata["partial_bar"]:
        warnings.append("A última barra está em formação: usada na projeção, excluída da validação e do backtest.")
    return {
        "ticker": ticker, "order": order, "mode": mode,
        **metrics, "baseline_rmse": baseline["rmse"], "baseline_mape": baseline["mape"],
        "backtest": backtest, "validation": validation,
        "patterns": detect_patterns(prices, interval), "warnings": warnings,
        "market": market.metadata, "interval": interval, "train_window": train_window,
        "comparison": comparison, "recommended_model": recommended,
        "holdout_comparison": [
            {"model": model, **_metrics(backtest, key)}
            for model, key in (("arima", "price"), ("last_close", "baseline"), ("trend", "trend"))
        ],
        "forecast": forecast,
        "trading": simulate_trading(completed, backtest, next_prediction[0], interval),
        "series": [
            {"date": serialize_date(date, interval), "value": float(value), "type": "history"}
            for date, value in prices.items()
        ],
        "last_train_date": serialize_date(model_prices.index[cutoff - 1], interval),
        "last_test_date": backtest[-1]["date"],
        "model_summary": f"ARIMA{order}; daily state updates; refit at latest close",
    }
