"""Mede o tempo de cada fonte das Empresas Globais (para achar as lentas).

Uso:
    python _probe_empresas_globais_tempos.py [termo]
"""
from __future__ import annotations

import json
import sys
import time
import urllib.request

BASE = "http://127.0.0.1:8002"
FONTES = ["all", "entity", "firma", "trademark", "organo_es", "adjudicataria_es"]


def main() -> int:
    termo = sys.argv[1] if len(sys.argv) > 1 else ""
    for fonte in FONTES:
        url = f"{BASE}/companies-global/search?q={urllib.parse.quote(termo)}&source={fonte}&size=24"
        t0 = time.perf_counter()
        try:
            with urllib.request.urlopen(url, timeout=300) as resposta:
                dados = json.load(resposta)
            segundos = time.perf_counter() - t0
            cartoes = ", ".join(f"{c['id']}={c['total']}{'!' + str(c['error']) if c.get('error') else ''}" for c in dados.get("sources") or [])
            print(f"{fonte:18s} {segundos:7.2f}s  total={dados.get('total'):>9}  itens={len(dados.get('items') or []):>3}  {cartoes}")
        except Exception as exc:
            print(f"{fonte:18s} {time.perf_counter() - t0:7.2f}s  ERRO {type(exc).__name__}: {exc}")
    return 0


if __name__ == "__main__":
    import urllib.parse  # noqa: E402

    raise SystemExit(main())
