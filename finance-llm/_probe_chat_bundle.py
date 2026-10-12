"""Confirma que o bundle servido pelo frontend inclui o chat por gateway.

Sondagem descartável: pede o `index.html` de `/chat`, extrai os bundles com hash
e procura os marcadores do catálogo de cérebros (`/chat/backends`, «Cérebro»).
"""
from __future__ import annotations

import re
import sys

import httpx

BASE = "http://127.0.0.1:4180"
MARCADORES = ("/chat/backends", "hermes-agent", "C\u00e9rebro (gateway)", "gatewayDefault")


def main() -> int:
    try:
        html = httpx.get(f"{BASE}/chat", timeout=30.0)
    except Exception as erro:  # noqa: BLE001
        print(f"frontend inacessivel: {erro}")
        return 2
    print(f"GET /chat -> {html.status_code} | cache-control: {html.headers.get('cache-control')}")

    # Só o bundle da própria aplicação: `//cdn…` é protocol-relative (terceiros).
    bundles = [
        c for c in re.findall(r'src="([^"]+\.js)"', html.text) if c.startswith("/") and not c.startswith("//")
    ]

    print(f"bundles locais: {bundles}")
    if not bundles:
        return 1

    falhas = 0
    for caminho in bundles:
        bundle = httpx.get(f"{BASE}{caminho}", timeout=60.0).text
        achados = {m: (m in bundle) for m in MARCADORES}
        print(f"{caminho} ({len(bundle) // 1024} kB)")
        for marcador, presente in achados.items():
            print(f"   {'OK ' if presente else 'X  '} {marcador}")
        if not all(achados.values()):
            falhas += 1
    return 1 if falhas else 0


if __name__ == "__main__":
    sys.exit(main())
