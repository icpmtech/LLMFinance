"""Vê que campos (e imagens) os itens indexados têm, por fonte."""
from __future__ import annotations

import collections
import json

from api import scraper_service as scraper

resultado = scraper.search_items(size=40, sort="recent")
print("total", resultado.get("total"))
por_fonte: dict[str, collections.Counter] = collections.defaultdict(collections.Counter)
com_imagem = 0
for item in resultado.get("items") or []:
    data = item.get("data") or {}
    fonte = item.get("source_id")
    if any(k.lower() in ("imagem", "image", "img", "foto", "thumbnail") for k in data):
        com_imagem += 1
    por_fonte[fonte].update(data.keys())

print("itens com imagem:", com_imagem)
for fonte, campos in por_fonte.items():
    print(f"  {fonte:42s} campos={sorted(campos)}")

amostra = (resultado.get("items") or [{}])[0]
print("exemplo:", json.dumps({k: v for k, v in amostra.items() if k != "text"}, ensure_ascii=False)[:600])
