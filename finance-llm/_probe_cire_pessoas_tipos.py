"""Mede a composição dos intervenientes do CIRE por papel e tipo de NIF.

Serve para dimensionar a ingestão de pessoas do CIRE no PessoasIQ
(`finance_people`) — quantas pessoas singulares distintas existem por papel.
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from api.elasticsearch_client import CIRE_INDEX, get_es_client  # noqa: E402

PAPEIS = ["Administrador Insolvência", "Insolvente", "Devedor", "Requerente", "Credor"]
PESSOA = [{"prefix": {"intervenientes.nif": p}} for p in ("1", "2", "3")]
EMPRESA = [{"prefix": {"intervenientes.nif": p}} for p in ("5", "6", "7", "9")]


def distinct(es, papel, prefixes):
    query = {
        "bool": {
            "must": [{"term": {"intervenientes.papel": papel}}],
            "should": prefixes,
            "minimum_should_match": 1,
        }
    }
    body = {
        "size": 0,
        "aggs": {
            "i": {
                "nested": {"path": "intervenientes"},
                "aggs": {"f": {"filter": query, "aggs": {"u": {"cardinality": {"field": "intervenientes.nif"}}}}},
            }
        },
    }
    return es.search(index=CIRE_INDEX, body=body)["aggregations"]["i"]["f"]["u"]["value"]


def main() -> int:
    es = get_es_client()
    print(f"Credor pessoa (calibração): ~{distinct(es, 'Credor', PESSOA):,}")
    for papel in PAPEIS:
        pessoa = distinct(es, papel, PESSOA)
        empresa = distinct(es, papel, EMPRESA)
        print(f"{papel:28s} pessoa=~{pessoa:>7,}  empresa=~{empresa:>7,}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
