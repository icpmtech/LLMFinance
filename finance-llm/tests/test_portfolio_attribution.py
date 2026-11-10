from unittest.mock import patch

import pandas as pd

from api import portfolio_service


def test_attribution_aligns_local_trading_dates_and_skips_sparse_tickers():
    tickers = ["AAA", "BBB", "SPARSE"]
    histories = {
        "AAA": pd.DataFrame(
            {
                "Date": pd.to_datetime(
                    ["2026-06-12 00:00:00-04:00", "2026-06-15 00:00:00-04:00"]
                ),
                "Close": [100.0, 110.0],
            }
        ),
        "BBB": pd.DataFrame(
            {
                "Date": pd.to_datetime(
                    ["2026-06-12 00:00:00+01:00", "2026-06-15 00:00:00+01:00"]
                ),
                "Close": [200.0, 220.0],
            }
        ),
        "SPARSE": pd.DataFrame(
            {
                "Date": pd.to_datetime(["2026-06-12 00:00:00+01:00"]),
                "Close": [50.0],
            }
        ),
    }

    with (
        patch.object(
            portfolio_service,
            "enrich_tickers",
            return_value=[
                {"ticker": "AAA", "name": "Alpha", "sector": "Technology"},
                {"ticker": "BBB", "name": "Beta", "sector": "Banking"},
                {"ticker": "SPARSE", "name": "Sparse", "sector": "Other"},
            ],
        ),
        patch.object(
            portfolio_service,
            "_get_tickers_and_weights",
            return_value=(tickers, [0.4, 0.4, 0.2]),
        ),
        patch.object(
            portfolio_service,
            "_fetch_history",
            side_effect=lambda ticker, period="6mo": histories[ticker],
        ),
    ):
        result = portfolio_service.portfolio_attribution(tickers, [0.4, 0.4, 0.2])

    assert "error" not in result
    assert result["portfolio_return"] == 10.0
    assert result["excluded_tickers"] == ["SPARSE"]
    assert {item["ticker"] for item in result["top_contributors"]} == {"AAA", "BBB"}
    assert sum(item["weight"] for item in result["top_contributors"]) == 1.0
