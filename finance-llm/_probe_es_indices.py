import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from api.elasticsearch_client import get_es_client

OUTPUT = ROOT / "_probe_es_indices.json"


def main() -> None:
    es = get_es_client(request_timeout=30)
    if es is None:
        err = {"error": "Não foi possível ligar ao Elasticsearch"}
        OUTPUT.write_text(json.dumps(err, indent=2, ensure_ascii=False), encoding="utf-8")
        print(json.dumps(err, indent=2, ensure_ascii=False))
        return

    stats = es.indices.stats(metric="docs,store", index="*")
    health = es.cluster.health(level="indices")
    all_indices = es.indices.get(index="*")

    results = []
    for index_name in sorted(all_indices.keys()):
        if index_name.startswith("finance_") or index_name in ("contratos", "contratos_es"):
            doc_count = (
                stats.get("indices", {})
                .get(index_name, {})
                .get("total", {})
                .get("docs", {})
                .get("count", 0)
            )
            index_health = health.get("indices", {}).get(index_name, {}).get("status", "unknown")
            meta = all_indices.get(index_name, {})
            status = meta.get("status", "unknown")
            store_size = (
                stats.get("indices", {})
                .get(index_name, {})
                .get("total", {})
                .get("store", {})
                .get("size_in_bytes", 0)
            )
            results.append(
                {
                    "index": index_name,
                    "docs_count": doc_count,
                    "health": index_health,
                    "status": status,
                    "size_bytes": store_size,
                }
            )

    OUTPUT.write_text(json.dumps(results, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps(results, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
