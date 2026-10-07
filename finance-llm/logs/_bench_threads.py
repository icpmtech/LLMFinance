"""A codificação escala com o número de threads do PyTorch?

Um processo com 12 threads deu ~15 docs/s. Se o ritmo for quase igual com 1
thread, o problema é a codificação gerada/limites de memória e vale mais correr
**muitos processos com poucas threads**. Se escalar bem, vale mais um processo
com todas as threads.
"""
from __future__ import annotations

import os
import sys
import time
from pathlib import Path

RAIZ = str(Path(__file__).resolve().parent.parent)
sys.path.insert(0, RAIZ)
os.environ.setdefault("PYTHONIOENCODING", "utf-8")
os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")

N = 128


def main() -> None:
    import torch

    print(f"torch {torch.__version__} | cpu_count={os.cpu_count()}")
    try:
        import onnxruntime

        print(f"onnxruntime {onnxruntime.__version__}")
    except Exception:
        print("onnxruntime: não instalado")

    from api import vector_service as vs

    es = vs.get_es_client()
    resposta = es.search(
        index=vs.CONTRACTS_INDEX,
        body={
            "query": {"bool": {"must_not": {"exists": {"field": "embedding"}}}},
            "_source": ["objectoContrato", "descContrato"],
            "size": N,
        },
    )
    if resposta.get("_scroll_id"):
        es.clear_scroll(scroll_id=resposta["_scroll_id"])
    textos = [vs._contract_text(h.get("_source", {})) for h in resposta["hits"]["hits"]]
    comprimentos = sorted(len(t) for t in textos)
    print(f"{len(textos)} textos | p50 {comprimentos[len(comprimentos) // 2]} caracteres")

    modelo = vs._get_embedding_model()
    for threads in (1, 2, 4, 6, 8, 12, 14):
        torch.set_num_threads(threads)
        modelo.encode(textos[:16], batch_size=16, show_progress_bar=False, normalize_embeddings=True)  # aquece
        t0 = time.time()
        modelo.encode(textos, batch_size=32, show_progress_bar=False, normalize_embeddings=True)
        gasto = time.time() - t0
        print(f"  threads={threads:2d}: {gasto:6.2f}s -> {len(textos) / gasto:6.1f} docs/s ({len(textos) / gasto / threads:5.2f} por thread)")


if __name__ == "__main__":
    main()
