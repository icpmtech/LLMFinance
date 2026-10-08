"""Diagnóstico do carregamento do script do Tawk.to (porque falha o pedido).

Compara três formas de pedir o mesmo script, para separar «problema do script»
de «problema de atributo/CORS»:

A. como o nosso componente faz hoje (`crossorigin="*"`);
B. sem o atributo `crossorigin` (carregamento clássico);
C. pedido direto ao URL pelo próprio browser (fetch), para ver o estado HTTP.

Mostra sempre o texto COMPLETO do erro de consola e as respostas de rede.

Uso::

    python logs/_diag_tawk_cors.py [página-base]
"""
from __future__ import annotations

import sys

from playwright.sync_api import sync_playwright

URL = "https://embed.tawk.to/6ac786035f2ded34cbd1cbeb/1k4dm7048"


def _tentar(pagina, nome: str, *, crossorigin: bool) -> None:
    eventos: list[str] = []
    pagina.on("console", lambda m: eventos.append(f"  console[{m.type}] {m.text}"))
    pagina.on("requestfailed", lambda r: eventos.append(f"  falhou {r.url[:60]} -> {r.failure}"))
    pagina.on("response", lambda r: eventos.append(f"  resp {r.status} {r.url[:60]}") if "tawk.to" in r.url else None)

    pagina.goto("about:blank")
    pagina.wait_for_timeout(300)
    resultado = pagina.evaluate(
        """async ([url, comCrossorigin]) => {
          const s = document.createElement('script');
          s.async = true;
          s.src = url;
          if (comCrossorigin) s.setAttribute('crossorigin', '*');
          const p = new Promise((resolve) => {
            s.onload = () => resolve('onload');
            s.onerror = (e) => resolve('onerror');
            setTimeout(() => resolve('sem-sinal'), 12000);
          });
          document.head.appendChild(s);
          const estado = await p;
          return { estado, temTawkApi: typeof window.Tawk_API, temTawkObject: typeof window.TawkObject };
        }""",
        [URL, crossorigin],
    )
    print(f"\n== {nome}")
    for linha in eventos:
        print("   ", linha)
    print("    resultado:", resultado)


def main() -> int:
    with sync_playwright() as p:
        browser = p.chromium.launch()
        pagina = browser.new_page()

        # C: pedido direto, para ver o estado HTTP e os cabeçalhos a partir do browser.
        pagina.goto("about:blank")
        direto = pagina.evaluate(
            """async (url) => {
              try {
                const r = await fetch(url, { mode: 'cors' });
                return { status: r.status, type: r.type, acao: r.headers.get('access-control-allow-origin') };
              } catch (e) { return { erro: String(e) }; }
            }""",
            URL,
        )
        print("== C. fetch direto do browser:", direto)

        _tentar(pagina, "A. como no componente (crossorigin=\"*\")", crossorigin=True)
        _tentar(pagina, "B. sem crossorigin", crossorigin=False)
        browser.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
