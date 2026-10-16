"""Extrai os 12 itens genuinamente novos do cms.json local para um patch.

Nao toca no cms.json. Escreve `_patch_cms.json` com {entidade: [itens]}.
"""

import json
from pathlib import Path

LOCAL = Path(r"C:\LLMFinance\finance-llm\data\cms\cms.json")
PATCH = Path(r"C:\LLMFinance\_deploy_diag\_patch_cms.json")

# Os 12 confirmados: 1 post + 3 municipios + 4 pesquisas + 4 media
A_MIGRAR = {
    "posts": ["post_8b984e2e4355"],
    "municipios": ["mun_2990c95f1de2", "mun_a1ee4e196c51", "mun_ccd93d0c1bc0"],
    "pesquisas": ["pes_23398b71c83d", "pes_2545aff62c2a", "pes_6fbe9716d6fc", "pes_aa02e47b2c77"],
    "media": ["med_a6940fe73d55", "med_aa2933ff176b", "med_b39eb208f327", "med_f581b89c0319"],
}

with LOCAL.open(encoding="utf-8") as fh:
    loc = json.load(fh)

patch = {}
resumo = []
for entidade, ids in A_MIGRAR.items():
    indice = {i.get("id"): i for i in (loc.get(entidade) or [])}
    itens = []
    for i in ids:
        if i not in indice:
            raise SystemExit(f"ERRO: {i} nao existe no cms.json local ({entidade})")
        itens.append(indice[i])
        resumo.append((entidade, i, indice[i].get("title") or indice[i].get("filename") or ""))
    patch[entidade] = itens

PATCH.write_text(json.dumps(patch, ensure_ascii=False, indent=1), encoding="utf-8")

print(f"patch escrito: {PATCH}  ({PATCH.stat().st_size:,} bytes)".replace(",", " "))
print()
tot = 0
for entidade, itens in patch.items():
    print(f"  {entidade:<12} {len(itens)} itens")
    tot += len(itens)
print(f"  {'TOTAL':<12} {tot} itens")

print()
print("=== os ficheiros media a criar na VM ===")
for d in patch["media"]:
    print(f"  data/cms/media/{d['id']}{d.get('extension')}   <- de api/site_assets/{d.get('filename')}  ({d.get('size')} bytes)")
