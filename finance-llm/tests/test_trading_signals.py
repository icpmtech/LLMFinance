import numpy as np
import pandas as pd
import pytest
from unittest.mock import patch

from forecasting.trading_signals import classify_signal, simulate_trading, technical_indicators


def prices(values):
    return pd.Series(values, index=pd.date_range("2026-01-01", periods=len(values), freq="h", tz="UTC"))


@pytest.mark.parametrize("values,expected", [
    (np.arange(100, 180), 100),
    (np.arange(180, 100, -1), 0),
    (np.full(80, 100), 50),
])
def test_rsi_extremes_and_flat_prices_are_finite(values, expected):
    result = technical_indicators(prices(values))
    assert result.iloc[-1]["rsi14"] == expected
    assert result.iloc[50:].notna().all().all()


def test_indicators_never_see_later_bars():
    original = prices(100 + np.sin(np.arange(100)) * 3)
    changed = original.copy()
    changed.iloc[80:] *= 2
    pd.testing.assert_frame_equal(
        technical_indicators(original).iloc[:80],
        technical_indicators(changed).iloc[:80],
    )


def test_rules_combine_metrics_and_forecast_instead_of_forecast_alone():
    neutral = {"rsi14": 50, "macd_histogram": 1, "sma20": 102, "sma50": 100}
    assert classify_signal(neutral, 1)[0] == "buy"
    assert classify_signal(neutral, 0.1)[0] == "hold"
    assert classify_signal(neutral, -1)[0] == "sell"
    assert classify_signal({**neutral, "rsi14": 75}, 1)[0] == "sell"
    assert classify_signal({**neutral, "macd_histogram": -1, "sma20": 99}, 1)[0] == "hold"


def test_fills_are_delayed_fees_are_exact_and_there_are_no_short_positions():
    series = prices(np.full(84, 100.0))
    backtest = [{"price": value} for value in (101, 101, 99, 99)]
    with patch("forecasting.trading_signals.classify_signal", side_effect=[
        (action, 0, []) for action in ("buy", "buy", "sell", "sell", "buy")
    ]):
        result = simulate_trading(series, backtest, 101, "1h")
    rows = result["signals"]
    assert [row["action"] for row in rows] == ["buy", "buy", "sell", "sell", "buy"]
    assert [row["execution"] for row in rows[:-1]] == ["buy", "none", "sell", "none"]
    assert all(row["execution_date"] > row["date"] for row in rows[:-1])
    assert result["trades"] == 2
    assert result["position"] == "cash"
    expected = 100 / 1.001 * 0.999
    assert result["final_equity"] == pytest.approx(expected)
    assert result["fees_paid"] == pytest.approx(100 - expected)
    assert result["buy_hold_return_pct"] == pytest.approx(expected - 100)
    assert result["max_drawdown_pct"] == pytest.approx(100 - expected)
    assert "execution" not in rows[-1]


def test_later_prices_change_fills_but_not_earlier_decisions():
    original = prices(100 + np.sin(np.arange(85)) * 2)
    modified = original.copy()
    modified.iloc[-2:] *= 1.5
    backtest = [{"price": 101.0} for _ in range(5)]
    before = simulate_trading(original, backtest, 101, "1h")
    after = simulate_trading(modified, backtest, 101, "1h")
    for first, second in zip(before["signals"][:4], after["signals"][:4]):
        for key in ("date", "price", "rsi14", "macd", "action", "score", "prediction"):
            assert first[key] == second[key]
