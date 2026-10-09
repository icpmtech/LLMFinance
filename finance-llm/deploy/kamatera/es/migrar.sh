#!/bin/bash
# Migra indices do Elasticsearch local para o ES da VM do edge.
#
# Corre NA VM (ver `12-es-migrar.ps1`, que o envia e executa). O ES local chega
# aqui pelo encaminhamento do tunel reverso, em 127.0.0.1:9201.
#
#   SOURCE=http://127.0.0.1:9201   ES do PC (via tunel)
#   DEST=http://127.0.0.1:9200     ES desta VM
#   MAX_MB=3072                    ignora indices maiores que isto (MB inteiros)
#   DRY=1                          so mostra o plano, nao escreve nada
#   FORCE=1                        refaz indices que ja existam no destino
#   SYNC=1                         so os indices cuja contagem diverge da origem
#                                  (implica FORCE; e o modo para realinhar)
#
# Ordem: do mais leve para o mais pesado -- e o que permite comecar já, e o que
# deixa para o fim o `contratos` (20 GB), que so cabe depois de crescer o disco.
set -uo pipefail

SOURCE="${SOURCE:-http://127.0.0.1:9201}"
DEST="${DEST:-http://127.0.0.1:9200}"
MAX_MB="${MAX_MB:-3072}"
DRY="${DRY:-0}"
FORCE="${FORCE:-0}"
SYNC="${SYNC:-0}"

MAX_BYTES=$(( MAX_MB * 1024 * 1024 ))

# Em modo sincronizacao o objetivo e trazer indices ja copiados de volta ao
# alinhamento, por isso refazer e implicito.
if [ "$SYNC" = "1" ]; then FORCE=1; fi

command -v jq >/dev/null || { echo "falta o jq nesta maquina"; exit 1; }

echo "origem  : $SOURCE"
echo "destino : $DEST"
echo "limite  : ${MAX_MB} MB por indice"
[ "$SYNC" = "1" ] && echo "modo    : sincronizacao (so o que divergir)"
echo

if ! curl -fsS -m 15 "$SOURCE" >/dev/null; then
    echo "ERRO: nao consigo falar com a origem ($SOURCE)."
    echo "      O tunel do PC esta de pe? (docker logs iqos-origin-tunnel)"
    exit 1
fi
if ! curl -fsS -m 15 "$DEST" >/dev/null; then
    echo "ERRO: nao consigo falar com o destino ($DEST)."
    exit 1
fi

if [ "$SYNC" = "1" ]; then
    # Percorre os indices que JA existem no destino e compara as contagens. A
    # copia e a mesma do modo normal -- muda so a escolha do que copiar.
    # As contagens vao como 3.o/4.o campo da linha (e nao para stderr): assim
    # aparecem ao lado do indice, em vez de fora de ordem.
    PLANO=$(
        curl -fsS "$DEST/_cat/indices?h=index" | grep -v '^$' | LC_ALL=C sort \
        | while read -r idx; do
            o=$(curl -fsS -m 60 "$SOURCE/$idx/_count" 2>/dev/null | jq -r '.count // "?"')
            d=$(curl -fsS -m 60 "$DEST/$idx/_count"   2>/dev/null | jq -r '.count // "?"')
            if [ "$o" != "$d" ]; then
                bytes=$(curl -fsS -m 30 "$SOURCE/_cat/indices/$idx?h=pri.store.size&bytes=b" 2>/dev/null | tr -d ' ')
                echo "$idx ${bytes:-0} $o $d"
            fi
        done
    )
    TOTAL=$(echo "$PLANO" | grep -c . || true)
    echo "indices desalinhados: $TOTAL"
else
    # `bytes=b` da o tamanho do primario em bytes, para comparar com o limite.
    PLANO=$(curl -fsS "$SOURCE/_cat/indices?h=index,pri.store.size&bytes=b&s=pri.store.size:asc" \
            | awk -v max="$MAX_BYTES" 'NF==2 && $2+0 <= max { printf "%s %s\n", $1, $2 }')
    TOTAL=$(echo "$PLANO" | grep -c . || true)
    echo "indices dentro do limite: $TOTAL"
fi
echo

feitos=0
saltados=0
falhados=0

