"""Compara datas de modificacao dos itens comuns no cms.json (local vs VM).

Se um lado tem datas sistematicamente mais recentes, e esse o lado "a frente".
"""

import json
import subprocess
from pathlib import Path

LOCAL = Path(r"C:\LLMFinance\finance-llm\data\cms\cms.json")
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
res = subprocess.run(SSH, capture_output=True, timeout=120)
vm = json.loads(res.stdout.decode("utf-8"))

# Datas ao nivel do documento.
print("=== datas do documento ===")
for chave in ("created_at", "updated_at", "version"):
    print(f"  {chave:<14} local={loc.get(chave)}   vm={vm.get(chave)}")

print()
print("=== chaves de topo ===")
pl = sorted(loc.keys())
pv = sorted(vm.keys())
print(f"  so local: {[k for k in pl if k not in pv]}")
print(f"  so vm   : {[k for k in pv if k not in pl]}")

CAMPOS_DATA = ("updated_at", "created_at", "published_at", "scheduled_at")

print()
print("=== datas dos itens comuns ===")
print(f"  {'entidade/id':<34} {'local':<21} {'vm':<21} {'quem e mais novo'}")
print("  " + "-" * 92)

mais_novo_local = 0
mais_novo_vm = 0
for entidade in ("pages", "posts", "contents", "categories", "templates", "menus", "remuneracoes", "pesquisas"):
    a = {i.get("id"): i for i in (loc.get(entidade) or [])}
    b = {i.get("id"): i for i in (vm.get(entidade) or [])}
    for i in sorted(set(a) & set(b)):
        da = max((str(a[i].get(c) or "") for c in CAMPOS_DATA), default="")
        db = max((str(b[i].get(c) or "") for c in CAMPOS_DATA), default="")
        if not da and not db:
            continue
        if da > db:
            quem = "local"
            mais_novo_local += 1
        elif db > da:
            quem = "vm"
            mais_novo_vm += 1
        else:
            quem = "igual"
        titulo = (a[i].get("title") or a[i].get("name") or "")[:28]
        print(f"  {entidade + '/' + i:<34} {da[:19]:<21} {db[:19]:<21} {quem:<6} {titulo}")

print()
print(f"  local mais recente: {mais_novo_local}")
print(f"  vm mais recente   : {mais_novo_vm}")

# Media: quantos itens a VM tem a mais e com que datas.
print()
print("=== media so na VM: datas ===")
ma = {i.get("id"): i for i in (loc.get("media") or [])}
mb = {i.get("id"): i for i in (vm.get("media") or [])}
so_vm = sorted(set(mb) - set(ma))
datas = sorted(str(mb[i].get("created_at") or mb[i].get("updated_at") or "")[:10] for i in so_vm)
print(f"  {len(so_vm)} itens; datas de criacao de {datas[0]} a {datas[-1]}")
from collections import Counter
for d, n in sorted(Counter(datas).items()):
    print(f"    {d}: {n}")

print()
print("=== media so no local: datas ===")
so_local = sorted(set(ma) - set(mb))
datas = sorted(str(ma[i].get("created_at") or ma[i].get("updated_at") or "")[:10] for i in so_local)
if datas:
    print(f"  {len(so_local)} itens; datas de {datas[0]} a {datas[-1]}")
    for d, n in sorted(Counter(datas).items()):
        print(f"    {d}: {n}")
