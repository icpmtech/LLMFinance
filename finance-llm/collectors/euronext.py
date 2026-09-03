"""Coleta dados da Euronext."""
from pathlib import Path
import requests

RAW_DIR = Path(__file__).resolve().parents[1] / "data" / "raw" / "euronext"
RAW_DIR.mkdir(parents=True, exist_ok=True)

EURONEXT_API = "https://live.euronext.com"


def fetch_quote(isin: str, mic: str = "XLIS") -> dict:
    """Obtém cotação de um instrumento na Euronext."""
    url = f"{EURONEXT_API}/pt/instrument/{isin}/{mic}"
    resp = requests.get(url, timeout=30, headers={"Accept": "application/json"})
    resp.raise_for_status()
    return {"isin": isin, "mic": mic, "status": resp.status_code, "len": len(resp.text)}


def save_quote(isin: str, mic: str = "XLIS") -> Path:
    data = fetch_quote(isin, mic)
    path = RAW_DIR / f"{isin}_{mic}.json"
    path.write_text(str(data).replace("'", '"'))
    return path


if __name__ == "__main__":
    for isin in ["PTEDP0AM0009", "PTGAL0AM0009"]:
        print(save_quote(isin, "XLIS"))
