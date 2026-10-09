"""Probe: valida o leitor de subvencoes nos ficheiros reais (amostra limitada)."""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from api import subvencoes_service as sub  # noqa: E402

LIMITE = 4000
OUT = ROOT / "_probe_subvencoes_parse.json"

relatorio = []
for item in sub.ficheiros():
    path = Path(str(item["path"]))
    inicio = time.time()
    registos = []
    total = 0
    tipos = {}
    montantes = 0.0
    for bruto in sub._iter_registos(path):
        total += 1
        if total <= LIMITE:
            registo = sub.registo_de_linha(
                celulas=bruto["celulas"],
                indices=bruto["indices"],
                ano=item["ano"],
                ficheiro=path.name,
                folha=bruto["folha"],
                linha=int(bruto["linha"]),
                lido_em="probe",
            )
            if registo:
                registos.append(registo)
                montantes += float(registo.get("montante") or 0.0)
                tipos[str(registo.get("beneficiario_tipo"))] = tipos.get(str(registo.get("beneficiario_tipo")), 0) + 1
        if total >= LIMITE:
            break
    relatorio.append(
        {
            "rel_path": item["rel_path"],
            "ano": item["ano"],
            "ano_origem": item["ano_origem"],
            "segundos_amostra": round(time.time() - inicio, 2),
            "linhas_lidas": total,
            "registos_amostra": len(registos),
            "ignoradas": total - len(registos),
            "montante_total_amostra": round(montantes, 2),
            "tipos": tipos,
            "primeiros": registos[:4],
        }
    )

OUT.write_text(json.dumps(relatorio, ensure_ascii=False, indent=2), encoding="utf-8")
print("escrito:", OUT)
for r in relatorio:
    print(
        f"{r['rel_path']}: ano={r['ano']} ({r['ano_origem']}) linhas={r['linhas_lidas']} "
        f"registos={r['registos_amostra']} ignoradas={r['ignoradas']} montante={r['montante_total_amostra']} "
        f"{r['segundos_amostra']}s"
    )
