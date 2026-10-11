"""Porque é que a sonda não viu o preço? Mostra o HTML real de um item.

Dado um URL de listagem, corre a análise determinística, escolhe o melhor
contentor, e imprime (a) o HTML de um item e (b) todos os seus textos, marcando
os que *parecem* preço/descrição. Serve para ajustar os seletores com dados
reais em vez de adivinhar.

Uso (no contentor)::

    python /app/logs/_diagnosticar_item_sonda.py "https://www.worten.pt/..." --fetcher dynamic
"""
from __future__ import annotations

import argparse
import re
import sys
from typing import Any, List

sys.stdout.reconfigure(encoding="utf-8")

from api import scraper_ai  # noqa: E402
from api import scraper_service  # noqa: E402

PRECO = re.compile(r"(?:€|EUR)\s*\d|\d[.,]\d{2}\s*(?:€|EUR)", re.IGNORECASE)


def textos_do_no(no: Any, limite: int = 40) -> List[str]:
    textos: List[str] = []
    try:
        for elemento in no.css("body *"):
            pass
    except Exception:  # noqa: BLE001
        return textos
    return textos


def principal() -> int:
    parser = argparse.ArgumentParser(description="Inspecionar um item de uma listagem.")
    parser.add_argument("url")
    parser.add_argument("--fetcher", default="dynamic")
    parser.add_argument("--itens", type=int, default=2, help="Quantos itens mostrar")
    parser.add_argument("--html", type=int, default=2500, help="Bytes de HTML por item")
    args = parser.parse_args()

    with scraper_service._open_session(args.fetcher, {}) as session:
        page = scraper_service._session_fetch(session, args.fetcher, args.url, {})
    if page is None:
        print("sem página")
        return 1

    print("URL:", args.url)
    print("título:", (page.css("title::text").get() or "").strip()[:90])

    analise = scraper_ai.analyze_page(page, limit=8)
    for cand in analise[:4]:
        print(
            f"  candidato {cand.get('selector')!r} tipo={cand.get('type')} itens={cand.get('count')} "
            f"cobertura={cand.get('coverage')}"
        )
    if not analise:
        print("nenhum candidato")
        return 1

    melhor = analise[0]
    no = melhor.get("node")
    print("\n--- heurística de produto (como está hoje)")
    heuristica = scraper_ai.product_heuristic_definition(args.url, page, analise)
    campos = heuristica.get("campos") or {}
    for chave, valor in campos.items():
        seletor = valor.get("selector") if isinstance(valor, dict) else None
        print(f"  {chave:15} {seletor}")
    print("  lista:", (heuristica.get("list") or {}).get("selector"))

    if no is None:
        print("\n(o candidato não traz nó; a mostrar contentores crus)")
        return 0

    for indice in range(min(args.itens, 1)):
        print(f"\n--- HTML do item #{indice}")
        try:
            html = no.get_all_text() if indice else str(no.html_content)
        except Exception as exc:  # noqa: BLE001
            print("  erro:", exc)
            continue
        print(str(html)[: args.html])

    print("\n--- textos do item (marcando preços)")
    try:
        for elemento in no.css("*"):
            texto = " ".join((elemento.get_all_text() or "").split())
            if not texto or len(texto) > 140:
                continue
            marca = "PRECO?" if PRECO.search(texto) else "       "
            classes = " ".join((elemento.attrib.get("class") or "").split())[:60]
            print(f"  {marca} <{getattr(elemento, 'tag', '?')} class={classes!r}> {texto[:90]}")
    except Exception as exc:  # noqa: BLE001
        print("  erro:", exc)
    return 0


if __name__ == "__main__":
    sys.exit(principal())
