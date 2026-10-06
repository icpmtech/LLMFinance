"""Confirma que o Vite compila os modulos alterados (nao substitui o browser).

Pede cada modulo ao *dev server* e procura sinais de erro de transformacao. Um
`grep` amplo por "error" da falsos positivos (as props `error` do componente,
por exemplo), por isso os padroes sao especificos.
"""

import httpx

BASE = "http://127.0.0.1:8893"
TARGETS = {
    "/src/views/Home.vue": ["useIqosTheme", "theme-toggle"],
    "/src/components/IqosHistory.vue": ["iqos-auto-refresh", "deleteTarget", "A atualizar"],
    "/src/components/IqosCharts.vue": ["slice-running", "bar-fill"],
    "/src/composables/useIqosTheme.js": ["data-iqos-theme", "iqos-theme"],
}
FALHAS = ("SyntaxError", "Transform failed", "[plugin:vite", "Internal server error")

with httpx.Client(timeout=60) as client:
    for path, markers in TARGETS.items():
        response = client.get(f"{BASE}{path}", params={"t": "check"})
        body = response.text
        erro = next((sinal for sinal in FALHAS if sinal in body), None)
        faltam = [m for m in markers if m not in body]
        estado = "OK" if response.status_code == 200 and not erro and not faltam else "FALHA"
        print(f"{estado:<6} {path:<38} {response.status_code} {len(body)}B", end="")
        if erro:
            print(f"  erro={erro}")
        elif faltam:
            print(f"  sem marcadores: {faltam}")
        else:
            print()
