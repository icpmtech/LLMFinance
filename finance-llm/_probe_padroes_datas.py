"""Sonda: partes (adjudicantes/adjudicatários) e intervalos de datas reais do Portal BASE."""
from __future__ import annotations

import json
import sys

import numpy as np

sys.path.insert(0, r"c:\LLMFinance\finance-llm")

from api.elasticsearch_client import CONTRACTS_INDEX, get_es_client  # noqa: E402

es = get_es_client()
body = {
    "size": 5,
    "track_total_hits": False,
    "query": {"bool": {"filter": [{"term": {"Ano": 2023}}]}},
    "sort": ["_doc"],
    "_source": ["adjudicantes", "adjudicatarios", "dataPublicacao", "dataDecisaoAdjudicacao", "dataCelebracaoContrato", "precoContratual", "precoBaseProcedimento", "PrecoTotalEfetivo", "concorrentes", "cpv"],
}
resp = es.search(index=CONTRACTS_INDEX, body=body)
for hit in resp["hits"]["hits"][:2]:
    print(json.dumps(hit["_source"], ensure_ascii=False, indent=2)[:1800])
    print("---")

# Intervalos reais (2018-2024, amostra por ano com sort _doc)
rows = []
for ano in (2018, 2020, 2022, 2024):
    b = {
        "size": 1500,
        "track_total_hits": False,
        "query": {"bool": {"filter": [{"term": {"Ano": ano}}]}},
        "sort": ["_doc"],
        "_source": ["dataPublicacao", "dataDecisaoAdjudicacao", "dataCelebracaoContrato", "PrecoTotalEfetivo", "precoContratual", "precoBaseProcedimento", "concorrentes"],
    }
    rows.extend(h["_source"] for h in es.search(index=CONTRACTS_INDEX, body=b)["hits"]["hits"])
print("linhas:", len(rows))

from datetime import datetime  # noqa: E402


def d(value):
    if not value:
        return None
    try:
        return datetime.strptime(str(value)[:10], "%Y-%m-%d")
    except ValueError:
        return None


pub_award, award_sign, pub_sign, ratio_base, ratio_efet = [], [], [], [], []
for r in rows:
    p, a, s = d(r.get("dataPublicacao")), d(r.get("dataDecisaoAdjudicacao")), d(r.get("dataCelebracaoContrato"))
    if p and a:
        pub_award.append((a - p).days)
    if a and s:
        award_sign.append((s - a).days)
    if p and s:
        pub_sign.append((p - s).days)
    pc, pb, pe = r.get("precoContratual"), r.get("precoBaseProcedimento"), r.get("PrecoTotalEfetivo")
    if pc and pb and pb > 0:
        ratio_base.append(pc / pb)
    if pc and pe and pc > 0:
        ratio_efet.append(pe / pc)


def show(name, values):
    if not values:
        print(name, "vazio")
        return
    arr = np.array(values, dtype=float)
    print(
        f"{name:18s} n={len(arr):6d} min={arr.min():9.1f} p1={np.quantile(arr,0.01):8.1f} p25={np.quantile(arr,0.25):8.1f} "
        f"med={np.median(arr):8.1f} p75={np.quantile(arr,0.75):8.1f} p99={np.quantile(arr,0.99):9.1f} max={arr.max():9.1f} "
        f"neg={int((arr<0).sum())}"
    )


show("award-pub", pub_award)
show("sign-award", award_sign)
show("pub-sign", pub_sign)
show("ratio_base", ratio_base)
show("ratio_efetivo", ratio_efet)
show(">1.15 aditivo", [1 if v > 1.15 else 0 for v in ratio_efet])

conc = [str(r.get("concorrentes"))[:40] for r in rows if r.get("concorrentes")]
print("concorrentes amostra:", conc[:15])
