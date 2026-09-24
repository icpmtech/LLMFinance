"""Descobrir a API do leidata.gleif.org (raiz, docs, openapi)."""
from __future__ import annotations

import httpx

URLS = [
    "https://leidata.gleif.org/api/v1/",
    "https://leidata.gleif.org/api/",
    "https://leidata.gleif.org/",
    "https://leidata.gleif.org/api/v1/openapi.json",
    "https://leidata.gleif.org/api/v1/swagger.json",
    "https://leidata.gleif.org/api/v1/docs",
    "https://leidata.gleif.org/api/v1/golden-copy",
    "https://leidata.gleif.org/api/v1/gleif-golden-copy",
    "https://leidata.gleif.org/api/v1/lei-cdf/latest",
]

with httpx.Client(timeout=25, follow_redirects=True) as client:
    for url in URLS:
        try:
            r = client.get(url)
            body = r.text[:400].replace("\n", " ")
            print(f"GET {url} -> {r.status_code} {r.headers.get('content-type')}\n    {body}\n")
        except Exception as exc:  # noqa: BLE001
            print(f"GET {url} -> ERR {exc}\n")
