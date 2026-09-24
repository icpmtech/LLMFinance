"""Sonda 2: Reddit com Scrapling (impersonate) e formatos de payload.

- Reddit: JSON público via `FetcherSession(impersonate="chrome")` (TLS/JA3 de Chrome)
- TikTok: extrai `__UNIVERSAL_DATA_FOR_REHYDRATION__` da página /tag
- LinkedIn: extrai JSON-LD / `pageKey` e testa `/company/<x>/posts` (guest)
- Facebook: testa o Graph API e o mbasic com UA de browser

Uso:  python _probe_social2.py [termo]
"""
from __future__ import annotations

import json
import re
import sys

TERM = sys.argv[1] if len(sys.argv) > 1 else "edp"


def _json_between(text: str, start_marker: str, open_char: str = "{") -> object | None:
    """Extrai o JSON que começa no primeiro `{` após o marcador."""
    idx = text.find(start_marker)
    if idx < 0:
        return None
    begin = text.find(open_char, idx)
    if begin < 0:
        return None
    depth = 0
    in_str = False
    escape = False
    for pos in range(begin, len(text)):
        ch = text[pos]
        if in_str:
            if escape:
                escape = False
            elif ch == "\\":
                escape = True
            elif ch == '"':
                in_str = False
            continue
        if ch == '"':
            in_str = True
        elif ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                try:
                    return json.loads(text[begin : pos + 1])
                except json.JSONDecodeError:
                    return None
    return None


def probe_reddit_scrapling() -> None:
    from scrapling.fetchers import FetcherSession

    with FetcherSession(impersonate="chrome") as session:
        for label, url, params in (
            ("search.json", "https://www.reddit.com/search.json", {"q": TERM, "limit": 5}),
            ("r/investimentos/new.json", "https://www.reddit.com/r/investimentos/new.json", {"limit": 3}),
        ):
            try:
                resp = session.get(url, params=params, stealthy_headers=True, timeout=25)
            except TypeError:
                resp = session.get(url, params=params, timeout=25)
            print(f"\n--- reddit {label}: status={getattr(resp, 'status', '?')}")
            text = getattr(resp, "text", "") or ""
            if "search.json" in label or "new.json" in label:
                try:
                    data = json.loads(text)
                    children = data.get("data", {}).get("children", [])
                    print(f"    JSON ok: {len(children)} posts")
                    for child in children[:3]:
                        d = child.get("data", {})
                        print(f"      r/{d.get('subreddit')} | {str(d.get('title'))[:60]!r} score={d.get('score')}")
                except Exception as exc:
                    print(f"    não é JSON ({exc}); primeiros 200: {text[:200]!r}")


def probe_tiktok_payload() -> None:
    import httpx

    ua = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    resp = httpx.get(
        f"https://www.tiktok.com/tag/{TERM}",
        headers={"User-Agent": ua, "Accept-Language": "pt-PT,pt;q=0.9,en;q=0.8"},
        follow_redirects=True,
        timeout=30,
    )
    payload = _json_between(resp.text, "__UNIVERSAL_DATA_FOR_REHYDRATION__")
    print(f"\n--- tiktok tag  status={resp.status_code} universal={payload is not None}")
    if not isinstance(payload, dict):
        return
    default = payload.get("__DEFAULT_SCOPE__", {}) if isinstance(payload, dict) else {}
    print("    chaves do scope:", list(default.keys())[:12])
    detail = default.get("webapp.video-detail") or default.get("webapp.challenge-detail") or {}
    if isinstance(detail, dict):
        print("    chaves detail:", list(detail.keys())[:12])
        item_list = (((detail.get("itemList")) or (detail.get("itemStruct")) or []))
        print("    itemList tipo:", type(item_list).__name__, "n=", len(item_list) if hasattr(item_list, "__len__") else "?")
        if isinstance(item_list, list) and item_list:
            print("    chaves item:", list(item_list[0].keys())[:20])
    # procurar itemStruct em qualquer lado
    found = re.findall(r'"itemStruct"\s*:\s*\{', resp.text)
    print("    ocorrências de itemStruct:", len(found))


def probe_linkedin_posts() -> None:
    import httpx

    ua = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    for url in (
        "https://www.linkedin.com/company/microsoft/",
        "https://www.linkedin.com/company/microsoft/posts/",
    ):
        resp = httpx.get(url, headers={"User-Agent": ua, "Accept-Language": "pt-PT,pt;q=0.9"}, timeout=30, follow_redirects=True)
        text = resp.text or ""
        ld = re.findall(r'<script type="application/ld\+json">(.*?)</script>', text, re.S)
        print(f"\n--- linkedin {url} status={resp.status_code} bytes={len(text)} ld_json={len(ld)}")
        print("    pageKey:", (re.search(r'name="pageKey" content="([^"]+)"', text) or ["", "?"])[1] if re.search(r'name="pageKey" content="([^"]+)"', text) else "?")
        if ld:
            try:
                data = json.loads(ld[0])
                print("    ld+json:", json.dumps(data, ensure_ascii=False)[:400])
            except Exception as exc:
                print("    ld+json inválido:", exc)
        print("    auth wall:", "auth wall" in text.lower() or "join now" in text.lower())


def probe_facebook_graph() -> None:
    import httpx

    ua = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    resp = httpx.get(
        "https://graph.facebook.com/v21.0/me",
        headers={"User-Agent": ua},
        timeout=20,
    )
    print(f"\n--- facebook graph /me status={resp.status_code}")
    print("    ", (resp.text or "")[:240])
    resp2 = httpx.get(
        "https://www.facebook.com/public/EDP",
        headers={"User-Agent": ua, "Accept-Language": "pt-PT,pt;q=0.9"},
        timeout=25,
        follow_redirects=True,
    )
    print(f"--- facebook www/public status={resp2.status_code} bytes={len(resp2.text or '')}")
    print("    login wall:", "login" in (resp2.text or "").lower()[:5000])


if __name__ == "__main__":
    for name, fn in (
        ("reddit-scrapling", probe_reddit_scrapling),
        ("tiktok-payload", probe_tiktok_payload),
        ("linkedin-posts", probe_linkedin_posts),
        ("facebook-graph", probe_facebook_graph),
    ):
        try:
            fn()
        except Exception as exc:
            print(f"\n=== {name} ERRO {type(exc).__name__}: {exc}")
