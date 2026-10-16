"""Compara a ESTRUTURA dos itens media: o local guarda base64 embutido?

Se sim, os media nao podem ser migrados como JSON puro -- na VM sao ficheiros.
"""

import json
from pathlib import Path

LOCAL = Path(r"C:\LLMFinance\finance-llm\data\cms\cms.json")

with LOCAL.open(encoding="utf-8") as fh:
    loc = json.load(fh)

media = loc.get("media") or []
print(f"=== media no local: {len(media)} itens, cms.json {LOCAL.stat().st_size:,} bytes ===".replace(",", " "))

# Tamanho dos itens media e das outras entidades, para ver onde esta o volume.
print()
print("=== volume por entidade ===")
for entidade, itens in sorted(loc.items()):
    if not isinstance(itens, list) or not itens:
        continue
    bruto = len(json.dumps(itens, ensure_ascii=False))
    print(f"  {entidade:<14} {len(itens):>4} itens   {bruto / 1048576:>7.2f} MB")

print()
print("=== chaves presentes nos itens media ===")
todas = set()
for d in media:
    todas |= set(d.keys())
print(f"  {sorted(todas)}")

# Detectar base64 embutido.
print()
print("=== deteccao de base64 embutido ===")
com_data = [d for d in media if d.get("data")]
print(f"  itens com campo 'data': {len(com_data)}")
if com_data:
    bruto = sum(len(str(d.get("data") or "")) for d in com_data)
    print(f"  total do campo 'data': {bruto / 1048576:.2f} MB  <-- isto explica o tamanho do ficheiro")

print()
print("=== amostra: 3 media do local ===")
for d in media[:3]:
    for k, v in d.items():
        s = str(v)
        if k == "data" or len(s) > 90:
            s = f"<{len(s)} chars>"
        print(f"    {k:<16} {s[:90]}")

print()
print("=== o que aponta cada media ===")
com_url = sum(1 for d in media if d.get("url"))
com_file = sum(1 for d in media if d.get("filename"))
com_ext = sum(1 for d in media if d.get("external_url"))
print(f"  com 'url'         : {com_url}")
print(f"  com 'filename'    : {com_file}")
print(f"  com 'external_url': {com_ext}")

print()
print("=== media do local que apontam para site_assets (viajam com o codigo) ===")
assets = Path(r"C:\LLMFinance\finance-llm\api\site_assets")
nomes_assets = {p.name for p in assets.rglob("*") if p.is_file()} if assets.is_dir() else set()
print(f"  {len(nomes_assets)} ficheiros em api/site_assets/")
aponta = 0
for d in media:
    f = Path(d.get("filename") or "").name
    u = str(d.get("url") or "")
    if f in nomes_assets or "site_assets" in u or "/assets/" in u:
        aponta += 1
print(f"  media que apontam para site_assets: {aponta}")
