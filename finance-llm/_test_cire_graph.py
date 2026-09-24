"""Testa o construtor do grafo do CIRE contra o Elasticsearch real."""
from __future__ import annotations

import os
import time

from api.cire_graph import build_cire_graph, cire_graph_dimensions


def run(title: str, **kwargs) -> None:
    t0 = time.perf_counter()
    res = build_cire_graph(**kwargs)
    dt = time.perf_counter() - t0
    if res.get("error"):
        print(f"[{title}] ERRO: {res['error']}")
        return
    meta = res["meta"]
    print(
        f"[{title}] {dt:0.2f}s | nós={len(res['nodes'])}/{meta['nodes_total']} "
        f"arestas={len(res['edges'])}/{meta['edges_total']} mode={meta['mode']} "
        f"docs={meta['documents_scanned']}/{meta['documents_matching']} complete={meta['complete']}"
    )
    for node in res["nodes"][:5]:
        print(f"    nó  {node['label'][:48]:<50} pub={node['count']:<5} menções={node['mentions']}")
    for edge in res["edges"][:3]:
        labels = {n["id"]: n["label"] for n in res["nodes"]}
        print(f"    aresta {labels.get(edge['source'], edge['source'])[:28]} → {labels.get(edge['target'], edge['target'])[:28]} pub={edge['count']}")
    for note in meta["notes"]:
        print(f"    nota: {note}")


print("=== dimensões disponíveis ===")
info = cire_graph_dimensions()
print("dims:", [(d["key"], d["aggable"]) for d in info["dimensions"]])
print("metrics:", [m["key"] for m in info["metrics"]])
print("recipes:", [r["id"] for r in info["recipes"]])

run("comarca (exato, agg)", dimension_a="comarca", mode="exato", limit=10)
run("mes (exato, agg)", dimension_a="mes", mode="exato", limit=12)
run("tipo (exato, agg)", dimension_a="tipo", mode="exato")
run("ato (exato, agg)", dimension_a="ato", mode="exato", limit=8)

run("administrador (amostra)", dimension_a="administrador", sample=5000, limit=10)
run("admin → insolvente", dimension_a="administrador", dimension_b="insolvente", sample=5000, limit=25, edge_limit=20)
run("insolvente → credor", dimension_a="insolvente", dimension_b="credor", sample=3000, limit=25, edge_limit=20)
run("credor × credor", dimension_a="credor", dimension_b="credor", sample=3000, limit=20, edge_limit=15)
run("tipo × especie (sankey)", dimension_a="tipo", dimension_b="especie", sample=5000, limit=30, edge_limit=20)
run("comarca × administrador", dimension_a="comarca", dimension_b="administrador", sample=5000, limit=30, edge_limit=20)
run("comarca filtrada PER", dimension_a="comarca", dimension_b="tipo", tipo="PER", sample=0, limit=20)

print("\n=== varredura total (sem amostragem) ===")
run("comarca × admin (tudo)", dimension_a="comarca", dimension_b="administrador", sample=0, limit=40, edge_limit=30)
