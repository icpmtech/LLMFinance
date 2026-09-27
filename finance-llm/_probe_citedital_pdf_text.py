"""Descarrega um PDF de édito (na sessão da pesquisa), guarda-o e mostra o texto."""
from __future__ import annotations

import re
import sys
from pathlib import Path

import requests

BASE = "https://www.citius.mj.pt/portal/consultas/"
PAGE = BASE + "ConsultasCitEdital.aspx"
PREFIX = "ctl00$ContentPlaceHolder1$"
OUT = Path(__file__).with_name("logs") / "citedital"
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/126.0 Safari/537.36"
    ),
    "Accept-Language": "pt-PT,pt;q=0.9,en;q=0.8",
    "Referer": PAGE,
}


def main() -> int:
    nome = sys.argv[1] if len(sys.argv) > 1 else "MONTEPIO"
    quantos = int(sys.argv[2]) if len(sys.argv) > 2 else 2
    s = requests.Session()
    s.headers.update(HEADERS)
    html = s.get(PAGE, timeout=60).text

    def value(name: str) -> str:
        m = re.search(r'id="' + name + r'"[^>]*value="([^"]*)"', html)
        return m.group(1) if m else ""

    data = {
        "__EVENTTARGET": "",
        "__EVENTARGUMENT": "",
        "__VIEWSTATE": value("__VIEWSTATE"),
        "__VIEWSTATEGENERATOR": value("__VIEWSTATEGENERATOR"),
        "__VIEWSTATEENCRYPTED": "",
        "__EVENTVALIDATION": value("__EVENTVALIDATION"),
        PREFIX + "txtNome": nome,
        PREFIX + "rblDias": "15",
        PREFIX + "ddlTribunais": "todos",
        PREFIX + "btnSearch": "Pesquisar",
    }
    html = s.post(PAGE, data=data, timeout=90).text
    tokens = re.findall(r'<input\s+value=\'([^\']+)\'\s+type="hidden"\s+id="queryString"', html)
    if not tokens:
        tokens = re.findall(r'id="queryString"\s+/>', html) or []
    print("tokens encontrados:", len(tokens))

    import pymupdf as fitz

    for i, token in enumerate(tokens[:quantos], start=1):
        url = f"{BASE}ConsultasCitEditalPDF.ashx?q={token}"
        r = s.get(url, timeout=60)
        print(f"\n=== documento {i}: {r.status_code} {r.headers.get('Content-Type')} {len(r.content)} bytes ===")
        if r.content[:4] != b"%PDF":
            print(re.sub(r"\s+", " ", r.text)[:200])
            continue
        pdf = OUT / f"documento_{i}.pdf"
        OUT.mkdir(parents=True, exist_ok=True)
        pdf.write_bytes(r.content)
        doc = fitz.open(stream=r.content, filetype="pdf")
        texto = "\n".join(page.get_text("text") for page in doc)
        (OUT / f"documento_{i}.txt").write_text(texto, encoding="utf-8")
        print(texto[:3000])
    return 0


if __name__ == "__main__":
    sys.exit(main())
