"""Sonda: endpoint da ficha do contrato (peças + destaques)."""

from __future__ import annotations

import json
import sys
import time

import httpx

BASE = "http://localhost:8002"


def main() -> int:
    alvos = sys.argv[1:] or ["/contracts/11970045/document"]
    with httpx.Client(timeout=120) as c:
        for alvo in alvos:
            url = alvo if alvo.startswith("http") else BASE + alvo
            inicio = time.time()
            r = c.get(url)
            print("=" * 78)
            print(f"{url} -> {r.status_code}  ({time.time() - inicio:.1f}s)")
            if r.status_code != 200:
                print(r.text[:400])
                continue
            dados = r.json()
            print(f"source={dados.get('source')!r} uid={dados.get('uid')!r} pieces_total={dados.get('pieces_total')!r}")
            print(f"error={dados.get('error')!r}")
            print(f"pieces={[p.get('name') for p in dados.get('pieces') or []]}")
            for h in (dados.get("highlights") or [])[:8]:
                print(f"   - {h.get('label')}: {str(h.get('value'))[:70]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
