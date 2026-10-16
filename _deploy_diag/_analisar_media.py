"""Analisa os media so-locais contra os da VM: serao duplicados com ID diferente?

Tambem verifica se os binarios existem em data/cms/media/.
"""

import json
import subprocess
from collections import Counter
from pathlib import Path

RAIZ = Path(r"C:\LLMFinance\finance-llm")
LOCAL = RAIZ / "data" / "cms" / "cms.json"
MEDIA_LOCAL = RAIZ / "data" / "cms" / "media"
SSH = [
    "ssh",
    "-i", str(Path.home() / ".ssh" / "iqos_kamatera_ed25519"),
    "-o", "BatchMode=yes",
    "-o", "ConnectTimeout=15",
    "-o", "LogLevel=ERROR",
    "root@45.147.251.188",
    "cat /opt/iqos/servicos/backend/data/cms/cms.json",
]

with LOCAL.open(encoding="utf-8") as fh:
    loc = json.load(fh)
vm = json.loads(subprocess.run(SSH, capture_output=True, timeout=120).stdout.decode("utf-8"))

ma = {i.get("id"): i for i in (loc.get("media") or [])}
mb = {i.get("id"): i for i in (vm.get("media") or [])}

so_local = sorted(set(ma) - set(mb))
print(f"=== media so no local ({len(so_local)}) ===")
for i in so_local:
    d = ma[i]
    print(f"  {i}")
    print(f"    title    : {d.get('title')!r}")
    print(f"    filename : {d.get('filename')!r}")
    print(f"    mime     : {d.get('mime')!r}")
    print(f"    url      : {d.get('url') or d.get('external_url') or '(sem url)'}")

print()
print("=== na VM, itens com o MESMO filename ou title (potenciais duplicados) ===")
por_filename_vm = {}
por_title_vm = {}
for i, d in mb.items():
    f = (d.get("filename") or "").lower()
    t = (d.get("title") or "").strip().lower()
    if f:
        por_filename_vm.setdefault(f, []).append(i)
    if t:
        por_title_vm.setdefault(t, []).append(i)

for i in so_local:
    d = ma[i]
    f = (d.get("filename") or "").lower()
    t = (d.get("title") or "").strip().lower()
    cands = set(por_filename_vm.get(f, [])) | set(por_title_vm.get(t, []))
    if cands:
        print(f"  {i}  ->  probabilidade de duplicado:")
        for c in sorted(cands):
            v = mb[c]
            print(f"      {c}  {v.get('title')!r}  file={v.get('filename')!r}")
    else:
        print(f"  {i}  ->  sem equivalente na VM (item GENUINAMENTE novo)")

print()
print("=== binarios dos media so-locais em disco ===")
if MEDIA_LOCAL.is_dir():
    ficheiros = {p.name for p in MEDIA_LOCAL.rglob("*") if p.is_file()}
    print(f"  {len(ficheiros)} ficheiros em data/cms/media/")
    for i in so_local:
        d = ma[i]
        f = d.get("filename") or ""
        st = d.get("storage") or d.get("path") or ""
        candidatos = [f, st, Path(st).name if st else "", i]
        achado = next((c for c in candidatos if c and c in ficheiros), None)
        print(f"  {i}: {'ENCONTRADO ' + achado if achado else 'NAO encontrado no disco'}  (filename={f!r})")
else:
    print("  (pasta data/cms/media/ nao existe)")

print()
print("=== contagens por decisao ===")
sem_eq = [i for i in so_local if not (
    (ma[i].get("filename") or "").lower() in por_filename_vm
    or (ma[i].get("title") or "").strip().lower() in por_title_vm)]
print(f"  media genuinamente novos (sem equivalente): {len(sem_eq)}")
print(f"  media provavelmente duplicados            : {len(so_local) - len(sem_eq)}")
