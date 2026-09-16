"""Valida pedidos 'sem limites' (todos os nós e todas as arestas) no modo exato."""
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from api.elasticsearch_client import build_contract_graph  # noqa: E402


def run(label, **kwargs):
    start = time.perf_counter()
    result = build_contract_graph(**kwargs)
    elapsed = time.perf_counter() - start
    meta = result.get("meta", {})
    print(
        f"{label}: modo={meta.get('mode')} completo={meta.get('complete')} "
        f"docs={meta.get('documents_matching')} nós={len(result.get('nodes', []))}"
        f"/{meta.get('nodes_total')} arestas={len(result.get('edges', []))}"
        f"/{meta.get('edges_total')} tempo={elapsed:.1f}s"
    )
    for note in meta.get("notes", []):
        print("   ·", note)
    if result.get("error"):
        print("   ERRO:", result["error"])


def main():
    run(
        "exato adjudicante × adjudicatario (todos os nós/arestas)",
        dimension_a="adjudicante",
        dimension_b="adjudicatario",
        year=2025,
        mode="exato",
        limit=0,
        edge_limit=0,
    )
    run(
        "exato adjudicante × adjudicatario (top 100 nós, todas as arestas)",
        dimension_a="adjudicante",
        dimension_b="adjudicatario",
        year=2025,
        mode="exato",
        limit=100,
        edge_limit=0,
    )
    run(
        "exato adjudicante (todos os nós, sem arestas)",
        dimension_a="adjudicante",
        year=2025,
        mode="exato",
        limit=0,
    )
    run(
        "amostra todos (concorrentes Algarve)",
        dimension_a="concorrente",
        dimension_b="concorrente",
        year=2025,
        region="PT150",
        mode="amostra",
        sample=0,
        limit=0,
        edge_limit=0,
    )


if __name__ == "__main__":
    main()
