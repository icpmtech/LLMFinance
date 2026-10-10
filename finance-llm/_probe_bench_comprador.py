"""Sonda: grafo do comprador (fornecedores, forças/fraquezas, clientes, regiões)."""
from __future__ import annotations

import os
import sys

os.environ.setdefault("ELASTICSEARCH_URL", "http://127.0.0.1:9200")

from api import benchmark_service as bench  # noqa: E402

CASOS = [
    ("pt", "508142156", "Unidade Local de Saúde de Gaia/Espinho", None),
    ("pt", "508142156", "Unidade Local de Saúde de Gaia/Espinho", "33000000"),
    ("es", "Q2801043J", None, "50660000"),
]

for pais, nif, nome, cpv in CASOS:
    print("=" * 74)
    dados = bench.benchmark_buyer_graph(nif=nif, name=nome, country=pais, cpv_code=cpv, top_suppliers=6, top_clients=4)
    if dados.get("error"):
        print(f"{pais} {nif} -> ERRO: {dados['error']}")
        continue
    comprador = dados["buyer"]
    print(
        f"{pais} {comprador['name'][:38]!r} contratos={comprador['contracts']} valor={comprador['total_value']:.0f} "
        f"mediana={comprador['median']} (mercado {comprador['market_median']}) cpv={cpv}"
    )
    for linha in dados["suppliers"]:
        forcas = "; ".join(linha["strengths"][:2])
        fraquezas = "; ".join(linha["weaknesses"][:2])
        print(
            f"   {linha['name'][:34]!r} valor={linha['value']:.0f} quota={linha['share_pct']} "
            f"dep={linha['dependency_pct']} clientes={linha['client_count']} preco={linha['price_index']} "
            f"cpv={linha['cpvs_here']}/{linha['cpvs_market']} [{linha['status']}] score={linha['score']}"
        )
        print(f"      forças: {forcas or '—'} | fraquezas: {fraquezas or '—'}")
    print("  clientes comuns:", ", ".join(f"{c['name'][:24]}({c['contracts']})" for c in dados["clients"][:5]))
    print("  regiões:", ", ".join(f"{r['code']}({r['contracts']})" for r in dados["regions"][:6]))
    print("  ontologia:", [t["id"] for t in dados["ontology"]["object_types"]], [l["id"] for l in dados["ontology"]["link_types"]])
