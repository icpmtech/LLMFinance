"""Mede onde se gasta o tempo no backfill: scroll, codificação ou bulk.

O piloto deu ~16 docs/s (≈40 h para 2,25 M), demasiado lento. Isto separa as
três fases para se saber o que otimizar em vez de adivinhar.
"""
from __future__ import annotations

import os
import sys
import time
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))
os.environ.setdefault("PYTHONIOENCODING", "utf-8")

import torch  # noqa: E402

from api import vector_service as vs  # noqa: E402

N = 256
print(f"torch {torch.__version__} | threads={torch.get_num_threads()} | cpu_count={os.cpu_count()}")

es = vs.get_es_client()

# --- 1. leitura (scroll) -------------------------------------------------
t0 = time.time()
resposta = es.search(
    index=vs.CONTRACTS_INDEX,
    body={
        "query": {"bool": {"must_not": {"exists": {"field": "embedding"}}}},
        "_source": vs._SOURCE_FIELDS[vs.CONTRACTS_INDEX],
        "size": N,
    },
    scroll="5m",
)
scroll_id = resposta.get("_scroll_id")
hits = resposta["hits"]["hits"]
t_scroll = time.time() - t0
print(f"1) scroll {len(hits)} docs: {t_scroll:.2f}s")

textos = [vs._contract_text(h.get("_source", {})) for h in hits]
t_texto = time.time() - t0 - t_scroll
comprimentos = sorted(len(t) for t in textos)
print(
    "   texto: min %d | p50 %d | p90 %d | max %d caracteres | montar texto %.2fs"
    % (
        comprimentos[0],
        comprimentos[len(comprimentos) // 2],
        comprimentos[int(len(comprimentos) * 0.9)],
        comprimentos[-1],
        t_texto,
    )
)

modelo = vs._get_embedding_model()
print(f"   max_seq_length do modelo: {getattr(modelo, 'max_seq_length', '?')}")
modelo.encode(["aquecimento"], show_progress_bar=False)  # aquece

# --- 2. codificação -----------------------------------------------------
t0 = time.time()
vetores = vs._encode_texts(textos)
t_enc = time.time() - t0
print(f"2) encode {N} (texto completo): {t_enc:.2f}s -> {N / t_enc:.1f} docs/s")

curtos = [t[:512] for t in textos]
modelo.encode(curtos[:1], show_progress_bar=False)
t0 = time.time()
vs._encode_texts(curtos)
t_curto = time.time() - t0
print(f"   encode {N} (cortado a 512): {t_curto:.2f}s -> {N / t_curto:.1f} docs/s")

if hasattr(modelo, "tokenizer"):
    t0 = time.time()
    modelo.tokenizer(textos, padding=False, truncation=True, max_length=256)
    t_tok = time.time() - t0
    print(f"   só tokenizar (truncagem 256): {t_tok:.2f}s -> {N / t_tok:.1f} docs/s")

# --- 3. escrita (bulk) --------------------------------------------------
corpo = []
for hit, vetor in zip(hits, vetores):
    corpo.append({"update": {"_index": vs.CONTRACTS_INDEX, "_id": hit["_id"]}})
    corpo.append({"doc": {"embedding": vetor}})
t0 = time.time()
bruto = es.bulk(body=corpo, refresh=False)
t_bulk = time.time() - t0
print(f"3) bulk {N}: {t_bulk:.2f}s -> {N / t_bulk:.1f} docs/s (errors={bruto.get('errors')})")

total = t_scroll + t_enc + t_bulk
print(
    f"\ntotal {total:.2f}s -> {N / total:.1f} docs/s | repartição: "
    f"scroll {100 * t_scroll / total:.0f}% | encode {100 * t_enc / total:.0f}% | bulk {100 * t_bulk / total:.0f}%"
)

if scroll_id:
    es.clear_scroll(scroll_id=scroll_id)
