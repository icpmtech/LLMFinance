"""Coleta dados macroeconómicos do FRED."""
from pathlib import Path
from fredapi import Fred
import pandas as pd

RAW_DIR = Path(__file__).resolve().parents[1] / "data" / "raw" / "fred"
RAW_DIR.mkdir(parents=True, exist_ok=True)


def fetch_series(series_id: str, api_key: str | None = None) -> pd.Series:
    """Descarrega uma série temporal do FRED."""
    fred = Fred(api_key=api_key)
    return fred.get_series(series_id)


def save_series(series_id: str, api_key: str | None = None) -> Path:
    series = fetch_series(series_id, api_key)
    path = RAW_DIR / f"{series_id}.csv"
    series.to_csv(path, header=["value"])
    return path


if __name__ == "__main__":
    for sid in ["GDP", "CPIAUCSL", "UNRATE", "DGS10", "FEDFUNDS"]:
        print(save_series(sid))
