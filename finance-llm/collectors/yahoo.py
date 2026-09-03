"""Coleta dados de mercado via Yahoo Finance."""
from pathlib import Path
import json
import yfinance as yf
import pandas as pd

RAW_DIR = Path(__file__).resolve().parents[1] / "data" / "raw" / "yfinance"
RAW_DIR.mkdir(parents=True, exist_ok=True)

TICKERS = ["AAPL", "MSFT", "GOOGL", "TSLA", "AMZN", "NVDA", "META", "JPM"]


def download_prices(ticker: str, period: str = "5y", interval: str = "1d") -> pd.DataFrame:
    """Descarrega preços históricos para um ticker."""
    df = yf.download(ticker, period=period, interval=interval, progress=False)
    df = df.copy()
    df["ticker"] = ticker
    return df


def save_raw(ticker: str, period: str = "5y", interval: str = "1d") -> tuple[Path, Path]:
    """Guarda dados raw em parquet (preços) e JSON (info)."""
    ticker_obj = yf.Ticker(ticker)
    info = ticker_obj.info
    info_path = RAW_DIR / f"{ticker.replace('/', '_')}_info.json"
    with info_path.open("w", encoding="utf-8") as f:
        json.dump(info, f, indent=2, default=str)

    df = download_prices(ticker, period=period, interval=interval)
    price_path = RAW_DIR / f"{ticker.replace('/', '_')}_{interval}.parquet"
    df.to_parquet(price_path)
    return price_path, info_path


if __name__ == "__main__":
    for t in TICKERS:
        print(t, "->", save_raw(t))
