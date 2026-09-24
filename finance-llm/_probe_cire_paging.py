"""Depura a leitura paginada do CIRE (search_after por pub_id)."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from api.elasticsearch_client import CIRE_INDEX, get_es_client  # noqa: E402

BODY = {
    "size": 3,
    "query": {"exists": {"field": "intervenientes"}},
    "_source": ["pub_id", "intervenientes"],
    "sort": [{"pub_id": "asc"}],
}


def main() -> int:
    es = get_es_client()
    print("count total:", es.count(index=CIRE_INDEX).get("count"))
    try:
        resp = es.search(index=CIRE_INDEX, body=BODY)
        hits = resp["hits"]["hits"]
        print("hits:", len(hits), "| total:", resp["hits"]["total"])
        for hit in hits:
            print("   ", hit["_source"].get("pub_id"), "| sort:", hit.get("sort"), "| intervenientes:",
                  len((hit["_source"].get("intervenientes") or [])))
    except Exception as exc:
        print("ERRO:", type(exc).__name__, exc)

    # Alternativa: agregar sem sort (from/size) para confirmar que o filtro funciona.
    try:
        resp = es.search(index=CIRE_INDEX, body={"size": 2, "query": {"nested": {"path": "intervenientes", "query": {"match_all": {}}}}})
        print("nested match_all hits:", len(resp["hits"]["hits"]), "| total:", resp["hits"]["total"])
    except Exception as exc:
        print("ERRO nested:", type(exc).__name__, exc)
    return 0


if __name__ == "__main__":
    sys.exit(main())
