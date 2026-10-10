"""Sonda: PDF do relatório de empresa com o risco de preço por CPV/ano."""
from __future__ import annotations

import os
from pathlib import Path

os.environ.setdefault("ELASTICSEARCH_URL", "http://127.0.0.1:9200")

from api import benchmark_report as relatorio  # noqa: E402

SAIDA = Path("logs/relatorios_benchmark")
SAIDA.mkdir(parents=True, exist_ok=True)

params = {"mode": "empresa", "country": "pt", "nif": "500189412", "role": "adjudicatario"}
dados = relatorio.build(relatorio.normalise(params))
risco = dados.get("price_risk") or {}
print("risco:", risco.get("summary", {}).get("risk_level"), "| cpvs:", len(risco.get("items") or []))
secoes = relatorio.sections(relatorio.normalise(params), dados, reference="REP-RISCO", requester="qa@iqos.dev")
for secao in secoes:
    print(f"  {secao['title']} ({len(secao.get('rows') or [])})")
ficheiro, pdf, _ = relatorio.render(params, reference="REP-RISCO", requester="qa@iqos.dev")
(SAIDA / ficheiro).write_bytes(pdf)
print("pdf:", ficheiro, f"{len(pdf) / 1024:.0f} KB")

import pymupdf  # noqa: E402

documento = pymupdf.open(SAIDA / ficheiro)
print("páginas:", documento.page_count)
for indice in range(documento.page_count):
    texto = documento[indice].get_text()
    if "Risco de preço" in texto or "Preço por CPV e ano" in texto:
        print(f"  risco de preço na página {indice + 1}")
        documento[indice].get_pixmap(dpi=105).save(SAIDA / f"pagina_risco_{indice + 1}.png")
