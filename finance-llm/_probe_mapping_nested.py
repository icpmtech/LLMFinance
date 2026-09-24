"""Testa, num índice temporário, a adição de campos novos (topo e dentro de `nested`)."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from api.elasticsearch_client import get_es_client  # noqa: E402

INDEX = "tmp-mapping-probe"


def main() -> int:
    es = get_es_client()
    if es.indices.exists(index=INDEX):
        es.indices.delete(index=INDEX)
    es.indices.create(index=INDEX, body={"mappings": {"properties": {
        "nif": {"type": "keyword"},
        "roles": {"type": "nested", "properties": {"role": {"type": "keyword"}}},
    }}})

    from api.elasticsearch_client import _missing_mapping_fields

    existing = es.indices.get_mapping(index=INDEX)[INDEX]["mappings"]["properties"]
    spec = {
        "nif": {"type": "keyword"},
        "sources": {"type": "keyword"},
        "roles": {"type": "nested", "properties": {
            "role": {"type": "keyword"},
            "tribunal": {"type": "keyword", "ignore_above": 512},
        }},
    }
    missing = _missing_mapping_fields(existing, spec)
    print("missing:", missing)
    try:
        es.indices.put_mapping(index=INDEX, body={"properties": missing})
        print("put_mapping OK")
    except Exception as exc:
        print("put_mapping ERRO:", type(exc).__name__, str(exc)[:600])
    print("resultado:", es.indices.get_mapping(index=INDEX)[INDEX]["mappings"]["properties"])
    es.indices.delete(index=INDEX)
    return 0


if __name__ == "__main__":
    sys.exit(main())
