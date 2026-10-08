"""Verificação rápida: valores por contrato + referência de mercado por CPV.

Corre contra o Elasticsearch a sério (não é teste unitário), para confirmar que
os valores chegam ao prompt e que a agregação por CPV devolve números plausíveis.
"""
import json
import sys
import time

sys.path.insert(0, r"C:\LLMFinance\finance-llm")

from api import deep_search_service as ds  # noqa: E402

PERGUNTA = "Quantos contratos tem a CLARANET II SOLUTIONS e qual o valor total adjudicado?"

collected = ds.retrieve(PERGUNTA, mode="hybrid", per_source=6, max_sources=12)
print(f"modo={collected['mode']} fontes={len(collected['sources'])} took={collected['took_ms']}ms")

contratos = [s for s in collected["sources"] if s.get("scope") == "contracts"]
print(f"\ncontratos na lista: {len(contratos)}")
for src in contratos[:6]:
    meta = src.get("meta") or {}
    print(f"  [{src['n']}] {str(src['title'])[:58]}")
    print(f"      meta={json.dumps(meta, ensure_ascii=False)}")
    print(f"      linha={ds._meta_linha(meta)!r}")

cpvs = [(s.get("meta") or {}).get("cpv") for s in collected["sources"]]
cpvs = [c for c in cpvs if c]
print(f"\nCPV distintos: {sorted(set(cpvs))}")

t0 = time.perf_counter()
mercado = ds.mercado_por_cpv(cpvs)
print(f"mercado_por_cpv: {len(mercado)} referências em {(time.perf_counter()-t0)*1000:.0f} ms")
for ref in mercado:
    print("  ", json.dumps(ref, ensure_ascii=False))

print("\n--- bloco que entra no prompt ---")
print(ds._mercado_bloco(mercado) or "(vazio)")

msgs = ds.build_messages(PERGUNTA, collected["sources"], None, mercado=mercado)
prompt = msgs[-1]["content"]
print("\n--- prompt: primeiras linhas com valor/CPV ---")
for linha in prompt.splitlines():
    if "valor " in linha or "CPV " in linha:
        print("  ", linha.strip()[:160])
print(f"\ntamanho do prompt: {len(prompt)} caracteres")
