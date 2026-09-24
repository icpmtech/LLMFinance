"""Mede o volume de ocorrências (interveniente × publicação) de pessoas no CIRE.

Necessário para dimensionar a memória da extração de pessoas do CIRE:
quantas fichas e quantos cargos serão construídos em `finance_people`.
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from api.elasticsearch_client import CIRE_INDEX, get_es_client  # noqa: E402

PESSOA = [{"prefix": {"intervenientes.nif": p}} for p in ("1", "2", "3")]
EMPRESA = [{"prefix": {"intervenientes.nif": p}} for p in ("5", "6", "7", "9")]


def nested_count(es, should, label):
    body = {
        "size": 0,
        "track_total_hits": True,
        "query": {
            "nested": {
                "path": "intervenientes",
                "query": {"bool": {"should": should, "minimum_should_match": 1}},
            }
        },
    }
    total = es.search(index=CIRE_INDEX, body=body)["hits"]["total"]["value"]
    print(f"{label}: {total:,} ocorrências")
    return total


def main() -> int:
    es = get_es_client()
    nested_count(es, PESSOA, "Intervenientes pessoa singular")
    nested_count(es, EMPRESA, "Intervenientes pessoa coletiva")
    body = {
        "size": 0,
        "aggs": {
            "i": {
                "nested": {"path": "intervenientes"},
                "aggs": {
                    "f": {
                        "filter": {"bool": {"should": PESSOA, "minimum_should_match": 1}},
                        "aggs": {"top": {"terms": {"field": "intervenientes.nif", "size": 10}}},
                    }
                },
            }
        },
    }
    out = es.search(index=CIRE_INDEX, body=body)["aggregations"]["i"]["f"]["top"]["buckets"]
    print("NIF pessoa com mais processos:")
    for bucket in out:
        print(f"   {bucket['key']}: {bucket['doc_count']:,}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
