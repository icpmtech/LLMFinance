"""Verifica o benchmark multi-país: PT (regressão), ES, FR e o quadro por CPV."""
from __future__ import annotations

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from api import benchmark_service as bench
from api.elasticsearch_client import get_es_client

client = get_es_client(request_timeout=300)


def cronometrar(rotulo, fn, **kwargs):
    inicio = time.perf_counter()
    res = fn(es=client, **kwargs)
    print(f"{rotulo}: {time.perf_counter() - inicio:.1f}s erro={res.get('error')}")
    return res


print("=== meta ===")
print(cronometrar("meta tudo", bench.benchmark_meta))

print("\n=== PT (regressão) ===")
pt = cronometrar("pt braun", bench.benchmark_entity, country="pt", nif="501506543", role="adjudicatario", cpv_code="33000000", top=5)
if not pt.get("error"):
    print("  país:", pt["country_label"], "| entidade:", pt["entity"]["name"][:30], pt["entity"]["contracts"], "rank", pt["entity"]["rank"], "índice", pt["entity"]["price_index"])
    print("  mercado mediana:", pt["reference"]["median"], "| pares:", pt["market"]["peers"], "| concorrentes:", [r["name"][:22] for r in pt["competitors"][:2]])

print("\n=== ES ===")
# Entidade real de Espanha (maior adjudicatária do CPV de publicidade)
es_sug = bench.top_cpv(country="es", size=3, es=client)
print("  cpv ES:", [(i["code"], i["count"]) for i in es_sug.get("items", [])])
es = cronometrar("es top entidade", bench.benchmark_entity, country="es", name="UTE ATP CADENAS", role="adjudicatario", top=5)
if not es.get("error"):
    print("  entidade:", es["entity"]["name"][:34], es["entity"]["contracts"], "rank", es["entity"]["rank"], "mediana", es["entity"]["median_value"], "| presença:", es["entity"]["present"])
    print("  referência:", es["reference"])
    print("  concorrentes:", [(r["name"][:26], r["count"]) for r in es["competitors"][:3]])
    print("  compradores (mercado):", [(r["name"][:26], r["count"]) for r in es["counterparties"][:3]])
    print("  historial:", [(r["name"][:26], r["count"]) for r in es["history"][:2]])
    print("  top cpv:", [(c["code"], c["count"]) for c in es["entity"]["top_cpv"][:3]])
    print("  recente:", es["entity"]["recent"][:1])

print("\n=== FR ===")
fr = cronometrar("fr entidade vazia", bench.benchmark_entity, country="fr", role="adjudicatario", top=5)
print("  (entidade vazia deve dar erro) ->", fr.get("error"))

from api import benchmark_countries as bc  # noqa: E402

# maior titular do índice (por valor), para servir de entidade de teste
resp = client.search(
    index="contratos_fr",
    body={"size": 0, "query": {"range": {"valor": {"gt": 0, "lte": 1e12}}}, "aggs": {"top": bc.rank_agg("fr", bc.SUPPLIER, 3)}},
)
linhas = bc.rank_rows("fr", bc.SUPPLIER, resp["aggregations"]["top"], 3, None)
print("  maiores titulares FR:", [(r["nif"], r["name"][:34], r["count"]) for r in linhas])
if linhas:
    alvo = linhas[0]
    fr = cronometrar("fr benchmark", bench.benchmark_entity, country="fr", nif=alvo["nif"], name=alvo["name"], role="adjudicatario", top=5)
    if not fr.get("error"):
        print("  entidade:", fr["entity"]["name"][:34], fr["entity"]["contracts"], "rank", fr["entity"]["rank"], "mediana", fr["entity"]["median_value"])
        print("  referência:", fr["reference"])
        print("  concorrentes:", [(r["name"][:24], r["count"]) for r in fr["competitors"][:3]])
        print("  compradores:", [(r["name"][:24], r["count"]) for r in fr["counterparties"][:3]])
        print("  top cpv:", [(c["code"], c["count"]) for c in fr["entity"]["top_cpv"][:3]])

print("\n=== por CPV (tudo) ===")
geral = cronometrar("by_cpv", bench.benchmark_by_cpv, countries=["pt", "es", "fr"], top=6)
if not geral.get("error"):
    for p in geral["countries"]:
        print(f"  {p['label']:9} contratos={p['contracts']:>9} com valor={p['priced_contracts']:>9} valor={p['total_value']:>16,.0f} mediana={p['median']}")
    print("  CPV:")
    for row in geral["items"][:5]:
        partes = " | ".join(f"{k}:{v['contracts']}" for k, v in row["by_country"].items())
        print(f"   {row['rank']}. {row['code']:10} {row['description'][:38]:38} total={row['value']:>16,.0f} [{partes}]")
