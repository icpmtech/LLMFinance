"""Probe: le a pasta data/subvencoes por ano e indexa no Elasticsearch."""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from api import subvencoes_service as sub  # noqa: E402

OUT = ROOT / "_probe_subvencoes_ingest.json"
acao = (sys.argv[1] if len(sys.argv) > 1 else "tudo").lower()

meta = sub.meta()
print("dir:", meta["dir"])
print("ficheiros no disco:", meta["ficheiros_disco"])
for ano in meta["anos"]:
    print("  ano", ano["ano"], "ficheiros", ano["ficheiros"], "lidos", ano["lidos"], "pendentes", ano["pendentes"])
print("indice:", meta["indice"])

progresso = {}

if acao in ("tudo", "ler"):
    inicio = time.time()
    resultado = sub.ler_pasta(progresso=progresso)
    resultado["segundos"] = round(time.time() - inicio, 1)
    print(f"LIDOS: {resultado['lidos_total']} ficheiros, {resultado['registos']} registos, "
          f"{resultado['montante']} EUR, {resultado['segundos']}s")
    for lote in resultado["lidos"]:
        print(f"   {lote['rel_path']}: ano={lote['ano']} folha={lote['folha']} registos={lote['registos']} "
              f"ignoradas={lote['ignoradas']} montante={lote['montante_total']} "
              f"{lote['primeira_decisao']}..{lote['ultima_decisao']}")
    for erro in resultado["erros"]:
        print("   ERRO:", erro)
    OUT.write_text(json.dumps(resultado, ensure_ascii=False, indent=2, default=str), encoding="utf-8")

if acao in ("tudo", "indexar"):
    inicio = time.time()
    resultado = sub.indexar(progresso=progresso)
    resultado["segundos"] = round(time.time() - inicio, 1)
    print(f"INDEXADOS: {resultado['indexados']} registos em {resultado['ficheiros']} ficheiros, "
          f"{resultado['segundos']}s")
    for erro in resultado.get("errors") or []:
        print("   ERRO:", erro)

print("indice agora:", sub.meta()["indice"])
