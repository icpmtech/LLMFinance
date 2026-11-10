from unittest.mock import patch

import pandas as pd
import pytest

from forecasting.market_series import load_market_series, future_dates, serialize_date, _session_time


def test_provider_session_times_accept_epoch_and_formatted_timestamps():
    stamp = pd.Timestamp("2026-11-10 09:30", tz="America/New_York")
    assert _session_time(stamp, "America/New_York") == stamp
    assert _session_time(stamp.timestamp(), "America/New_York") == stamp
    assert _session_time(None, "America/New_York") is None


def test_hourly_uses_real_prepost_bars_without_filling_gaps():
    index = pd.DatetimeIndex(["2025-01-02 04:00", "2025-01-02 09:30", "2025-01-02 16:00"], tz="America/New_York")
    frame = pd.DataFrame({"Close": [100, 101, 102]}, index=index)
    with patch("forecasting.market_series.yf.Ticker") as instrument:
        instrument.return_value.history.return_value = frame
        instrument.return_value.history_metadata = {"currency": "USD", "exchangeTimezoneName": "America/New_York"}
        result = load_market_series("AAA", "1h", True)
        instrument.return_value.history.assert_called_once_with(
            period="60d", interval="1h", prepost=True, auto_adjust=True, raise_errors=True,
        )
    assert len(result.prices) == 3
    assert result.prices.tolist() == [100, 101, 102]
    assert result.metadata["prepost"] is True
    assert "T" in serialize_date(result.prices.index[0], "1h")


@pytest.mark.parametrize("interval", ["1wk", "1mo"])
def test_aggregates_only_observed_daily_closes(interval):
    frame = pd.DataFrame({"Close": range(100, 160)}, index=pd.bdate_range("2025-01-01", periods=60, tz="Europe/Lisbon"))
    with patch("forecasting.market_series.yf.Ticker") as instrument:
        instrument.return_value.history.return_value = frame
        instrument.return_value.history_metadata = {"currency": "EUR"}
        result = load_market_series("AAA", interval, False)
    assert set(result.prices.index).issubset(set(frame.index))
    assert result.prices.iloc[-1] == frame["Close"].iloc[-1]
    assert result.metadata["currency"] == "EUR"
    assert len(result.prices) < len(frame)


@pytest.mark.parametrize("interval", ["1m", "1h", "1d", "1wk", "1mo"])
def test_future_dates_are_unique_and_strictly_future(interval):
    prices = pd.Series([100, 101, 102], index=pd.DatetimeIndex(
        ["2026-11-06 09:30", "2026-11-06 10:30", "2026-11-06 11:30"], tz="America/New_York",
    ))
    result = future_dates(prices, 30, interval)
    assert len(result) == len(set(result)) == 30
    assert (result > prices.index[-1]).all()
    assert all(point.weekday() < 5 for point in result)


def test_hourly_future_skips_weekend_and_preserves_observed_session_slots():
    prices = pd.Series([100, 101], index=pd.DatetimeIndex(["2026-11-06 09:30", "2026-11-06 10:30"], tz="America/New_York"))
    dates = future_dates(prices, 2, "1h")
    assert dates[0].weekday() == 0
    assert [(point.hour, point.minute) for point in dates] == [(9, 30), (10, 30)]


def test_missing_history_is_an_explicit_error():
    with patch("forecasting.market_series.yf.Ticker") as instrument:
        instrument.return_value.history.return_value = pd.DataFrame()
        with pytest.raises(ValueError, match="No observed"):
            load_market_series("AAA", "1h", True)


def test_forming_hourly_bar_is_real_but_not_completed():
    now = pd.Timestamp.now(tz="America/New_York").floor("h")
    frame = pd.DataFrame({"Close": [100, 101, 102]}, index=pd.date_range(now - pd.Timedelta(hours=2), periods=3, freq="h"))
    with patch("forecasting.market_series.yf.Ticker") as instrument:
        instrument.return_value.history.return_value = frame
        instrument.return_value.history_metadata = {"currency": "USD"}
        result = load_market_series("AAA", "1h", True)
    assert len(result.prices) == 3
    assert len(result.completed) == 2
    assert result.metadata["partial_bar"] is True
    assert result.metadata["market_state"] == "unknown"


def test_minute_history_keeps_points_and_excludes_forming_minute():
    now = pd.Timestamp.now(tz="UTC").floor("min")
    frame = pd.DataFrame({"Close": [100, 101, 102]}, index=pd.date_range(now - pd.Timedelta(minutes=2), periods=3, freq="min"))
    with patch("forecasting.market_series.yf.Ticker") as instrument:
        instrument.return_value.history.return_value = frame
        instrument.return_value.history_metadata = {"currency": "USD"}
        result = load_market_series("AAA", "1m", True)
        instrument.return_value.history.assert_called_once_with(
            period="7d", interval="1m", prepost=True, auto_adjust=True, raise_errors=True,
        )
    assert len(result.completed) == 2
    assert result.metadata["partial_bar"]
    assert len({serialize_date(date, "1m") for date in result.prices.index}) == 3


def test_minute_future_uses_previous_full_session_not_only_last_300_points():
    yesterday = pd.date_range("2026-11-09 09:30", periods=390, freq="min", tz="America/New_York")
    today = pd.date_range("2026-11-10 09:30", periods=80, freq="min", tz="America/New_York")
    series = pd.Series(100.0, index=yesterday.append(today))
    result = future_dates(series, 7, "1m")
    assert result[0] == pd.Timestamp("2026-11-10 10:50", tz="America/New_York")
    assert result[-1] == pd.Timestamp("2026-11-10 10:56", tz="America/New_York")
