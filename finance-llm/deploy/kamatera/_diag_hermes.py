#!/usr/bin/env python3
"""Diagnostico do servidor de API do Hermes, corre **dentro** do contentor.

Uso (o script vai pelo stdin, sem aspas a atravessar o PowerShell e o ssh):

    Get-Content -Raw _diag_hermes.py | ssh ... "docker exec -i iqos-hermes-agent python3 -"

Porque dentro do contentor: do lado de fora, o `docker-proxy` aceita a ligacao a
`127.0.0.1:8642` mesmo quando **nada** escuta na 8642 la dentro. A ligacao TCP
estabelece, o pedido HTTP nao obtem resposta, e o `curl` devolve `000`. Isso e
ambiguo: pode ser um servico em baixo ou um servico que nao fala HTTP ali. So de
dentro se distingue.
"""
from __future__ import annotations

import socket
import urllib.error
import urllib.request

PORTAS = (8642, 9119)


def em_escuta(porta: int) -> bool:
    """Ha algo a escutar nesta porta, dentro do contentor?"""
    s = socket.socket()
    s.settimeout(2)
    try:
        s.connect(("127.0.0.1", porta))
        return True
    except OSError:
        return False
    finally:
        s.close()


def tentar_http(porta: int, metodo: str = "GET") -> str:
    pedido = urllib.request.Request(f"http://127.0.0.1:{porta}/", method=metodo)
    try:
        with urllib.request.urlopen(pedido, timeout=4) as r:
            return f"HTTP {r.status}"
    except urllib.error.HTTPError as e:
        # 401/403/404/405 contam como **resposta**: o servico esta vivo e a falar
        # HTTP. So a ausencia de resposta e que e interessante.
        return f"HTTP {e.code}"
    except Exception as e:  # noqa: BLE001
        return f"sem resposta HTTP ({type(e).__name__}: {e})"


print("=== o que escuta dentro do contentor ===")
for p in PORTAS:
    print(f"  {p}: {'em escuta' if em_escuta(p) else 'NADA a escutar'}")

print()
print("=== resposta HTTP ===")
for p in PORTAS:
    print(f"  GET  {p}: {tentar_http(p)}")
# O servidor de API do Hermes pode so aceitar POST (e um endpoint de agente, nao
# uma pagina). Vale a pena distinguir "nao fala HTTP" de "nao responde a GET".
print(f"  POST 8642: {tentar_http(8642, 'POST')}")

print()
print("=== variaveis que controlam o servidor de API ===")
import os  # noqa: E402

for chave in ("API_SERVER_ENABLED", "API_SERVER_HOST", "API_SERVER_PORT",
              "API_SERVER_KEY", "HERMES_DASHBOARD", "HERMES_DASHBOARD_HOST",
              "HERMES_DASHBOARD_PORT"):
    valor = os.environ.get(chave)
    if valor and "KEY" in chave:
        valor = f"<definida, {len(valor)} caracteres>"
    print(f"  {chave} = {valor!r}")
