"""Causal close-based signals and a long/cash paper-trading simulation."""
from __future__ import annotations

import pandas as pd

from forecasting.market_series import serialize_date

FEE = 0.001


def technical_indicators(prices: pd.Series) -> pd.DataFrame:
    delta = prices.diff()
    gain = delta.clip(lower=0).rolling(14).mean()
    loss = (-delta.clip(upper=0)).rolling(14).mean()
    rsi = 100 - 100 / (1 + gain / loss.replace(0, float("nan")))
    rsi = rsi.mask((loss == 0) & (gain > 0), 100)
    rsi = rsi.mask((gain == 0) & (loss > 0), 0)
    rsi = rsi.mask((gain == 0) & (loss == 0), 50)
    macd = prices.ewm(span=12, adjust=False).mean() - prices.ewm(span=26, adjust=False).mean()
    signal = macd.ewm(span=9, adjust=False).mean()
    return pd.DataFrame({
        "rsi14": rsi, "macd": macd, "macd_signal": signal,
        "macd_histogram": macd - signal,
        "sma20": prices.rolling(20).mean(), "sma50": prices.rolling(50).mean(),
    })


def classify_signal(indicators: dict, expected_return_pct: float) -> tuple[str, int, list[str]]:
    rsi = indicators["rsi14"]
    histogram = indicators["macd_histogram"]
    spread = indicators["sma20"] - indicators["sma50"]
    threshold = 2 * FEE * 100
    score = (
        (1 if rsi <= 30 else -1 if rsi >= 70 else 0)
        + (1 if histogram > 0 else -1 if histogram < 0 else 0)
        + (1 if spread > 0 else -1 if spread < 0 else 0)
        + (1 if expected_return_pct > threshold else -1 if expected_return_pct < -threshold else 0)
    )
    action = "hold"
    if rsi >= 70 or score <= -2 or expected_return_pct < -threshold:
        action = "sell"
    elif score >= 2 and expected_return_pct > threshold:
        action = "buy"
    reasons = [
        f"RSI14 {rsi:.1f}: " + ("sobrevendido" if rsi <= 30 else "sobrecomprado" if rsi >= 70 else "neutro"),
        "MACD " + ("acima" if histogram > 0 else "abaixo" if histogram < 0 else "na linha") + " do sinal",
        "SMA20 " + ("acima" if spread > 0 else "abaixo" if spread < 0 else "ao nivel") + " da SMA50",
        f"Previsao ARIMA de uma barra: {expected_return_pct:+.3f}% (limiar {threshold:.2f}%)",
    ]
    return action, score, reasons


def simulate_trading(
    completed: pd.Series, backtest: list[dict], next_price: float, interval: str,
) -> dict:
    indicators = technical_indicators(completed)
    start = len(completed) - len(backtest)
    cash, units, peak, max_drawdown = 100.0, 0.0, 100.0, 0.0
    fees, trades = 0.0, 0
    rows = []
    for offset in range(len(backtest) + 1):
        index = start + offset - 1
        values = {key: float(value) for key, value in indicators.iloc[index].items()}
        if not all(pd.notna(value) for value in values.values()):
            raise ValueError("Insufficient completed history for trading indicators.")
        price = float(completed.iloc[index])
        prediction = backtest[offset]["price"] if offset < len(backtest) else next_price
        expected = (prediction / price - 1) * 100
        action, score, reasons = classify_signal(values, expected)
        row = {
            "date": serialize_date(completed.index[index], interval),
            "price": price, **values, "prediction": prediction,
            "expected_return_pct": expected, "action": action,
            "score": score, "reasons": reasons,
        }
        if offset < len(backtest):
            fill = float(completed.iloc[index + 1])
            execution = "none"
            fee = 0.0
            if action == "buy" and units == 0:
                notional = cash / (1 + FEE)
                fee = notional * FEE
                units, cash = notional / fill, 0.0
                execution = "buy"
            elif action == "sell" and units > 0:
                notional = units * fill
                fee = notional * FEE
                cash, units = notional - fee, 0.0
                execution = "sell"
            fees += fee
            trades += int(execution != "none")
            # Net liquidation value includes the estimated exit fee on an open position.
            equity = cash + units * fill * (1 - FEE)
            peak = max(peak, equity)
            max_drawdown = max(max_drawdown, (1 - equity / peak) * 100)
            row.update({
                "execution_date": serialize_date(completed.index[index + 1], interval),
                "execution": execution, "execution_price": fill,
                "fee": fee, "equity": equity, "position": "long" if units else "cash",
            })
        rows.append(row)
    first_fill = float(completed.iloc[start])
    benchmark = 100 / (1 + FEE) / first_fill * float(completed.iloc[-1]) * (1 - FEE)
    return {
        "signals": rows,
        "latest": rows[-1],
        "initial_equity": 100.0,
        "final_equity": rows[-2]["equity"],
        "return_pct": rows[-2]["equity"] - 100,
        "buy_hold_return_pct": benchmark - 100,
        "max_drawdown_pct": max_drawdown,
        "fees_paid": fees, "fee_pct": FEE * 100, "trades": trades,
        "position": "long" if units else "cash",
    }
