"""Cabeçalhos de cada ficheiro da lista de devedores (página 1 e última)."""
from __future__ import annotations

import io
import sys

import pymupdf
import requests

BASE = "https://static.portaldasfinancas.gov.pt/app/devedores_static/listaFS{n}.pdf"

for n in range(1, int(sys.argv[1]) if len(sys.argv) > 1 else 7):
    url = BASE.format(n=n)
    try:
        r = requests.get(url, timeout=120)
        r.raise_for_status()
    except Exception as exc:  # noqa: BLE001
        print(f"listaFS{n}: falhou ({exc})")
        continue
    with pymupdf.open(stream=io.BytesIO(r.content), filetype="pdf") as doc:
        linhas = [l.strip() for l in doc[0].get_text("text").splitlines() if l.strip()]
        cabecalho = [l for l in linhas[:6] if not l.isdigit()]
        nifs = sum(1 for i in range(doc.page_count) for l in doc[i].get_text("text").splitlines() if l.strip().isdigit() and len(l.strip()) == 9)
        print(f"listaFS{n}: {len(r.content)} bytes · {doc.page_count} págs · {nifs} NIFs · {cabecalho}")
