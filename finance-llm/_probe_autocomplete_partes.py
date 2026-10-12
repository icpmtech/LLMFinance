"""Sonda: isolar as duas metades do autocomplete (consulta nested e agregação)."""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from api.elasticsearch_client import CONTRACTS_INDEX, get_es_client  # noqa: E402

cliente = get_es_client()
q = "jan"


def contar(rotulo: str, corpo: dict) -> None:
    resposta = cliente.search(index=CONTRACTS_INDEX, body=corpo)
    total = resposta["hits"]["total"]["value"]
    print(f"{rotulo}: {total}")


# 1. prefix nested (case_insensitive)
contar(
    "prefix nested case_insensitive",
    {
        "size": 0,
        "track_total_hits": True,
        "query": {"nested": {"path": "adjudicantes.parsed", "query": {"prefix": {"adjudicantes.parsed.nome": {"value": q, "case_insensitive": True}}}}},
    },
)
# 2. prefix nested exato (sem case_insensitive)
contar(
    "prefix nested exato 'JAN'",
    {
        "size": 0,
        "track_total_hits": True,
        "query": {"nested": {"path": "adjudicantes.parsed", "query": {"prefix": {"adjudicantes.parsed.nome": {"value": "JAN"}}}}},
    },
)
# 3. term exato
contar(
    "term exato 'JANSSEN CILAG FARMACEUTICA'",
    {
        "size": 0,
        "track_total_hits": True,
        "query": {"nested": {"path": "adjudicantes.parsed", "query": {"term": {"adjudicantes.parsed.nome": "JANSSEN CILAG FARMACEUTICA"}}}},
    },
)

# 4. agregação isolada (sem consulta) com include por regex
resposta = cliente.search(
    index=CONTRACTS_INDEX,
    body={
        "size": 0,
        "query": {"match_all": {}},
        "aggs": {
            "adjudicantes": {
                "nested": {"path": "adjudicantes.parsed"},
                "aggs": {"names": {"terms": {"field": "adjudicantes.parsed.nome", "size": 5, "include": f"(?i).*{q}.*"}}},
            }
        },
    },
)
baldes = resposta["aggregations"]["adjudicantes"]["names"]["buckets"]
print("agg include regex (match_all):", json.dumps(baldes, ensure_ascii=False)[:300])

# 5. agregação sobre os docs da consulta prefix (sem include)
resposta2 = cliente.search(
    index=CONTRACTS_INDEX,
    body={
        "size": 0,
        "query": {"nested": {"path": "adjudicantes.parsed", "query": {"prefix": {"adjudicantes.parsed.nome": {"value": "JAN", "case_insensitive": True}}}}},
        "aggs": {
            "adjudicantes": {
                "nested": {"path": "adjudicantes.parsed"},
                "aggs": {"names": {"terms": {"field": "adjudicantes.parsed.nome", "size": 5}}},
            }
        },
    },
)
baldes2 = resposta2["aggregations"]["adjudicantes"]["names"]["buckets"]
print("agg sem include sobre a consulta:", json.dumps(baldes2, ensure_ascii=False)[:300])
