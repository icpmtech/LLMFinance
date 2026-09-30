"""Recolhe uma página de detalhe Iberinform individual.

Uso:
    c:\LLMFinance\.venv\Scripts\python.exe _run_iberinform_detail_only.py https://www.iberinform.pt/empresa/24050518/alvaro-fernandes-and-filhos-lda
"""

import argparse
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, r"c:\LLMFinance\finance-llm")

from api import scraper_service


def fetch_detail(url: str) -> dict:
    src = {
        "id": "iberinform-detail-temp",
        "name": "Iberinform detalhe individual",
        "url": url,
        "enabled": False,
        "fetcher": "http",
        "list": {"selector": "div#detalleEmpresa", "type": "css"},
        "fields": [
            {"name": "text", "label": "Texto", "selector": "div#detalleEmpresa", "type": "css", "max_length": 20000}
        ],
        "pagination": {},
        "detail": {"enabled": False},
        "options": {"impersonate": "chrome", "timeout": 30},
        "tags": ["iberinform", "detalhe"],
        "id_fields": ["url"],
        "title_field": "text",
        "summary_field": "text",
    }
    res = scraper_service.preview_source(src, limit=1, max_pages=1)
    return res


def main():
    parser = argparse.ArgumentParser(description="Recolher página de detalhe Iberinform individual")
    parser.add_argument("url")
    args = parser.parse_args()

    res = fetch_detail(args.url)
    out_dir = Path(r"c:\LLMFinance\finance-llm\data\scraper\exports\iberinform\detail")
    out_dir.mkdir(parents=True, exist_ok=True)
    # slug from url
    m = re.search(r"/empresa/(\d+)/([^/]+)", args.url)
    if m:
        filename = f"{m.group(1)}_{m.group(2)}.json"
    else:
        filename = "detail.json"
    out_file = out_dir / filename
    out_file.write_text(json.dumps(res, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Exportado: {out_file}")
    print(json.dumps(res, ensure_ascii=False, indent=2)[:2000])


if __name__ == "__main__":
    main()
