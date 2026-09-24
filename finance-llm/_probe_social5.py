"""Sonda 5: HTML do Reddit (sem chave) e embeds do TikTok — o que é parseável.

Uso:  python _probe_social5.py [termo]
"""
from __future__ import annotations

import re
import sys

TERM = sys.argv[1] if len(sys.argv) > 1 else "edp"

REDDIT_SELECTORS = [
    "shreddit-post",
    "article",
    "div.thing",
    ".search-result-link",
    "div[data-testid='post-container']",
    "a[href*='/comments/']",
]

TIKTOK_SELECTORS = ["a[href*='/video/']", "blockquote", "li", "div[data-e2e]"]


def probe_reddit_html() -> None:
    from scrapling.fetchers import FetcherSession

    urls = [
        f"https://www.reddit.com/search/?q={TERM}",
        "https://www.reddit.com/r/investimentos/hot/",
        "https://old.reddit.com/r/investimentos/",
    ]
    with FetcherSession(impersonate="chrome") as session:
        for url in urls:
            try:
                page = session.get(url, stealthy_headers=True, timeout=30)
            except TypeError:
                page = session.get(url, timeout=30)
            status = getattr(page, "status", "?")
            html = getattr(page, "text", "") or ""
            print(f"\n--- reddit {url}: status={status} bytes={len(html)}")
            for selector in REDDIT_SELECTORS:
                try:
                    nodes = page.css(selector)
                    print(f"    {selector}: {len(nodes)}")
                except Exception as exc:
                    print(f"    {selector}: ERRO {exc}")
            # tirar um exemplo de título
            for selector in ("shreddit-post", "div.thing", "article"):
                try:
                    nodes = page.css(selector)
                except Exception:
                    continue
                if nodes:
                    node = nodes[0]
                    text = " ".join((node.get_all_text() if hasattr(node, "get_all_text") else []).__str__().split()) if hasattr(node, "get_all_text") else ""
                    print(f"    exemplo {selector}: {text[:180]!r}")
                    break


def probe_tiktok_embed() -> None:
    from scrapling.fetchers import FetcherSession

    url = f"https://www.tiktok.com/embed/tag/{TERM}"
    with FetcherSession(impersonate="chrome") as session:
        page = session.get(url, stealthy_headers=True, timeout=30)
        html = getattr(page, "text", "") or ""
        print(f"\n--- tiktok embed: status={getattr(page, 'status', '?')} bytes={len(html)}")
        ids = sorted(set(re.findall(r"/video/(\d{6,})", html)))
        print(f"    ids de vídeo: {len(ids)} exemplos {ids[:5]}")
        for selector in TIKTOK_SELECTORS:
            try:
                print(f"    {selector}: {len(page.css(selector))}")
            except Exception as exc:
                print(f"    {selector}: ERRO {exc}")
        # oEmbed em lote para os ids encontrados
        if ids:
            import httpx

            for vid in ids[:2]:
                resp = httpx.get(
                    "https://www.tiktok.com/oembed",
                    params={"url": f"https://www.tiktok.com/@i/video/{vid}"},
                    timeout=20,
                )
                print(f"    oembed {vid}: {resp.status_code} {(resp.text or '')[:120]}")


if __name__ == "__main__":
    for name, fn in (("reddit-html", probe_reddit_html), ("tiktok-embed", probe_tiktok_embed)):
        try:
            fn()
        except Exception as exc:
            print(f"\n=== {name} ERRO {type(exc).__name__}: {exc}")
