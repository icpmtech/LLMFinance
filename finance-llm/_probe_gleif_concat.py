"""Inspecionar a resposta de /api/v1/concatenated-files/lei2 e derivar URLs de download."""
from __future__ import annotations

import json

import httpx

with httpx.Client(timeout=30, follow_redirects=True) as client:
    r = client.get("https://leidata.gleif.org/api/v1/concatenated-files/lei2")
    data = r.json()
    print("status", r.status_code)
    print("top keys", list(data.keys()))
    items = data.get("data") or []
    print("n items", len(items))
    first = items[0] if items else {}
    print("item keys", list(first.keys()))
    print(json.dumps({k: v for k, v in first.items() if k != "sources"}, indent=2, ensure_ascii=False)[:2000])
    src = (first.get("sources") or [{}])[0]
    print("source keys", list(src.keys()))
    print("lou_file keys", list((src.get("lou_file") or {}).keys()))
    print(json.dumps(src.get("lou_file"), indent=2, ensure_ascii=False)[:1200])
    # Tentar o link de download típico
    for cand in [
        "https://leidata.gleif.org/api/v1/concatenated-files/lei2/latest/lei2-latest.zip",
        "https://leidata.gleif.org/api/v1/concatenated-files/lei2/42290/lei2-42290.zip",
        "https://leidata.gleif.org/api/v1/concatenated-files/lei2/42290/download",
    ]:
        try:
            h = client.head(cand)
            print("HEAD", cand, h.status_code, h.headers.get("content-length"), h.headers.get("content-type"))
        except Exception as exc:  # noqa: BLE001
            print("HEAD", cand, "ERR", exc)
