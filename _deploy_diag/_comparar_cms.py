"""Compara o cms.json local e o da VM: contagens por entidade e IDs divergentes.

Le o local do disco e o da VM por ssh, sem escrever nada em lado nenhum.
"""

import json
import subprocess
import sys
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

ENTIDADES = (
    "pages", "posts", "municipios", "pesquisas", "remuneracoes",
    "contents", "media", "categories", "templates", "menus", "contactos",
)


def carregar_local():
    with LOCAL.open(encoding="utf-8") as fh:
        return json.load(fh)


def carregar_vm():
    resultado = subprocess.run(SSH, capture_output=True, timeout=120)
    if resultado.returncode != 0:
        erro = resultado.stderr.decode("utf-8", "replace").strip()
        raise SystemExit(f"ssh falhou: {erro}")
    return json.loads(resultado.stdout.decode("utf-8"))


def ids(dados, entidade):
    itens = dados.get(entidade) or []
    return {item.get("id") for item in itens if isinstance(item, dict)}


def main():
    print(f"local: {LOCAL}  ({LOCAL.stat().st_size:,} bytes)".replace(",", " "))
    loc = carregar_local()
    vm = carregar_vm()
    print(f"vm   : /opt/iqos/servicos/backend/data/cms/cms.json")

    print()
    print(f"{'entidade':<16} {'local':>7} {'vm':>7}   {'so local':>8} {'so vm':>6}")
    print("-" * 54)

    total_so_local = 0
    total_so_vm = 0
    for entidade in ENTIDADES:
        a = ids(loc, entidade)
        b = ids(vm, entidade)
        so_local = a - b
        so_vm = b - a
        total_so_local += len(so_local)
        total_so_vm += len(so_vm)
        marca = "  <--" if (so_local or so_vm) else ""
        print(f"{entidade:<16} {len(a):>7} {len(b):>7}   {len(so_local):>8} {len(so_vm):>6}{marca}")

    print("-" * 54)
    print(f"{'TOTAL':<16} {'':>7} {'':>7}   {total_so_local:>8} {total_so_vm:>6}")

    print()
    print("=" * 60)
    print("ITENS SO NO LOCAL (existem no PC, faltam na VM)")
    print("=" * 60)
    for entidade in ENTIDADES:
        so = ids(loc, entidade) - ids(vm, entidade)
        if not so:
            continue
        print(f"\n  {entidade} ({len(so)}):")
        por_id = {item.get("id"): item for item in (loc.get(entidade) or [])}
        for i in sorted(so):
            item = por_id.get(i) or {}
            titulo = item.get("title") or item.get("name") or item.get("filename") or ""
            estado = item.get("status") or ""
            print(f"    {i:<28} {estado:<11} {titulo[:60]}")

    print()
    print("=" * 60)
    print("ITENS SO NA VM (existem na VM, faltam no local)")
    print("=" * 60)
    vazio = True
    for entidade in ENTIDADES:
        so = ids(vm, entidade) - ids(loc, entidade)
        if not so:
            continue
        vazio = False
        print(f"\n  {entidade} ({len(so)}):")
        por_id = {item.get("id"): item for item in (vm.get(entidade) or [])}
        for i in sorted(so):
            item = por_id.get(i) or {}
            titulo = item.get("title") or item.get("name") or item.get("filename") or ""
            estado = item.get("status") or ""
            print(f"    {i:<28} {estado:<11} {titulo[:60]}")
    if vazio:
        print("\n  (nenhum - copiar o local para a VM nao perde nada)")

    print()
    print("=" * 60)
    print("ITENS EM AMBOS MAS DIFERENTES (mesmo id, conteudo distinto)")
    print("=" * 60)
    divergentes = 0
    for entidade in ENTIDADES:
        a = ids(loc, entidade)
        b = ids(vm, entidade)
        comuns = a & b
        if not comuns:
            continue
        por_local = {item.get("id"): item for item in (loc.get(entidade) or [])}
        por_vm = {item.get("id"): item for item in (vm.get(entidade) or [])}
        for i in sorted(comuns):
            ja = json.dumps(por_local[i], sort_keys=True, ensure_ascii=False)
            jb = json.dumps(por_vm[i], sort_keys=True, ensure_ascii=False)
            if ja != jb:
                divergentes += 1
                titulo = por_local[i].get("title") or por_local[i].get("name") or ""
                print(f"  {entidade:<14} {i:<26} {titulo[:44]}")
    if divergentes == 0:
        print("\n  (nenhum)")
    else:
        print(f"\n  total: {divergentes}")


if __name__ == "__main__":
    main()
