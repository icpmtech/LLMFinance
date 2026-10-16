"""Fusao cirurgica: insere no cms.json da VM os itens do patch que faltam.

NAO apaga nem altera nada existente: so insere IDs ausentes.
Faz copia de seguranca antes de escrever. Escrita atomica (tmp + replace).
"""

import json
import shutil
import sys
from datetime import datetime
from pathlib import Path

CMS = Path("/opt/iqos/servicos/backend/data/cms/cms.json")
PATCH = Path("/tmp/_patch_cms.json")

if not PATCH.is_file():
    raise SystemExit(f"patch nao encontrado: {PATCH}")

with CMS.open(encoding="utf-8") as fh:
    store = json.load(fh)
with PATCH.open(encoding="utf-8") as fh:
    patch = json.load(fh)

# --- copia de seguranca ---
marca = datetime.now().strftime("%Y%m%d-%H%M%S")
backup = CMS.with_name(f"cms.json.bak-{marca}")
shutil.copy2(CMS, backup)
print(f"copia de seguranca: {backup}  ({backup.stat().st_size:,} bytes)".replace(",", " "))

print()
print("=== insercoes ===")
total = 0
for entidade, itens in patch.items():
    if entidade not in store:
        store[entidade] = []
    existentes = {i.get("id") for i in store[entidade] if isinstance(i, dict)}
    novos = [d for d in itens if d.get("id") not in existentes]
    saltados = [d for d in itens if d.get("id") in existentes]

    for d in novos:
        store[entidade].insert(0, d)
    total += len(novos)

    print(f"  {entidade:<12} a inserir {len(novos):>2}   ja existiam {len(saltados)}")
    for d in novos:
        titulo = (d.get("title") or d.get("filename") or "")[:52]
        print(f"      + {d.get('id'):<24} {titulo}")

print()
print(f"  total inserido: {total}")
if total == 0:
    print("  (nada a fazer, ficheiro nao alterado)")
    sys.exit(0)

# --- escrita atomica ---
tmp = CMS.with_suffix(".json.tmp")
with tmp.open("w", encoding="utf-8") as fh:
    json.dump(store, fh, ensure_ascii=False)
tmp.replace(CMS)
print(f"  escrito: {CMS}  ({CMS.stat().st_size:,} bytes)".replace(",", " "))

print()
print("=== contagens finais por entidade ===")
for entidade in ("pages", "posts", "municipios", "pesquisas", "remuneracoes", "media", "contents", "categories", "templates", "menus"):
    n = len(store.get(entidade) or [])
    print(f"  {entidade:<14} {n}")
