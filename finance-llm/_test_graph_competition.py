"""Verificação rápida do grafo de concorrência (co-ocorrência de concorrentes)."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from api.elasticsearch_client import build_contract_graph  # noqa: E402


def main():
    result = build_contract_graph(
        "concorrente", "concorrente", metric="contratos", year=2025, sample=3000, limit=25
    )
    meta = result.get("meta", {})
    print("meta:", {k: meta.get(k) for k in (
        "kept_nodes", "nodes_total", "kept_edges", "edges_total", "coverage_count_share")})
    print("--- nós ---")
    for node in result["nodes"][:10]:
        print(f"  {node['label'][:58]:60s} contratos={node['count']}")
    print("--- arestas ---")
    for edge in result["edges"][:8]:
        print(f"  {edge['source'][:44]:46s} -> {edge['target'][:44]:46s} contratos={edge['count']}")

    masked = [n for n in result["nodes"] if n["label"].startswith("-")]
    print(f"nós com prefixo inválido: {len(masked)}")


if __name__ == "__main__":
    main()
