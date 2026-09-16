"""Confirma, via API em execução, o grupo 'Não especificado' no grafo e na rede regional."""
import json
import urllib.parse
import urllib.request

BASE = "http://127.0.0.1:8002"


def get(path):
    with urllib.request.urlopen(f"{BASE}{path}", timeout=180) as response:
        return json.loads(response.read().decode("utf-8"))


def main():
    graph = get("/contracts/analytics/graph?dimension_a=regiao&year=2025&mode=exato&limit=0")
    node = next((n for n in graph["nodes"] if n["key"] == "Não especificado"), None)
    print("exato regiao (2025): nós =", len(graph["nodes"]))
    print("  grupo:", json.dumps(node, ensure_ascii=False) if node else "ausente")

    region = urllib.parse.quote("Não especificado")
    network = get(f"/contracts/analytics/network?limit=300&region={region}")
    print("rede da região 'Não especificado': nós =", len(network["nodes"]), "arestas =", len(network["edges"]))
    relations = get(f"/contracts/analytics/relations?limit=500&region={region}")
    print("relações:", len(relations["relations"]))

    pair = get(
        "/contracts/analytics/graph?dimension_a=regiao&dimension_b=tipo_contrato&year=2025&mode=exato&limit=0"
    )
    print(
        "exato regiao x tipo_contrato: nós =",
        len(pair["nodes"]),
        "arestas =",
        len(pair["edges"]),
        "| grupo presente:",
        any(n["key"] == "Não especificado" for n in pair["nodes"]),
    )


if __name__ == "__main__":
    main()
