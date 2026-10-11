"""Lê o texto do cartão de um estudo na página `/benchmarks` (headless).

Serve para confirmar, no browser, o que o cartão mostra: números de ofertas e
produtos, preço médio (que já apareceu «—» para sempre), a chave de comparação e
o aviso de que uma só loja não permite comparação.

Uso::

    python logs/_ler_cartao_benchmark.py portateis-lojas [base]
"""
from __future__ import annotations

import json
import re
import subprocess
import sys

from playwright.sync_api import sync_playwright

SLUG = sys.argv[1] if len(sys.argv) > 1 else "portateis-lojas"
BASE = sys.argv[2] if len(sys.argv) > 2 else "http://127.0.0.1:4180"


def token() -> str:
    codigo = (
        "from api import auth_service;"
        "u = auth_service.list_users(1) or [];"
        "s = auth_service.create_session(u[0]) if u else {};"
        "print('TOKEN=' + str(s.get('token', '')))"
    )
    saida = subprocess.run(
        ["docker", "exec", "finance-llm-backend", "python", "-c", codigo],
        capture_output=True, text=True, timeout=120,
    )
    for linha in (saida.stdout or "").splitlines():
        if linha.startswith("TOKEN="):
            return linha.split("=", 1)[1].strip()
    return ""


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    chave = token()
    with sync_playwright() as navegador:
        contexto = navegador.chromium.launch().new_context(viewport={"width": 1500, "height": 950}, locale="pt-PT")
        if chave:
            contexto.add_init_script(
                f"try {{ window.localStorage.setItem('finance-llm-token', {json.dumps(chave)}); }} catch (e) {{}}"
            )
        pagina = contexto.new_page()
        pagina.goto(f"{BASE}/benchmarks", wait_until="load", timeout=60000)
        pagina.wait_for_timeout(6000)

        # Cada cartão tem o botão «Abrir estudo»: sobe-se ao antepassado que o contém.
        cartoes = pagina.locator("main div", has=pagina.locator("button:has-text('Abrir estudo')"))
        total = cartoes.count()
        print(f"cartões: {total}")
        for indice in range(total):
            cartao = cartoes.nth(indice)
            texto = " ".join(cartao.inner_text().split())
            if SLUG.split("-")[0].lower() in texto.lower() or total == 1:
                print(f"\n--- cartão de «{SLUG}»")
                print(texto[:400])
                numero = re.search(r"preço médio\s*([\d\s.,]+EUR)", texto)
                print("\npreço médio lido:", numero.group(1).strip() if numero else "não encontrado")
                break
        contexto.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
