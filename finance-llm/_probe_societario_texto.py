"""Mostra o texto integral de publicações de uma entidade (para afinar a extração)."""
from __future__ import annotations

import os
import sys

os.environ.setdefault("ELASTICSEARCH_URL", "http://127.0.0.1:9200")

from api.elasticsearch_client import company_publicacoes  # noqa: E402

nif = sys.argv[1] if len(sys.argv) > 1 else "503106542"
limit = int(sys.argv[2]) if len(sys.argv) > 2 else 3
filtro = (sys.argv[3] if len(sys.argv) > 3 else "").upper()

items = (company_publicacoes(nif, size=1000) or {}).get("items", [])
mostrados = 0
for it in items:
    acto = (it.get("acto") or "").upper()
    if filtro and filtro not in acto:
        continue
    print("=" * 100)
    print(f"pub_id={it.get('pub_id')} data={it.get('data_publicacao')} acto={it.get('acto')!r}")
    print("-" * 100)
    print((it.get("texto") or "").strip()[:2600])
    mostrados += 1
    if mostrados >= limit:
        break
print(f"\n[{len(items)} publicações no total]")
