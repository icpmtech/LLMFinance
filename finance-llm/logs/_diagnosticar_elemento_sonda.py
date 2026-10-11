"""O que é, afinal, um «elemento» do Scrapling? (atributos e tag)

Diagnóstico curto: para o primeiro item de uma listagem, mostra o tipo do objeto,
o que devolve `tagname`/`tag`, as chaves de `attrib` e o `root.tag` do lxml. Foi
isto que revelou que `_selector_do_no` estava a devolver seletores **vazios**
(nada era minerado) porque `tagname` não existia nestes elementos.

Uso::

    python -u /app/logs/_diagnosticar_elemento_sonda.py "https://www.worten.pt/..." --fetcher dynamic
"""
from __future__ import annotations

import argparse
import sys

sys.stdout.reconfigure(encoding="utf-8")

from api import scraper_ai  # noqa: E402
from api import scraper_service  # noqa: E402


def principal() -> int:
    parser = argparse.ArgumentParser(description="Inspecionar elementos do Scrapling.")
    parser.add_argument("url")
    parser.add_argument("--fetcher", default="dynamic")
    args = parser.parse_args()

    with scraper_service._open_session(args.fetcher, {}) as session:
        page = scraper_service._session_fetch(session, args.fetcher, args.url, {})

    item = page.css("article")[0]
    print("item:", type(item).__module__, type(item).__name__)
    print("  tagname     :", repr(getattr(item, "tagname", "<sem atributo>")))
    print("  tag         :", repr(getattr(item, "tag", "<sem atributo>")))
    print("  root.tag    :", repr(getattr(getattr(item, "root", None), "tag", "<sem root>")))
    print("  attrib keys :", list((item.attrib or {}).keys())[:8])

    elementos = item.css(scraper_ai._ELEMENTOS_BUSCA)
    print(f"elementos: {len(elementos)}")
    for elemento in elementos[:6]:
        print(
            "  ",
            type(elemento).__name__,
            "| tagname=", repr(getattr(elemento, "tagname", "<não tem>")),
            "| tag=", repr(getattr(elemento, "tag", "<não tem>")),
            "| root.tag=", repr(getattr(getattr(elemento, "root", None), "tag", "<sem root>")),
            "| classes=", repr((elemento.attrib or {}).get("class")),
            "| seletor=", repr(scraper_ai._selector_do_no(elemento)),
        )
    return 0


if __name__ == "__main__":
    sys.exit(principal())
