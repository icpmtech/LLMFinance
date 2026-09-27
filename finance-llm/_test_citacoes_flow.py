"""Fluxo completo do módulo de citações editais: opções → recolha → importação → pesquisa."""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from api import citacoes_service  # noqa: E402
from api.elasticsearch_client import (  # noqa: E402
    CITACOES_INDEX,
    citacoes_status,
    ensure_indices,
    get_es_client,
    search_citacoes,
)

nome = sys.argv[1] if len(sys.argv) > 1 else "MONTEPIO"
meses = int(sys.argv[2]) if len(sys.argv) > 2 else 6
max_pages = int(sys.argv[3]) if len(sys.argv) > 3 else 4

client = get_es_client()
print("ES:", "ok" if client else "indisponível", "| índice:", CITACOES_INDEX)
if client:
    ensure_indices(client)

print("\n--- meta ---")
print(json.dumps({k: v for k, v in citacoes_service.meta().items() if k != "notes"}, ensure_ascii=False)[:500])

print("\n--- opções do portal (5 primeiros tribunais) ---")
opts = citacoes_service.form_options()
print("total serviços:", len(opts.get("tribunais", [])))
print([o["label"] for o in opts.get("tribunais", [])[:4]])
print("dias:", opts.get("dias"))

print(f"\n--- recolha «{nome}» (últimos {meses} meses, max {max_pages} páginas) ---")


def progress(info):
    if info.get("stage") == "collecting":
        print(f"  página {info.get('page')}: {info.get('collected')} éditos · {info.get('declared_total')} no portal")


res = citacoes_service.collect(nome=nome, meses=meses, max_pages=max_pages, on_progress=progress)
meta = res["meta"]
print("run_id:", res["run_id"])
print(
    "collected:", meta["collected"],
    "| declarados:", meta["declared_total"],
    "| páginas:", meta["pages"],
    "| antigos ignorados:", meta["older_than_cutoff"],
    "| duração:", meta["duration_s"], "s",
)
print("erros:", meta["errors"])

if not meta["collected"]:
    print("Nada a importar.")
    raise SystemExit(0)

print("\n--- importação ---")
ing = citacoes_service.ingest_run(res["run_id"])
print(json.dumps(ing, ensure_ascii=False)[:400])

print("\n--- pesquisa ---")
found = search_citacoes(q=nome, size=3)
print("total:", found.get("total"), "| itens:", len(found.get("items", [])))
for item in found.get("items", [])[:3]:
    print(
        f"  {item.get('data_publicacao')} · {item.get('tipo')} · {item.get('citado')} · "
        f"{item.get('tribunal')} · ref {item.get('referencia')} · docs {item.get('has_documento')}"
    )
print("facetas:", {k: len(v) for k, v in (found.get("facets") or {}).items()})

print("\n--- estado ---")
estado = citacoes_status()
print(
    "docs:", estado.get("documents"),
    "| referências:", estado.get("referencias"),
    "| processos:", estado.get("processos"),
    "| tribunais:", estado.get("tribunais"),
    "| intervalo:", estado.get("min_date"), "→", estado.get("max_date"),
)
print("por tipo:", estado.get("by_tipo"))
print("por papel:", (estado.get("by_papel") or [])[:5])

print("\n--- idempotência (reimportar) ---")
again = citacoes_service.ingest_run(res["run_id"])
print("indexados:", again.get("indexed_count"), "| já existiam:", again.get("skipped_existing"), "| total no índice:", again.get("index_total"))

print("\n--- recolhas em disco ---")
for run in citacoes_service.runs_with_index_counts(5):
    print(f"  {run['run_id']} · {run.get('collected')} itens · índice {run.get('index_count')}")
