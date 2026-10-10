"""Exporta o `_source` de um indice para NDJSON comprimido, em partes.

Porque e que isto existe
------------------------
Copiar os indices `contratos` e `contratos_es` com um snapshot do Elasticsearch
transfere ~25 GB: os segmentos Lucene ja vem comprimidos com LZ4, e gzip por cima
de dados ja comprimidos ganha quase nada.

Medido neste projeto (amostras de 2000 documentos):

    indice          JSON cru    ratio gzip    gzip
    contratos        22,95 GB      38,2%      8,78 GB
    contratos_es      9,54 GB      16,0%      1,53 GB
    ---------------------------------------------------
    total            32,49 GB      31,7%     10,31 GB

O `_source` e JSON cru, e JSON comprime muito bem. Sao 10,3 GB a atravessar a
ligacao em vez de 25 GB -- e a ligacao, medida a 4,39 MB/s, e o gargalo real.

O formato da saida e directamente aceite pelo `_bulk`: linhas alternadas

    {"index":{"_index":"<indice>","_id":"<id>"}}
    {<source>}

por isso o importador nao precisa de voltar a fazer `json.loads` de 32 GB.

Uso:
    python exportar_source.py --indice contratos --destino ./_export
    python exportar_source.py --indice contratos --destino ./_export --limite 20000
"""

from __future__ import annotations

import argparse
import gzip
import json
import os
import shutil
import sys
import time

from elasticsearch import Elasticsearch

# Porque e que isto se da ao trabalho de usar `orjson`
# ----------------------------------------------------
# Medido neste ambiente, num documento sintetico de 8 KB:
#
#     json.dumps : 23.212 docs/s
#     gzip n3    : 36.601 docs/s
#     exportador :  1.246 docs/s   <- 20x abaixo dos dois
#
# Nem serializar nem comprimir sao o muro. O custo esta em **desserializar as
# respostas do `scroll`**: um lote de 5000 contratos sao ~53 MB de JSON que o
# cliente transforma em dicionarios Python antes de o script lhes tocar. Trocar
# o `json` da stdlib pelo `orjson` (que esta instalado) move esse muro.
try:
    import orjson
except ImportError:  # pragma: no cover
    orjson = None

if orjson is not None:
    from elasticsearch.serializer import JsonSerializer

    class SerializadorRapido(JsonSerializer):
        """Serializador do cliente ES apoiado em `orjson`.

        O cliente aceita um serializador proprio; substituir so o `loads` ja
        resolve o gargalo, mas o `dumps` tambem conta para os pedidos.
        """

        def loads(self, s):
            if s in (None, b"", ""):
                return None
            return orjson.loads(s)

        def dumps(self, data):
            if data is None:
                return b""
            return orjson.dumps(data)


def dumps_linha(obj) -> bytes:
    """Serializa uma linha do NDJSON ja em bytes.

    `ensure_ascii=False` mantem os acentos em UTF-8: menos bytes e sem \\uXXXX a
    poluir. O `_bulk` aceita UTF-8 sem problema.
    """
    if orjson is not None:
        return orjson.dumps(obj)
    return json.dumps(obj, ensure_ascii=False).encode("utf-8")


def fmt_bytes(n: float) -> str:
    for unidade in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024:
            return f"{n:,.1f} {unidade}"
        n /= 1024
    return f"{n:,.1f} PB"


