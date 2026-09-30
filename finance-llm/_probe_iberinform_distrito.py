"""Descobre os concelhos de um distrito no diretório do Iberinform.

Lê `https://www.iberinform.pt/diretorio/<distrito>` e extrai os links
`/diretorio/<distrito>/<concelho>` que o próprio site publica. Serve para a
recolha em lote não depender de uma lista de concelhos escrita à mão.

Uso:
    python _probe_iberinform_distrito.py evora
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from api import scraper_service as scraper  # noqa: E402


def concelhos(distrito: str) -> list[str]:
    """Concelhos do distrito, pela ordem em que o site os apresenta."""
    url = f"https://www.iberinform.pt/diretorio/{distrito}"
    options = {"impersonate": "chrome", "timeout": 30}
    with scraper._open_session("http", options) as session:
        page = scraper._session_fetch(session, "http", url, options)
    if page is None:
        raise RuntimeError(f"Sem resposta de {url}")
    hrefs = page.css("a::attr(href)").getall()
    padrao = re.compile(rf"^/diretorio/{re.escape(distrito)}/([a-z0-9\-]+)/?$", re.I)
    nomes: list[str] = []
    for href in hrefs:
        match = padrao.match(str(href).strip())
        if match:
            slug = match.group(1).lower()
            if slug not in nomes:
                nomes.append(slug)
    return sorted(nomes)


def main() -> int:
    distrito = (sys.argv[1] if len(sys.argv) > 1 else "evora").strip().lower()
    nomes = concelhos(distrito)
    print(f"distrito={distrito} concelhos={len(nomes)}")
    for nome in nomes:
        print(nome)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
