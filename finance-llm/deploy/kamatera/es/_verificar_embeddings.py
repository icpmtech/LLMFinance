"""Verifica se os embeddings sobreviveram intactos a migracao.

Porque nao basta contar
-----------------------
A migracao passou 32 GB de JSON por `orjson` -> gzip -> ssh -> `_bulk`. Se algo
se perdesse num vetor, o Elasticsearch **nao dava erro nenhum**: aceitaria o
documento, construiria o grafo HNSW com um vetor errado e as pesquisas
semanticas limitar-se-iam a devolver resultados piores. Um erro silencioso.

Por isso isto compara o **conteudo** dos vetores com a origem, e nao so a
cobertura. O `sha256` e calculado sobre os floats empacotados em float32 -- a
precisao real de um `dense_vector` -- para nao depender da formatacao do JSON.

Dois modos
----------
    # 1. amostra: escolhe N documentos e imprime id + resumo de cada vetor
    python _verificar_embeddings.py --url http://127.0.0.1:9200 --modo amostra --n 8

    # 2. verificar: procura EXATAMENTE esses ids (para comparar noutra instancia)
    python _verificar_embeddings.py --url http://elasticsearch:9200 --modo verificar --ids a,b,c

Foi escrito para correr em dois sitios diferentes (PC e VM) e os resultados serem
comparados linha a linha.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import struct
import sys

from elasticsearch import Elasticsearch

INDICE = "contratos"


def resumo_vetor(v) -> str:
    """Resumo estavel e sensivel a qualquer alteracao do vetor.

    `float32` porque e a precisao de armazenamento de um `dense_vector` com
    `index: true`: comparar em `float64` acusaria diferencas que nao existem no
    indice.
    """
    if not isinstance(v, (list, tuple)):
        return f"nao-e-lista:{type(v).__name__}"
    n = len(v)
    try:
        pacote = struct.pack(f"<{n}f", *[float(x) for x in v])
    except Exception as e:  # noqa: BLE001
        return f"erro-a-empacotar:{e}"
    return f"{n}d:{hashlib.sha256(pacote).hexdigest()[:24]}"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default="http://127.0.0.1:9200")
    ap.add_argument("--modo", choices=("amostra", "verificar", "cobertura"), default="cobertura")
    ap.add_argument("--n", type=int, default=8)
    ap.add_argument("--ids", default="")
    args = ap.parse_args()

    es = Elasticsearch(args.url, request_timeout=300)

    # --- cobertura: `exists` e o operador correto para um dense_vector; uma
    # `query_string` do tipo `embedding:*` pode nao filtrar e devolver o total,
    # o que da uma falsa sensacao de cobertura completa.
    total = es.count(index=INDICE)["count"]
    com_vetor = es.count(
        index=INDICE, body={"query": {"exists": {"field": "embedding"}}}
    )["count"]

    print(f"url        : {args.url}")
    print(f"total      : {total:,}")
    print(f"com vetor  : {com_vetor:,}  ({100.0*com_vetor/total:.2f}%)")
    print(f"sem vetor  : {total - com_vetor:,}")

    if args.modo == "cobertura":
        return 0

    print()

    if args.modo == "amostra":
        # Sem `sort` explicito a ordem nao e deterministica nem igual entre
        # instancias -- e e por isso que a amostra imprime os `_id`, para o outro
        # lado os poder procurar exatamente.
        r = es.search(index=INDICE, body={
            "size": args.n,
            "sort": ["_doc"],
            "_source": ["embedding"],
        })
        print(f"{'id':<26} {'resumo do vetor':<30}")
        print("-" * 60)
        for h in r["hits"]["hits"]:
            print(f"{h['_id']:<26} {resumo_vetor((h.get('_source') or {}).get('embedding')):<30}")
        return 0

    ids = [i for i in args.ids.split(",") if i]
    if not ids:
        print("ERRO: --modo verificar exige --ids", file=sys.stderr)
        return 2

    print(f"{'id':<26} {'resumo do vetor':<30}")
    print("-" * 60)
    for i in ids:
        try:
            d = es.get(index=INDICE, id=i)
            v = (d.get("_source") or {}).get("embedding")
            print(f"{i:<26} {resumo_vetor(v):<30}")
        except Exception as e:  # noqa: BLE001
            print(f"{i:<26} AUSENTE ({type(e).__name__})")

    # kNN a serio: se o grafo HNSW nao existir, isto rebenta ou devolve vazio.
    # Prova que os vetores nao estao so guardados, estao *indexados*.
    try:
        v = (es.get(index=INDICE, id=ids[0]).get("_source") or {}).get("embedding")
        if v:
            r = es.search(index=INDICE, body={
                "knn": {"field": "embedding", "query_vector": v, "k": 3, "num_candidates": 100},
                "size": 3,
                "_source": False,
            })
            hits = r["hits"]["hits"]
            print()
            print(f"kNN        : {len(hits)} resultados; primeiro = {hits[0]['_id']} "
                  f"(score {hits[0]['_score']:.4f}); o proprio id esta? "
                  f"{any(h['_id'] == ids[0] for h in hits)}")
    except Exception as e:  # noqa: BLE001
        print()
        print(f"kNN        : FALHOU: {type(e).__name__}: {str(e)[:200]}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
