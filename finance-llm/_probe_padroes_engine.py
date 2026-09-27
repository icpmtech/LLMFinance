"""Sonda rápida do motor de padrões (amostra pequena)."""
from __future__ import annotations

import json
import sys

sys.path.insert(0, r"c:\LLMFinance\finance-llm")

from api import padroes_service as padroes  # noqa: E402

payload = padroes.analyze(pais="PT", ano_from=2022, ano_to=2023, per_year=400, seed=7, use_cache=False)
if payload.get("error"):
    print("ERRO:", payload["error"])
    raise SystemExit(1)

print("overview:", json.dumps(payload["overview"], ensure_ascii=False, indent=2)[:1200])
print("deteccao:", payload["deteccao"]["algoritmos"], "limiar", payload["deteccao"]["limiar_consenso"])
print("anomalias:", len(payload["anomalias"]))
if payload["anomalias"]:
    print("top:", json.dumps(payload["anomalias"][0], ensure_ascii=False, indent=2)[:900])
print("cpvs:", json.dumps(payload["cpvs"][:3], ensure_ascii=False, indent=2))
print("entidades:", json.dumps(payload["entidades"][:2], ensure_ascii=False, indent=2)[:700])
print("risco:", json.dumps({k: v for k, v in payload["risco_aditivo"].items() if k not in ("top_contratos", "importancias")}, ensure_ascii=False))
print("risco importancias:", json.dumps(payload["risco_aditivo"].get("importancias"), ensure_ascii=False)[:400])
print("relacoes nos/arestas:", len(payload["relacoes"]["nodes"]), len(payload["relacoes"]["edges"]))
print("lacos:", json.dumps(payload["relacoes"]["lacos"][:2], ensure_ascii=False, indent=2)[:600])
print("concentracao:", json.dumps(payload["relacoes"]["concentracao"][:2], ensure_ascii=False, indent=2)[:600])
print("insolventes:", len(payload["relacoes"]["insolventes"]), "pessoas:", len(payload["relacoes"]["pessoas"]))
print("duracao:", payload["duracao_s"])
