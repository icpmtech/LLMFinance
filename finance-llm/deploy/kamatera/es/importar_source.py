"""Importa partes NDJSON comprimidas produzidas pelo `exportar_source.py`.

Corre na VM, tipicamente dentro de um contentor que ja tenha Python e a
biblioteca `elasticsearch` -- o `iq-os-backend` serve, e ja esta na VM.

    docker run --rm --network iqos-net \
        -v /opt/iqos/export:/export \
        --entrypoint python iq-os-backend:latest \
        /export/importar_source.py --url http://elasticsearch:9200 --pasta /export

Porque e que nao se faz `json.loads` de nada
--------------------------------------------
O ficheiro ja esta no formato que o `_bulk` consome -- linhas alternadas de
accao e documento. Enviar os bytes tal como saem do gzip evita reconstruir 32 GB
de objectos Python so para os voltar a serializar. E o mesmo principio que fez
o exportador escrever NDJSON em vez de usar o `helpers.bulk`.

Retomavel
---------
Cada parte que termina fica marcada com um `.ok` ao lado. Uma parte a meio deixa
o Elasticsearch com alguns documentos repetidos, mas como a accao leva `_id`
explicito, repetir a mesma parte e idempotente: reescreve os mesmos documentos.
Por isso `--refazer` apenas apaga os marcadores.
"""

from __future__ import annotations

import argparse
import glob
import gzip
import os
import re
import sys
import time

from elasticsearch import Elasticsearch


def fmt_bytes(n: float) -> str:
    for unidade in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024:
            return f"{n:,.1f} {unidade}"
        n /= 1024
    return f"{n:,.1f} PB"


