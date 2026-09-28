"""Isolar qual parte da agregação de empresas estoura o circuit breaker do ES."""
from __future__ import annotations

import json
import os

os.environ.setdefault("ELASTICSEARCH_URL", "http://127.0.0.1:9200")

from api.elasticsearch_client import PEOPLE_INDEX, get_es_client  # noqa: E402

NIF = "503106542"
QUERY = {"nested": {"path": "roles", "query": {"term": {"roles.company_nif": NIF}}}}

VARIANTES = {
    "1. só filtro": {"size": 0, "query": QUERY, "track_total_hits": True},
    "2. filtro + terms": {
        "size": 0,
        "query": QUERY,
        "aggs": {"r": {"nested": {"path": "roles"}, "aggs": {"por": {"terms": {"field": "roles.company_nif", "size": 5}}}}},
    },
    "3. + reverse_nested/cardinality": {
        "size": 0,
        "query": QUERY,
        "aggs": {
            "r": {
                "nested": {"path": "roles"},
                "aggs": {
                    "por": {
                        "terms": {"field": "roles.company_nif", "size": 5},
                        "aggs": {
                            "pessoas": {"reverse_nested": {}, "aggs": {"d": {"cardinality": {"field": "nif"}}}},
                            "cargos": {"value_count": {"field": "roles.publication_id"}},
                        },
                    }
                },
            }
        },
    },
    "4. + top_hits": {
        "size": 0,
        "query": QUERY,
        "aggs": {
            "r": {
                "nested": {"path": "roles"},
                "aggs": {
                    "por": {
                        "terms": {"field": "roles.company_nif", "size": 5},
                        "aggs": {
                            "pessoas": {"reverse_nested": {}, "aggs": {"d": {"cardinality": {"field": "nif"}}}},
                            "cargos": {"value_count": {"field": "roles.publication_id"}},
                            "nome": {"top_hits": {"size": 1, "_source": {"includes": ["company_name"]}}},
                        },
                    }
                },
            }
        },
    },
    "5. filtro por nome (match) + aggs": {
        "size": 0,
        "query": {"nested": {"path": "roles", "query": {"match": {"roles.company_name": "JAJA"}}}},
        "aggs": {
            "r": {
                "nested": {"path": "roles"},
                "aggs": {
                    "por": {
                        "terms": {"field": "roles.company_nif", "size": 5},
                        "aggs": {
                            "pessoas": {"reverse_nested": {}, "aggs": {"d": {"cardinality": {"field": "nif"}}}},
                            "nome": {"top_hits": {"size": 1, "_source": {"includes": ["company_name"]}}},
                        },
                    }
                },
            }
        },
    },
    "6. sem nested agg (terms direto no campo nested)": {
        "size": 0,
        "query": QUERY,
        "aggs": {"por": {"terms": {"field": "roles.company_nif", "size": 5}}},
    },
    "7. latest_roles (objeto simples?)": {
        "size": 0,
        "query": QUERY,
        "aggs": {"por": {"terms": {"field": "latest_roles.company_nif", "size": 5}}},
    },
}

if __name__ == "__main__":
    client = get_es_client()
    for nome, body in VARIANTES.items():
        try:
            resp = client.search(index=PEOPLE_INDEX, body=body)
            total = (resp.get("hits", {}).get("total") or {})
            aggs = resp.get("aggregations")
            resumo = "ok"
            if nome.startswith("1."):
                resumo = f"docs={total.get('value')}"
            elif aggs:
                resumo = json.dumps(aggs, ensure_ascii=False)[:260]
            elif total:
                resumo = f"docs={total.get('value')}"
            print(f"{nome}: {resumo}")
        except Exception as exc:  # noqa: BLE001
            print(f"{nome}: FALHOU -> {str(exc)[:180]}")
