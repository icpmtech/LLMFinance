"""Inspecionar o esquema de um registo LEI da API do GLEIF e contagens por jurisdição."""
from __future__ import annotations

import json

import httpx

BASE = "https://api.gleif.org/api/v1"

with httpx.Client(timeout=40, follow_redirects=True) as client:
    r = client.get(f"{BASE}/lei-records", params={"page[size]": 1, "filter[entity.legalAddress.country]": "PT"})
    print("status", r.status_code)
    data = r.json()
    print("meta keys", list(data.get("meta", {}).keys()))
    print("pagination", json.dumps(data.get("meta", {}).get("pagination"), ensure_ascii=False))
    rec = data["data"][0]
    print("record top keys", list(rec.keys()))
    print(json.dumps(rec, indent=2, ensure_ascii=False)[:6000])
    for country in ("PT", "ES", "FR", "DE", "GB", "US"):
        rr = client.get(f"{BASE}/lei-records", params={"page[size]": 1, "filter[entity.legalAddress.country]": country})
        j = rr.json()
        print(country, "total =", j.get("meta", {}).get("pagination", {}).get("total"))
