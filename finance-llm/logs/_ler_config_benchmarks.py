"""O que a página de configuração mostra mesmo? (texto do `main` e botões)

Diagnóstico curto: abre `/benchmarks/configuracao`, imprime as últimas linhas do
texto do `main` e quantos botões «Sondar e guardar» existem no DOM — para separar
«não carregou o catálogo» de «carregou mas ficou fora do ecrã».

Uso::

    python logs/_ler_config_benchmarks.py [base]
"""
from __future__ import annotations

import json
import subprocess
import sys

from playwright.sync_api import sync_playwright

BASE = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:4180"


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
        contexto = navegador.chromium.launch().new_context(viewport={"width": 1600, "height": 1100}, locale="pt-PT")
        if chave:
            contexto.add_init_script(
                f"try {{ window.localStorage.setItem('finance-llm-token', {json.dumps(chave)}); }} catch (e) {{}}"
            )
        pagina = contexto.new_page()
        erros: list[str] = []
        pagina.on("console", lambda m: erros.append(f"{m.type}: {m.text}") if m.type in ("error", "warning") else None)
        pagina.goto(f"{BASE}/benchmarks/configuracao", wait_until="load", timeout=90000)
        pagina.wait_for_timeout(7000)

        dados = pagina.evaluate("async () => (await fetch('/api/benchmarks/configuracao').then(r => r.json()))")
        print("lojas no JSON da API:", len(dados.get("lojas") or []))
        print("botões «Sondar e guardar»:", pagina.locator("button:has-text('Sondar e guardar')").count())
        print("texto do main (últimos 700):")
        print(pagina.locator("main").inner_text()[-700:])
        pagina.mouse.wheel(0, 1500)
        pagina.wait_for_timeout(1500)
        print("\ndepois de rolar — botões «Sondar e guardar»:", pagina.locator("button:has-text('Sondar e guardar')").count())
        print("cartões do catálogo (div com 'fetcher'):", pagina.locator("main div:has-text('fetcher')").count())
        print("\nconsola:", erros[:5])
        contexto.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
