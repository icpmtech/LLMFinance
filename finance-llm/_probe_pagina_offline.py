"""Exercita os ramos da página do backfill quando o Elasticsearch não responde.

Não precisa de ES nem de tocar em nada: substitui o cliente por `None` e verifica
   1) sem histórico nenhum -> erro limpo (a página mostra "sem ligação");
   2) já com uma leitura boa  -> devolve a última leitura + aviso `es.ok=false`,
      e não regista amostra (senão o ritmo parecia 0 = «parado»).
"""
from __future__ import annotations

import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parent
sys.path.insert(0, str(RAIZ))
sys.path.insert(0, str(RAIZ / "logs"))

import backfill_pagina as bp  # noqa: E402

bp.vs.get_es_client = lambda: None
falhas = 0

try:
    bp._dados()
    print("FALHA 1) sem ES e sem historico devia dar erro")
    falhas += 1
except Exception as erro:  # noqa: BLE001
    print(f"1) sem ES e sem historico: erro devolvido -> {type(erro).__name__}: {erro}")

bp._ultima.update({"ts": 1700000000.0, "total": 2250969, "com": 2235234})
antes = len(bp._amostras)
d = bp._dados()
print(f"2) com ultima leitura: es={d['es']}")
print(f"   numeros mostrados: {d['com']} de {d['total']} (faltam {d['sem']}, {d['percent']}%)")
if d["es"]["ok"] is not False or d["es"]["erro"] is None or d["es"]["ts"] is None:
    print("FALHA 2) o aviso devia trazer ok=false, erro e a hora da leitura")
    falhas += 1
if len(bp._amostras) != antes:
    print(f"FALHA 2) registou {len(bp._amostras) - antes} amostra(s) com o ES em baixo")
    falhas += 1

print("probe: " + ("tudo OK" if not falhas else f"{falhas} falha(s)"))
raise SystemExit(1 if falhas else 0)
