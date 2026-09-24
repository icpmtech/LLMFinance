"""Sonda de conectividade e formatos das APIs públicas das redes sociais.

Testa, sem chaves, o que é possível recolher de Reddit, TikTok, Facebook e
LinkedIn. Serve para decidir o desenho dos coletores (`api/social_collectors.py`).

Uso:  python _probe_social.py [termo]
"""
from __future__ import annotations

import json
import sys

import httpx

TERM = sys.argv[1] if len(sys.argv) > 1 else "EDP"

UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)


def _show(label: str, resp: httpx.Response, limit: int = 600) -> None:
    body = resp.text or ""
    print(f"\n=== {label} :: HTTP {resp.status_code} ({len(body)} B)")
    print(f"    content-type: {resp.headers.get('content-type', '?')}")
    print("    " + body[:limit].replace("\n", " ")[:limit])


def probe_reddit(client: httpx.Client) -> None:
    """Reddit expõe JSON público em qualquer caminho + `.json`."""
    headers = {"User-Agent": "IQOS/1.0 (pesquisa social autorizada)"}
    r = client.get(
        "https://www.reddit.com/search.json",
        params={"q": TERM, "limit": 5, "sort": "relevance", "t": "month"},
        headers=headers,
    )
    _show("reddit /search.json", r)
    if r.status_code == 200:
        data = r.json()
        children = data.get("data", {}).get("children", [])
        print(f"    -> {len(children)} posts")
        for child in children[:3]:
            d = child.get("data", {})
            print(
                f"       r/{d.get('subreddit')} | {str(d.get('title'))[:70]} | "
                f"score={d.get('score')} comments={d.get('num_comments')} | {d.get('created_utc')}"
            )
    r2 = client.get(
        "https://www.reddit.com/r/investimentos/new.json",
        params={"limit": 3},
        headers=headers,
    )
    _show("reddit /r/investimentos/new.json", r2, 300)


def probe_tiktok(client: httpx.Client) -> None:
    """TikTok: oEmbed público (sem chave) + página de hashtag (HTML com JSON embutido)."""
    r = client.get(
        "https://www.tiktok.com/oembed",
        params={"url": "https://www.tiktok.com/@tiktok/video/6718335390845095173"},
        headers={"User-Agent": UA},
    )
    _show("tiktok oembed", r, 400)
    r2 = client.get(
        f"https://www.tiktok.com/tag/{TERM.lower()}",
        headers={"User-Agent": UA, "Accept-Language": "pt-PT,pt;q=0.9,en;q=0.8"},
        follow_redirects=True,
    )
    _show("tiktok /tag/<termo>", r2, 300)
    if r2.status_code == 200:
        print("    UNIVERSAL_DATA presente:", "__UNIVERSAL_DATA_FOR_REHYDRATION__" in r2.text)


def probe_facebook(client: httpx.Client) -> None:
    """Facebook público: `mbasic`/`www` sem sessão (quase sempre login wall)."""
    r = client.get(
        f"https://mbasic.facebook.com/search/posts/?q={TERM}",
        headers={"User-Agent": UA, "Accept-Language": "pt-PT,pt;q=0.9"},
        follow_redirects=True,
    )
    _show("facebook mbasic search posts", r, 300)
    print("    login wall:", "login" in r.text.lower()[:4000])


def probe_linkedin(client: httpx.Client) -> None:
    """LinkedIn exige sessão para quase tudo; sem cookies devolve 999/302."""
    r = client.get(
        "https://www.linkedin.com/company/microsoft/",
        headers={"User-Agent": UA, "Accept-Language": "pt-PT,pt;q=0.9"},
        follow_redirects=False,
    )
    _show("linkedin /company/microsoft", r, 200)


def main() -> None:
    print(f"termo: {TERM!r}")
    with httpx.Client(timeout=25.0, follow_redirects=False) as client:
        for name, fn in (
            ("reddit", probe_reddit),
            ("tiktok", probe_tiktok),
            ("facebook", probe_facebook),
            ("linkedin", probe_linkedin),
        ):
            try:
                fn(client)
            except Exception as exc:  # pragma: no cover - sonda
                print(f"\n=== {name} :: ERRO {type(exc).__name__}: {exc}")


if __name__ == "__main__":
    main()
