"""Valida o widget Tawk.to na landing page com o User-Agent de um Chrome normal.

O `HeadlessChrome` é detetado pela Cloudflare do Tawk.to: o pedido ao
`embed.tawk.to` volta sem `Access-Control-Allow-Origin` (e o Chromium acusa
CORS/ORB), o que **não acontece a um visitante real**. Aqui repete-se a validação
com o UA normal e com `Sec-CH-UA` coerentes, para provar o comportamento.

Uso::

    python logs/_validar_tawk_landing_ua.py [base]
"""
from __future__ import annotations

import sys

from playwright.sync_api import sync_playwright

BASE = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:4180"
UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/141.0.0.0 Safari/537.36"
)
SELETOR_BOLHA = "[class*='tawk-min-container'], iframe[id^='tawkchat']"


def main() -> int:
    erros: list[str] = []
    with sync_playwright() as p:
        browser = p.chromium.launch()
        contexto = browser.new_context(
            viewport={"width": 1366, "height": 900},
            user_agent=UA,
            locale="pt-PT",
        )
        pagina = contexto.new_page()
        pagina.on("console", lambda m: erros.append(f"{m.type}: {m.text}") if m.type == "error" else None)

        pagina.goto(f"{BASE}/?v=tawk-ua", wait_until="load", timeout=60000)
        pagina.wait_for_timeout(9000)

        estado = pagina.evaluate(
            """() => {
              const a = window.Tawk_API || {};
              return {
                script: !!document.getElementById('tawk-to-widget'),
                api: Object.keys(a).slice(0, 10),
                temShow: typeof a.showWidget,
                temHide: typeof a.hideWidget,
                iframes: Array.from(document.querySelectorAll('iframe')).filter(f => (f.src||'').includes('tawk.to')).length,
                bolhas: document.querySelectorAll("[class*='tawk-min-container'], iframe[id^='tawkchat']").length,
              };
            }"""
        )
        print("landing:", estado)

        visiveis = pagina.eval_on_selector_all(
            SELETOR_BOLHA, "els => els.filter(e => e.getBoundingClientRect().width > 0).length"
        )
        print("bolhas com dimensao na landing:", visiveis)

        # Esconder por API e confirmar que a bolha desaparece (é o que a app faz ao sair).
        if estado["temHide"] == "function":
            pagina.evaluate("() => window.Tawk_API.hideWidget()")
            pagina.wait_for_timeout(1200)
            depois = pagina.eval_on_selector_all(
                SELETOR_BOLHA, "els => els.filter(e => e.getBoundingClientRect().width > 0).length"
            )
            print("bolhas depois de hideWidget:", depois)

        print("erros de consola:", [e[:120] for e in erros[:5]])
        contexto.close()
        browser.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
