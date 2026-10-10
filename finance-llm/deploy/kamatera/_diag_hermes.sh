#!/bin/sh
# Diagnostico do iqos-hermes-agent.
#
# Porque e que isto e um ficheiro e nao um comando de uma linha: as aspas
# aninhadas (`sh -c 'awk "$4==..."'`) atravessam PowerShell -> ssh -> bash -> sh
# e o parser do PowerShell acaba por interpretar um `-i` como parametro proprio
# ("A value that is not valid ... for the inputFormat parameter"). O script vai
# pelo stdin, sem aspas nenhumas pelo caminho.
set -u

C=iqos-hermes-agent

echo "=== estado do contentor ==="
docker ps --filter "name=$C" --format '{{.Names}}  {{.Status}}'

echo
echo "=== socket de escuta dentro do contentor ==="
# /proc/net/tcp e sempre legivel; nao depende de ter `ss` ou `netstat` na imagem.
# A coluna 4 com o estado `0A` e LISTEN. O segundo campo e endereco:porta, em
# hexadecimal -- 8642 = 0x21C2, 9119 = 0x239F. Ler dali e o que distingue
# "o servico da API nao arrancou" de "arrancou noutra porta".
if [ -r /proc/1/root/proc/net/tcp ]; then :; fi
docker exec "$C" cat /proc/net/tcp 2>/dev/null | awk 'NR==1 || $4=="0A" {print}' \
    || echo "(nao consegui ler /proc/net/tcp)"

echo
echo "=== traducao das portas em escuta ==="
docker exec "$C" cat /proc/net/tcp 2>/dev/null \
    | awk '$4=="0A" {split($2,a,":"); printf "  porta %d (0x%s)  em %s\n", strtonum("0x" a[2]), a[2], a[1]}' \
    || echo "(sem dados)"

echo
echo "=== ultimas linhas do log ==="
docker logs "$C" 2>&1 | tail -30
