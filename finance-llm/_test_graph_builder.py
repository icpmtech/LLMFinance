"""Valida o construtor genérico de grafos contra o Elasticsearch, sem servidor."""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from api.elasticsearch_client import GRAPH_DIMENSIONS, build_contract_graph  # noqa: E402


def show(title, result, top=4):
    if result.get("error"):
        print(f"[ERRO] {title}: {result['error']}")
        return
    meta = result.get("meta", {})
    print(f"\n=== {title} ===")
    print(
        f"  nós={meta.get('kept_nodes')}/{meta.get('nodes_total')} "
        f"arestas={meta.get('kept_edges')}/{meta.get('edges_total')} "
        f"docs={meta.get('documents_scanned')}/{meta.get('documents_matching')} "
        f"cobertura_valor={meta.get('coverage_value_share')}"
    )
    for note in meta.get("notes", []):
        print(f"  · {note}")
    for node in result["nodes"][:top]:
        print(
            f"  NÓ {node['dimension']:14s} {node['label'][:52]:54s} "
            f"contratos={node['count']:<6d} valor={node['total_value']:,.0f}"
        )
    for edge in result["edges"][:top]:
        print(
            f"  ARE {edge['source'][:34]:36s} -> {edge['target'][:34]:36s} "
            f"contratos={edge['count']:<5d} valor={edge['value']:,.0f}"
        )


def main():
    print("Dimensões:", ", ".join(GRAPH_DIMENSIONS.keys()))

    show(
        "adjudicante × adjudicatario (2025)",
        build_contract_graph("adjudicante", "adjudicatario", year=2025, sample=1500),
    )
    show(
        "cpv_divisao × cpv_classe (2025)",
        build_contract_graph("cpv_divisao", "cpv_classe", year=2025, sample=2000, limit=40),
    )
    show(
        "concorrente (co-ocorrência, 2025)",
        build_contract_graph("concorrente", "concorrente", year=2025, sample=3000, limit=40),
    )
    show(
        "regiao (nós, 2025)",
        build_contract_graph("regiao", None, year=2025, sample=3000, limit=25),
    )
    show(
        "procedimento × regiao (2025)",
        build_contract_graph("procedimento", "regiao", year=2025, sample=2000, limit=30),
    )
    show(
        "ano × adjudicatario (2024)",
        build_contract_graph("ano", "adjudicatario", year=2024, sample=1500, limit=30),
    )
    show(
        "tipo_contrato (nós, 2025) — agregação corrigida",
        build_contract_graph("tipo_contrato", None, year=2025, sample=1500, limit=15),
    )

    payload = build_contract_graph("adjudicante", "cpv_classe", year=2025, sample=800, limit=20)
    out = Path(__file__).resolve().parent / "_graph_builder_sample.json"
    out.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\nExemplo guardado em {out}")


if __name__ == "__main__":
    main()
