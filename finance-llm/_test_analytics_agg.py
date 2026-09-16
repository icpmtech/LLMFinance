"""Verifica a agregação de tipos de procedimento/contrato (runtime field)."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from api.elasticsearch_client import CONTRACTS_INDEX, get_es_client, get_contract_analytics  # noqa: E402


def main():
    result = get_contract_analytics(year=2025, top_entities=3, top_cpv=3)
    if result.get("error"):
        print("ERRO analytics:", result["error"])
    else:
        print("procedure_types:", [(r["key"], r["count"]) for r in result["procedure_types"][:5]])
        print("contract_types:", [(r["key"], r["count"]) for r in result["contract_types"][:5]])

    es = get_es_client()
    body = {
        "size": 0,
        "query": {"term": {"Ano": 2025}},
        "runtime_mappings": {
            "tipoprocedimento_kw": {
                "type": "keyword",
                "script": {
                    "source": (
                        "if (params._source.containsKey('tipoprocedimento')) {"
                        " def v = params._source.tipoprocedimento;"
                        " if (v instanceof List) { for (def item : v) { if (item != null) emit(item) } }"
                        " else if (v != null) { emit(v) } }"                    )
                },
            }
        },
        "aggs": {"procedure_types": {"terms": {"field": "tipoprocedimento_kw", "size": 5}}},
    }
    try:
        resp = es.search(index=CONTRACTS_INDEX, body=body)
        print("runtime field OK:", [(b["key"], b["doc_count"]) for b in resp["aggregations"]["procedure_types"]["buckets"]])
    except Exception as exc:
        print("ERRO runtime field:", str(exc)[:400])


if __name__ == "__main__":
    main()
