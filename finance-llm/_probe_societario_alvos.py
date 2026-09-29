"""Alvos da recolha societária filtrados por anos de contrato e por empresa."""
from __future__ import annotations

import json
import os
import sys

os.environ.setdefault("ELASTICSEARCH_URL", "http://127.0.0.1:9200")

from api.elasticsearch_client import (  # noqa: E402
    companies_with_contracts_in_years,
    contract_years,
    societario_targets_filtered,
)


def main() -> None:
    anos = contract_years()
    if anos.get("error"):
        print("faceta de anos: erro", anos["error"])
    else:
        print("anos:", ", ".join(f"{y['year']}={y['contracts']}" for y in anos["years"][:8]), "...")

    ano_ini = int(sys.argv[1]) if len(sys.argv) > 1 else 2024
    ano_fim = int(sys.argv[2]) if len(sys.argv) > 2 else 2024
    agg = companies_with_contracts_in_years(ano_ini, ano_fim)
    print(f"\nempresas com contratos em {ano_ini}-{ano_fim}: {agg.get('total')} (erro={agg.get('error')})")
    top = sorted((agg.get("items") or {}).items(), key=lambda kv: -kv[1]["contracts"])[:5]
    for nif, m in top:
        print(f"  {nif} contratos={int(m['contracts'])} valor={m['value']:,.0f}")

    print(f"\n--- alvos (anos {ano_ini}-{ano_fim}, sem excluir recolhidas, q vazio) ---")
    res = societario_targets_filtered(ano_ini=ano_ini, ano_fim=ano_fim, limit=8, exclude_collected=False)
    print(json.dumps({k: v for k, v in res.items() if k != "items"}, ensure_ascii=False))
    for item in res.get("items", [])[:6]:
        print(
            f"  {item['nif']} {(item.get('name') or '')[:38]:<38} "
            f"periodo={item.get('period_contracts')} tot={item.get('contracts_count')} pubs={item['publications_count']}"
        )

    print("\n--- alvos por empresa (q=JAJA, sem anos) ---")
    res2 = societario_targets_filtered(q="JAJA", limit=5, exclude_collected=False)
    for item in res2.get("items", []):
        print(f"  {item['nif']} {item.get('name')} pubs={item['publications_count']}")
    if res2.get("error"):
        print("  erro:", res2["error"])


if __name__ == "__main__":
    main()
