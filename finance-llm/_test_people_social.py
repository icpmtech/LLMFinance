"""Testa a recolha de dados públicos e a análise 360 de uma pessoa do PessoasIQ.

Uso:
    python _test_people_social.py [NIF] [limite_paginas]

Sem NIF, procura uma pessoa pelo nome e usa a primeira (de preferência com
cargos de gestão, que dá mais matéria à análise).
"""
import asyncio
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from api.elasticsearch_client import search_people  # noqa: E402
from api.people_360 import person_360  # noqa: E402
from api.people_social import collect_person_social  # noqa: E402


def pick_person() -> str:
    page = search_people(q="Wilson Mendes", size=5)
    for item in page.get("items") or []:
        print("candidato:", item.get("nif"), item.get("name"), "| cargos:", item.get("roles_count"))
    items = page.get("items") or []
    return str(items[0]["nif"]) if items else ""


def main() -> int:
    nif = (sys.argv[1] if len(sys.argv) > 1 else "") or pick_person()
    limit = int(sys.argv[2]) if len(sys.argv) > 2 else 3
    if not nif:
        print("Nenhuma pessoa encontrada.")
        return 1
    print(f"\n=== recolha pública de {nif} (limite {limit} páginas/fonte) ===")
    collected = collect_person_social(nif, sources=None, limit=limit)
    print(json.dumps({k: v for k, v in collected.items() if k != "queries"}, ensure_ascii=False, indent=2)[:4000])
    print("consultas:", json.dumps(collected.get("queries"), ensure_ascii=False)[:600])

    print("\n=== análise 360 (sem IA) ===")
    report = asyncio.run(person_360(nif, with_ai=False))
    print("risco:", json.dumps(report.get("risk"), ensure_ascii=False)[:800])
    print("cire total:", (report.get("cire") or {}).get("total"), "| papeis:", (report.get("cire") or {}).get("by_papel"))
    print("social total:", (report.get("social") or {}).get("total"), "| imagens:", len((report.get("social") or {}).get("images") or []))
    print("grafo:", (report.get("graph") or {}).get("node_count"), "nós /", (report.get("graph") or {}).get("edge_count"), "arestas")
    print("\n--- ficha analítica ---")
    print((report.get("analysis") or {}).get("text", "")[:3000])
    return 0


if __name__ == "__main__":
    sys.exit(main())