def main() -> int:
    ap = argparse.ArgumentParser(description="Importa NDJSON .gz para o Elasticsearch")
    ap.add_argument("--url", default="http://elasticsearch:9200")
    ap.add_argument("--pasta", required=True)
    ap.add_argument("--indice", default="", help="so as partes deste indice; vazio = todas")
    ap.add_argument("--lote-mb", type=int, default=20, help="MB de NDJSON por pedido _bulk")
    ap.add_argument("--refazer", action="store_true", help="ignorar os marcadores .ok")
    args = ap.parse_args()

    padrao = f"{args.indice}-part-*.ndjson.gz" if args.indice else "*-part-*.ndjson.gz"
    partes = sorted(glob.glob(os.path.join(args.pasta, padrao)))
    if not partes:
        print(f"ERRO: nenhuma parte encontrada em {args.pasta} com o padrao '{padrao}'", file=sys.stderr)
        return 2

    es = Elasticsearch(args.url, request_timeout=600)

    # Indices alvo, derivados do nome dos ficheiros:
    # `<indice>[-s<fatia>]-part-NNNNN.ndjson.gz`.
    indices_alvo = sorted({
        re.sub(r"-s\d+$", "", os.path.basename(p).split("-part-")[0])
        for p in partes
    })

    # Afinacao para carga massiva.
    #
    # `refresh_interval=-1` evita que o ES feche segmentos pequenos a cada
    # segundo. Menos segmentos significa menos trabalho de fusao -- mas sobretudo
    # menos grafos HNSW a construir, e e esse o custo que domina aqui: os
    # documentos de `contratos` trazem o vetor de 384 dimensoes dentro do
    # `_source` e o campo e `dense_vector` com `index: true`. Medido, isso baixa o
    # `_bulk` para ~800 docs/s, contra ~2.400 num indice sem vetor.
    #
    # `translog.durability=async` tira o fsync de cada pedido. E seguro neste
    # contexto: o pior caso e repetir o import, e o import e idempotente porque
    # as accoes levam `_id` fixo.
    for idx in indices_alvo:
        try:
            es.indices.put_settings(index=idx, body={"index": {
                "refresh_interval": "-1",
                "translog.durability": "async",
            }})
            print(f"afinado {idx}: refresh_interval=-1, translog.durability=async", flush=True)
        except Exception as e:
            print(f"AVISO: nao consegui afinar '{idx}': {e}", flush=True)

    total_geral = 0
    bytes_geral = 0
    partes_feitas = 0
    t_geral = time.time()

    print(f"partes      : {len(partes)}", flush=True)
    print(f"destino     : {args.url}", flush=True)
    print(f"lote        : ~{args.lote_mb} MB de NDJSON por pedido", flush=True)
    print("", flush=True)

    for caminho in partes:
        nome = os.path.basename(caminho)
        marca = caminho + ".ok"

        if os.path.exists(marca) and not args.refazer:
            print(f"  {nome}  -- ja feito, salto", flush=True)
            continue

        alvo = args.lote_mb * 1024 * 1024
        docs_parte = 0
        bytes_parte = 0
        erros_parte = 0
        primeiro_erro = None
        t0 = time.time()

        def enviar(payload: bytes) -> None:
            nonlocal docs_parte, erros_parte, primeiro_erro
            resp = es.options(request_timeout=600).bulk(body=payload)
            # Cada payload tem pares accao+documento, logo metade sao documentos.
            docs_parte += payload.count(b"\n") // 2
            if resp.get("errors"):
                for item in resp["items"]:
                    for op, res in item.items():
                        if res.get("error"):
                            erros_parte += 1
                            if primeiro_erro is None:
                                primeiro_erro = (
                                    f"{op} id={res.get('_id')}: "
                                    f"{res['error'].get('type')} "
                                    f"{str(res['error'].get('reason'))[:160]}"
                                )

        buf = bytearray()
        linhas = 0
        with gzip.open(caminho, "rb") as gz:
            for linha in gz:
                buf += linha
                linhas += 1
                if len(buf) >= alvo and linhas % 2 == 0:
                    bytes_parte += len(buf)
                    enviar(bytes(buf))
                    buf = bytearray()
                    linhas = 0
            if buf:
                if linhas % 2 == 0:
                    bytes_parte += len(buf)
                    enviar(bytes(buf))
                else:
                    print(f"  AVISO: {nome} tem um numero impar de linhas no fim "
                          f"({linhas}); a ultima accao ficou sem documento", flush=True)

        el = time.time() - t0
        vel = bytes_parte / el if el else 0
        total_geral += docs_parte
        bytes_geral += bytes_parte
        partes_feitas += 1

        estado = "OK" if not erros_parte else f"{erros_parte} ERROS"
        print(f"  {nome}  {docs_parte:>10,} docs  {fmt_bytes(bytes_parte):>10}  "
              f"{el:>6.1f}s  {fmt_bytes(vel)}/s  {estado}", flush=True)
        if primeiro_erro:
            print(f"      primeiro erro: {primeiro_erro}", flush=True)

        if not erros_parte:
            with open(marca, "w", encoding="utf-8") as m:
                m.write(f"{docs_parte}\n")
        else:
            print(f"      marco .ok NAO escrito -- repetir esta parte e seguro", flush=True)

    # Repor o comportamento normal e tornar os documentos pesquisaveis de
    # imediato. Sem isto o indice ficava sem refresh automatico e as pesquisas
    # nao viam nada do que acabou de entrar.
    for idx in indices_alvo:
        try:
            es.indices.put_settings(index=idx, body={"index": {
                "refresh_interval": "1s",
                "translog.durability": "request",
            }})
            es.indices.refresh(index=idx)
            print(f"reposto {idx}: refresh_interval=1s, translog.durability=request", flush=True)
        except Exception as e:
            print(f"AVISO: nao consegui repor '{idx}': {e}", flush=True)

    el = time.time() - t_geral
    print("", flush=True)
    print(f"FIM  {partes_feitas} partes  {total_geral:,} docs  {fmt_bytes(bytes_geral)}  "
          f"em {el/60:.1f} min", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
