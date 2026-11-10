import sys
from types import SimpleNamespace
from unittest.mock import Mock, patch

from api import portfolio_service


def test_forecast_includes_all_tickers_and_preserves_individual_errors():
    tickers = ["AAA", "BBB", "CCC", "DDD", "EEE", "FFF", "GGG"]

    def run_pipeline(ticker, **kwargs):
        if ticker == "BBB":
            raise ValueError("Insufficient history")
        return {
            "ticker": ticker,
            "currency": "EUR",
            "forecast": [
                {"date": "2026-11-11", "price": 105, "lower": 95, "upper": 115}
            ],
            "series": [
                {"date": "2026-11-09", "value": 99, "type": "train"},
                {"date": "2026-11-10", "value": 100, "type": "test"},
            ],
            "rmse": 1.5,
            "mape": 2.0,
        }

    pipeline = Mock(side_effect=run_pipeline)
    with (
        patch.dict(
            sys.modules,
            {
                "forecasting.portfolio_simulation": SimpleNamespace(simulate_portfolio_ticker=pipeline),
                "api.tools": SimpleNamespace(_normalize_ticker=lambda ticker: ticker),
            },
        ),
        patch.object(
            portfolio_service, "_get_tickers_and_weights", return_value=(tickers, [])
        ),
        patch.object(portfolio_service, "_fetch_news_from_es", return_value=[]),
        patch.object(portfolio_service, "_fetch_yahoo_news", return_value=[]),
        patch.object(portfolio_service, "_apply_news_translations", side_effect=lambda news: news),
    ):
        result = portfolio_service.portfolio_forecast(tickers, future_days=7)

    assert [item["ticker"] for item in result["forecasts"]] == tickers
    assert pipeline.call_count == len(tickers)
    assert all(call.kwargs["future_steps"] == 7 for call in pipeline.call_args_list)
    failed = result["forecasts"][1]
    assert failed["error"] == "Insufficient history"
    assert failed["forecast"] == []
    assert failed["series"] == []
    assert result["forecasts"][-1]["forecast"][0]["price"] == 105
    assert result["forecasts"][-1]["series"][-1]["type"] == "test"


def test_refresh_wires_scale_and_window_and_skips_news():
    pipeline = Mock(return_value={
        "forecast": [{"date": "2026-11-10T15:00:00+00:00", "price": 102, "lower": 99, "upper": 105, "trend": 103, "recommended": 100}],
        "series": [{"date": "2026-11-10T14:00:00+00:00", "value": 100, "type": "history"}],
        "market": {"currency": "EUR", "market_state": "regular"},
        "interval": "1h",
        "recommended_model": "last_close",
        "trading": {"signals": [{"date": "2026-11-10T14:00:00+00:00", "action": "hold", "rsi14": 50}]},
    })
    with (
        patch.dict(sys.modules, {
            "forecasting.portfolio_simulation": SimpleNamespace(simulate_portfolio_ticker=pipeline),
            "api.tools": SimpleNamespace(_normalize_ticker=lambda ticker: ticker),
        }),
        patch.object(portfolio_service, "_get_tickers_and_weights", return_value=(["AAA"], [])),
        patch.object(portfolio_service, "_fetch_news_from_es") as news,
        patch.object(portfolio_service, "_fetch_yahoo_news") as yahoo,
        patch.object(portfolio_service, "_apply_news_translations", side_effect=lambda rows: rows),
    ):
        result = portfolio_service.portfolio_forecast(
            ["AAA"], 7, arima_mode="manual", arima_order=(2, 0, 1),
            backtest_days=10, interval="1h", train_window=60, prepost=True, include_news=False,
        )
    pipeline.assert_called_once_with(ticker="AAA", future_steps=7, mode="manual", order=(2, 0, 1), backtest_days=10, interval="1h", train_window=60, prepost=True)
    news.assert_not_called()
    yahoo.assert_not_called()
    item = result["forecasts"][0]
    assert item["currency"] == "EUR"
    assert item["forecast"][0]["trend"] == 103
    assert item["forecast"][0]["recommended"] == 100
    assert item["recommended_model"] == "last_close"
    assert item["trading"]["signals"][0]["rsi14"] == 50
