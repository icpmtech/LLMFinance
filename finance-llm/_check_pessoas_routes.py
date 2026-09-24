"""Verificação rápida das rotas do PessoasIQ (tempos e conteúdo essencial)."""
import sys
import time
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

BASE = "http://127.0.0.1:8002"
CHECKS = [
    ("status", "/people/status"),
    ("grafo 599 cargos", "/people/198126450/graph"),
    ("grafo empresa", "/people/company/501854495/graph"),
    ("360 (factual)", "/people/166577626/360?with_ai=false"),
    ("resumo guardado", "/people/summary?node_id=person:166577626"),
    ("pesquisa", "/people/search?q=Wilson%20Jos%C3%A9%20Gabriel%20Mendes&size=3"),
    ("social", "/people/186037457/social?size=20"),
]


def main() -> int:
    for label, path in CHECKS:
        started = time.time()
        try:
            response = httpx.get(BASE + path, timeout=180)
        except Exception as exc:
            print(f"{label:18s} ERRO {exc}")
            continue
        elapsed = time.time() - started
        extra = ""
        if response.status_code == 200:
            data = response.json()
            if isinstance(data, dict):
                if "node_count" in data:
                    extra = f"{data['node_count']} nós/{data['edge_count']} arestas"
                elif "documents" in data:
                    extra = f"{data['documents']} fichas"
                elif "risk" in data:
                    extra = f"risco {data['risk']['score']} ({data['risk']['level']})"
                elif "found" in data:
                    extra = f"found={data['found']} modo={data.get('mode')}"
                elif "total" in data:
                    extra = f"total {data['total']}"
        print(f"{label:18s} {response.status_code} {elapsed:.2f}s {extra}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
