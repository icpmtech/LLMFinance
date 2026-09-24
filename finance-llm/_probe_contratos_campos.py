"""Descobre os campos de NIF dos contratos e um NIF com muitas contrapartes."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from api.elasticsearch_client import CONTRACTS_INDEX, get_es_client  # noqa: E402


def main() -> int:
    es = get_es_client()
    mapping = es.indices.get_mapping(index=CONTRACTS_INDEX)[CONTRACTS_INDEX]["mappings"]["properties"]
    nif_fields = [name for name in mapping if "nif" in name.lower() or "nipc" in name.lower()]
    print("campos NIF:", nif_fields[:20])
    for field in nif_fields[:6]:
        try:
            body = {
                "size": 0,
                "aggs": {"top": {"terms": {"field": field, "size": 3}}},
            }
            buckets = es.search(index=CONTRACTS_INDEX, body=body)["aggregations"]["top"]["buckets"]
            print(f"-- {field}:", [(b["key"], b["doc_count"]) for b in buckets])
        except Exception as exc:
            print(f"-- {field}: erro {str(exc)[:110]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
