from unittest.mock import patch

import numpy as np
import pandas as pd
import pytest

from forecasting import portfolio_simulation as simulation
from forecasting import arima_model
from forecasting.market_series import MarketSeries


def market(prices, completed=None):
    return MarketSeries(
        prices, prices if completed is None else completed,
        {"partial_bar": completed is not None, "interval": "1d"},
    )


def price_series(count=110):
    rng = np.random.default_rng(42)
    return pd.Series(
        100 * np.exp(np.cumsum(rng.normal(0.001, 0.008, count))),
        index=pd.bdate_range("2025-01-01", periods=count),
        name="Close",
    )


def test_manual_simulation_is_anchored_at_latest_close_and_backtests_daily():
    prices = price_series()
    with patch.object(simulation, "load_market_series", return_value=market(prices)):
        result = simulation.simulate_portfolio_ticker("AAA", 7, "manual", (0, 0, 0), 10)
    assert len(result["backtest"]) == 10
    assert len(result["forecast"]) == 7
    assert len(result["series"]) == len(prices)
    assert result["forecast"][0]["date"] > result["series"][-1]["date"]
    expected = simulation._fit(simulation.to_log_returns(prices), (0, 0, 0))
    expected_first = prices.iloc[-1] * np.exp(np.asarray(expected.get_forecast(1).predicted_mean)[0] / 100)
    assert result["forecast"][0]["price"] == pytest.approx(expected_first)
    for row in result["backtest"] + result["forecast"]:
        assert row["lower"] <= row["price"] <= row["upper"]
    assert result["backtest"][0]["baseline"] == prices.iloc[-11]
    assert result["baseline_rmse"] >= 0


def test_walk_forward_never_uses_same_day_or_future_prices():
    prices = price_series()
    modified = prices.copy()
    modified.iloc[-5:] *= 2
    original_rows = simulation._walk_forward(prices, 100, (0, 0, 0))
    changed_rows = simulation._walk_forward(modified, 100, (0, 0, 0))
    for index in range(6):
        assert original_rows[index]["price"] == pytest.approx(changed_rows[index]["price"])
    assert original_rows[5]["actual"] != changed_rows[5]["actual"]


def test_auto_selection_never_sees_backtest_prices():
    prices = price_series()
    calls = []

    def walk(data, start, order, interval="1d", train_window=252, next_prediction=None):
        calls.append((data.index[-1], start, order))
        if next_prediction is not None:
            next_prediction.append(float(data.iloc[-1]))
        return [
            {"date": str(date.date()), "actual": float(value), "price": float(value),
             "baseline": float(value), "trend": float(value), "lower": float(value), "upper": float(value)}
            for date, value in data.iloc[start:].items()
        ]

    with (
        patch.object(simulation, "load_market_series", return_value=market(prices)),
        patch.object(simulation, "_walk_forward", side_effect=walk),
    ):
        result = simulation.simulate_portfolio_ticker("AAA", 7, "auto", backtest_days=10)
    assert len(result["validation"]) == 4
    assert all(last == prices.index[-11] for last, _, _ in calls[:4])
    assert calls[-1][0] == prices.index[-1]


def test_sparse_history_and_invalid_configuration_are_explicit_errors():
    with patch.object(simulation, "load_market_series", return_value=market(price_series(10))):
        with pytest.raises(ValueError, match="Insufficient history"):
            simulation.simulate_portfolio_ticker("AAA")
    with pytest.raises(ValueError, match="mode"):
        simulation.simulate_portfolio_ticker("AAA", mode="other")
    with pytest.raises(ValueError, match="order"):
        simulation.simulate_portfolio_ticker("AAA", order=(4, 0, 0))


def test_single_close_does_not_squeeze_into_scalar():
    frame = pd.DataFrame({"Close": [100.0]}, index=pd.bdate_range("2025-01-01", periods=1))
    with patch.object(arima_model.yf, "Ticker") as ticker:
        ticker.return_value.history.return_value = frame
        with pytest.raises(ValueError, match="Histórico insuficiente"):
            arima_model.download_close_prices("AAA")


def test_patterns_are_descriptive_and_use_only_observed_prices():
    prices = pd.Series(np.linspace(100, 150, 100), index=pd.bdate_range("2025-01-01", periods=100))
    result = simulation.detect_patterns(prices)
    assert result["trend"] == "up"
    assert result["sma20"] > result["sma50"]
    assert result["support"] is None
    assert result["resistance"] is None
    assert result["window"] == 60


def test_partial_bar_is_excluded_from_backtest_but_used_for_projection():
    prices = price_series()
    changed = prices.copy()
    changed.iloc[-1] *= 1.2
    with patch.object(simulation, "load_market_series", return_value=market(prices, prices.iloc[:-1])):
        original = simulation.simulate_portfolio_ticker("AAA", 7, "manual", (0, 0, 0), 10)
    with patch.object(simulation, "load_market_series", return_value=market(changed, changed.iloc[:-1])):
        updated = simulation.simulate_portfolio_ticker("AAA", 7, "manual", (0, 0, 0), 10)
    assert original["backtest"] == updated["backtest"]
    assert original["trading"] == updated["trading"]
    assert original["forecast"][0]["price"] != updated["forecast"][0]["price"]
    assert updated["backtest"][-1]["date"] < updated["series"][-1]["date"]


@pytest.mark.parametrize("interval", ["1m", "1h"])
def test_hourly_simulation_preserves_distinct_timestamps_and_manual_window(interval):
    prices = price_series()
    prices.index = pd.date_range("2025-01-01 09:00", periods=len(prices), freq="h", tz="America/New_York")
    with patch.object(simulation, "load_market_series", return_value=market(prices)):
        result = simulation.simulate_portfolio_ticker("AAA", 7, "manual", (0, 0, 0), 10, interval, 60)
    assert result["interval"] == interval
    assert result["train_window"] == 60
    assert len({point["date"] for point in result["backtest"]}) == 10
    assert all("T" in point["date"] for point in result["series"] + result["forecast"])
    assert len(result["trading"]["signals"]) == 11
    assert result["trading"]["latest"]["date"] == result["series"][-1]["date"]
    assert result["trading"]["fee_pct"] == 0.1
    assert len(result["comparison"]) == 3
    assert len(result["holdout_comparison"]) == 3
    assert result["recommended_model"] in {"arima", "trend", "last_close"}


def test_trend_scenario_is_causal_and_does_not_change_arima_output():
    prices = price_series()
    modified = prices.copy()
    modified.iloc[-5:] *= 2
    original_rows = simulation._walk_forward(prices, 100, (0, 0, 0))
    changed_rows = simulation._walk_forward(modified, 100, (0, 0, 0))
    for index in range(6):
        assert original_rows[index]["trend"] == pytest.approx(changed_rows[index]["trend"])


def test_recommended_model_is_not_chosen_using_the_reserved_backtest():
    prices = price_series()
    changed = prices.copy()
    changed.iloc[-10:] *= np.linspace(1.0, 1.5, 10)
    with patch.object(simulation, "load_market_series", return_value=market(prices)):
        original = simulation.simulate_portfolio_ticker("AAA", 7, "manual", (0, 0, 0), 10)
    with patch.object(simulation, "load_market_series", return_value=market(changed)):
        updated = simulation.simulate_portfolio_ticker("AAA", 7, "manual", (0, 0, 0), 10)
    assert original["comparison"] == updated["comparison"]
    assert original["recommended_model"] == updated["recommended_model"]
    assert original["holdout_comparison"] != updated["holdout_comparison"]
