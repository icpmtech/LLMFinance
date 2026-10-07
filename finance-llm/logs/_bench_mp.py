"""Sweep de paralelismo para a codificação de embeddings.

Um processo com 12 threads só faz ~15 docs/s (a codificação é limitada por
largura de banda de memória, não por núcleos). Vários processos com menos
threads cada costumam somar muito mais. Isto mede o agregado real.
"""
from __future__ import annotations

import multiprocessing as mp
import os
import sys
import time
from pathlib import Path

RAIZ = str(Path(__file__).resolve().parent.parent)
N_DOCS = 384


def worker(threads: int, fila) -> None:
    sys.path.insert(0, RAIZ)
    import torch

    torch.set_num_threads(threads)
    try:
        torch.set_num_interop_threads(1)
    except Exception:  # pragma: no cover - já iniciado
        pass

    from api import vector_service as vs

    es = vs.get_es_client()
    resposta = es.search(
        index=vs.CONTRACTS_INDEX,
        body={
            "query": {"bool": {"must_not": {"exists": {"field": "embedding"}}}},
            "_source": vs._SOURCE_FIELDS[vs.CONTRACTS_INDEX],
            "size": N_DOCS,
        },
        scroll="5m",
    )
    if resposta.get("_scroll_id"):
        es.clear_scroll(scroll_id=resposta["_scroll_id"])
    textos = [vs._contract_text(h.get("_source", {})) for h in resposta["hits"]["hits"]]

    modelo = vs._get_embedding_model()
    modelo.encode(textos[:8], show_progress_bar=False)  # aquece
    t0 = time.time()
    modelo.encode(textos, batch_size=64, show_progress_bar=False, normalize_embeddings=True)
    gasto = time.time() - t0
    fila.put(len(textos) / gasto)


def medir(threads_por_processo: int, processos: int) -> None:
    inicio = time.time()
    fila = mp.Queue()
    procs = [mp.Process(target=worker, args=(threads_por_processo, fila)) for _ in range(processos)]
    for p in procs:
        p.start()
    ritmos = []
    for _ in procs:
        try:
            ritmos.append(fila.get(timeout=600))
        except Exception:
            ritmos.append(0.0)
    for p in procs:
        p.join()
    # O ritmo agregado é o total de documentos (N por processo) sobre a parede,
    # mas cada processo demorou o seu tempo: usamos a soma dos ritmos.
    print(
        f"  {processos} proc x {threads_por_processo} threads: soma {sum(ritmos):6.1f} docs/s "
        f"(por processo {', '.join(f'{r:.1f}' for r in ritmos)}) | parede {time.time() - inicio:.0f}s"
    )


if __name__ == "__main__":
    mp.freeze_support()
    nucleos = os.cpu_count() or 8
    print(f"cpu_count={nucleos}")
    try:
        import psutil

        print(f"afinidade: {len(psutil.Process().cpu_affinity())} núcleos")
    except Exception:
        pass
    try:
        import onnxruntime

        print(f"onnxruntime disponível: {onnxruntime.__version__}")
    except Exception:
        print("onnxruntime: não instalado")

    for processos in (1, 2, 4, 6):
        medir(max(1, nucleos // processos), processos)
