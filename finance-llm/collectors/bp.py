"""Coleta dados do Banco de Portugal (BPSTAT)."""
from pathlib import Path
import requests

RAW_DIR = Path(__file__).resolve().parents[1] / "data" / "raw" / "bp"
RAW_DIR.mkdir(parents=True, exist_ok=True)

BPSTAT_API = "https://bpstat.bportugal.pt/data/v1"


def fetch_series_json(series_id: str) -> dict:
    """Obtém uma série do BPSTAT."""
    url = f"{BPSTAT_API}/series/?series_ids={series_id}"
    resp = requests.get(url, timeout=60)
    resp.raise_for_status()
    return resp.json()


def save_series(series_id: str) -> Path:
    data = fetch_series_json(series_id)
    path = RAW_DIR / f"{series_id}.json"
    path.write_text(str(data).replace("'", '"'))
    return path


if __name__ == "__main__":
    for sid in ["12236677", "12236678"]:
        print(save_series(sid))
