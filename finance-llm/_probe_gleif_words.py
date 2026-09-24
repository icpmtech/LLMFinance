"""Varrer recursos de topo da API leidata v1."""
from __future__ import annotations

import httpx

WORDS = [
    "golden-copy-files", "golden-copy", "golden-copies", "concatenated-files", "concatenated",
    "lei-records", "lei2", "files", "file", "download", "downloads", "status", "health",
    "releases", "releases/latest", "latest", "versions", "metadata", "lei-cdf", "cdf",
    "rr-cdf", "reporting-exceptions", "deltas", "delta-files", "publisher", "sources",
    "lei-records/latest", "golden-copy-files/latest", "concatenated-files/lei2",
]

with httpx.Client(timeout=20, follow_redirects=True) as client:
    for word in WORDS:
        url = f"https://leidata.gleif.org/api/v1/{word}"
        try:
            r = client.get(url)
            ct = (r.headers.get("content-type") or "").split(";")[0]
            if r.status_code != 404:
                print(f"[{r.status_code}] {url} ({ct})\n    {r.text[:300].replace(chr(10), ' ')}\n")
            else:
                print(f"[404] {url}")
        except Exception as exc:  # noqa: BLE001
            print(f"[ERR] {url} -> {exc}")
