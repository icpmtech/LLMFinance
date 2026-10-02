"""Gera um relatório PDF de entidade e mostra o texto pintado (validação rápida).

Uso: `python _probe_relatorio_entidade.py 503933813`
"""
from __future__ import annotations

import sys

sys.path.insert(0, "c:/LLMFinance/finance-llm")

from api.entity_enrichment_service import build_entity_report_pdf  # noqa: E402
from _probe_pdf_texto import extrair  # noqa: E402

if __name__ == "__main__":
    nif = sys.argv[1] if len(sys.argv) > 1 else "500189412"
    caminho = build_entity_report_pdf(nif)
    print("pdf:", caminho)
    if not caminho:
        raise SystemExit("sem PDF")
    linhas = extrair(caminho)
    print(f"linhas de texto: {len(linhas)}")
    for linha in linhas:
        print("  ", linha[:130])
