"""Coleta dados da CMVM (Comissão do Mercado de Valores Mobiliários)."""
from pathlib import Path
import requests

RAW_DIR = Path(__file__).resolve().parents[1] / "data" / "raw" / "cmvm"
RAW_DIR.mkdir(parents=True, exist_ok=True)

CMVM_BASE = "https://www.cmvm.pt"


def fetch_fundamental_data(isin: str) -> dict:
    """Obtém informação fundamental de uma entidade pela ISIN."""
    url = f"{CMVM_BASE}/pt/Pages/urd/ctx/infocimv/infocimv.aspx?ISIN={isin}"
    resp = requests.get(url, timeout=30)
    resp.raise_for_status()
    return {"isin": isin, "status": resp.status_code, "len": len(resp.text)}


def save_fundamental_data(isin: str) -> Path:
    data = fetch_fundamental_data(isin)
    path = RAW_DIR / f"{isin}.json"
    path.write_text(str(data).replace("'", '"'))
    return path


if __name__ == "__main__":
    for isin in ["PTEDP0AM0009", "PTGAL0AM0009"]:
        print(save_fundamental_data(isin))
