"""Procura fontes abertas equivalentes às publicações de atos societários."""
from __future__ import annotations

import json
import re

import requests

UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/129.0.0.0 Safari/537.36",
      "Accept": "application/json,text/html;q=0.9,*/*;q=0.8"}

TESTS = [
    ("dados.gov.pt datasets", "https://dados.gov.pt/api/1/datasets/?q=atos+societarios&page_size=5"),
    ("dados.gov.pt datasets2", "https://dados.gov.pt/api/1/datasets/?q=registro+comercial&page_size=5"),
    ("DRE pesquisa", "https://diariodarepublica.pt/dr/pesquisa?q=atos+societarios"),
    ("DRE api v1", "https://diariodarepublica.pt/dr/api/v1/search?q=constituicao%20de%20sociedade"),
    ("IRN publicacoes", "https://www.irn.mj.pt/IRN/sections/irn/a_registral/"),
]

s = requests.Session()
s.headers.update(UA)
for label, url in TESTS:
    try:
        r = s.get(url, timeout=40, allow_redirects=True)
        ct = r.headers.get("content-type", "")
        print(f"### {label}: {r.status_code} {len(r.content)} {ct.split(';')[0]} -> {r.url[:120]}")
        body = r.content.decode("utf-8", errors="replace")
        if "json" in ct:
            try:
                data = r.json()
                txt = json.dumps(data, ensure_ascii=False)
                hits = data.get("data", data) if isinstance(data, dict) else data
                if isinstance(hits, list):
                    print("   resultados:", len(hits))
                    for it in hits[:5]:
                        if isinstance(it, dict):
                            print("     -", (it.get("title") or it.get("name") or "")[:100])
                else:
                    print("   chaves:", list(data)[:15] if isinstance(data, dict) else type(data))
                    print("   amostra:", txt[:400])
            except Exception as e:
                print("   json err", e, body[:200])
        else:
            t = re.sub(r"<script.*?</script>", " ", body, flags=re.I | re.S)
            t = re.sub(r"<[^>]+>", " ", t)
            t = re.sub(r"\s+", " ", t).strip()
            print("   texto:", t[:500])
    except Exception as e:
        print("### ", label, "ERR", e)
    print()
