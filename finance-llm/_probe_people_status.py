"""Depura `people_status` e a pesquisa por cargo depois da ingestão do CIRE."""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from api.elasticsearch_client import PEOPLE_INDEX, get_es_client, people_status, search_people  # noqa: E402


def main() -> int:
    print("status:", json.dumps(people_status(), ensure_ascii=False)[:1200])
    es = get_es_client()
    print("count:", es.count(index=PEOPLE_INDEX))
    body = {
        "size": 0,
        "aggs": {"roles": {"nested": {"path": "roles"}, "aggs": {"r": {"terms": {"field": "roles.role", "size": 10}}}}},
    }
    try:
        print("aggs:", json.dumps(es.search(index=PEOPLE_INDEX, body=body)["aggregations"], ensure_ascii=False)[:600])
    except Exception as exc:
        print("ERRO aggs:", exc)
    try:
        print("mapping roles:", json.dumps(es.indices.get_mapping(index=PEOPLE_INDEX)[PEOPLE_INDEX]["mappings"]["properties"].get("roles"), ensure_ascii=False))
    except Exception as exc:
        print("ERRO mapping:", exc)
    for role in ("Administrador da insolvência", "credor", "Credor"):
        page = search_people(role=role, size=2)
        print(f"search role={role!r}:", page.get("total"), page.get("error"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
