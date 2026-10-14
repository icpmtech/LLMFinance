"""Recolha completa (temporária) dos anos do SRAP e respetivas contagens."""
from __future__ import annotations

import io
import json
import os
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parent
sys.path.insert(0, str(RAIZ))

from api import remuneracoes_ap_service as servico  # noqa: E402

resultado = servico.recolher(forcar=True, anos=[2020, 2021, 2022, 2023, 2024, 2025, 2026])
saida = io.open(Path(os.environ["TEMP"]) / "srap_recolha.txt", "w", encoding="utf-8")
saida.write(json.dumps(resultado, ensure_ascii=False, indent=1) + "\n")
saida.write("\n--- TRU: nível 5 e último, por ano ---\n")
for ano in servico.anos_disponiveis():
    parametros = servico.parametros_do_ano(ano)
    ultimo = max((item for item in servico.niveis(ano) if item.get("valor")), key=lambda item: item["nivel"], default={})
    ano_antes = servico.nivel_valor(ano - 1, 5)
    brap = parametros.get("brap")
    variacao = None
    if brap and ano_antes:
        variacao = round((brap / ano_antes - 1) * 100, 2)
    saida.write(
        f"  {ano}: BRAP={brap} (variação {variacao}%) | nível máx={ultimo.get('nivel')} "
        f"({ultimo.get('valor')} €) | versão={parametros.get('versao')}\n"
    )
saida.close()
print("escrito", Path(os.environ["TEMP"]) / "srap_recolha.txt")
