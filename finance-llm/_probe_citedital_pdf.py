"""Testa se o PDF do édito abre sem os cookies da sessão da pesquisa e extrai o texto."""
from __future__ import annotations

import re
import sys
from pathlib import Path

import requests

TOKEN = (
    "9WZydNoRX%2fgXix0gbzhhJzGIYp8nISoQJ5LDOXnRNKf0DuUgTstkw%2fAGF3ErDMb37kGpdzhislQLoeNwtDaVYPk4wK89rKqdwF0gVH2lS3BL9pvyolllt2UCVoXObdruqlMkDiEQth0%3d"
)
URL = f"https://www.citius.mj.pt/portal/consultas/ConsultasCitEditalPDF.ashx?q={TOKEN}"
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/126.0 Safari/537.36"
    ),
    "Accept-Language": "pt-PT,pt;q=0.9,en;q=0.8",
    "Referer": "https://www.citius.mj.pt/portal/consultas/ConsultasCitEdital.aspx",
}


def extrair(pdf_bytes: bytes) -> dict:
    try:
        import pymupdf as fitz  # PyMuPDF novo
    except Exception:
        try:
            import fitz  # PyMuPDF antigo
        except Exception as exc:  # noqa: BLE001
            return {"erro": f"sem PyMuPDF: {exc}"}
    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    paginas = [page.get_text("text") or "" for page in doc]
    texto = "\n".join(paginas)
    return {
        "paginas": len(paginas),
        "caracteres": len(texto),
        "inicio": re.sub(r"\s+", " ", texto)[:600],
    }


def main() -> int:
    # 1. Sessão nova, sem cookies (o token é da sessão da pesquisa original).
    s = requests.Session()
    s.headers.update(HEADERS)
    r = s.get(URL, timeout=60)
    print("sem cookies ->", r.status_code, r.headers.get("Content-Type"), len(r.content), "bytes")
    print("  primeiros bytes:", r.content[:8])
    if r.content[:4] == b"%PDF":
        out = Path(__file__).with_name("logs") / "citedital" / "documento_sem_sessao.pdf"
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_bytes(r.content)
        print("  guardado em", out)
        print("  extração:", extrair(r.content))
    else:
        print("  corpo:", re.sub(r"\s+", " ", r.text)[:300])

    # 2. Sessão com cookies (pesquisa + documento).
    s2 = requests.Session()
    s2.headers.update(HEADERS)
    html = s2.get("https://www.citius.mj.pt/portal/consultas/ConsultasCitEdital.aspx", timeout=60).text
    prefix = "ctl00$ContentPlaceHolder1$"

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
        prefix + "txtNome": "MONTEPIO",
        prefix + "rblDias": "15",
        prefix + "ddlTribunais": "todos",
        prefix + "btnSearch": "Pesquisar",
    }
    html = s2.post("https://www.citius.mj.pt/portal/consultas/ConsultasCitEdital.aspx", data=data, timeout=90).text
    m = re.search(r'id="queryString"\s+value=\'([^\']+)\'', html) or re.search(
        r'value=\'([^\']+)\'\s+type="hidden"\s+id="queryString"', html
    )
    token2 = m.group(1) if m else None
    print("\nnovo token:", (token2 or "")[:40], "…")
    if token2:
        url2 = f"https://www.citius.mj.pt/portal/consultas/ConsultasCitEditalPDF.ashx?q={token2}"
        r2 = s2.get(url2, timeout=60)
        print("com cookies ->", r2.status_code, r2.headers.get("Content-Type"), len(r2.content), "bytes")
        if r2.content[:4] == b"%PDF":
            print("  extração:", extrair(r2.content))
        else:
            print("  corpo:", re.sub(r"\s+", " ", r2.text)[:300])
        # O mesmo token numa sessão nova?
        r3 = requests.get(url2, timeout=60, headers=HEADERS)
        print("token novo sem cookies ->", r3.status_code, len(r3.content), r3.content[:8])
    return 0


if __name__ == "__main__":
    sys.exit(main())
