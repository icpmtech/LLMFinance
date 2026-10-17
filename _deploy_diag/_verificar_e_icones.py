"""Verifica que a fusao so ACRESCENTOU e cria os 4 ficheiros dos icones.

1. Prova que todos os itens do backup continuam presentes e iguais.
2. Copia api/site_assets/<ficheiro> -> data/cms/media/<id>.svg para os 4 media novos.
"""

import json
import shutil
from pathlib import Path

BASE = Path("/app")
CMS = BASE / "data" / "cms" / "cms.json"
MEDIA_DIR = BASE / "data" / "cms" / "media"
ASSETS = BASE / "api" / "site_assets"

backups = sorted(CMS.parent.glob("cms.json.bak-*"))
if not backups:
    raise SystemExit("nao encontrei copia de seguranca")
backup = backups[-1]

with backup.open(encoding="utf-8") as fh:
    antes = json.load(fh)
with CMS.open(encoding="utf-8") as fh:
    depois = json.load(fh)

print(f"backup: {backup.name}")
print()

print("=" * 64)
print("1. VERIFICACAO: nada foi perdido nem alterado?")
print("=" * 64)
perdidos = 0
alterados = 0
total_itens = 0
for entidade, itens in antes.items():
    if not isinstance(itens, list):
        continue
    novos = {i.get("id"): i for i in (depois.get(entidade) or []) if isinstance(i, dict)}
    for d in itens:
        if not isinstance(d, dict):
            continue
        total_itens += 1
        i = d.get("id")
        if i not in novos:
            perdidos += 1
            print(f"  PERDIDO   {entidade}/{i}  {d.get('title') or d.get('name') or ''}")
        elif json.dumps(d, sort_keys=True, ensure_ascii=False) != json.dumps(novos[i], sort_keys=True, ensure_ascii=False):
            alterados += 1
            print(f"  ALTERADO  {entidade}/{i}  {d.get('title') or d.get('name') or ''}")

print(f"\n  itens no backup : {total_itens}")
print(f"  perdidos        : {perdidos}")
print(f"  alterados       : {alterados}")
print(f"  => {'OK, so houve acrescimos' if perdidos == 0 and alterados == 0 else 'ATENCAO: houve alteracoes'}")

print()
print("=" * 64)
print("2. FICHEIROS DOS 4 ICONES NOVOS")
print("=" * 64)
NOVOS = {
    "med_a6940fe73d55": "icone-analise-medida.svg",
    "med_aa2933ff176b": "icone-dados.svg",
    "med_b39eb208f327": "icone-imprensa.svg",
    "med_f581b89c0319": "icone-correcao.svg",
}
MEDIA_DIR.mkdir(parents=True, exist_ok=True)
for mid, ficheiro in NOVOS.items():
    origem = ASSETS / ficheiro
    destino = MEDIA_DIR / f"{mid}.svg"
    if not origem.is_file():
        print(f"  FALTA origem  {origem}")
        continue
    if destino.is_file():
        print(f"  ja existe     {destino.name}  ({destino.stat().st_size} bytes)")
        continue
    shutil.copy2(origem, destino)
    print(f"  criado        {destino.name}  ({destino.stat().st_size} bytes)  <- {ficheiro}")

print()
print("  total em data/cms/media/: " + str(len(list(MEDIA_DIR.iterdir()))))
