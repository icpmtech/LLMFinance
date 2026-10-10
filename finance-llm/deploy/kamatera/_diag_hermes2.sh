#!/bin/sh
# De onde vem a mensagem "aiohttp not installed", se o aiohttp esta instalado?
#
# O log do gateway diz:
#   WARNING gateway.run: API Server: aiohttp not installed
#   WARNING gateway.run: No adapter available for api_server
#
# Mas `python3 -c 'import aiohttp'` dentro do contentor devolve 3.14.3. Portanto
# nao e o pacote que falta -- e outra coisa. Este script procura a mensagem no
# codigo para perceber o que o gateway testa na realidade (import, find_spec,
# nome diferente) e com que interpretador o faz.
#
# Vai pelo stdin (`ssh ... sh -s`), sem aspas a atravessar PowerShell e bash.
set -u

C=iqos-hermes-agent

echo "=== onde esta a mensagem ==="
docker exec "$C" grep -rn "aiohttp not installed" /opt /app /usr/local/lib /usr/lib 2>/dev/null | head -5

echo
echo "=== que interpretador corre o gateway ==="
docker exec "$C" sh -c 'cat /proc/1/cmdline | tr "\0" " "; echo'
docker exec "$C" sh -c 'ls -d /opt/hermes/.venv 2>/dev/null; ls -l /opt/hermes/.venv/bin/python* 2>/dev/null'

echo
echo "=== aiohttp visto por esse interpretador ==="
# Se houver um venv, e a ele que o gateway obedece -- nao ao `python3` do PATH.
for P in /opt/hermes/.venv/bin/python /usr/local/bin/python3 /usr/bin/python3; do
    if [ -x "$P" ]; then
        printf '  %s -> ' "$P"
        "$P" -c "import aiohttp, sys; print(aiohttp.__version__, sys.executable)" 2>&1 | head -2
    fi
done

echo
echo "=== o codigo do adaptador api_server ==="
docker exec "$C" sh -c 'grep -rln "api_server" /opt/hermes 2>/dev/null | head -10'

echo
echo "=== o no que faz o teste ==="
docker exec "$C" sh -c 'grep -rn -B4 -A4 "aiohttp" /opt/hermes 2>/dev/null | head -60'
