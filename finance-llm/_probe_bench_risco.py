"""Sonda: preço por CPV e ano (eu vs mercado) com risco."""
from __future__ import annotations

import os

os.environ.setdefault("ELASTICSEARCH_URL", "http://127.0.0.1:9200")

from api import benchmark_service as bench  # noqa: E402

CASOS = [
    ("pt", "501506543", None),
    ("pt", "500189412", "33600000"),
    ("es", "A28599033", "50660000"),
]

for pais, nif, cpv in CASOS:
    print("=" * 76)
    dados = bench.benchmark_price_risk(nif=nif, role="adjudicatario", country=pais, cpv_code=cpv, top_cpvs=5, top_years=4)
    if dados.get("error"):
        print(f"{pais} {nif} -> ERRO: {dados['error']}")
        continue
    print(
        f"{pais} {nif} | risco global = {dados['summary']['risk_level']} | "
        f"mercado: media={dados['reference']['avg']} mediana={dados['reference']['median']} "
        f"contratos={dados['reference']['contracts']}"
    )
    for item in dados["summary"]["items"]:
        print(f"   [{item['severity']}] {item['title']} :: {item['detail'][:110]}")
    for linha in dados["items"]:
        anos = " ".join(f"{a['year']}:{a['ratio'] or '—'}" for a in linha["years"][:4])
        print(
            f"   {linha['code']} {str(linha['description'])[:32]!r} "
            f"eu: n={linha['contracts']} med={linha['avg']} | mercado: n={linha['market_contracts']} "
            f"med={linha['market_avg']} | ratio={linha['ratio']} quota={linha['share_pct']}% "
            f"conc={linha['suppliers']} | {linha['risk'].upper()}: {linha['risk_reason'][:60]}"
        )
        print(f"      anos: {anos}")
        if linha["competitors"]:
            print("      maiores: " + ", ".join(f"{c['name'][:22]}({c['value']:.0f})" for c in linha["competitors"][:3]))
