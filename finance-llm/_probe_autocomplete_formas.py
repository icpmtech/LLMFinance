"""Sonda: (a) versão do ES, (b) formas válidas do `include`, (c) prefix nested real."""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from api.elasticsearch_client import CONTRACTS_INDEX, get_es_client  # noqa: E402

cliente = get_es_client()
print("info:", json.dumps(cliente.info()["version"], ensure_ascii=False))
print("indices contratos*:", json.dumps(list(cliente.cat.indices(index="contratos*", format="json", h="index,docs.count,store.size")), ensure_ascii=False))


def contar(rotulo: str, corpo: dict) -> None:
    resposta = cliente.search(index=CONTRACTS_INDEX, body=corpo)
    print(f"{rotulo}: {resposta['hits']['total']['value']}")


# prefix nested real: «Município» como adjudicante, «JAN» como adjudicatário
for papel in ("adjudicantes", "adjudicatarios"):
    for termo in ("Munic", "JAN", "janssen"):
        contar(
            f"prefix {papel} {termo!r}",
            {
                "size": 0,
                "track_total_hits": True,
                "query": {"nested": {"path": f"{papel}.parsed", "query": {"prefix": {f"{papel}.parsed.nome": {"value": termo, "case_insensitive": True}}}}},
            },
        )

# formas do include na agregação de nomes
formas = {
    "objeto pattern+flags": {"pattern": ".*janssen.*", "flags": "CASE_INSENSITIVE"},
    "objeto regexp+flags": {"regexp": ".*janssen.*", "flags": "CASE_INSENSITIVE"},
    "objeto pattern só": {"pattern": ".*janssen.*"},
    "string (?i)": "(?i).*janssen.*",
    "string simples": ".*janssen.*",
    "string prefixo": "JANSSEN.*",
}
for rotulo, include in formas.items():
    try:
        resposta = cliente.search(
            index=CONTRACTS_INDEX,
            body={
                "size": 0,
                "query": {"match_all": {}},
                "aggs": {
                    "adjudicantes": {
                        "nested": {"path": "adjudicantes.parsed"},
                        "aggs": {"names": {"terms": {"field": "adjudicantes.parsed.nome", "size": 8, "include": include}}},
                    }
                },
            },
        )
        baldes = resposta["aggregations"]["adjudicantes"]["names"]["buckets"]
        print(f"include {rotulo}: {len(baldes)} baldes {[b['key'] for b in baldes[:3]]}")
    except Exception as erro:  # noqa: BLE001
        print(f"include {rotulo}: ERRO {str(erro)[:110]}")

# agg simples sem include (prova que a nested agg funciona)
resposta = cliente.search(
    index=CONTRACTS_INDEX,
    body={
        "size": 0,
        "query": {"match_all": {}},
        "aggs": {
            "adjudicantes": {
                "nested": {"path": "adjudicantes.parsed"},
                "aggs": {"names": {"terms": {"field": "adjudicantes.parsed.nome", "size": 4}}},
            }
        },
    },
)
print("sem include:", json.dumps([b["key"] for b in resposta["aggregations"]["adjudicantes"]["names"]["buckets"]], ensure_ascii=False))
