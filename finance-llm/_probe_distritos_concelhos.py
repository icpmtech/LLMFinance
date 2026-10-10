"""Alcance do bug do slug: que distritos recolhiam zero em silencio.

`concelhos_com_nome_do_site` comparava o prefixo das ligacoes usando `_slugify`
(underscores) enquanto o site publica hifenes. O prefixo nunca casava, a lista de
concelhos vinha vazia e `run_district_sync` fechava o trabalho com estado **done**
sem recolher nada.

O defeito so se manifesta em distritos de **nome composto** -- nos de uma palavra
os dois slugs coincidem. Este script lista-os, com a contagem de concelhos que
cada um devolve agora.

    python _probe_distritos_concelhos.py
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

# O Scrapling enche o stderr de avisos que atrapalham a leitura do resultado.
logging.getLogger().setLevel(logging.ERROR)

from api import empresas_recolha_service as s  # noqa: E402

cat = s.catalogo()
distritos = sorted(cat.get("distritos", []), key=lambda d: d["slug"])

print(f"{'distrito':<26} {'nome composto':<14} {'concelhos':>9}")
print("-" * 52)
compostos = []
for d in distritos:
    composto = "-" in d["slug"]
    n = len(d.get("concelhos") or [])
    if composto:
        compostos.append((d["slug"], n, d.get("empresas")))
    print(f"{d['slug']:<26} {('SIM' if composto else '-'):<14} {n:>9}")

print()
print(f"distritos de nome composto: {len(compostos)} de {len(distritos)}")
print("Estes eram os que devolviam 0 concelhos antes da correcao:")
for slug, n, empresas in compostos:
    estado = "ok" if n else "AINDA 0 -- verificar"
    print(f"  {slug:<24} concelhos={n:<4} empresas={empresas}  {estado}")

vazios = [d["slug"] for d in distritos if not (d.get("concelhos") or [])]
print()
print(f"distritos ainda sem concelhos: {len(vazios)} {vazios}")
