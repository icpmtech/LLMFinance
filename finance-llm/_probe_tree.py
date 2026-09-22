"""Árvore compacta de um nó (tag.classes + [attr] + texto), para desenhar campos.

Uso:  python _probe_tree.py "url|seletor|fetcher" [...]
Grava em `_probe_tree.txt` (UTF-8).
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from api import scraper_service as scraper  # noqa: E402

_OUT = Path(__file__).resolve().parent / "_probe_tree.txt"
INTERESTING = ("datetime", "href", "src", "content", "aria-label", "title")


def describe(node, depth: int = 0, lines: list | None = None, budget: list | None = None) -> None:
    lines = lines if lines is not None else []
    budget = budget if budget is not None else [70]
    if budget[0] <= 0 or depth > 7:
        return
    budget[0] -= 1
    classes = ".".join((node.attrib.get("class") or "").split()[:2])
    name = node.tag + (f".{classes}" if classes else "")
    attrs = []
    for attr in INTERESTING:
        value = node.attrib.get(attr)
        if value:
            attrs.append(f"{attr}={str(value)[:60]}")
    text = ""
    try:
        own = [t.strip() for t in (node.text or "").split("\n") if t.strip()]
        text = " ".join(own)[:90]
    except Exception:
        text = ""
    lines.append(f"{'  ' * depth}{name}{' [' + ', '.join(attrs) + ']' if attrs else ''}{' :: ' + text if text else ''}")
    for child in node.children:
        if not isinstance(child, str):
            describe(child, depth + 1, lines, budget)
    return lines


def main() -> None:
    out: list[str] = []
    cache: dict[str, tuple] = {}
    for spec in sys.argv[1:]:
        url, selector, fetcher = (spec.split("|") + ["http"])[:3]
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
        nodes = list(page.css(selector))
        out.append("=" * 100)
        out.append(f"URL {url} | {selector!r} | {fetcher} | nós {len(nodes)}")
        for node in nodes[:1]:
            out.extend(describe(node) or [])
    for session, _context in cache.values():
        try:
            session.__exit__(None, None, None)
        except Exception:
            pass
    _OUT.write_text("\n".join(out), encoding="utf-8")


if __name__ == "__main__":
    main()
