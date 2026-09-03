"""Normaliza dados raw para os ficheiros JSONL processados."""
from pathlib import Path
import json
import pandas as pd

RAW_DIR = Path(__file__).resolve().parents[1] / "data" / "raw"
PROCESSED_DIR = Path(__file__).resolve().parents[1] / "data" / "processed"


def append_jsonl(path: Path, records: list[dict]) -> None:
    """Acrescenta registos a um ficheiro JSONL."""
    with path.open("a", encoding="utf-8") as f:
        for r in records:
            f.write(json.dumps(r, default=str) + "\n")


def normalize_market() -> Path:
    """Normaliza preços de mercado."""
    records = []
    for parquet in (RAW_DIR / "yfinance").glob("*.parquet"):
        df = pd.read_parquet(parquet).reset_index()
        records.extend(df.to_dict(orient="records"))
    path = PROCESSED_DIR / "market.jsonl"
    append_jsonl(path, records)
    return path


if __name__ == "__main__":
    print(normalize_market())
