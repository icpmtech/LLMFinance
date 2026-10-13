"""Recolha dos dados financeiros da ERC (script de operação, corre no contentor).

A secção `dafin` é servida por API e só responde exercício a exercício: a janela
de anos é varrida por inteiro e cada ano custa um pedido. O script lê a janela de
`argv` (`--inicio`, `--fim`, `--limite`, `--trabalhadores`, `--vazios`), mostra o
progresso no log e recalcula a análise de risco no fim.

    python logs/erc_financeiro.py --limite 5
    python logs/erc_financeiro.py --inicio 2015 --vazios 3
"""
from __future__ import annotations

import argparse
import logging
import sys
import threading
import time

sys.path.insert(0, "/app")

logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(name)s: %(message)s")

from api import erc_service as erc  # noqa: E402

parser = argparse.ArgumentParser(description="Recolha dos dados financeiros da ERC")
parser.add_argument("--limite", type=int, default=None, help="entidades a varrer (0 = todas)")
parser.add_argument("--inicio", type=int, default=None, help="primeiro exercício a sondar")
parser.add_argument("--fim", type=int, default=None, help="último exercício a sondar")
parser.add_argument("--trabalhadores", type=int, default=8)
parser.add_argument("--pausa", type=float, default=0.15)
parser.add_argument("--vazios", type=int, default=0, help="parar após N anos vazios seguidos (0 = janela toda)")
parser.add_argument("--todas", action="store_true", help="recolher também as entidades que já têm dados")
args = parser.parse_args()

progresso: dict = {}


def vigiar() -> None:
    while True:
        time.sleep(60)
        print(
            f"[progresso] fase={progresso.get('phase')} "
            f"entidades={progresso.get('entidades_done')}/{progresso.get('entidades_total')} "
            f"(com dados={progresso.get('com_dados')}) anos={progresso.get('anos')} "
            f"atual={str(progresso.get('current'))[:45]}",
            flush=True,
        )


threading.Thread(target=vigiar, daemon=True).start()

inicio = time.time()
resultado = erc.recolher_financeiro(
    limite=args.limite or None,
    ano_inicio=args.inicio,
    ano_fim=args.fim,
    vazios_seguidos=args.vazios,
    pausa=args.pausa,
    trabalhadores=args.trabalhadores,
    apenas_sem_financeiro=not args.todas,
    progresso=progresso,
)
print(
    f"[financeiro] janela {resultado['anos']['inicio']}-{resultado['anos']['fim']}: "
    f"{resultado['varridas']} entidades varridas, {resultado['com_dados']} com dados "
    f"em {(time.time() - inicio) / 60:.1f} min | erros: {len(resultado['errors'])}",
    flush=True,
)
print("[analise]", resultado["analise"], flush=True)
for erro in resultado["errors"][:15]:
    print("   erro:", erro, flush=True)

print("[indexação] a indexar (recriando os índices)…", flush=True)
print("[indexação]", erc.indexar(forcar=True), flush=True)
print("[fim]", flush=True)
