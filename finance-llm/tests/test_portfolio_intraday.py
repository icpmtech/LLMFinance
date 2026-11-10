import os
import uuid
from unittest.mock import Mock, patch

import pandas as pd
import pytest

from api import portfolio_intraday as feed
from forecasting.market_series import MarketSeries


def market():
    series = pd.Series([100, 101], index=pd.date_range("2026-01-01T10:00:00Z", periods=2, freq="min"))
    return MarketSeries(series, series.iloc[:1], {"source": "Yahoo", "currency": "USD", "delay_seconds": 30})


@pytest.mark.parametrize("mode,kind,count", [("bars", "minute", 2), ("samples", "sample", 1)])
def test_bars_and_poll_samples_are_separate_and_keep_source_timestamp(mode, kind, count):
    client = Mock()
    client.search.return_value = {"hits": {"hits": []}}
    with (
        patch.object(feed, "load_market_series", return_value=market()),
        patch.object(feed.store, "_client", return_value=client),
        patch.object(feed.store, "_write") as write,
    ):
        result = feed.intraday_points("a", "portfolio:p", "AAA", mode, True)
    operations = write.call_args.args[1]
    assert len(operations) == count
    operation = operations[-1]
    doc = operation["_source"] if mode == "samples" else operation["script"]["params"]["doc"]
    assert doc["kind"] == kind
    assert doc["reference_date"] == "2026-01-01T10:01:00+00:00"
    if mode == "samples":
        assert doc["target_date"] != doc["reference_date"]
        assert doc["status"] == "partial"
    else:
        assert operations[0]["script"]["params"]["doc"]["status"] == "completed"
        assert doc["status"] == "partial"
    filters = client.search.call_args.kwargs["body"]["query"]["bool"]["filter"]
    assert {"term": {"owner_id": "a"}} in filters
    assert {"term": {"prepost": True}} in filters
    assert result["poll_seconds"] == 15
    assert doc["signal"]["action"] == "wait"
    assert doc["signal"]["provisional"] is True


def test_unconfigured_external_provider_never_uses_yahoo_as_fake_realtime():
    with patch.dict(os.environ, {"PORTFOLIO_REALTIME_URL": ""}):
        with pytest.raises(RuntimeError, match="indisponivel"):
            feed.intraday_points("a", "p", "AAA", "provider", True)


def test_provider_requires_https_and_original_timezone():
    with patch.dict(os.environ, {"PORTFOLIO_REALTIME_URL": "http://example.test/quote"}):
        with pytest.raises(ValueError, match="HTTPS"):
            feed._external_quote("AAA")
    response = Mock(status_code=200)
    response.json.return_value = {"price": 100, "timestamp": "2026-01-01T10:00:00"}
    with (
        patch.dict(os.environ, {"PORTFOLIO_REALTIME_URL": "https://example.test/quote"}),
        patch.object(feed.requests, "get", return_value=response),
    ):
        with pytest.raises(ValueError, match="fuso"):
            feed._external_quote("AAA")


def test_external_adapter_uses_source_timestamp_and_deduplicates_trade_points():
    client = Mock()
    client.search.return_value = {"hits": {"hits": []}}
    response = Mock(status_code=200)
    response.json.return_value = {"price": 100.25, "timestamp": "2026-01-01T10:00:00Z", "currency": "USD"}
    with (
        patch.dict(os.environ, {"PORTFOLIO_REALTIME_URL": "https://example.test/quote", "PORTFOLIO_REALTIME_TOKEN": ""}),
        patch.object(feed.requests, "get", return_value=response) as request,
        patch.object(feed.store, "_client", return_value=client),
        patch.object(feed.store, "_write") as write,
    ):
        feed.intraday_points("a", "p", "AAA", "provider", True)
    doc = write.call_args.args[1][0]["_source"]
    assert doc["target_date"] == doc["reference_date"] == "2026-01-01T10:00:00+00:00"
    assert doc["actual"] == 100.25
    assert request.call_args.kwargs["allow_redirects"] is False


