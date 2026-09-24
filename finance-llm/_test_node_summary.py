"""Testa o resumo de um nó de grafo (IA + web) e a respetiva gravação no Elasticsearch.

Uso:
    python _test_node_summary.py ["Nome da pessoa"] [NIF]
"""
import asyncio
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from api.elasticsearch_client import get_node_summary, search_people  # noqa: E402
from api.node_summary import node_summary, saved_summary  # noqa: E402

NAME = "Pedro Manuel Gomes Ortins de Bettencourt"


def main() -> int:
    name = sys.argv[1] if len(sys.argv) > 1 else NAME
    nif = sys.argv[2] if len(sys.argv) > 2 else ""

    if not nif:
        page = search_people(q=name, size=5)
        print(f"procura por «{name}»: {page.get('total')} resultado(s)")
        for item in page.get("items") or []:
            print("  -", item.get("nif"), item.get("name"), "| cargos:", item.get("roles_count"))
        items = page.get("items") or []
        if not items:
            print("Pessoa não encontrada no PessoasIQ.")
            return 1
        nif = str(items[0]["nif"])
        name = str(items[0].get("name") or name)

    node_id = f"person:{nif}"
    print(f"\n=== resumo de {node_id} ({name}) ===")
    result = asyncio.run(node_summary(node_id=node_id, nif=nif, name=name, pages=2))
    print("modo:", result.get("mode"), "| guardado:", result.get("saved"), "| geração:", result.get("generations"))
    print("evidência:", result.get("evidence_count"), "| páginas lidas:", result.get("pages_read"))
    print("avisos:", result.get("warnings"))
    print("notas:", result.get("notes"))
    print("\n--- resumo ---")
    print((result.get("summary") or "")[:2500])

    stored = get_node_summary(node_id)
    print("\n=== gravado no Elasticsearch ===")
    print("node_id:", stored.get("node_id"), "| modo:", stored.get("mode"), "| geração:", stored.get("generations"))
    print("tamanho do resumo:", len(stored.get("summary") or ""), "carateres | evidência guardada:", len(stored.get("evidence") or []))
    print("factos guardados:", sorted((stored.get("facts") or {}).keys()))

    again = saved_summary(node_id=node_id)
    print("leitura pelo endpoint (saved_summary): encontrado =", again.get("found"), "| modo:", again.get("mode"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
