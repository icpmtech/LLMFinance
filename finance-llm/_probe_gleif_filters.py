"""Sondar a sintaxe de filtros da API do GLEIF (paginação profunda)."""
from __future__ import annotations

import httpx

BASE = "https://api.gleif.org/api/v1/lei-records"

TESTS = [
    {"filter[registration.initialRegistrationDate]": "gte:2024-01-01"},
    {"filter[registration.initialRegistrationDate]": "gte:2024-01-01,lte:2024-12-31"},
    {"filter[entity.legalAddress.region]": "PT-11"},
    {"filter[entity.status]": "ACTIVE"},
    {"filter[entity.legalAddress.country]": "PT", "filter[entity.status]": "ACTIVE"},
]

with httpx.Client(timeout=40) as client:
    for params in TESTS:
        params = {**params, "page[size]": 1}
        try:
            r = client.get(BASE, params=params)
            if r.status_code == 200:
                print(f"OK  {params} -> total={r.json()['meta']['pagination']['total']}")
            else:
                print(f"ERR {r.status_code} {params} -> {r.text[:200]}")
        except Exception as exc:  # noqa: BLE001
            print(f"EXC {params} -> {exc}")
    # Limite de paginação: página 51 com size 200
    r = client.get(BASE, params={"page[size]": 200, "page[number]": 50, "filter[entity.legalAddress.country]": "PT"})
    print("pagina 50 ->", r.status_code)
    r = client.get(BASE, params={"page[size]": 200, "page[number]": 51, "filter[entity.legalAddress.country]": "PT"})
    print("pagina 51 ->", r.status_code, r.text[:200])
    # Alternativa: `page[after]` / cursor?
    r = client.get(BASE, params={"page[size]": 200, "page[number]": 51, "filter[entity.legalAddress.country]": "PT", "sort": "entity.legalName"})
    print("pagina 51 sort ->", r.status_code, r.text[:200])
