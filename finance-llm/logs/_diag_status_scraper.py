"""O objeto devolvido pelo fetcher traz o código HTTP? (para diagnosticar bloqueios)

Um 403 da Fnac aparecia na sonda como «não foi possível identificar uma lista de
produtos» — que aponta para o *markup*, quando na verdade a página foi recusada.
Isto mostra o que o `Selector` do Scrapling expõe (`status`, `status_code`, …) para
se poder distinguir «site bloqueou» de «markup diferente».

Uso::

    python -u /app/logs/_diag_status_scraper.py "https://www.fnac.pt/informatica/h10" --fetcher stealth
"""
from __future__ import annotations

import argparse
import sys

sys.stdout.reconfigure(encoding="utf-8")

from api import scraper_service as scraper  # noqa: E402


def principal() -> int:
    parser = argparse.ArgumentParser(description="Ver o status HTTP do fetcher.")
    parser.add_argument("url")
    parser.add_argument("--fetcher", default="http")
    args = parser.parse_args()

    with scraper._open_session(args.fetcher, {}) as session:
        page = scraper._session_fetch(session, args.fetcher, args.url, {})

    print("tipo:", type(page).__module__, type(page).__name__)
    for atributo in ("status", "status_code", "status_text", "reason", "headers", "url", "meta"):
        valor = getattr(page, atributo, "<não tem>")
        if isinstance(valor, dict):
            valor = {k: str(v)[:40] for k, v in list(valor.items())[:6]}
        print(f"  {atributo:12} {str(valor)[:160]}")
    texto = ""
    try:
        texto = (page.get_all_text() or "").strip()
    except Exception:  # noqa: BLE001
        pass
    print("  texto (início):", repr(texto[:180]))
    return 0


if __name__ == "__main__":
    sys.exit(principal())
