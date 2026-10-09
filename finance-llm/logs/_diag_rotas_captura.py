"""Compara rotas que ficaram no login com rotas que ficaram autenticadas.

A captura de 2026-10-09 saiu com os primeiros ecrãs no **ecrã de login** (todos com
o mesmo tamanho de ficheiro) e os últimos já com a aplicação — sinal de que algo
muda a meio. Aqui visita-se cada rota com o mesmo token e regista-se o que a app
mostra, para saber se é permissão da conta, tempo de validação ou ordem.

Uso::

    python logs/_diag_rotas_captura.py
"""
from __future__ import annotations

import json
import subprocess
import sys

from playwright.sync_api import sync_playwright

BASE = "http://127.0.0.1:4180"
ROTAS = ["/contracts/dashboard", "/empresas-iq", "/hermes", "/visualizador", "/reports", "/crm"]
CODIGO_TOKEN = (
    "from api import auth_service;"
    "us = auth_service.list_users(3) or [];"
    "print('UTILIZADORES=' + json.dumps([u.get('email') for u in us]));"
    "s = auth_service.create_session(us[0]) if us else {};"
    "print('TOKEN=' + str(s.get('token', '')))"
)


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    saida = subprocess.run(
        ["docker", "exec", "finance-llm-backend", "python", "-c",
         CODIGO_TOKEN.replace("json.dumps", "__import__('json').dumps")],
        capture_output=True, text=True, timeout=120,
    )
    token = ""
    for linha in (saida.stdout or "").splitlines():
        if linha.startswith("UTILIZADORES="):
            print("contas mais recentes:", linha.split("=", 1)[1])
        if linha.startswith("TOKEN="):
            token = linha.split("=", 1)[1].strip()
    print("token:", len(token), "caracteres")
    if not token:
        print(saida.stderr[-400:])
        return 1

    with sync_playwright() as p:
        browser = p.chromium.launch()
        contexto = browser.new_context(viewport={"width": 1600, "height": 950})
        contexto.add_init_script(
            f"try {{ window.localStorage.setItem('finance-llm-token', {json.dumps(token)}); }} catch (e) {{}}"
        )
        pagina = contexto.new_page()
        pagina.set_default_timeout(30000)
        for rota in ROTAS:
            auth: list[str] = []
            pagina.on("response", lambda r: auth.append(f"{r.status} {r.url.split('?')[0][-28:]}")
                      if "/auth/" in r.url else None)
            try:
                pagina.goto(f"{BASE}{rota}", wait_until="load", timeout=60000)
                pagina.wait_for_timeout(8000)
                estado = pagina.evaluate(
                    """() => ({
                      url: window.location.pathname,
                      login: !!document.querySelector("input[type=password]"),
                      aValidar: (document.body.innerText || '').includes('A validar'),
                      amostra: (document.querySelector('main')?.innerText || document.body.innerText || '').slice(0, 70).replace(/\\n/g, ' | '),
                    })"""
                )
                print(f"{rota:24} -> {estado['url']:22} login={estado['login']} validar={estado['aValidar']} :: {estado['amostra']}")
            except Exception as exc:  # noqa: BLE001
                print(f"{rota:24} -> ERRO {type(exc).__name__}: {str(exc)[:90]}")
            print("    /auth/:", "; ".join(auth[-3:]))
        contexto.close()
        browser.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
