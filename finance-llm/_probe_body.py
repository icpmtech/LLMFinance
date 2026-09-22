"""Encontra o contentor do corpo de um artigo (maior densidade de parágrafos).

Uso:  python _probe_body.py "url|fetcher" [...]
Grava em `_probe_body.txt` (UTF-8).
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from api import scraper_service as scraper  # noqa: E402

_OUT = Path(__file__).resolve().parent / "_probe_body.txt"
SKIP_TAGS = {"html", "body", "head", "nav", "header", "footer", "aside", "form"}


def candidates(page, limit: int = 10):
    found: list[tuple[int, int, str, str]] = []
    try:
        elements = page.css("article, section, main, div")
    except Exception:
        return found
    for element in elements:
        tag = getattr(element, "tag", "")
        if tag in SKIP_TAGS:
            continue
        classes = [c for c in (element.attrib.get("class") or "").split() if c]
        if not classes and tag == "div":
            continue
        try:
            paragraphs = element.css("p")
        except Exception:
            continue
        if len(paragraphs) < 3:
            continue
        total = 0
        for paragraph in paragraphs:
            try:
                total += len((paragraph.get_all_text() or "").strip())
            except Exception:
                continue
        selector = f"{tag}." + ".".join(classes[:3]) if classes else tag
        try:
            text = (element.get_all_text() or "").strip().replace("\n", " ")
        except Exception:
            text = ""
        found.append((total, len(paragraphs), selector, text[:120]))
    found.sort(key=lambda item: -item[0])
    return found[:limit]


def main() -> None:
    out: list[str] = []
    cache: dict[str, tuple] = {}
    for spec in sys.argv[1:]:
        url, fetcher = (spec.split("|") + ["http"])[:2]
        fetcher = fetcher or "http"
        if fetcher not in cache:
            options = dict(scraper.DEFAULT_OPTIONS.get(fetcher, {}))
            session = scraper._open_session(fetcher, options)
            cache[fetcher] = (session, session.__enter__())
        session, context = cache[fetcher]
        try:
            page = scraper._session_fetch(context, fetcher, url, dict(scraper.DEFAULT_OPTIONS.get(fetcher, {})))
        except Exception as exc:
            out.append(f"ERRO {url}: {type(exc).__name__}: {exc}")
            continue
        out.append("=" * 100)
        out.append(f"URL {url}")
        for total, count, selector, sample in candidates(page):
            out.append(f"  {total:7d} chars  {count:3d} p  {selector:52s} {sample}")
    for session, _context in cache.values():
        try:
            session.__exit__(None, None, None)
        except Exception:
            pass
    _OUT.write_text("\n".join(out), encoding="utf-8")


if __name__ == "__main__":
    main()
