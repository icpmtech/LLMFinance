"""Separa os itens so-locais em GENUINAMENTE NOVOS vs DUPLICADOS do re-seed.

Duplicado = existe na VM um item com o mesmo titulo/nome/slug mas ID diferente.
So os genuinamente novos valem a pena migrar.
"""

import json
import subprocess
import sys
from pathlib import Path

LOCAL = Path(r"C:\LLMFinance\finance-llm\data\cms\cms.json")
SSH = [
    "ssh", "-i", str(Path.home() / ".ssh" / "iqos_kamatera_ed25519"),
    "-o", "BatchMode=yes", "-o", "ConnectTimeout=20", "-o", "LogLevel=ERROR",
    "root@45.147.251.188",
    "cat /opt/iqos/servicos/backend/data/cms/cms.json",
]

ENTIDADES = ("pages", "posts", "municipios", "pesquisas", "remuneracoes", "media")

CHAVES = ("title", "name", "slug", "filename")


def chave_de(item):
    """Chave de comparacao: o primeiro identificador humano nao vazio."""
    for c in CHAVES:
        v = item.get(c)
        if v and str(v).strip():
            return str(v).strip().lower()
    return None


with LOCAL.open(encoding="utf-8") as fh:
    loc = json.load(fh)

print("a ler o cms.json da VM...", file=sys.stderr)
res = subprocess.run(SSH, capture_output=True, timeout=300)
if res.returncode != 0:
    raise SystemExit("ssh falhou: " + res.stderr.decode("utf-8", "replace"))
vm = json.loads(res.stdout.decode("utf-8"))

novos_total = []
dups_total = []

for entidade in ENTIDADES:
    a = {i.get("id"): i for i in (loc.get(entidade) or [])}
    b = {i.get("id"): i for i in (vm.get(entidade) or [])}
    so_local = sorted(set(a) - set(b))
    if not so_local:
        continue

    chaves_vm = {}
    for i, d in b.items():
        k = chave_de(d)
        if k:
            chaves_vm.setdefault(k, []).append(i)

    print()
    print("=" * 72)
    print(f"{entidade.upper()} -- {len(so_local)} itens so no local")
    print("=" * 72)

    for i in so_local:
        d = a[i]
        k = chave_de(d)
        estado = d.get("status") or ""
        titulo = (d.get("title") or d.get("name") or d.get("filename") or "")[:56]
        gemeo = chaves_vm.get(k) if k else None
        if gemeo:
            dups_total.append((entidade, i, titulo, gemeo))
            print(f"  DUPLICADO  {i:<24} {estado:<10} {titulo}")
            print(f"             -> ja existe na VM como {', '.join(gemeo)}")
        else:
            novos_total.append((entidade, i, titulo))
            print(f"  NOVO       {i:<24} {estado:<10} {titulo}")

print()
print("=" * 72)
print("RESUMO")
print("=" * 72)
por_ent = {}
for ent, _, _ in novos_total:
    por_ent[ent] = por_ent.get(ent, 0) + 1
print(f"  GENUINAMENTE NOVOS (a migrar): {len(novos_total)}")
for ent, n in sorted(por_ent.items()):
    print(f"    {ent:<14} {n}")

por_ent = {}
for ent, _, _, _ in dups_total:
    por_ent[ent] = por_ent.get(ent, 0) + 1
print(f"  DUPLICADOS do re-seed (NAO migrar): {len(dups_total)}")
for ent, n in sorted(por_ent.items()):
    print(f"    {ent:<14} {n}")
