"""Lista o conteúdo de /app/uploads (projetos, simulações, relatórios).

Corre com:
    docker exec -w /app/backend <container> /app/backend/.venv/bin/python /tmp/_probe_uploads.py
"""
import json
import os

BASE = "/app/backend/uploads"

for kind in ("projects", "simulations", "reports"):
    path = os.path.join(BASE, kind)
    if not os.path.isdir(path):
        print(f"{kind}: (não existe)")
        continue
    entries = sorted(os.listdir(path))
    print(f"{kind}: {len(entries)} entradas -> {entries[:6]}")
    if entries:
        first = os.path.join(path, entries[0])
        if os.path.isdir(first):
            inner = sorted(os.listdir(first))[:10]
            print(f"    exemplo {entries[0]}/ -> {inner}")
            # mostra as chaves do primeiro json encontrado
            for name in inner:
                if name.endswith(".json"):
                    with open(os.path.join(first, name), encoding="utf-8") as handle:
                        try:
                            data = json.load(handle)
                        except Exception as exc:
                            print(f"      {name}: ilegível ({exc})")
                            continue
                    keys = list(data.keys())[:18] if isinstance(data, dict) else f"lista de {len(data)}"
                    print(f"      {name}: {keys}")
                    break
