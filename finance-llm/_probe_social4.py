"""Sonda 4: caminhos alternativos para TikTok e Reddit.

TikTok: endpoints de API internos, versão móvel, oEmbed em lote.
Reddit: `api.reddit.com`, `old.reddit.com`, e o endpoint OAuth (sem token, só
para confirmar o contrato de erro/401).

Uso:  python _probe_social4.py [termo]
"""
from __future__ import annotations

import json
import os
import re
import sys

import httpx

TERM = sys.argv[1] if len(sys.argv) > 1 else "edp"
PROXY = os.environ.get("SOCIAL_PROXY") or ""
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
MOBILE_UA = "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1"


def _head(label: str, resp: httpx.Response, limit: int = 220) -> None:
    body = resp.text or ""
    ctype = resp.headers.get("content-type", "?")
    print(f"\n--- {label}: HTTP {resp.status_code} | {ctype} | {len(body)} B")
    print("    " + body[:limit].replace("\n", " "))


def tiktok(client: httpx.Client) -> None:
    cases = [
        ("api challenge detail", "https://www.tiktok.com/api/challenge/detail/", {"challengeName": TERM, "aid": "1988"}),
        ("api challenge info", "https://www.tiktok.com/api/challenge/info/", {"challengeName": TERM, "aid": "1988"}),
        ("mobile tag page", f"https://m.tiktok.com/tag/{TERM}", None),
        ("embed page", f"https://www.tiktok.com/embed/tag/{TERM}", None),
        ("discover", f"https://www.tiktok.com/discover/{TERM}", None),
    ]
    for label, url, params in cases:
        headers = {"User-Agent": MOBILE_UA if label.startswith("mobile") else UA, "Accept-Language": "pt-PT,pt;q=0.9,en;q=0.8"}
        try:
            resp = client.get(url, params=params, headers=headers, follow_redirects=True)
        except Exception as exc:
            print(f"\n--- {label}: ERRO {type(exc).__name__}: {exc}")
            continue
        _head(f"tiktok {label}", resp)
        if "application/json" in (resp.headers.get("content-type") or ""):
            try:
                data = resp.json()
                print("    chaves:", list(data.keys())[:12])
                print("    ", json.dumps(data, ensure_ascii=False)[:300])
            except Exception:
                pass
        else:
            print("    itemStruct:", len(re.findall(r'"itemStruct"', resp.text)), "| /video/ links:", len(re.findall(r'/video/\d+', resp.text)))


def reddit(client: httpx.Client) -> None:
    cases = [
        ("api.reddit.com/search", "https://api.reddit.com/search", {"q": TERM, "limit": 3}),
        ("old.reddit .json", "https://old.reddit.com/search.json", {"q": TERM, "limit": 3}),
        ("oauth (sem token)", "https://oauth.reddit.com/search", {"q": TERM}),
        ("reddit.com/r/x.json UA googlebot", "https://www.reddit.com/r/portugal/new.json", {"limit": 3}),
    ]
    for label, url, params in cases:
        headers = {"User-Agent": "Mozilla/5.0 (compatible; Googlebot/2.1; +http://www.google.com/bot.html)" if "googlebot" in label else "IQOS/1.0"}
        try:
            resp = client.get(url, params=params, headers=headers, follow_redirects=True)
        except Exception as exc:
            print(f"\n--- {label}: ERRO {type(exc).__name__}: {exc}")
            continue
        _head(f"reddit {label}", resp, 160)
        if resp.headers.get("content-type", "").startswith("application/json"):
            try:
                data = resp.json()
                children = (data.get("data") or {}).get("children") or []
                print(f"    JSON ok: {len(children)} itens")
            except Exception as exc:
                print("    JSON inválido:", exc)


if __name__ == "__main__":
    kwargs = {"timeout": 30.0, "follow_redirects": True}
    if PROXY:
        kwargs["proxy"] = PROXY
        print(f"(proxy ativo: {PROXY.split('@')[-1]})")
    with httpx.Client(**kwargs) as client:
        for name, fn in (("tiktok", tiktok), ("reddit", reddit)):
            try:
                fn(client)
            except Exception as exc:
                print(f"\n=== {name} ERRO {type(exc).__name__}: {exc}")
