"""Sonda mínima: cliente ES com vários timeouts."""
from __future__ import annotations

import os

os.environ.setdefault("ELASTICSEARCH_URL", "http://127.0.0.1:9200")

from api import elasticsearch_client as ec  # noqa: E402

print("url:", ec._get_es_url())
for timeout in (30, 120):
    try:
        cliente = ec.get_es_client(request_timeout=timeout)
        print("timeout", timeout, "->", "cliente" if cliente else "None")
    except Exception as exc:  # noqa: BLE001
        print("timeout", timeout, "-> exceção", type(exc).__name__, exc)
