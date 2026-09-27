"""Sonda: cobertura de campos e volumes para o módulo «Deteção de padrões».

Corre sem sessão HTTP. Usa o cliente ES do projeto.
"""
from __future__ import annotations

import json
import sys

sys.path.insert(0, r"c:\LLMFinance\finance-llm")

from api.elasticsearch_client import (  # noqa: E402
    CONTRACTS_INDEX,
    CONTRATOS_ES_INDEX,
    CIRE_INDEX,
    CONTRIBUINTES_INDEX,
    PEOPLE_INDEX,
    ENTITIES_INDEX,
    SCRAPED_INDEX,
    SOCIAL_INDEX,
    CITACOES_INDEX,
    SOCIETARIO_INDEX,
    get_es_client,
)

es = get_es_client()
if es is None:
    print("ES INDISPONIVEL")
    raise SystemExit(1)

print("ES:", json.dumps(es.info()["version"], ensure_ascii=False))

indices = [
    CONTRACTS_INDEX,
    CONTRATOS_ES_INDEX,
    PEOPLE_INDEX,
    ENTITIES_INDEX,
    SCRAPED_INDEX,
    SOCIAL_INDEX,
    CIRE_INDEX,
    CONTRIBUINTES_INDEX,
    CITACOES_INDEX,
    SOCIETARIO_INDEX,
    "finance_news",
    "contratos",
]
for idx in indices:
    try:
        n = es.count(index=idx)["count"]
        print(f"{idx:32s} {n:>12,}")
    except Exception as exc:  # noqa: BLE001
        print(f"{idx:32s} ERRO {type(exc).__name__}")

print("\n=== contrato PT: campos ===")
fields = [
    "precoContratual",
    "precoBaseProcedimento",
    "PrecoTotalEfetivo",
    "prazoExecucao",
    "dataDecisaoAdjudicacao",
    "dataCelebracaoContrato",
    "dataPublicacao",
    "cpv.code",
    "adjudicatarios.parsed.nif",
    "adjudicantes.parsed.nif",
    "fundamentAjusteDireto",
    "tipoprocedimento",
    "concorrentes",
    "Lotes",
    "tipoFimContrato",
]
for f in fields:
    body = {"query": {"bool": {"filter": [{"exists": {"field": f}}]}}}
    if "." in f:
        body = {"query": {"nested": {"path": f.split(".")[0], "query": {"exists": {"field": f}}}}}
    try:
        n = es.count(index=CONTRACTS_INDEX, body=body)["count"]
        print(f"{f:32s} {n:>12,}")
    except Exception as exc:  # noqa: BLE001
        print(f"{f:32s} ERRO {exc}")

print("\n=== tipoprocedimento top ===")
for idx in (CONTRACTS_INDEX, CONTRATOS_ES_INDEX):
    field = "tipoprocedimento" if idx == CONTRACTS_INDEX else "procedimiento_label"
    body = {"size": 0, "aggs": {"t": {"terms": {"field": field, "size": 8}}}}
    try:
        for b in es.search(index=idx, body=body)["aggregations"]["t"]["buckets"]:
            print(f"  {idx:16s} {str(b['key'])[:46]:48s} {b['doc_count']:>10,}")
    except Exception as exc:  # noqa: BLE001
        print(f"  {idx} ERRO {exc}")

print("\n=== desvio preco base vs contratual (contratos PT) ===")
body = {
    "size": 0,
    "query": {
        "bool": {
            "filter": [
                {"exists": {"field": "precoBaseProcedimento"}},
                {"exists": {"field": "precoContratual"}},
                {"range": {"precoBaseProcedimento": {"gt": 0}}},
            ]
        }
    },
    "aggs": {"b": {"histogram": {"field": "precoBaseProcedimento", "interval": 1000000}}},
}
try:
    r = es.search(index=CONTRACTS_INDEX, body=body)
    print("  docs com ambos:", r["hits"]["total"]["value"])
    print("  buckets:", len(r["aggregations"]["b"]["buckets"]))
except Exception as exc:  # noqa: BLE001
    print("  ERRO", exc)
