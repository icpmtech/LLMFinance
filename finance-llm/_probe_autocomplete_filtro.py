"""Sonda: verificar o filtro em Python do autocomplete (porque passou «Unidade Local de Saúde do Norte»?)."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from api import elasticsearch_client as ec  # noqa: E402
from api.elasticsearch_client import CONTRACTS_INDEX, get_es_client  # noqa: E402

cliente = get_es_client()
resposta = cliente.search(
    index=CONTRACTS_INDEX,
    body={
        "size": 0,
        "query": {
            "bool": {
                "should": [
                    {"match_phrase_prefix": {"objectoContrato": "jan"}},
                    {"match_phrase_prefix": {"descContrato": "jan"}},
                    {
                        "bool": {
                            "should": [
                                {"nested": {"path": "adjudicantes.parsed", "query": {"prefix": {"adjudicantes.parsed.nome": {"value": "jan", "case_insensitive": True}}}}},
                                {"nested": {"path": "adjudicatarios.parsed", "query": {"prefix": {"adjudicatarios.parsed.nome": {"value": "jan", "case_insensitive": True}}}}},
                            ],
                            "minimum_should_match": 1,
                        }
                    },
                ],
                "minimum_should_match": 1,
            }
        },
        "aggs": {
            "adjudicantes": {
                "nested": {"path": "adjudicantes.parsed"},
                "aggs": {"names": {"terms": {"field": "adjudicantes.parsed.nome", "size": 8, "order": {"_count": "desc"}}}},
            }
        },
    },
)
print("total de documentos que casam:", resposta["hits"]["total"]["value"])
for balde in resposta["aggregations"]["adjudicantes"]["names"]["buckets"]:
    texto = balde["key"]
    print(f"{balde['doc_count']:>7} {'OK ' if 'jan' in texto.lower() else 'FORA'} {texto!r}")

print("\nsugestões do endpoint:")
print(ec.contracts_autocomplete("jan", size=6))
