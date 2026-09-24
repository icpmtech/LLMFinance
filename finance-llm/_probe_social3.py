"""Sonda 3: LinkedIn JSON-LD detalhado, TikTok com browser, Reddit por proxy.

A proxy residencial (2captcha) é lida de `SOCIAL_PROXY`/`TWOCAPTCHA_PROXY`
(nunca fica no código).

Uso:  python _probe_social3.py [termo]
"""
from __future__ import annotations

import json
import os
import re
import sys

TERM = sys.argv[1] if len(sys.argv) > 1 else "edp"
PROXY = os.environ.get("SOCIAL_PROXY") or os.environ.get("TWOCAPTCHA_PROXY") or ""

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"


def probe_linkedin_detail() -> None:
    import httpx

    resp = httpx.get(
        "https://www.linkedin.com/company/microsoft/",
        headers={"User-Agent": UA, "Accept-Language": "pt-PT,pt;q=0.9"},
        timeout=30,
        follow_redirects=True,
    )
    blocks = re.findall(r'<script type="application/ld\+json">(.*?)</script>', resp.text, re.S)
    print(f"--- linkedin ld+json blocos={len(blocks)}")
    for block in blocks:
        try:
            data = json.loads(block)
        except Exception as exc:
            print("    inválido:", exc)
            continue
        graph = data.get("@graph") or ([data] if data.get("@type") else [])
        for node in graph:
            if node.get("@type") == "SocialMediaPosting":
                print("    POST:", json.dumps(node, ensure_ascii=False)[:700])
        types = [n.get("@type") for n in graph]
        print("    tipos:", types[:15])
    # procurar metadados da empresa (nome, seguidores)
    print("    followers?", bool(re.search(r"(followers|seguidores)", resp.text, re.I)))


def probe_reddit_proxy() -> None:
    if not PROXY:
        print("--- reddit por proxy: SOCIAL_PROXY não definido; saltado")
        return
    import httpx

    try:
        resp = httpx.get(
            "https://www.reddit.com/search.json",
            params={"q": TERM, "limit": 5},
            headers={"User-Agent": "IQOS/1.0 (pesquisa social)"},
            proxy=PROXY,
            timeout=40,
        )
        print(f"--- reddit por proxy: status={resp.status_code} bytes={len(resp.text or '')}")
        if resp.status_code == 200:
            children = resp.json().get("data", {}).get("children", [])
            print(f"    JSON ok: {len(children)} posts")
            for child in children[:3]:
                d = child.get("data", {})
                print(f"      r/{d.get('subreddit')} | {str(d.get('title'))[:60]!r} score={d.get('score')}")
        else:
            print("    corpo:", (resp.text or "")[:200])
    except Exception as exc:
        print(f"    ERRO {type(exc).__name__}: {exc}")


def probe_tiktok_browser() -> None:
    """O TikTok monta a lista com JavaScript: usa-se o browser do Scrapling."""
    try:
        from scrapling.fetchers import DynamicSession
    except Exception as exc:
        print("--- tiktok browser: Scrapling indisponível:", exc)
        return
    captured: list = []
    try:
        with DynamicSession(headless=True, network_idle=True) as session:
            try:
                page = session.fetch(f"https://www.tiktok.com/tag/{TERM}", timeout=60000)
            except TypeError:
                page = session.fetch(f"https://www.tiktok.com/tag/{TERM}")
            html = getattr(page, "html_content", "") or getattr(page, "text", "") or ""
            print(f"--- tiktok browser: status={getattr(page, 'status', '?')} bytes={len(html)}")
            print("    itemStruct no HTML:", len(re.findall(r'"itemStruct"', html)))
            links = getattr(page, "css", lambda *a, **k: [])('a[href*="/video/"]')
            hrefs = []
            for node in links:
                try:
                    href = node.attrib.get("href") if hasattr(node, "attrib") else None
                except Exception:
                    href = None
                if href:
                    hrefs.append(href)
            print(f"    ligações de vídeo: {len(hrefs)}; exemplos: {hrefs[:3]}")
    except Exception as exc:
        print(f"    ERRO {type(exc).__name__}: {exc}")
    del captured


if __name__ == "__main__":
    for name, fn in (
        ("linkedin-detail", probe_linkedin_detail),
        ("reddit-proxy", probe_reddit_proxy),
        ("tiktok-browser", probe_tiktok_browser),
    ):
        try:
            fn()
        except Exception as exc:
            print(f"\n=== {name} ERRO {type(exc).__name__}: {exc}")