while read -r idx bytes src_n dst_n; do
    [ -z "${idx:-}" ] && continue
    mb=$(( bytes / 1024 / 1024 ))
    # Em modo sincronizacao vale a pena ver quanto diverge antes de recopiar.
    [ -n "${src_n:-}" ] && echo "  (origem $src_n / destino $dst_n)"

    if curl -fsS -o /dev/null -m 10 -I "$DEST/$idx" 2>/dev/null; then
        if [ "$FORCE" != "1" ]; then
            echo "  [salta]  $idx (ja existe no destino; usa FORCE=1 para refazer)"
            saltados=$(( saltados + 1 ))
            continue
        fi
        echo "  [refaz]  $idx"
        [ "$DRY" = "1" ] || curl -fsS -X DELETE "$DEST/$idx" >/dev/null
    fi

    echo "  [migra]  $idx  (${mb} MB)"

    if [ "$DRY" = "1" ]; then
        feitos=$(( feitos + 1 ))
        continue
    fi

    # Recriar o indice com as definicoes da origem antes de copiar. Sem isto o
    # `_reindex` criaria um mapeamento dinamico e perderia `keyword`/`date`/
    # analisadores personalizados. `number_of_replicas: 0` porque so ha um no.
    #
    # O `GET /<indice>` devolve `{"<indice>": {mappings, settings}}`, por isso o
    # `to_entries[0].value` -- ler `.mappings` na raiz dava `null` e o ES
    # respondia 500 (NullPointerException em CreateIndexRequest.source).
    if ! curl -fsS "$SOURCE/$idx?features=mappings,settings" \
        | jq 'to_entries[0].value as $v | {
                settings: { index: (
                    ($v.settings.index
                     | del(.uuid, .creation_date, .version, .provided_name,
                           .resize, .routing, .blocks, .store, .number_of_replicas))
                    + { number_of_replicas: 0 }
                ) },
                mappings: ($v.mappings // {})
              }' > /tmp/iqos-migra.json; then
        echo "      FALHOU a ler as definicoes"
        falhados=$(( falhados + 1 ))
        continue
    fi

    if ! curl -fsS -X PUT "$DEST/$idx" -H 'Content-Type: application/json' \
            --data-binary @/tmp/iqos-migra.json >/dev/null; then
        echo "      FALHOU a criar o indice no destino"
        falhados=$(( falhados + 1 ))
        continue
    fi

    # `wait_for_completion=false` + sondeo: um indice grande nao cabe num
    # pedido HTTP sincrono nem no tempo de vida de uma sessao SSH.
    #
    # Sem `slices`: o ES recusa (`reindex from remote sources doesn't support
    # slices > 1`). Copia remota e sempre um so fluxo -- logo, mais lenta.
    #
    # Sem `-f` de proposito: o corpo do erro do ES e a unica pista util quando
    # isto falha (whitelist, versao, mapeamento...).
    resp=$(curl -sS -X POST "$DEST/_reindex?wait_for_completion=false" \
        -H 'Content-Type: application/json' -d "{
            \"source\": {
                \"remote\": {
                    \"host\": \"$SOURCE\",
                    \"socket_timeout\": \"60s\",
                    \"connect_timeout\": \"30s\"
                },
                \"index\": \"$idx\",
                \"size\": 1000
            },
            \"dest\": { \"index\": \"$idx\" }
        }" 2>&1)

    tarefa=$(echo "$resp" | jq -r '.task // empty' 2>/dev/null)

    if [ -z "$tarefa" ]; then
        echo "      FALHOU a lancar o _reindex:"
        echo "$resp" | jq -r 'if .error then "        \(.error.type): \(.error.reason)" else "        \(.)" end' 2>/dev/null \
            || echo "        $resp"
        falhados=$(( falhados + 1 ))
        continue
    fi

    printf "      a copiar"
    while true; do
        estado=$(curl -fsS -m 20 "$DEST/_tasks/$tarefa" | jq -r 'if .completed == true then "fim" else "corre" end' 2>/dev/null)
        [ "$estado" = "fim" ] && break
        printf "."
        sleep 3
    done
    echo

    curl -fsS -X POST "$DEST/$idx/_refresh" >/dev/null
    o=$(curl -fsS "$SOURCE/$idx/_count" | jq -r '.count')
    d=$(curl -fsS "$DEST/$idx/_count" | jq -r '.count')

    if [ "$o" = "$d" ]; then
        echo "      OK  $d documentos"
        feitos=$(( feitos + 1 ))
    else
        echo "      DIVERGE  origem=$o  destino=$d"
        falhados=$(( falhados + 1 ))
    fi
done <<< "$PLANO"

echo
echo "resumo: $feitos migrados, $saltados saltados, $falhados falhados"
[ "$falhados" -eq 0 ] || exit 1
