"""Mede o volume de empresas por concelho no diretório do Iberinform.

Para cada concelho de um distrito, lê a 1.ª página do diretório e descobre:
- o número total de empresas anunciado pelo site (se existir);
- o número da última página (pela paginação);
- quantas empresas vêm na 1.ª página.

Serve para planear a recolha de um distrito inteiro antes de a lançar.

Uso:
    python _probe_iberinform_volume.py evora [--concelho alandroal]
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from api import scraper_service as scraper  # noqa: E402
from _probe_iberinform_distrito import concelhos  # noqa: E402


def _pagina(distrito: str, concelho: str, pagina: int):
    url = f"https://www.iberinform.pt/diretorio/{distrito}/{concelho}/pagina/{pagina}"
    options = {"impersonate": "chrome", "timeout": 30}
    with scraper._open_session("http", options) as session:
        return url, scraper._session_fetch(session, "http", url, options)


def medir(distrito: str, concelho: str) -> dict:
    """Volumetria de um concelho (1 pedido)."""
    url, page = _pagina(distrito, concelho, 1)
    if page is None:
        return {"concelho": concelho, "erro": "sem resposta"}
    linhas = len(page.css("table.tabla-directorio-geografico tbody tr"))
    hrefs = [str(h) for h in page.css("a::attr(href)").getall()]
    padrao = re.compile(rf"/diretorio/{re.escape(distrito)}/{re.escape(concelho)}/pagina/(\d+)")
    paginas = {int(m.group(1)) for h in hrefs if (m := padrao.search(h))}
    titulo = page.css("h1::text").get() or page.css("title::text").get() or ""
    total = None
    match = re.search(r"([\d\.\s]+)\s*(?:empresas|resultados)", page.get_all_text() or "", re.I)
    if match:
        total = int(re.sub(r"[^\d]", "", match.group(1)) or 0)
    return {
        "concelho": concelho,
        "url": url,
        "linhas_pagina1": linhas,
        "ultima_pagina_vista": max(paginas) if paginas else 1,
        "total_anunciado": total,
        "titulo": str(titulo).strip()[:120],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Volumetria do diretório Iberinform por concelho")
    parser.add_argument("distrito", nargs="?", default="evora")
    parser.add_argument("--concelho", help="Limita a um concelho")
    args = parser.parse_args()

    distrito = args.distrito.strip().lower()
    lista = [args.concelho.strip().lower()] if args.concelho else concelhos(distrito)
    soma = 0
    for nome in lista:
        info = medir(distrito, nome)
        est = (info.get("ultima_pagina_vista") or 1) * (info.get("linhas_pagina1") or 0)
        soma += est
        print(
            f"{nome:26s} linhas_pag1={info.get('linhas_pagina1'):>4} "
            f"ultima_pagina={info.get('ultima_pagina_vista'):>3} total_site={info.get('total_anunciado')} "
            f"estimativa={est}"
        )
    print(f"TOTAL concelhos={len(lista)} estimativa_empresas={soma}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
