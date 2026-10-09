"""Probe 3: mostra a linha de cabecalho numerada (celula a celula)."""
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent
src = json.loads((ROOT / "_probe_subvencoes_ods.json").read_text(encoding="utf-8"))

lines: list[str] = []
for key, info in src.items():
    lines.append("=" * 100)
    lines.append(f"{key}  linhas={info['rows']}")
    lines.append("--- histograma de larguras (primeiras 5000 linhas de dados) ---")
    lines.append(json.dumps(info["width_hist"], ensure_ascii=False))
    hdr = info.get("header_row")
    if hdr:
        lines.append(f"--- cabecalho candidato: linha {hdr['i']} ({len(hdr['cells'])} celulas) ---")
        for j, cell in enumerate(hdr["cells"]):
            lines.append(f"  col{j:>2}: {cell[:200]!r}")
    lines.append("--- amostra de dados ---")
    for row in info["sample"]:
        lines.append("  " + json.dumps(row[:11], ensure_ascii=False)[:900])
    lines.append("--- primeiras 8 linhas nao vazias do topo ---")
    for item in info["head"][:8]:
        joined = " | ".join(c[:60] for c in item["cells"])
        lines.append(f"  [{item['i']}] {joined[:300]}")

out = ROOT / "_probe_subvencoes_cabecalho.txt"
out.write_text("\n".join(lines), encoding="utf-8")
print("escrito:", out)
