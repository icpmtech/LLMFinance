"""Sonda de custo da agregação de empresas (contratos) com diferentes filtros."""
from __future__ import annotations

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from api import ontology_service as ontology  # noqa: E402
from api.elasticsearch_client import get_es_client  # noqa: E402


def timed(label: str, fn) -> None:
    ontology.clear_cache()
    started = time.time()
    try:
        result = fn()
        elapsed = (time.time() - started) * 1000
        print(f"  {label:46s} {elapsed:7.0f} ms  total={result.get('total')} erro={result.get('error', '-')}")
    except Exception as exc:
        print(f"  {label:46s} EXCEÇÃO {type(exc).__name__}: {exc}")


def raw_agg(label: str, query: dict, size: int) -> None:
    es = get_es_client()
    started = time.time()
    try:
        resp = es.search(
            index="contratos",
            body={
                "size": 0,
                "query": query,
                "aggs": {
                    "a": {
                        "nested": {"path": "adjudicantes.parsed"},
                        "aggs": {"por_nif": {"terms": {"field": "adjudicantes.parsed.nif", "size": size, "order": {"_count": "desc"}},
                                             "aggs": {"nome": {"top_hits": {"size": 1, "_source": ["adjudicantes.parsed.nome"]}}}}},
                    }
                },
            },
            request_timeout=60,
        )
        elapsed = (time.time() - started) * 1000
        buckets = resp["aggregations"]["a"]["por_nif"]["buckets"]
        print(f"  {label:46s} {elapsed:7.0f} ms  buckets={len(buckets)} top={buckets[0]['key'] if buckets else '-'} count={buckets[0]['doc_count'] if buckets else '-'}")
    except Exception as exc:
        print(f"  {label:46s} EXCEÇÃO {type(exc).__name__}: {exc}")


def main() -> int:
    print("== agregação da ontologia ==")
    timed("sem filtros (size 150)", lambda: ontology.query_objects("empresa", size=3))
    timed("ano=2025", lambda: ontology.query_objects("empresa", filters={"ano": 2025}, size=3))
    timed("ano=2026", lambda: ontology.query_objects("empresa", filters={"ano": 2026}, size=3))
    timed("regiao=Lisboa", lambda: ontology.query_objects("empresa", filters={"regiao": "Lisboa"}, size=3))
    timed("search=EDP", lambda: ontology.query_objects("empresa", search="EDP", size=3))

    print("== agregação crua (um lado, sem reverse_nested) ==")
    raw_agg("match_all, size 150", {"match_all": {}}, 150)
    raw_agg("match_all, size 25", {"match_all": {}}, 25)
    raw_agg("ano=2025, size 150", {"term": {"Ano": 2025}}, 150)
    raw_agg("range ano>=2024, size 150", {"range": {"Ano": {"gte": 2024}}}, 150)
    raw_agg("Ano=2026, size 150", {"term": {"Ano": 2026}}, 150)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
