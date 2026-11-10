"""Observed market bars and explicitly approximate future market timestamps."""
from __future__ import annotations

from dataclasses import dataclass

import pandas as pd
import yfinance as yf


def _session_time(value, timezone: str) -> pd.Timestamp | None:
    if value is None:
        return None
    stamp = pd.Timestamp(value, unit="s", tz="UTC") if isinstance(value, (int, float)) else pd.Timestamp(value)
    return stamp.tz_localize(timezone) if stamp.tzinfo is None else stamp.tz_convert(timezone)


@dataclass
class MarketSeries:
    prices: pd.Series
    completed: pd.Series
    metadata: dict


def load_market_series(ticker: str, interval: str, prepost: bool) -> MarketSeries:
    if interval not in {"1m", "1h", "1d", "1wk", "1mo"}:
        raise ValueError("Unsupported market interval.")
    instrument = yf.Ticker(ticker)
    frame = instrument.history(
        period="7d" if interval == "1m" else "60d" if interval == "1h" else "10y",
        interval=interval if interval in {"1m", "1h"} else "1d",
        prepost=prepost if interval in {"1m", "1h"} else False,
        auto_adjust=True,
        raise_errors=True,
    )
    if frame.empty:
        raise ValueError(f"No observed prices available for {ticker} ({interval}).")
    prices = frame["Close"].dropna().sort_index()
    prices = prices[~prices.index.duplicated(keep="last")]
    if not isinstance(prices, pd.Series):
        raise ValueError("Expected one close-price series.")
    metadata = instrument.history_metadata or {}
    timezone = metadata.get("exchangeTimezoneName") or str(prices.index.tz or "UTC")
    index = pd.DatetimeIndex(prices.index)
    index = index.tz_localize(timezone) if index.tz is None else index.tz_convert(timezone)
    prices.index = index
    if interval in {"1wk", "1mo"}:
        periods = prices.index.tz_localize(None).to_period("W-FRI" if interval == "1wk" else "M")
        # Label aggregated bars with the last actual observation, never a made-up close.
        prices = prices.groupby(periods, sort=True).apply(lambda group: group.iloc[-1:])
        prices.index = pd.DatetimeIndex(prices.index.get_level_values(-1))
    now = pd.Timestamp.now(tz=timezone)
    sessions = metadata.get("currentTradingPeriod") or {}
    state = "unknown"
    for name in ("pre", "regular", "post"):
        session = sessions.get(name) or {}
        start = _session_time(session.get("start"), timezone)
        end = _session_time(session.get("end"), timezone)
        if start is not None and end is not None and start <= now < end:
            state = name
            break
    if state == "unknown" and sessions.get("regular"):
        state = "closed"
    regular_end = _session_time((sessions.get("regular") or {}).get("end"), timezone)
    close_minute = 16 * 60
    if regular_end is not None:
        close_minute = regular_end.hour * 60 + regular_end.minute
    if interval in {"1m", "1h"}:
        complete_mask = prices.index + pd.Timedelta(minutes=1 if interval == "1m" else 60) <= now
    else:
        close_dates = prices.index.normalize()
        if interval == "1wk":
            close_dates = close_dates + pd.to_timedelta(4 - close_dates.weekday, unit="D")
        elif interval == "1mo":
            close_dates = close_dates + pd.offsets.BMonthEnd(0)
        complete_mask = close_dates + pd.Timedelta(minutes=close_minute) <= now
    completed = prices.loc[complete_mask]
    return MarketSeries(
        prices=prices,
        completed=completed,
        metadata={
            "interval": interval, "timezone": timezone, "currency": metadata.get("currency"),
            "company_name": metadata.get("longName") or metadata.get("shortName") or ticker,
            "market_state": state, "prepost": prepost if interval in {"1m", "1h"} else False,
            "source": "Yahoo Finance · adjusted observed closes",
            "observed_at": prices.index[-1].isoformat(), "fetched_at": now.isoformat(),
            "partial_bar": not bool(complete_mask[-1]),
            "delay_seconds": max(0, int((now - prices.index[-1]).total_seconds())),
        },
    )


def serialize_date(date: pd.Timestamp, interval: str) -> str:
    if interval in {"1m", "1h"}:
        return date.tz_convert("UTC").isoformat() if date.tzinfo else date.tz_localize("UTC").isoformat()
    return str(date.date())


def future_dates(prices: pd.Series, steps: int, interval: str) -> pd.DatetimeIndex:
    last = prices.index[-1]
    if interval == "1d":
        return pd.bdate_range(last + pd.offsets.BusinessDay(), periods=steps)
    if interval == "1wk":
        end = last.normalize() + pd.Timedelta(days=(4 - last.weekday()) % 7)
        return pd.date_range(end + pd.Timedelta(days=7), periods=steps, freq="W-FRI")
    if interval == "1mo":
        end = last.normalize() + pd.offsets.BMonthEnd(0)
        return pd.date_range(end + pd.offsets.BMonthEnd(), periods=steps, freq="BME")
    # Infer session slots from real bars. No synthetic observations are added to history.
    recent = prices.index if interval == "1m" else prices.tail(300).index
    slots = sorted(set((stamp.hour, stamp.minute) for stamp in recent))
    candidates = []
    date = last.normalize()
    while len(candidates) < steps:
        if date.weekday() < 5:
            for hour, minute in slots:
                stamp = date + pd.Timedelta(hours=hour, minutes=minute)
                if stamp > last:
                    candidates.append(stamp)
        date += pd.DateOffset(days=1)
    return pd.DatetimeIndex(candidates[:steps])
