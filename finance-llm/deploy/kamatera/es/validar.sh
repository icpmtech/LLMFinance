#!/bin/bash
# Valida o espelho do Elasticsearch na VM contra o ES local.
#
# Corre NA VM (ver `13-es-validar.ps1`). Nao escreve nada em lado nenhum: so le.
#
#   SOURCE=http://127.0.0.1:9201   ES do PC (via tunel)
#   DEST=http://127.0.0.1:9200     ES desta VM
#
# Verifica, indice a indice:
#   - a contagem de documentos (`_count`, so documentos vivos)
#   - o mapeamento (ordenado de forma canonica, porque a ordem das chaves varia)
#   - a saude do cluster e dos shards
#   - indices que existam na origem e nao no destino (e vice-versa)
set -uo pipefail

SOURCE="${SOURCE:-http://127.0.0.1:9201}"
DEST="${DEST:-http://127.0.0.1:9200}"

command -v jq >/dev/null || { echo "falta o jq nesta maquina"; exit 1; }

echo "origem  : $SOURCE"
echo "destino : $DEST"
echo

# --- 1. Ligacoes ------------------------------------------------------------
for par in "origem:$SOURCE" "destino:$DEST"; do
    nome=${par%%:*}; url=${par#*:}
    if ! curl -fsS -m 15 "$url" >/dev/null; then
        echo "ERRO: $nome nao responde ($url)."
        [ "$nome" = "origem" ] && echo "      O tunel do PC esta de pe? docker logs iqos-origin-tunnel"
        exit 1
    fi
done

# --- 2. Saude ---------------------------------------------------------------
echo "=== Cluster ==="
sh=$(curl -fsS -m 15 "$DEST/_cluster/health")
printf "  estado              : %s\n" "$(echo "$sh" | jq -r .status)"
printf "  nos                 : %s\n" "$(echo "$sh" | jq -r .number_of_nodes)"
printf "  shards ativos       : %s\n" "$(echo "$sh" | jq -r .active_shards)"
printf "  shards nao alocados : %s\n" "$(echo "$sh" | jq -r .unassigned_shards)"
printf "  inicializando       : %s\n" "$(echo "$sh" | jq -r .initializing_shards)"
echo

# --- 3. Comparacao indice a indice ------------------------------------------
# `LC_ALL=C sort`: o `_cat/indices` ordena pela collation do cluster, que nao e
# a mesma que a do `comm`. Sem isto o `comm` avisa "not in sorted order" (e o
# resultado deixa de ser fiavel).
curl -fsS -m 30 "$DEST/_cat/indices?h=index"   | grep -v '^$' | LC_ALL=C sort > /tmp/iqos-dest.txt
curl -fsS -m 30 "$SOURCE/_cat/indices?h=index" | grep -v '^$' | LC_ALL=C sort > /tmp/iqos-src.txt

echo "=== Indice a indice ==="
printf "  %-32s %10s %10s  %s\n" INDICE ORIGEM DESTINO MAPEAMENTO

falhas=0
tot_o=0
tot_d=0

while read -r idx; do
    [ -z "$idx" ] && continue

    o=$(curl -fsS -m 60 "$SOURCE/$idx/_count" | jq -r '.count // "?"' 2>/dev/null)
    d=$(curl -fsS -m 60 "$DEST/$idx/_count"   | jq -r '.count // "?"' 2>/dev/null)

    # `jq -S` ordena as chaves: o mesmo mapeamento serializa sempre igual.
    mo=$(curl -fsS -m 60 "$SOURCE/$idx/_mapping" | jq -S ".[\"$idx\"].mappings" 2>/dev/null)
    md=$(curl -fsS -m 60 "$DEST/$idx/_mapping"   | jq -S ".[\"$idx\"].mappings" 2>/dev/null)

    if [ -n "$mo" ] && [ "$mo" = "$md" ]; then map="igual"; else map="DIFERE"; fi
    if [[ "$o" =~ ^[0-9]+$ ]]; then tot_o=$(( tot_o + o )); fi
    if [[ "$d" =~ ^[0-9]+$ ]]; then tot_d=$(( tot_d + d )); fi

    if [ "$o" = "$d" ] && [ "$map" = "igual" ]; then
        printf "  %-32s %10s %10s  %s\n" "$idx" "$o" "$d" "$map"
    else
        printf "  %-32s %10s %10s  %s  <-- VER\n" "$idx" "$o" "$d" "$map"
        falhas=$(( falhas + 1 ))
    fi
done < /tmp/iqos-dest.txt

# --- 4. Diferencas de inventario --------------------------------------------
echo
echo "=== Indices em falta ==="
em_falta=$(comm -23 /tmp/iqos-src.txt /tmp/iqos-dest.txt)
if [ -z "$em_falta" ]; then
    echo "  (nenhum)"
else
    while read -r idx; do
        [ -z "$idx" ] && continue
        tam=$(curl -fsS -m 30 "$SOURCE/_cat/indices/$idx?h=pri.store.size" 2>/dev/null | tr -d ' ')
        echo "  na origem e nao no destino: $idx ($tam)"
    done <<< "$em_falta"
fi

sobra=$(comm -13 /tmp/iqos-src.txt /tmp/iqos-dest.txt)
if [ -n "$sobra" ]; then
    echo "  no destino e nao na origem:"
    echo "$sobra" | sed 's/^/    /'
fi

# --- 5. Resumo --------------------------------------------------------------
echo
echo "=== Resumo ==="
printf "  indices na origem  : %s\n" "$(wc -l < /tmp/iqos-src.txt)"
printf "  indices no destino : %s\n" "$(wc -l < /tmp/iqos-dest.txt)"
printf "  documentos origem  : %s\n" "$tot_o"
printf "  documentos destino : %s\n" "$tot_d"
printf "  em falta           : %s\n" "$(echo "$em_falta" | grep -c . )"
printf "  divergencias       : %s\n" "$falhas"
echo

if [ "$falhas" -eq 0 ]; then
    echo "OK: todos os indices do destino batem certo com a origem."
    exit 0
else
    echo "ATENCAO: $falhas indice(s) divergem -- ver as linhas <-- VER acima."
    exit 1
fi
