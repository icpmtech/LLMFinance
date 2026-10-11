"""Diagnóstico do ambiente de recolha dentro do contentor.

Diz, sem rodeios: o Scrapling está instalado? os *browsers* do Playwright estão
descarregados (sem eles `dynamic`/`stealth` falham)? qual o caminho do Chromium?
E faz uma leitura de ensaio com cada fetcher, para se ver o que o site devolve.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")

from api import scraper_service  # noqa: E402

ALVO = sys.argv[1] if len(sys.argv) > 1 else "https://books.toscrape.com/"

info = scraper_service.availability()
print("scrapling        :", info.get("scrapling"), info.get("version"))
print("fetchers         :", info.get("fetchers"))
print("playwright       :", info.get("playwright"))
print("browsers         :", info.get("browsers"), "→", str(info.get("browsers_hint"))[:120])

try:
    from playwright.sync_api import sync_playwright

    with sync_playwright() as playwright:
        caminho = Path(playwright.chromium.executable_path)
        print("chromium         :", caminho, "existe =", caminho.exists())
        print("cache playwright :", sorted(p.name for p in caminho.parent.parent.glob("*"))[:8])
except Exception as exc:  # noqa: BLE001
    print("chromium         : ERRO", type(exc).__name__, exc)

for fetcher in ("http", "dynamic", "stealth"):
    try:
        with scraper_service._open_session(fetcher, {}) as session:
            page = scraper_service._session_fetch(session, fetcher, ALVO, {})
        titulo = ""
        html = 0
        if page is not None:
            try:
                titulo = (page.css("title::text").get() or "").strip()[:70]
            except Exception:  # noqa: BLE001
                pass
            html = len(getattr(page, "html_content", "") or "")
        print(f"[{fetcher:7}] ok · título={titulo!r} · html={html} bytes")
    except Exception as exc:  # noqa: BLE001
        print(f"[{fetcher:7}] FALHOU · {type(exc).__name__}: {str(exc)[:180]}")
