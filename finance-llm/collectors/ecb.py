"""Coleta dados do Banco Central Europeu (ECB SDMX)."""
from pathlib import Path
import requests

RAW_DIR = Path(__file__).resolve().parents[1] / "data" / "raw" / "ecb"
RAW_DIR.mkdir(parents=True, exist_ok=True)

ECB_API = "https://sdw-wsrest.ecb.europa.eu/service/data"


def fetch_dataflow(dataflow: str = "ICP", key: str = "M.U2.N.000000.4.ANR") -> str:
    """Obtém dados em formato CSV de um dataflow ECB."""
    url = f"{ECB_API}/{dataflow}/{key}?format=csvdata"
    resp = requests.get(url, timeout=60)
    resp.raise_for_status()
    return resp.text


def save_dataflow(dataflow: str = "ICP", key: str = "M.U2.N.000000.4.ANR") -> Path:
    csv = fetch_dataflow(dataflow, key)
    path = RAW_DIR / f"{dataflow}_{key.replace('.', '_')}.csv"
    path.write_text(csv, encoding="utf-8")
    return path


if __name__ == "__main__":
    print(save_dataflow("ICP", "M.U2.N.000000.4.ANR"))
