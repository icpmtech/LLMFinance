"""Coleta filings e reports da SEC (EDGAR)."""
from pathlib import Path
import requests
import time

RAW_DIR = Path(__file__).resolve().parents[1] / "data" / "raw" / "sec"
RAW_DIR.mkdir(parents=True, exist_ok=True)

EDGAR_ROOT = "https://www.sec.gov/Archives/edgar/daily-index"
HEADERS = {"User-Agent": "IQ OS contact@example.com"}


def fetch_submissions(cik: str) -> dict:
    """Obtém submissions JSON para um CIK."""
    cik_padded = cik.zfill(10)
    url = f"https://data.sec.gov/submissions/CIK{cik_padded}.json"
    resp = requests.get(url, headers=HEADERS, timeout=30)
    resp.raise_for_status()
    return resp.json()


def save_submissions(cik: str) -> Path:
    data = fetch_submissions(cik)
    path = RAW_DIR / f"{cik}_submissions.json"
    path.write_text(str(data).replace("'", '"'))
    return path


if __name__ == "__main__":
    for cik in ["0000320193", "0000789019", "0001652044"]:
        print(save_submissions(cik))
        time.sleep(0.2)
