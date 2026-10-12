"""Sonda: ficha do contrato -> peças Vortal -> texto e valores reconhecidos.

Uso: .\.venv\Scripts\python.exe _probe_ficha_vortal.py [idcontrato ...]
"""

from __future__ import annotations

import json
import sys
import time

from api import contract_document as cd


def mostrar(idcontrato: str) -> None:
    inicio = time.time()
    r = cd.contract_document(idcontrato)
    print("=" * 78)
    print(f"contrato {idcontrato}  ({time.time() - inicio:.1f}s)")
    print("links:")
    for link in r.get("links") or []:
        print(f"   - {link.get('label')}  [{(link.get('url') or '')[:60]}]")
    print(f"source={r.get('source')!r} uid={r.get('uid')!r} publicado={r.get('publicado')!r}")
    print(f"pieces_total={r.get('pieces_total')!r} erro={r.get('error')!r}")
    print(f"note={r.get('note')!r}")
    print(f"pieces ({len(r.get('pieces') or [])}):")
    for p in r.get("pieces") or []:
        texto = p.get("text") or ""
        print(f"   - {p.get('name')}  [{p.get('kind')}]  {len(texto)} chars")
    print(f"highlights ({len(r.get('highlights') or [])}):")
    for h in (r.get("highlights") or [])[:20]:
        print(f"   - {h.get('label')}: {str(h.get('value'))[:80]}   <- {h.get('document')}")


def main() -> int:
    alvos = sys.argv[1:] or ["11970015"]
    for alvo in alvos:
        try:
            mostrar(alvo)
        except Exception as exc:  # noqa: BLE001
            print(f"contrato {alvo}: erro {type(exc).__name__}: {exc}")
    print(json.dumps({"ok": True}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
