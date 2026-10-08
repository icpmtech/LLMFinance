"""Mede a Pesquisa profunda e valida o «sem limite» e a via semântica.

Corre contra o backend servido (Docker na 8002, servidor local na 8011) e mede,
para cada combinação de modo/limites, o tempo de parede no cliente, o tempo que o
servidor reporta (`took_ms`) e o número de fontes.

Uso:
    python logs/_qa_perf_deep.py
    QA_BACKEND=http://127.0.0.1:8011 QA_REPS=5 python logs/_qa_perf_deep.py
"""
from __future__ import annotations

import json
import os
import statistics
import time

import httpx

BACKEND = os.environ.get("QA_BACKEND", "http://127.0.0.1:8002").rstrip("/")
PERGUNTA = os.environ.get("QA_Q", "Quantos contratos tem a CLARANET II SOLUTIONS?")
REPS = int(os.environ.get("QA_REPS", "3"))

# (modo, per_source, max_sources). Mantido curto de propósito: cada linha
# demora segundos e o objetivo é isolar o custo de cada via.
CONFIGURACOES = [
    ("text", 6, 12),
    ("hybrid", 6, 12),
    ("vector", 6, 12),
    ("hybrid", 50, 0),  # «sem limite»
]


def uma_medicao(modo: str, per_source: int, max_sources: int) -> dict:
    parametros = {"q": PERGUNTA, "mode": modo, "max_sources": max_sources, "per_source": per_source}
    t0 = time.time()
    resposta = httpx.get(f"{BACKEND}/deep-search/search", params=parametros, timeout=600)
    parede = (time.time() - t0) * 1000
    resposta.raise_for_status()
    dados = resposta.json()
    return {
        "parede": parede,
        "servidor": dados.get("took_ms") or 0,
        "fontes": len(dados.get("sources") or []),
        "texto": dados.get("text_lists"),
        "vetor": dados.get("vector_lists"),
        "saltados": dados.get("vector_skipped") or {},
        "ilimitado": dados.get("unlimited"),
        "erro": dados.get("error"),
    }


def main() -> None:
    print(f"backend : {BACKEND}   (cada linha = mediana de {REPS} execuções)")
    print(f"pergunta: {PERGUNTA!r}")
    print(flush=True)

    # --- catálogo ---
    meta = httpx.get(f"{BACKEND}/deep-search/meta", timeout=60).json()
    limites = meta.get("limits") or {}
    print("catálogo:")
    print(f"  âmbitos: {len(meta.get('sources') or [])} | modos: {[m.get('id') for m in (meta.get('modes') or [])]}")
    print(f"  limites: max_sources={limites.get('max_sources')} per_source={limites.get('per_source')} "
          f"unlimited={limites.get('unlimited')} citable_max={limites.get('citable_max')}")
    print(f"  exemplos: {len(meta.get('examples') or [])}")
    print()

    print(f"{'modo':<8} {'per':>4} {'max':>5} {'parede':>9} {'servidor':>9} {'fontes':>7} {'listaT':>7} {'listaV':>7}  saltados")
    print("-" * 96)
    guardadas = []
    for modo, per_source, max_sources in CONFIGURACOES:
        amostras = []
        ultima = {}
        for _ in range(REPS):
            try:
                ultima = uma_medicao(modo, per_source, max_sources)
            except Exception as erro:  # noqa: BLE001
                print(f"{modo:<8} {per_source:>4} {max_sources:>5}   FALHOU: {type(erro).__name__}: {erro}")
                ultima = {}
                break
            amostras.append(ultima)
        if not amostras:
            continue
        parede = statistics.median(a["parede"] for a in amostras)
        servidor = statistics.median(a["servidor"] for a in amostras)
        saltados = ultima.get("saltados") or {}
        rotulo_saltados = ", ".join(f"{k}={str(v)[:28]}" for k, v in saltados.items()) or "-"
        print(
            f"{modo:<8} {per_source:>4} {max_sources:>5} {parede:>8.0f}ms {servidor:>8.0f}ms "
            f"{ultima.get('fontes'):>7} {str(ultima.get('texto')):>7} {str(ultima.get('vetor')):>7}  {rotulo_saltados}",
            flush=True,
        )
        guardadas.append((modo, per_source, max_sources, parede, servidor, ultima))

    print()
    print("validação:")
    sem_limite = [g for g in guardadas if g[2] == 0]
    texto = next((g for g in guardadas if g[0] == "text" and g[2] == 12), None)
    hibrido = next((g for g in guardadas if g[0] == "hybrid" and g[2] == 12), None)
    vetor = next((g for g in guardadas if g[0] == "vector" and g[2] == 12), None)

    if sem_limite:
        muitas = max(g[5].get("fontes") or 0 for g in sem_limite)
        marcado = any(g[5].get("ilimitado") for g in sem_limite)
        print(f"  'sem limite' (max_sources=0): {muitas} fontes, marcado unlimited={marcado} "
              f"{'OK' if muitas > 12 and marcado else 'FALHA'}")
    if texto and hibrido and vetor:
        print(f"  híbrido junta as duas vias: texto={texto[5].get('texto')}+vetor={texto[5].get('vetor')} vs "
              f"híbrido={hibrido[5].get('texto')}+{hibrido[5].get('vetor')} "
              f"{'OK' if (hibrido[5].get('vetor') or 0) >= (texto[5].get('vetor') or 0) else 'FALHA'}")
        print(f"  modo semântico usa vectores: listasV={vetor[5].get('vetor')} e listasT={vetor[5].get('texto')} "
              f"{'OK' if (vetor[5].get('vetor') or 0) > 0 else 'FALHA'}")
        custo = vetor[3] - texto[3]
        print(f"  custo da via semântica (vector - text, mesmos limites): {custo:+.0f} ms")
    if hibrido and sem_limite:
        print(f"  custo de 'sem limite' (hybrid 50/0 vs hybrid 6/12): {sem_limite[0][3] - hibrido[3]:+.0f} ms")


if __name__ == "__main__":
    main()
