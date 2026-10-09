"""Mostra a ontologia e as analogias de uma resposta real (sem modelo)."""
import json
import sys
import time

sys.path.insert(0, r"C:\LLMFinance\finance-llm")
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from api import deep_search_analysis as analysis  # noqa: E402
from api import deep_search_analogies as analogies  # noqa: E402
from api import deep_search_service as deep  # noqa: E402

PERGUNTA = sys.argv[1] if len(sys.argv) > 1 else "licenças de software e serviços de informática"

t0 = time.perf_counter()
recolha = deep.retrieve(PERGUNTA, sources=["contracts"], mode="hybrid", per_source=8, max_sources=12)
fontes = recolha["sources"]
print(f"recuperação: {len(fontes)} fontes em {time.perf_counter()-t0:.1f}s · modo {recolha['mode']}")

t0 = time.perf_counter()
ontologia = analysis.ontologia_das_fontes(fontes)
print(f"\n=== ONTOLOGIA ({time.perf_counter()-t0:.1f}s) ===")
print(f"nós {ontologia['totals']['nodes']} · arestas {ontologia['totals']['edges']} · por tipo {ontologia['totals']['by_type']}")
print(f"legenda: {[(item['type'], item['label'], item['count']) for item in ontologia['legend']]}")
print(f"meta: complete={ontologia['meta']['complete']} nodes_total={ontologia['meta']['nodes_total']}")
for nota in ontologia["meta"]["notes"]:
    print(f"  nota: {nota}")

print("\n-- nós com mais contratos --")
for no in ontologia["nodes"][:8]:
    etiqueta = f"{no['label'][:44]:<46}"
    extra = f" · CAE {no['cae']}" if no.get("cae") else ""
    print(f"  {no['type']:<9} {etiqueta} count={no['count']:<3} valor={no['total_value']:>12,.2f}{extra}")

print("\n-- arestas --")
for aresta in ontologia["edges"][:12]:
    print(f"  {aresta['label']:<18} {aresta['source'][:34]:<36} -> {aresta['target'][:34]:<36} ({aresta['count']})")

print("\n-- mermaid (início) --")
print("\n".join(ontologia["mermaid"].splitlines()[:6]))
print(f"(total de linhas: {len(ontologia['mermaid'].splitlines())})")

t0 = time.perf_counter()
analogias = analogies.analogias(fontes, contratos=3, semelhantes=3)
print(f"\n=== ANALOGIAS ({time.perf_counter()-t0:.1f}s) ===")
print(f"totais: {json.dumps(analogias['totals'], ensure_ascii=False)}")
for nota in analogias["notes"]:
    print(f"  nota: {nota}")
for item in analogias["items"]:
    contrato = item["contrato"]
    print(f"\n  [{contrato['id']}] {contrato['title'][:60]}")
    print(f"      {contrato['preco']} · CPV {contrato['cpv']} · {contrato['adjudicante'][:30]} -> {contrato['adjudicatario'][:30]}")
    print(f"      posição: {(item['posicao'] or {}).get('frase')}")
    for sem in item["semelhantes"]:
        desvio = f"{sem['desvio_pct']:+.1f}%" if sem.get("desvio_pct") is not None else "—"
        print(f"      · {sem['title'][:52]:<54} {sem['preco']:>12} ({desvio:>7}) · {sem.get('porque')}")
