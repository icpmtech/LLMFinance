"""Tempo de cada âmbito da pesquisa unificada, para saber qual pesa.

O `unified_search` corre os âmbitos em paralelo, mas o tempo total é ditado pelo
**âmbito mais lento**. Isto mede cada um isoladamente, para se decidir quais
manter no caminho rápido («núcleo primeiro») e quais deixar a pedido.

Uso:
    python logs/_qa_perf_ambitos.py
    QA_Q="contratos de saúde" QA_REPS=2 python logs/_qa_perf_ambitos.py
"""
from __future__ import annotations

import os
import statistics
import sys
import time
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))
os.environ.setdefault("PYTHONIOENCODING", "utf-8")

from api import deep_search_service as deep  # noqa: E402
from api import search_service  # noqa: E402

PERGUNTA = os.environ.get("QA_Q", "Quantos contratos tem a CLARANET II SOLUTIONS?")
REPS = int(os.environ.get("QA_REPS", "2"))


def main() -> None:
    # **Palavras-chave**, e não a pergunta crua: é o que a aplicação manda (o
    # `keywords()` tira interrogativas e termos genéricos). Com a pergunta
    # inteira, o `operator: and` cai para OR, casa o índice todo e os tempos não
    # querem dizer nada.
    termos = deep.keywords(PERGUNTA) or PERGUNTA
    print(f"pergunta : {PERGUNTA!r}")
    print(f"termos   : {termos!r} | {REPS} execuções por âmbito (mediana)")
    print()
    resultados = []
    for scope_id in search_service.SCOPE_IDS:
        tempos = []
        total = 0
        for _ in range(REPS):
            t0 = time.perf_counter()
            resposta = search_service.unified_search(termos, scope=scope_id, size=6)
            tempos.append((time.perf_counter() - t0) * 1000)
            if resposta.get("groups"):
                total = resposta["groups"][0].get("total") or 0
        resultados.append((scope_id, statistics.median(tempos), total))

    resultados.sort(key=lambda linha: -linha[1])
    print(f"{'âmbito':<14} {'ms':>8} {'resultados':>11}  acumulado")
    print("-" * 50)
    acumulado = 0.0
    for indice, (scope_id, ms, total) in enumerate(resultados, start=1):
        acumulado += ms
        marca = "  <-- mais lento" if indice == 1 else ""
        print(f"{scope_id:<14} {ms:>7.0f}ms {total:>11}  {acumulado:>7.0f}ms{marca}")
    print()
    nucleo = [r for r in resultados if r[2] > 0]
    print(f"âmbitos com resultados: {len(nucleo)} de {len(resultados)}")
    if nucleo:
        mais_lento = max(nucleo, key=lambda r: r[1])
        print(f"o mais lento com resultados: {mais_lento[0]} ({mais_lento[1]:.0f} ms)")
    total_paralelo_4 = sum(r[1] for r in resultados) / 4
    total_paralelo_8 = sum(r[1] for r in resultados) / 8
    print(f"soma de todos: {sum(r[1] for r in resultados):.0f} ms")
    print(f"estimativa em paralelo com 4 threads: {total_paralelo_4:.0f} ms | com 8: {total_paralelo_8:.0f} ms")


if __name__ == "__main__":
    main()
