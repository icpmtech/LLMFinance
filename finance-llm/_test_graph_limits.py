"""Valida o modo exato (sem amostragem) e os limites removíveis do construtor de grafos."""
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from api.elasticsearch_client import build_contract_graph  # noqa: E402


def show(title, result, top=3):
    if result.get("error"):
        print(f"[ERRO] {title}: {result['error']}")
        return
    meta = result.get("meta", {})
    elapsed = meta.get("_elapsed")
    print(f"\n=== {title} ===")
    print(
        f"  modo={meta.get('mode')} completo={meta.get('complete')} "
        f"docs={meta.get('documents_scanned')}/{meta.get('documents_matching')} "
        f"nós={meta.get('kept_nodes')}/{meta.get('nodes_total')} "
        f"arestas={meta.get('kept_edges')}/{meta.get('edges_total')} "
        f"cobertura_valor={meta.get('coverage_value_share')}"
        + (f" tempo={elapsed:.1f}s" if elapsed else "")
    )
    for note in meta.get("notes", []):
        print(f"  · {note}")
    for node in result["nodes"][:top]:
        print(
            f"  NÓ {node['dimension']:14s} {node['label'][:46]:48s} "
            f"contratos={node['count']:<7d} valor={node['total_value']:,.0f}"
        )


def timed(func, *args, **kwargs):
    start = time.perf_counter()
    result = func(*args, **kwargs)
    result.setdefault("meta", {})["_elapsed"] = time.perf_counter() - start
    return result


def main():
    # 1) Exato (agregações) num só nível: todos os contratos, sem amostra.
    show(
        "EXATO regiao (2025) — todos os contratos",
        timed(build_contract_graph, "regiao", None, year=2025, mode="exato", limit=0),
        top=4,
    )
    show(
        "EXATO cpv_classe (2025) — top 10 classes",
        timed(build_contract_graph, "cpv_classe", None, year=2025, mode="exato", limit=10),
        top=4,
    )
    show(
        "EXATO adjudicante (2025) — todos os nós (até teto)",
        timed(build_contract_graph, "adjudicante", None, year=2025, mode="exato", limit=0),
        top=4,
    )
    # 2) Exato com arestas (agregações de dois níveis: todos os contratos).
    show(
        "EXATO adjudicante × regiao (2025) — todos os contratos",
        timed(build_contract_graph, "adjudicante", "regiao", year=2025, mode="exato", limit=50),
        top=3,
    )
    show(
        "EXATO adjudicante × adjudicatario (2025) — todos os contratos",
        timed(build_contract_graph, "adjudicante", "adjudicatario", year=2025, mode="exato", limit=40, edge_limit=0),
        top=3,
    )
    show(
        "EXATO cpv_divisao × cpv_classe (2025)",
        timed(build_contract_graph, "cpv_divisao", "cpv_classe", year=2025, mode="exato", limit=30),
        top=3,
    )
    show(
        "EXATO procedimento × regiao (2025)",
        timed(build_contract_graph, "procedimento", "regiao", year=2025, mode="exato", limit=30),
        top=3,
    )
    # 3) Varredura total (dimensões não agregáveis, ex.: concorrentes).
    show(
        "TOTAL concorrente × concorrente (Algarve, 2025)",
        timed(
            build_contract_graph,
            "concorrente",
            "concorrente",
            year=2025,
            region="PT150",
            mode="amostra",
            sample=0,
            limit=0,
            edge_limit=0,
        ),
        top=3,
    )


if __name__ == "__main__":
    main()