def test_minute_forecast_and_store_keys_preserve_intraday_resolution():
    from api.portfolio_routes import ForecastRequest
    from api.portfolio_forecast_store import _key, _filters
    assert ForecastRequest(interval="1m").interval == "1m"
    assert _key("2026-01-01T10:01:00-05:00", "1m") == "2026-01-01T15:01:00+00:00"
    assert {"term": {"prepost": True}} in _filters("a", "p", "AAA", "1m", True)


@pytest.mark.skipif(os.getenv("FORECAST_STORE_INTEGRATION") != "1", reason="Requires local Elasticsearch")
def test_intraday_real_storage_keeps_bars_and_poll_samples_distinct():
    owner = f"intraday-test-{uuid.uuid4().hex}"
    client = feed.store._client()
    try:
        with patch.object(feed, "load_market_series", return_value=market()):
            bars = feed.intraday_points(owner, "test", "AAA", "bars", True)
            samples = feed.intraday_points(owner, "test", "AAA", "samples", True)
            updated = feed.intraday_points(owner, "test", "AAA", "bars", True)
        assert len(bars["points"]) == len(updated["points"]) == 2
        assert len(samples["points"]) == 1
        assert samples["points"][0]["date"] != bars["points"][-1]["date"]
        assert samples["points"][0]["source_date"] == bars["points"][-1]["date"]
        assert bars["points"][0]["completed"] is True
        assert bars["points"][-1]["completed"] is False
        assert all(point["signal"]["action"] == "wait" for point in bars["points"])
        assert samples["points"][0]["signal"]["method"] == "technical_only"
    finally:
        client.delete_by_query(index=feed.store.INDEX, query={"term": {"owner_id": owner}}, refresh=True)


def test_intraday_signal_history_is_causal_and_each_point_is_persisted():
    import numpy as np
    series = pd.Series(100 + np.sin(np.arange(100) / 3), index=pd.date_range("2026-01-01", periods=100, freq="min", tz="UTC"))
    changed = series.copy()
    changed.iloc[80:] *= 2
    client = Mock()
    client.search.return_value = {"hits": {"hits": []}}
    snapshots = []
    with patch.object(feed.store, "_client", return_value=client), patch.object(feed.store, "_write") as write:
        for prices in (series, changed):
            observed = MarketSeries(prices, prices.iloc[:-1], {"source": "test", "currency": "USD", "delay_seconds": 30})
            with patch.object(feed, "load_market_series", return_value=observed):
                feed.intraday_points("a", "p", "AAA", "bars", True)
            snapshots.append([op["script"]["params"]["doc"]["signal"] for op in write.call_args.args[1]])
    assert snapshots[0][:80] == snapshots[1][:80]
    assert len(snapshots[0]) == 100
    assert snapshots[0][48]["action"] == "wait"
    assert snapshots[0][49]["action"] != "wait"
    assert snapshots[0][-1]["provisional"] is True
    assert snapshots[0][-2]["provisional"] is False


def test_samples_use_source_minute_indicators_instead_of_poll_repetitions():
    import numpy as np
    series = pd.Series(100 + np.sin(np.arange(100) / 3), index=pd.date_range("2026-01-01", periods=100, freq="min", tz="UTC"))
    observed = MarketSeries(series, series.iloc[:-1], {"source": "test", "currency": "USD", "delay_seconds": 181})
    client = Mock()
    client.search.return_value = {"hits": {"hits": []}}
    with (
        patch.object(feed.store, "_client", return_value=client),
        patch.object(feed.store, "_write") as write,
        patch.object(feed, "load_market_series", return_value=observed),
    ):
        feed.intraday_points("a", "p", "AAA", "samples", True)
    signal = write.call_args.args[1][0]["_source"]["signal"]
    expected = feed.technical_indicators(series).iloc[-1]
    assert signal["rsi14"] == expected["rsi14"]
    assert signal["action"] == "wait"
    assert any("180" in reason for reason in signal["reasons"])
