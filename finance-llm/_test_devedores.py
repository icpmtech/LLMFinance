"""Testa a recolha de um ficheiro das Finanças (PDF + JSON + índice)."""
from __future__ import annotations

import json
import os
import sys

os.environ.setdefault("ELASTICSEARCH_URL", "http://127.0.0.1:9200")

from api import devedores_service as devedores  # noqa: E402

alvos = sys.argv[1:] or ["listaFC6.pdf"]
resultado = devedores.recolher_financas(alvos)
print(json.dumps({k: v for k, v in resultado.items() if k != "items"}, ensure_ascii=False))
for item in resultado["items"]:
    print(" ", item)
print("--- pesquisa ---")
pesquisa = devedores.search(size=3, sort="escalao", order="desc")
print({k: v for k, v in pesquisa.items() if k not in ("items",)})
for item in pesquisa.get("items", []):
    print("  ", item.get("nif"), "|", item.get("nome"), "|", item.get("escalao"), "|", item.get("collected_at"))
print("--- por nif ---")
if pesquisa.get("items"):
    alvo = pesquisa["items"][0]["nif"]
    print(json.dumps(devedores.por_nif(alvo), ensure_ascii=False)[:600])
print("--- meta ---")
print(json.dumps(devedores.meta(), ensure_ascii=False, default=str)[:900])
