import json
import pathlib

d = pathlib.Path("/app/data/cms")

print("copias de seguranca existentes:")
for p in sorted(d.glob("cms.json.bak*")):
    print(f"  {p.name}  {p.stat().st_size:,} bytes".replace(",", " "))

antes = json.load(open(d / "cms.json.bak-20261016-171556", encoding="utf-8"))
depois = json.load(open(d / "cms.json", encoding="utf-8"))

print()
print("=== comparacao: backup meu (171556) vs ficheiro atual ===")

perdidos = 0
alterados = 0
total = 0

for entidade, itens in antes.items():
    if not isinstance(itens, list):
        continue
    novos = {i.get("id"): i for i in (depois.get(entidade) or []) if isinstance(i, dict)}
    for x in itens:
        if not isinstance(x, dict):
            continue
        total += 1
        i = x.get("id")
        if i not in novos:
            perdidos += 1
            print(f"  PERDIDO   {entidade}/{i}")
        elif json.dumps(x, sort_keys=True, ensure_ascii=False) != json.dumps(novos[i], sort_keys=True, ensure_ascii=False):
            alterados += 1
            print(f"  ALTERADO  {entidade}/{i}  {x.get('title') or x.get('name') or ''}")

print()
print(f"  itens no backup : {total}")
print(f"  perdidos        : {perdidos}")
print(f"  alterados       : {alterados}")
print(f"  => {'OK: a fusao so acrescentou' if perdidos == 0 and alterados == 0 else 'ATENCAO'}")

# Confirmar as entidades de topo (nao so listas).
chaves_antes = set(antes)
chaves_depois = set(depois)
print()
print(f"  chaves de topo perdidas: {sorted(chaves_antes - chaves_depois) or '(nenhuma)'}")

# Contagens finais.
print()
print("=== contagens finais ===")
for entidade in ("pages", "posts", "municipios", "pesquisas", "remuneracoes", "media", "contents", "categories", "templates", "menus"):
    a = len(antes.get(entidade) or [])
    b = len(depois.get(entidade) or [])
    marca = f"  (+{b - a})" if b != a else ""
    print(f"  {entidade:<14} {a:>4} -> {b:>4}{marca}")
