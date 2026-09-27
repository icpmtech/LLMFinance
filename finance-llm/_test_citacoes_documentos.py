"""Recolha com extração de PDF + grafo + mapa (validação do backend)."""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from api import citacoes_service as s  # noqa: E402

nome = sys.argv[1] if len(sys.argv) > 1 else "MONTEPIO"
meses = int(sys.argv[2]) if len(sys.argv) > 2 else 6

print(f"=== recolha «{nome}» (últimos {meses} meses, com extração de PDF) ===", flush=True)


def progress(info):
    if info.get("stage") == "collecting":
        print(f"  página {info.get('page')}: {info.get('collected')} éditos ({info.get('declared_total')} no portal)", flush=True)
    elif info.get("stage") == "documentos":
        titulo = (info.get("titulo") or "")[:40]
        print(
            f"  documento {info.get('documento')}/{info.get('documentos')} "
            f"ref {info.get('referencia')} {titulo} {'ok' if info.get('ok') else 'ERRO'}",
            flush=True,
        )

res = s.collect(nome=nome, meses=meses, max_pages=200, on_progress=progress)
meta = res["meta"]
print(
    f"\nrecolha {res['run_id']}: {meta['collected']} éditos · "
    f"docs extraídos {meta['documentos_extraidos']} (falhados {meta['documentos_falhados']}) · "
    f"{meta['documentos_caracteres']} caracteres · {meta['duration_s']}s",
    flush=True,
)

ing = s.ingest_run(res["run_id"])
print("importação:", {k: ing.get(k) for k in ("indexed_count", "skipped_existing", "index_total")}, flush=True)

estado = s.status()
print("\n=== estado ===")
print(
    "docs:", estado.get("documents"), "| com texto:", estado.get("with_texto"),
    "| com valor:", estado.get("with_valor"), "| NIF distintos:", estado.get("nifs"),
)
print("valor total:", estado.get("valor_total"), "| médio:", estado.get("valor_medio"), "| máximo:", estado.get("valor_maximo"))
print("comarcas judiciais:", estado.get("top_comarcas_judiciais")[:5])
print("modelos:", estado.get("top_modelos")[:5])

print("\n=== grafo (parte ativa → parte passiva) ===")
g = s.grafo(dimension_a="parte_ativa", dimension_b="parte_passiva", limit=8, edge_limit=8)
print("nós:", len(g.get("nodes", [])), "arestas:", len(g.get("edges", [])))
for node in g.get("nodes", [])[:6]:
    print(f"  {node['type']:10} {node['label'][:44]:46} éditos {node['count']} valor {node['valor']}")
for edge in g.get("edges", [])[:4]:
    print(f"  {edge['source']} -> {edge['target']} ({edge['count']})")

print("\n=== grafo (co-ocorrência de intervenientes) ===")
g2 = s.grafo(dimension_a="interveniente", dimension_b="interveniente", limit=6, edge_limit=6)
print("nós:", len(g2.get("nodes", [])), "arestas:", len(g2.get("edges", [])))
for edge in g2.get("edges", [])[:4]:
    print("  ", edge["source"], "<->", edge["target"], edge["count"])

print("\n=== mapa (sede) ===")
m = s.mapa(nivel="sede")
print("totais:", json.dumps(m.get("totals", {}), ensure_ascii=False)[:300])
for p in m.get("points", [])[:8]:
    print(f"  {p['label'][:34]:36} {p['count']:4} éditos · {p['lat']},{p['lon']} · valor {p['valor']}")
print("sem localização:", [(p["label"], p["count"]) for p in m.get("sem_localizacao", [])][:5])

print("\n=== mapa (comarca) ===")
m2 = s.mapa(nivel="comarca")
for p in m2.get("points", [])[:6]:
    print(f"  {p['label'][:34]:36} {p['count']:4} éditos · {p['lat']},{p['lon']}")
print("sem localização:", [(p["label"], p["count"]) for p in m2.get("sem_localizacao", [])][:5])

print("\n=== texto de um documento ===")
achado = s.search(has_texto=True, size=1, with_texto=False)
if achado.get("items"):
    item = achado["items"][0]
    doc = s.texto_documento(item["pub_id"])
    print("pub_id:", doc.get("pub_id"), "| título:", doc.get("titulo"), "| modelo:", doc.get("modelo"))
    print("valor:", doc.get("valor"), "| prazo:", doc.get("prazo"), "| NIF:", doc.get("nifs"))
    print("partes:", json.dumps(doc.get("partes"), ensure_ascii=False)[:200])
    print("texto (300):", (doc.get("texto") or "")[:300].replace("\n", " "))
