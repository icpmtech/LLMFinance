"""Confirma que a raiz `/` serve a SPA ao browser e o JSON de estado a clientes.

Erro original: abrir `http://127.0.0.1:8002/` no browser mostrava o JSON
`{"status":"ok","service":"IQ OS API",...}` em vez da aplicação.
"""
import httpx

ACCEPT_BROWSER = "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8"
BASE = "http://127.0.0.1:8002"
falhas = 0


def check(label, ok, detail=""):
    global falhas
    print(("OK   " if ok else "FAIL ") + label + ("" if ok else " :: " + str(detail)))
    if not ok:
        falhas += 1


browser = httpx.get(BASE + "/", headers={"Accept": ACCEPT_BROWSER})
check("raiz (browser) 200", browser.status_code == 200, browser.status_code)
check("raiz (browser) HTML", "text/html" in browser.headers.get("content-type", ""), browser.headers.get("content-type"))
check("raiz (browser) shell da SPA", 'id="root"' in browser.text)
check("raiz (browser) no-store", "no-store" in browser.headers.get("cache-control", ""), browser.headers.get("cache-control"))

cliente = httpx.get(BASE + "/")
check("raiz (cliente) 200", cliente.status_code == 200, cliente.status_code)
check("raiz (cliente) JSON", cliente.headers.get("content-type", "").startswith("application/json"), cliente.headers.get("content-type"))
check("raiz (cliente) status ok", cliente.json().get("status") == "ok", cliente.text)

# Rotas vizinhas não devem ter regredido.
for caminho, espera_html in (("/health", False), ("/loja", True), ("/loja/conta", True), ("/shop/catalogue", False)):
    r = httpx.get(BASE + caminho, headers={"Accept": ACCEPT_BROWSER})
    tipo = r.headers.get("content-type", "")
    if espera_html:
        check(caminho + " serve HTML", r.status_code == 200 and "text/html" in tipo, (r.status_code, tipo))
    else:
        check(caminho + " responde JSON", r.status_code == 200 and "json" in tipo, (r.status_code, tipo))

print()
print("falhas:", falhas)
