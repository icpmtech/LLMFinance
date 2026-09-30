"""Diagnóstico das páginas de distrito que não devolvem concelhos.

Mostra as ligações que a página do distrito publica, para perceber se o padrão
`/diretorio/<distrito>/<concelho>` é diferente (ou se a página falhou).

Uso:
    python _probe_iberinform_distrito_links.py viana-do-castelo angra-do-heroismo
"""
from __future__ import annotations

import re
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from api import empresas_recolha_service as service  # noqa: E402


def main() -> int:
    for distrito in sys.argv[1:] or ["viana-do-castelo"]:
        url = f"https://www.iberinform.pt/diretorio/{distrito}"
        page = service._fetch_html(url)
        print(f"\n=== {distrito} ({url}) ===")
        if page is None:
            print("  sem resposta")
            continue
        hrefs = [str(a.attrib.get("href") or "") for a in page.css("a")]
        padrao = re.compile(r"^/diretorio/([a-z0-9\-]+)/?$", re.I)
        diretos = sorted({m.group(1).lower() for h in hrefs if (m := padrao.match(h))})
        print(f"  ligações /diretorio/<x> simples: {diretos}")
        prefixos = Counter()
        for h in hrefs:
            match = re.match(r"^/diretorio/(?:([a-z0-9\-]+)/)*(.*)$", h)
            if h.startswith("/diretorio/") and match:
                partes = [p for p in h.split("/") if p][1:]
                prefixos[len(partes)] += 1
        print(f"  profundidade das ligações /diretorio/…: {dict(prefixos)}")
        exemplos = [h for h in hrefs if h.startswith("/diretorio/")][:12]
        print("  exemplos:", exemplos)
        titulo = page.css("h1::text").get() or page.css("title::text").get()
        print("  título:", str(titulo).strip()[:120])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
