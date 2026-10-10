"""Sonda da pesquisa de entidades do benchmark (`/benchmark/entities`)."""
from __future__ import annotations

import json
import os
import sys

os.environ.setdefault("ELASTICSEARCH_URL", "http://127.0.0.1:9200")

from api import benchmark_service as bench  # noqa: E402

CASOS = [
    ("pt", "adjudicatario", "BRAUN"),
    ("es", "adjudicatario", "INDRA"),
    ("fr", "adjudicatario", "5421"),
]

for pais, papel, termo in CASOS:
    resultado = bench.search_entities(q=termo, role=papel, country=pais, size=4)
    print("====", pais, papel, termo)
    print(json.dumps(resultado, ensure_ascii=False)[:900])
