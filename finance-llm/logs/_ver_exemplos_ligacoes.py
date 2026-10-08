"""Mostra os exemplos dinâmicos e as ligações das fichas, com dados reais."""
import json
import sys
import time

sys.path.insert(0, r"C:\LLMFinance\finance-llm")
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from api import deep_search_service as ds  # noqa: E402

t0 = time.perf_counter()
exemplos = ds.dynamic_examples(refresh=True)
print(f"exemplos dinâmicos: {len(exemplos)} em {(time.perf_counter()-t0):.1f}s\n")
for exemplo in exemplos:
    print(f"  [{exemplo['scope']:>9}] {exemplo['text']}")
    print(f"              ({exemplo['hint']})")

print("\n--- ligações nos cartões de contrato ---")
t0 = time.perf_counter()
recolha = ds.retrieve(
    "Quem ganhou contratos de licenças de software?", sources=["contracts"], mode="text", per_source=4, max_sources=6
)
print(f"{len(recolha['sources'])} fontes em {(time.perf_counter()-t0):.1f}s")
for fonte in recolha["sources"][:4]:
    print(f"\n  [{fonte['n']}] {str(fonte['title'])[:60]}")
    print(f"      meta : {json.dumps(fonte['meta'], ensure_ascii=False)}")
    for ligacao in fonte.get("links") or []:
        destino = f"{ligacao['view']}:{ligacao['arg']}" if ligacao["view"] else "(sem ficha — falta NIF)"
        print(f"      {ligacao['label']:<20} {str(ligacao['text'])[:40]:<42} -> {destino}")
    if not (fonte.get("links") or []):
        print("      (sem ligações)")
