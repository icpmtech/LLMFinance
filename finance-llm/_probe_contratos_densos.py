"""Procura um NIF com muitos contratos (para testar grafos densos)."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from api.elasticsearch_client import CONTRACTS_INDEX, get_es_client  # noqa: E402


def main() -> int:
    es = get_es_client()
    body = {
        "size": 0,
        "aggs": {
            "por_nif": {
                "terms": {"field": "adjudicante_nif", "size": 5},
                "aggs": {"contrapartes": {"cardinality": {"field": "adjudicatario_nif"}}},
            }
        },
    }
    try:
        buckets = es.search(index=CONTRACTS_INDEX, body=body)["aggregations"]["por_nif"]["buckets"]
    except Exception as exc:
        print("falhou:", exc)
        return 1
    for bucket in buckets:
        print(bucket["key"], "| contratos:", bucket["doc_count"], "| contrapartes distintas:",
              bucket["contrapartes"]["value"])
    return 0


if __name__ == "__main__":
    sys.exit(main())
