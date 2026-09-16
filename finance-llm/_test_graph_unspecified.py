"""Valida a inclusão do grupo 'Não especificado' nos grafos (varredura e agregações)."""
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from api.elasticsearch_client import build_contract_graph, search_contracts  # noqa: E402


def find_node(result, key):
    return next((node for node in result.get("nodes", []) if node["key"] == key), None)


def report(label, result):
    if result.get("error"):
        print(f"[ERRO] {label}: {result['error']}")
        return
    node = find_node(result, "Não especificado")
    meta = result.get("meta", {})
    print(
        f"{label}: modo={meta.get('mode')} nós={len(result.get('nodes', []))} "
        f"arestas={len(result.get('edges', []))}"
    )
    if node:
        print(
            f"   · Não especificado: contratos={node['count']:,} valor={node['total_value']:,.0f} €"
        )
    else:
        print("   · Não especificado: ausente")


def main():
    # 1) Varredura (concorrência) — região com e sem o grupo
    report(
        "varredura regiao × adjudicatario (2025, amostra 5000)",
        build_contract_graph(
            "regiao", "adjudicatario", year=2025, mode="amostra", sample=5000, limit=40
        ),
    )
    # 2) Exato por agregações (um nível)
    report(
        "exato regiao (2025, todos os contratos)",
        build_contract_graph("regiao", None, year=2025, mode="exato", limit=0),
    )
    # 3) Exato com arestas
    report(
        "exato regiao × procedimento (2025)",
        build_contract_graph("regiao", "procedimento", year=2025, mode="exato", limit=0),
    )
    # 4) Filtro de região "Não especificado"
    filtered = search_contracts(region="Não especificado", size=1)
    print(
        "filtro region='Não especificado' -> total:",
        f"{filtered.get('total', 0):,}",
        "| erro:", filtered.get("error"),
    )
    # 5) Outras dimensões em falta
    for dimension in ("tipo_contrato", "pme", "procedimento"):
        result = build_contract_graph(dimension, None, year=2025, mode="exato", limit=12)
        node = find_node(result, "Não especificado")
        print(
            f"exato {dimension}: " + (f"Não especificado -> {node['count']:,} contratos" if node else "sem grupo em falta")
        )


if __name__ == "__main__":
    main()
