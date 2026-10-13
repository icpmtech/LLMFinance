"""Recolha completa do portal da ERC (script de operação, corre dentro do contentor).

Retoma o que já está em `data/erc/entidades.jsonl` (`saltar_existentes`), usa 3
pedidos em paralelo e indexa no fim. O progresso vai para o log.
"""
from __future__ import annotations

import logging
import sys
import threading
import time

sys.path.insert(0, "/app")

logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(name)s: %(message)s")

from api import erc_service as erc  # noqa: E402

progresso: dict = {}


def vigiar() -> None:
    while True:
        time.sleep(60)
        print(
            f"[progresso] fase={progresso.get('phase')} "
            f"entidades={progresso.get('entidades_done')}/{progresso.get('entidades_total')} "
            f"(saltadas={progresso.get('saltadas')}) "
            f"pessoas={progresso.get('pessoas_done')}/{progresso.get('pessoas_total')} "
            f"atual={str(progresso.get('current'))[:45]}",
            flush=True,
        )


threading.Thread(target=vigiar, daemon=True).start()

inicio = time.time()
resultado = erc.recolher(
    pausa=0.15,
    com_pessoas=True,
    com_estrutura=True,
    com_ocs=True,
    com_financeiro=False,
    guardar_html=False,
    forcar=True,
    saltar_existentes=True,
    trabalhadores=3,
    progresso=progresso,
)
print(
    f"[recolha] {resultado['entidades']} entidades, {resultado['pessoas']} pessoas, {resultado['ocs']} OCS "
    f"em {(time.time() - inicio) / 60:.1f} min | erros: {len(resultado['errors'])}",
    flush=True,
)
for erro in resultado["errors"][:15]:
    print("   erro:", erro, flush=True)

print("[indexação] a indexar…", flush=True)
print("[indexação]", erc.indexar(), flush=True)
print("[fim]", flush=True)
