"""Valida no browser (headless) o widget Tawk.to da landing page.

Confirma três coisas que só se veem em execução:

1. o `<script>` do Tawk.to é injetado **uma vez** (`#tawk-to-widget`);
2. o widget aparece na landing page (a iframe do Tawk.to é criada);
3. ao sair da landing page (rota da SPA) a bolha é escondida — o widget é para
   visitantes anónimos, não para dentro da aplicação.

Imprime também os erros de consola e os pedidos falhados, para distinguir
«bloqueado pelo iubenda» de «quebrado».

Uso::

    python logs/_validar_tawk_landing.py [http://127.0.0.1:4180]
"""
from __future__ import annotations

import sys
import time

from playwright.sync_api import sync_playwright

BASE = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:4180"
#: O autoblocking do iubenda só liberta o widget depois do consentimento; o
#: seletor da bolha é estável (`div#tawkchat-...` / classe `tawk-min-container`).
SELETOR_BOLHA = "[class*='tawk-min-container'], iframe[id^='tawkchat']"


def main() -> int:
    erros: list[str] = []
    falhados: list[str] = []
    with sync_playwright() as p:
        browser = p.chromium.launch()
        pagina = browser.new_page(viewport={"width": 1366, "height": 900})
        pagina.on("console", lambda msg: erros.append(f"{msg.type}: {msg.text}") if msg.type == "error" else None)
        pagina.on("requestfailed", lambda req: falhados.append(f"{req.url} ({req.failure})"))

        pagina.goto(f"{BASE}/?v=validar-tawk", wait_until="load", timeout=60000)
        pagina.wait_for_timeout(6000)  # o widget carrega depois do React

        script = pagina.evaluate(
            "() => { const s = document.getElementById('tawk-to-widget'); return s ? {src: s.src, async: s.async} : null; }"
        )
        print("script do Tawk.to:", script)

        iframes_tawk = pagina.evaluate(
            "() => Array.from(document.querySelectorAll('iframe')).filter(f => (f.src || '').includes('tawk.to')).map(f => f.id || f.src)"
        )
        print("iframes do Tawk.to:", iframes_tawk)

        api = pagina.evaluate(
            "() => { const a = window.Tawk_API || {}; return {chaves: Object.keys(a).slice(0, 12), temShow: typeof a.showWidget, temHide: typeof a.hideWidget}; }"
        )
        print("Tawk_API:", api)

        # --- navegar para dentro da aplicação (rota da SPA) ------------------
        pagina.goto(f"{BASE}/login?v=validar-tawk", wait_until="load", timeout=60000)
        pagina.wait_for_timeout(4000)
        bolhas = pagina.eval_on_selector_all(SELETOR_BOLHA, "els => els.length")
        visiveis = pagina.eval_on_selector_all(
            SELETOR_BOLHA, "els => els.filter(e => e.getBoundingClientRect().width > 0).length"
        )
        print(f"fora da landing: {bolhas} bolha(s) no DOM, {visiveis} com dimensao")

        anexado = pagina.evaluate(
            "() => { const a = window.Tawk_API || {}; return typeof a.hideWidget === 'function'; }"
        )
        print("hideWidget disponivel fora da landing:", anexado)

        print("\nerros de consola:", len(erros))
        for linha in erros[:8]:
            print("   ", linha[:160])
        print("pedidos falhados:", len(falhados))
        for linha in falhados[:8]:
            print("   ", linha[:160])
        browser.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
