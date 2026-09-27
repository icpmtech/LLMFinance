"""Sonda: variantes de filtro para as partes aninhadas dos contratos PT."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from api.elasticsearch_client import get_es_client  # noqa: E402

es = get_es_client()
if es is None:
    raise SystemExit("ES indisponível")


CASES = {
    "exists adjudicatarios.parsed.nif": {"exists": {"field": "adjudicatarios.parsed.nif"}},
    "exists adjudicatarios.raw": {"exists": {"field": "adjudicatarios.raw"}},
    "nested(path=adjudicatarios.parsed) exists nif": {
        "nested": {"path": "adjudicatarios.parsed", "query": {"exists": {"field": "adjudicatarios.parsed.nif"}}}
    },
    "nested(path=adjudicatarios) exists parsed.nif": {
        "nested": {"path": "adjudicatarios", "query": {"exists": {"field": "adjudicatarios.parsed.nif"}}}
    },
    "nested(path=adjudicatarios) nested(path=parsed) exists nif": {
        "nested": {
            "path": "adjudicatarios",
            "query": {"nested": {"path": "adjudicatarios.parsed", "query": {"exists": {"field": "adjudicatarios.parsed.nif"}}}},
        }
    },
    "term adjudicatarios.raw": {"term": {"adjudicatarios.raw": "x"}},
}

for label, query in CASES.items():
    try:
        count = es.count(index="contratos", body={"query": query})["count"]
        print("{0}: {1}".format(label, count))
    except Exception as exc:
        print("{0}: ERRO {1}".format(label, str(exc)[:200]))

# Uma amostra real, para ver a forma do campo.
resp = es.search(
    index="contratos",
    body={"size": 1, "query": {"match_all": {}}, "_source": ["adjudicatarios"]},
)
print("exemplo adjudicatarios:", str(resp["hits"]["hits"][0]["_source"].get("adjudicatarios"))[:400])