def main() -> int:
    ap = argparse.ArgumentParser(description="Exporta o _source de um indice em NDJSON .gz")
    ap.add_argument("--url", default="http://127.0.0.1:9200")
    ap.add_argument("--indice", required=True)
    ap.add_argument("--destino", required=True)
    ap.add_argument("--mb", type=int, default=200,
                    help="tamanho alvo de cada parte (MB de JSON, antes de comprimir)")
    ap.add_argument("--lote", type=int, default=5000, help="documentos por pedido ao ES")
    ap.add_argument("--nivel", type=int, default=6,
                    help="nivel de gzip: 1 e rapido e da um ficheiro maior, 9 e o contrario")
    ap.add_argument("--limite", type=int, default=0, help="0 = tudo; >0 = so para testar")
    ap.add_argument("--fatia", type=int, default=0, help="indice desta fatia (0..fatias-1)")
    ap.add_argument("--fatias", type=int, default=1,
                    help="dividir o scroll em N processos paralelos (1 = sem fatias)")
    ap.add_argument("--manter", action="store_true",
                    help="nao apagar partes existentes no destino")
    args = ap.parse_args()

    if args.fatias < 1:
        raise SystemExit("--fatias tem de ser >= 1")
    if not (0 <= args.fatia < args.fatias):
        raise SystemExit("--fatia tem de estar entre 0 e fatias-1")

    os.makedirs(args.destino, exist_ok=True)

    # Com fatias, cada uma escreve a sua propria serie de partes. Filas separadas:
    # nao ha nada partilhado para sincronizar, e a ordem entre fatias nao importa
    # porque o importador so precisa que cada ficheiro esteja completo.
    prefixo = args.indice if args.fatias <= 1 else f"{args.indice}-s{args.fatia}"

    # Uma exportacao interrompida deixa partes a meio (a ultima) e completas (as
    # outras). Como o `scroll` nao sabe retomar a meio, recomecar e mais honesto
    # do que tentar adivinhar -- mas avisamos, para nao apagar trabalho por engano.
    existentes = [
        f for f in os.listdir(args.destino)
        if f.startswith(f"{prefixo}-part-")
    ]
    if existentes and not args.manter:
        print(f"a apagar {len(existentes)} partes antigas de {prefixo} no destino", flush=True)
        for f in existentes:
            os.remove(os.path.join(args.destino, f))
    elif existentes:
        print(f"AVISO: --manter dado; as partes existentes ficam no destino", flush=True)

    if orjson is not None:
        es = Elasticsearch(args.url, request_timeout=300, serializer=SerializadorRapido())
    else:
        es = Elasticsearch(args.url, request_timeout=300)

    if not es.indices.exists(index=args.indice):
        print(f"ERRO: o indice '{args.indice}' nao existe em {args.url}", file=sys.stderr)
        return 2

    total = es.count(index=args.indice)["count"]
    alvo_docs = min(total, args.limite) if args.limite else total
    print(f"indice  : {args.indice}", flush=True)
    print(f"fatia   : {args.fatia}/{args.fatias}" + ("  (sem fatias)" if args.fatias <= 1 else ""), flush=True)
    print(f"orjson  : {'sim' if orjson is not None else 'NAO (a usar json da stdlib, muito mais lento)'}", flush=True)
    print(f"docs    : {total:,}" + (f"  (limitado a {alvo_docs:,})" if args.limite else ""), flush=True)
    print(f"destino : {os.path.abspath(args.destino)}", flush=True)
    print(f"partes  : ~{args.mb} MB de JSON cada", flush=True)
    print("", flush=True)

    alvo_bytes = args.mb * 1024 * 1024

    parte = 0
    fh = None
    gz = None
    parte_bytes = 0
    partes_fechadas: list[tuple[int, int]] = []  # (numero, bytes de JSON)

    nome_tmp = None
    nome_final = None

    def abrir_parte() -> None:
        nonlocal fh, gz, parte_bytes, nome_tmp, nome_final
        # Escreve primeiro para `.tmp` e so renomeia no fim. Assim, a mera
        # existencia de um `.ndjson.gz` prova que a parte esta COMPLETA -- e e
        # isso que permite ao orquestrador enviar cada parte para a VM enquanto o
        # exportador ainda produz as seguintes, em vez de esperar pelo fim.
        nome_final = os.path.join(args.destino, f"{prefixo}-part-{parte:05d}.ndjson.gz")
        nome_tmp = nome_final + ".tmp"
        fh = open(nome_tmp, "wb")
        # O nivel e ajustavel porque o exportador e, medido, o passo mais lento:
        # o ES le a 29 MB/s, mas `json.dumps` + gzip so dao ~880 docs/s, o que
        # para `contratos` sao 43 min. Transferir e um custo fixo por MB, logo
        # vale a pena pagar alguns MB a mais para sair daqui mais depressa.
        gz = gzip.GzipFile(fileobj=fh, mode="wb", compresslevel=args.nivel)
        parte_bytes = 0

    def fechar_parte() -> None:
        nonlocal fh, gz
        if gz is not None:
            gz.close()
        if fh is not None:
            fh.close()
        gz = None
        fh = None
        if nome_tmp and os.path.exists(nome_tmp):
            os.replace(nome_tmp, nome_final)

    docs = 0
    json_bytes = 0
    t0 = time.time()

    abrir_parte()
    # `size` vai dentro do `body`: passa-lo como parametro a parte do `body` esta
    # deprecado no cliente 8.x e enche a saida de DeprecationWarning.
    #
    # `slice` divide o scroll em fatias independentes. Com uma so shard, o pedido
    # continua a ser servido por um segmento, mas cada fatia corre num processo
    # proprio -- e o que tira o exportador do teto de ~18 MB/s de um so fio.
    corpo = {"_source": True, "sort": ["_doc"], "size": args.lote}
    if args.fatias > 1:
        corpo["slice"] = {"id": args.fatia, "max": args.fatias}
    pag = es.search(index=args.indice, scroll="30m", body=corpo)
    sid = pag["_scroll_id"]

    try:
        while True:
            hits = pag["hits"]["hits"]
            if not hits:
                break

            linhas: list[bytes] = []
            for h in hits:
                linhas.append(dumps_linha(
                    {"index": {"_index": args.indice, "_id": h["_id"]}}))
                linhas.append(dumps_linha(h["_source"]))
            dados = b"\n".join(linhas) + b"\n"

            gz.write(dados)
            parte_bytes += len(dados)
            json_bytes += len(dados)
            docs += len(hits)

            if parte_bytes >= alvo_bytes:
                fechar_parte()
                partes_fechadas.append((parte, parte_bytes))
                parte += 1
                abrir_parte()

            if docs % 200000 < args.lote:
                el = time.time() - t0
                vel = docs / el if el else 0
                eta = (alvo_docs - docs) / vel if vel else 0
                print(f"  {docs:>12,} docs   {fmt_bytes(json_bytes):>10} JSON   "
                      f"{vel:>9,.0f} docs/s   ETA {eta/60:>5.1f} min", flush=True)

            if args.limite and docs >= args.limite:
                break

            pag = es.scroll(scroll_id=sid, scroll="30m")
            sid = pag["_scroll_id"]
    except KeyboardInterrupt:
        print("\ninterrompido -- as partes escritas ficam, mas incompletas", flush=True)
        fechar_parte()
        return 130
    finally:
        try:
            es.clear_scroll(scroll_id=sid)
        except Exception:
            pass

    fechar_parte()
    partes_fechadas.append((parte, parte_bytes))

    # Uma ultima parte com poucos bytes e lixo de uma paragem a meio; nao faz mal
    # ficar, mas e melhor nao a anunciar como boa.
    vazias = [p for p, b in partes_fechadas if b == 0]

    el = time.time() - t0
    print("", flush=True)
    print(f"FIM  {args.indice}", flush=True)
    print(f"  docs          : {docs:,}", flush=True)
    print(f"  JSON escrito  : {fmt_bytes(json_bytes)}", flush=True)
    print(f"  partes        : {len(partes_fechadas)}" + (f"  ({len(vazias)} vazia(s))" if vazias else ""), flush=True)
    print(f"  tempo         : {el/60:.1f} min  ({docs/el:,.0f} docs/s)" if el else "", flush=True)

    if vazias:
        for p in vazias:
            caminho = os.path.join(args.destino, f"{args.indice}-part-{p:05d}.ndjson.gz")
            if os.path.exists(caminho):
                os.remove(caminho)
                print(f"  removida parte vazia {p:05d}", flush=True)

    # Tamanho em disco, que e o que vai ser transferido.
    total_disco = sum(
        os.path.getsize(os.path.join(args.destino, f))
        for f in os.listdir(args.destino)
        if f.startswith(f"{prefixo}-part-")
    )
    print(f"  em disco (.gz): {fmt_bytes(total_disco)}", flush=True)
    print(f"  a 4,39 MB/s   : {total_disco/1024/1024/4.39/60:.0f} min de transferencia", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
