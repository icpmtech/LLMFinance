"""Confirma, no que está a correr, o thinking do gateway e a palavra «sabemos».

    python _probe_chat_wake_estado.py
"""
from __future__ import annotations

import re
import sys

import httpx

API = "http://127.0.0.1:8002"
UI = "http://127.0.0.1:4180"


def main() -> int:
    falhas = 0

    print("== backend ==")
    try:
        voz = httpx.get(f"{API}/jarvis/voice", timeout=60.0).json()
    except Exception as erro:  # noqa: BLE001
        print(f"X  /jarvis/voice: {erro}")
        return 1
    wake = voz.get("wake") or {}
    palavras = wake.get("words") or []
    print(f"   palavras de ativacao: {palavras}")
    print(f"   disponivel: {wake.get('available')} | modelo: {wake.get('model')} | motor: {wake.get('engine')}")
    if "sabemos" in palavras:
        print("OK  «sabemos» esta na lista")
    else:
        print("X   «sabemos» NAO esta na lista")
        falhas += 1

    try:
        backends = httpx.get(f"{API}/chat/backends?probe=false", timeout=60.0).json()
        print(f"   cerebro predefinido: {backends.get('default')} | backend: {[b['id'] for b in backends['backends']]}")
    except Exception as erro:  # noqa: BLE001
        print(f"X  /chat/backends: {erro}")
        falhas += 1

    print("== frontend ==")
    html = httpx.get(f"{UI}/chat", timeout=30.0)
    bundles = [c for c in re.findall(r'src="([^"]+\.js)"', html.text) if c.startswith("/") and not c.startswith("//")]
    print(f"   bundle: {bundles}")
    if not bundles:
        print("X   sem bundle local")
        return 1
    bundle = httpx.get(f"{UI}{bundles[0]}", timeout=90.0).text
    for marcador in ("/jarvis/voice", "Palavra de ativação indisponível", "Raciocínio", "/chat/backends"):
        presente = marcador in bundle
        print(f"   {'OK ' if presente else 'X  '} {marcador}")
        if not presente:
            falhas += 1

    return 1 if falhas else 0


if __name__ == "__main__":
    sys.exit(main())
