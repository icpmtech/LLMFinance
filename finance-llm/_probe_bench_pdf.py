"""Sonda: gera os três PDFs do benchmark e verifica-os."""
from __future__ import annotations

import os
from pathlib import Path

os.environ.setdefault("ELASTICSEARCH_URL", "http://127.0.0.1:9200")

from api import benchmark_report as relatorio  # noqa: E402

SAIDA = Path("logs/relatorios_benchmark")
SAIDA.mkdir(parents=True, exist_ok=True)

CASOS = [
    ("empresa", {"mode": "empresa", "country": "pt", "nif": "501506543", "role": "adjudicatario", "cpv_code": "33000000"}),
    ("mercado", {"mode": "mercado", "countries": ["pt", "es", "fr"], "top": 25}),
    (
        "cruzar",
        {
            "mode": "cruzar",
            "role": "adjudicatario",
            "cpv_code": "33600000",
            "entities": [
                {"country": "pt", "nif": "500189412"},
                {"country": "es", "nif": "A08023145"},
            ],
        },
    ),
]

for nome, params in CASOS:
    try:
        ficheiro, dados, mime = relatorio.render(params, reference="REP-TESTE", requester="qa@iqos.dev")
    except Exception as exc:  # noqa: BLE001
        print(f"{nome}: ERRO {type(exc).__name__}: {exc}")
        continue
    destino = SAIDA / ficheiro
    destino.write_bytes(dados)
    resumo = relatorio.preview(params)
    print(f"{nome}: {ficheiro} · {len(dados) / 1024:.0f} KB · {mime} · {resumo['title']}")
    print(f"   subtítulo: {resumo['subtitle']}")

# Confirma que os PDFs abrem e quantas páginas têm.
try:
    import fitz

    for pdf in sorted(SAIDA.glob("*.pdf")):
        documento = fitz.open(pdf)
        texto = documento[0].get_text()[:90].replace("\n", " | ")
        print(f"   {pdf.name}: {documento.page_count} páginas · 1ª página: {texto}")
except Exception as exc:  # noqa: BLE001
    print("pymupdf indisponível:", exc)
