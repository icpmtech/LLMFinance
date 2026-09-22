"""Sonda de apoio aos templates de recolha.

Para cada URL, obtém a página e mostra:
  - os melhores candidatos a seletor de lista (análise do `scraper_ai`);
  - os seletores mais frequentes dentro dos itens (título, ligação, data, imagem);
  - o `link rel=alternate` (feed RSS) quando existe.

Uso:  python _probe_scraper_templates.py [url ...]
"""
from __future__ import annotations

import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from api import scraper_ai  # noqa: E402
from api import scraper_service as scraper  # noqa: E402

URLS = [
    "https://jornaleconomico.sapo.pt/",
    "https://eco.sapo.pt/",
    "https://www.jornaldenegocios.pt/",
    "https://www.dinheirovivo.pt/",
    "https://observador.pt/",
    "https://www.publico.pt/economia",
    "https://www.idealista.pt/news/",
]

FIELD_CANDIDATES = [
    "h1::text", "h2::text", "h3::text", "h4::text", "h1 a::text", "h2 a::text", "h3 a::text",
    "a::attr(href)", "h2 a::attr(href)", "h3 a::attr(href)", "time::attr(datetime)", "time::text",
    "span::text", "p::text", "img::attr(src)", "img::attr(data-src)", ".date::text",
]


_OUT = Path(__file__).resolve().parent / "_probe_templates.txt"
# O console do Windows estraga os acentos; o relatório vai para um ficheiro UTF-8.
_sink = _OUT.open("w", encoding="utf-8")
sys.stdout = _sink


def probe(url: str, fetcher: str = "http") -> None:
    print("=" * 100)
    print(f"URL: {url}  (fetcher={fetcher})")
    options = dict(scraper.DEFAULT_OPTIONS.get(fetcher, {}))
    try:
        with scraper._open_session(fetcher, options) as session:
            page = scraper._session_fetch(session, fetcher, url, options)
    except Exception as exc:
        print(f"  ERRO ao obter: {type(exc).__name__}: {exc}")
        return
    if page is None:
        print("  sem resposta")
        return

    feeds = []
    try:
        feeds = [str(v) for v in page.css("link[type='application/rss+xml']::attr(href)").getall()]
    except Exception:
        pass
    print(f"  feeds: {feeds[:4]}")

    analysis = scraper_ai.analyze_page(page, limit=5)
    for entry in analysis:
        print(
            f"  candidato {entry['selector']!r:50s} count={entry['count']:4d} "
            f"tit={entry['title_ratio']} txt={entry['text_ratio']} link={entry['link_ratio']} score={entry['score']}"
        )
        for sample in entry.get("samples", [])[:2]:
            print(f"      · {sample[:110]}")
    if not analysis:
        print("  (sem candidatos)")
        return

    rows = []
    try:
        rows = list(page.css(analysis[0]["selector"]))
    except Exception:
        pass
    if not rows:
        return
    counter: Counter[str] = Counter()
    for node in rows[:40]:
        for selector in FIELD_CANDIDATES:
            try:
                values = [str(v).strip() for v in node.css(selector).getall() if str(v).strip()]
            except Exception:
                continue
            if any(len(v) > 3 for v in values):
                counter[selector] += 1
    print("  dentro do melhor candidato (cobertura em 40 itens):")
    for selector, count in counter.most_common(14):
        print(f"      {count:3d}/40  {selector}")


if __name__ == "__main__":
    targets = sys.argv[1:] or URLS
    for target in targets:
        url, _, fetcher = target.partition("|")
        probe(url, fetcher or "http")
