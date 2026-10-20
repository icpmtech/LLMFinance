import json

from api import elasticsearch_client as esc
from api import transparencia_grafo_service as svc

empresa = svc.concelho_detalhe("Lisboa", limite=1)["empresas"][0]
nif = empresa["nif"]
print("empresa", empresa["nome"], nif)
c = esc.get_es_client()
corpo = {
    "size": 0,
    "query": {"nested": {"path": "adjudicatarios.parsed", "query": {"term": {"adjudicatarios.parsed.nif": nif}}}},
    "aggs": {
        "empresas": {
            "nested": {"path": "adjudicatarios.parsed"},
            "aggs": {
                "nifs": {
                    "terms": {"field": "adjudicatarios.parsed.nif", "size": 5},
                    "aggs": {
                        "raiz": {
                            "reverse_nested": {},
                            "aggs": {
                                "valor": {"sum": {"field": "precoContratual"}},
                                "adjudicantes": {
                                    "nested": {"path": "adjudicantes.parsed"},
                                    "aggs": {"nomes": {"terms": {"field": "adjudicantes.parsed.nome.keyword", "size": 3}}},
                                },
                            },
                        }
                    },
                }
            },
        }
    },
}
r = c.search(index=esc.CONTRACTS_INDEX, body=corpo)
print(json.dumps(r.get("aggregations"), ensure_ascii=False)[:2500])
r2 = c.search(index=esc.CONTRACTS_INDEX, body={"size": 1, "query": {"nested": {"path": "adjudicatarios.parsed", "query": {"term": {"adjudicatarios.parsed.nif": nif}}}}})
print(json.dumps(r2["hits"]["hits"][0]["_source"].get("adjudicantes"), ensure_ascii=False)[:600])
