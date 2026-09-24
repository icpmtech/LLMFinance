"""Sonda os endpoints do GLEIF (golden copy e concatenated) para descobrir URLs válidas."""
from __future__ import annotations

import json
import re

import httpx

PAGE = "https://www.gleif.org/en/lei-data/gleif-golden-copy/download-the-golden-copy"

CANDIDATES = [
    "https://leidata.gleif.org/api/v1/golden-copy-files",
    "https://leidata.gleif.org/api/v1/golden-copy-files/",
    "https://leidata.gleif.org/api/v1/concatenated-files/lei2/latest/lei2-latest.zip",
    "https://leidata.gleif.org/api/v1/golden-copy-files/lei2/latest/lei2-latest.zip",
    "https://leidata.gleif.org/api/v1/lei2/latest/lei2-latest.zip",
]


def main() -> None:
    with httpx.Client(timeout=30, follow_redirects=True) as client:
        try:
            resp = client.get(PAGE)
            links = sorted(set(re.findall(r'https?://[^"\'\s<>]*leidata[^"\'\s<>]*', resp.text)))
            print(f"PAGE status={resp.status_code} links={len(links)}")
            for link in links[:40]:
                print("  LINK", link)
        except Exception as exc:  # noqa: BLE001
            print("PAGE erro:", exc)

        for url in CANDIDATES:
            try:
                r = client.head(url)
                print(f"HEAD {url} -> {r.status_code} len={r.headers.get('content-length')} type={r.headers.get('content-type')}")
            except Exception as exc:  # noqa: BLE001
                print(f"HEAD {url} -> ERR {exc}")


if __name__ == "__main__":
    main()
