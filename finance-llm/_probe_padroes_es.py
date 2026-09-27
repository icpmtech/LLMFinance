"""Sonda: datas e valores dos contratos de Espanha (PLACSP)."""
from __future__ import annotations

import sys
from datetime import datetime

import numpy as np

sys.path.insert(0, r"c:\LLMFinance\finance-llm")

from api.elasticsearch_client import CONTRATOS_ES_INDEX, get_es_client  # noqa: E402

es = get_es_client()
rows = []
for ano in (2020, 2022, 2024):
    b = {
        "size": 1500,
        "track_total_hits": False,
        "query": {"bool": {"filter": [{"term": {"ano": ano}}]}},
        "sort": ["_doc"],
        "_source": ["fecha_publicacion", "fecha_adjudicacion", "fecha_actualizacion", "fecha_limite", "valor_adjudicado", "valor_base", "valor_estimado", "num_ofertas", "es_menor", "procedimiento_label"],
    }
    rows.extend(h["_source"] for h in es.search(index=CONTRATOS_ES_INDEX, body=b)["hits"]["hits"])
print("linhas:", len(rows))


def d(value):
    if not value:
        return None
    try:
        return datetime.strptime(str(value)[:10], "%Y-%m-%d")
    except ValueError:
        return None


pub_award, base_ratio, ofertas = [], [], []
base_cov = adj_cov = 0
for r in rows:
    p, a = d(r.get("fecha_publicacion")), d(r.get("fecha_adjudicacion"))
    if p and a:
        pub_award.append((a - p).days)
    va, vb = r.get("valor_adjudicado"), r.get("valor_base")
    if va:
        adj_cov += 1
    if vb:
        base_cov += 1
    if va and vb and vb > 0:
        base_ratio.append(va / vb)
    n = r.get("num_ofertas")
    if n is not None:
        ofertas.append(n)


def show(name, values):
    if not values:
        print(name, "vazio")
        return
    arr = np.array(values, dtype=float)
    print(
        f"{name:16s} n={len(arr):6d} min={arr.min():8.1f} p1={np.quantile(arr,0.01):7.1f} p25={np.quantile(arr,0.25):7.1f} "
        f"med={np.median(arr):7.1f} p75={np.quantile(arr,0.75):7.1f} p99={np.quantile(arr,0.99):8.1f} max={arr.max():8.1f} neg={int((arr<0).sum())}"
    )


print("cobertura valor_adjudicado:", adj_cov, "valor_base:", base_cov, "de", len(rows))
show("award-pub", pub_award)
show("ratio_base", base_ratio)
show("num_ofertas", ofertas)
print("menores:", sum(1 for r in rows if r.get("es_menor")))
print("proc:", {r.get("procedimiento_label"): 0 for r in rows[:0]} or None)
from collections import Counter  # noqa: E402

for k, v in Counter(str(r.get("procedimiento_label")) for r in rows).most_common(6):
    print(f"  {k:34s} {v}")
