"""Sonda: imprime o corpo que falha na pesquisa do grafo do comprador."""
from __future__ import annotations

import json
import os
import sys

os.environ.setdefault("ELASTICSEARCH_URL", "http://127.0.0.1:9200")

from api import benchmark_service as bench  # noqa: E402
from api.elasticsearch_client import get_es_client  # noqa: E402

cliente = get_es_client(request_timeout=60)
original = cliente.search


def espiao(**kwargs):  # noqa: ANN003
    try:
        return original(**kwargs)
    except Exception:
        corpo = kwargs.get("body") or {}
        if "do_mercado" in (corpo.get("aggs") or {}):
            print(json.dumps(corpo, ensure_ascii=False, indent=2))
        raise


cliente.search = espiao  # type: ignore[assignment]
resultado = bench.benchmark_buyer_graph(
    nif=sys.argv[1] if len(sys.argv) > 1 else "508142156", country="pt", es=cliente, top_suppliers=3, top_clients=3
)
print("erro:", resultado.get("error"))
