"""Descobre os endereços de categoria de cada loja (para a sonda de produtos).

Os sites de lojas mudam de caminhos («/portateis», «/c/computadores/…»), e um
endereço errado devolve 404 e dá a ideia errada de que a sonda falhou. Este
script abre a página inicial de cada loja com o fetcher indicado e lista as
ligações que *parecem* ser uma categoria de produtos — para depois se sondar o
endereço certo.

Uso (no contentor)::

    python /app/logs/_descobrir_categorias_lojas.py --fetcher stealth
    python /app/logs/_descobrir_categorias_lojas.py --lojas fnac,darty --termos portateis,laptop
"""
from __future__ import annotations

import argparse
import sys
import unicodedata
from typing import Any, Dict, List, Tuple
from urllib.parse import urljoin, urlparse

sys.stdout.reconfigure(encoding="utf-8")

from api import scraper_service  # noqa: E402

#: Página inicial de cada loja (o ponto de partida é sempre a raiz do site).
LOJAS: Dict[str, str] = {
    "worten": "https://www.worten.pt/",
    "fnac": "https://www.fnac.pt/",
    "fnac-es": "https://www.fnac.es/",
    "darty": "https://www.darty.com/",
    "pcdiga": "https://www.pcdiga.com/",
    "radiopopular": "https://www.radiopopular.pt/",
    "mediamarkt-pt": "https://www.mediamarkt.pt/",
    "auchan": "https://www.auchan.pt/",
}

TERMOS_POR_OMISSAO = ("portateis", "portáteis", "computadores", "informatica", "informática", "laptop", "ordinateur")


def _chave(texto: str) -> str:
    """Minúsculas sem acentos, para comparar palavras-chave."""
    base = unicodedata.normalize("NFKD", texto or "")
    return "".join(c for c in base if not unicodedata.combining(c)).lower()


def candidatos(url: str, fetcher: str, termos: List[str], maximo: int = 15) -> Tuple[str, List[Dict[str, Any]]]:
    with scraper_service._open_session(fetcher, {}) as session:
        page = scraper_service._session_fetch(session, fetcher, url, {})
    if page is None:
        return "", []
    try:
        titulo = (page.css("title::text").get() or "").strip()
    except Exception:  # noqa: BLE001
        titulo = ""
    ligacoes: List[Dict[str, Any]] = []
    vistos: set[str] = set()
    for ancora in page.css("a"):
        try:
            href = (ancora.attrib.get("href") or "").strip()
            texto = " ".join((ancora.get_all_text() or "").split())[:70]
        except Exception:  # noqa: BLE001
            continue
        if not href or href.startswith(("#", "javascript:", "mailto:", "tel:")):
            continue
        absoluto = urljoin(url, href)
        if urlparse(absoluto).netloc != urlparse(url).netloc:
            continue
        alvo = f"{_chave(texto)} {_chave(absoluto)}"
        if not any(termo in alvo for termo in termos):
            continue
        limpo = absoluto.split("?")[0]
        if limpo in vistos:
            continue
        vistos.add(limpo)
        ligacoes.append({"url": limpo, "texto": texto})
        if len(ligacoes) >= maximo:
            break
    return titulo, ligacoes


def principal() -> int:
    parser = argparse.ArgumentParser(description="Descobrir categorias de produtos por loja.")
    parser.add_argument("--lojas", default=",".join(LOJAS), help="Ids separados por vírgula")
    parser.add_argument("--fetcher", default="stealth", help="http | dynamic | stealth")
    parser.add_argument("--termos", default=",".join(TERMOS_POR_OMISSAO), help="Palavras-chave separadas por vírgula")
    args = parser.parse_args()

    termos = [_chave(t) for t in args.termos.split(",") if t.strip()]
    for chave_loja in [c.strip() for c in args.lojas.split(",") if c.strip()]:
        url = LOJAS.get(chave_loja)
        if not url:
            print(f"\n### {chave_loja}: desconhecida")
            continue
        print(f"\n### {chave_loja} · {url}")
        try:
            titulo, ligacoes = candidatos(url, args.fetcher, termos)
        except Exception as exc:  # noqa: BLE001
            print(f"  FALHOU · {type(exc).__name__}: {str(exc)[:160]}")
            continue
        print(f"  título: {titulo!r}")
        if not ligacoes:
            print("  (nenhuma categoria detetada — talvez seja preciso outro fetcher)")
        for ligacao in ligacoes:
            print(f"  - {ligacao['texto'][:50]:50} {ligacao['url']}")
    return 0


if __name__ == "__main__":
    sys.exit(principal())
