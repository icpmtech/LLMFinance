"""Verificação rápida da loja pela API a correr em 127.0.0.1:8002."""
from __future__ import annotations

import json

import httpx

BASE = "http://127.0.0.1:8002"
cliente = httpx.Client(base_url=BASE, timeout=20)

ok = 0


def check(label: str, condition: bool, detail: object = "") -> None:
    global ok
    if condition:
        ok += 1
        print(f"  OK  {label}")
    else:
        print(f" FAIL {label} :: {detail}")
        raise SystemExit(1)


print("== gestão ==")
catalogue = cliente.get("/shop/catalogue")
check("GET /shop/catalogue", catalogue.status_code == 200, catalogue.status_code)
dados = catalogue.json()
check("produtos no índice", len(dados["products_index"]) >= 9, len(dados["products_index"]))
check("definições incluídas", dados["settings"]["store_name"], dados["settings"].get("store_name"))

overview = cliente.get("/shop/overview")
check("GET /shop/overview", overview.status_code == 200, overview.status_code)
check("receita calculada", overview.json()["revenue"]["total"] > 0, overview.json()["revenue"])

tema = cliente.get("/shop/theme")
check("GET /shop/theme", tema.status_code == 200, tema.status_code)
check("tipos de secção no editor", len(tema.json().get("section_types", [])) == 8, tema.json().get("section_types"))
check("tema com secções", len(tema.json()["theme"]["sections"]) >= 1, tema.json()["theme"])
check("URL de pré-visualização", "preview=1" in tema.json()["preview_url"], tema.json()["preview_url"])

for entidade in ("products", "orders", "customers", "coupons", "shipping", "reviews", "categories"):
    resposta = cliente.get(f"/shop/{entidade}", headers={"Accept": "*/*"})
    check(f"GET /shop/{entidade}", resposta.status_code == 200 and "items" in resposta.json(), resposta.status_code)

produto = dados["products_index"][0]
ficha = cliente.get(f"/shop/products/{produto['id']}")
check("GET /shop/products/{id}", ficha.status_code == 200 and ficha.json()["item"]["name"] == produto["name"], ficha.status_code)

print("== vitrine pública ==")
montra = cliente.get("/loja")
check("GET /loja", montra.status_code == 200 and "text/html" in montra.headers["content-type"], montra.status_code)
check("montra com produtos", "data-add-to-cart" in montra.text, "sem botões de compra")
check("montra com carrinho", 'id="loja-dados"' in montra.text)
check("cabeçalho novo (faixa de topo + marca + navegação)",
      'class="topbar"' in montra.text and 'class="brand-mark"' in montra.text and 'class="nav-pills"' in montra.text)
check("rodapé novo (colunas + pagamentos + consulta)",
      'class="footer-grid"' in montra.text and "Pagamentos aceites" in montra.text and 'id="loja-consulta"' in montra.text)
check("carrinho com total no botão", "data-cart-total" in montra.text)
check("montra por secções (hero + vantagens)", 'class="hero' in montra.text and 'class="perk"' in montra.text)

preview = cliente.get("/loja", params={"preview": 1})
check("pré-visualização do editor", preview.status_code == 200 and 'data-preview="1"' in preview.text, preview.status_code)
check("pré-visualização sem cache", "no-store" in preview.headers.get("cache-control", ""), preview.headers.get("cache-control"))

check("newsletter recusa email inválido", cliente.post("/loja/newsletter", json={"email": "invalido"}).status_code == 422)
subscricao = cliente.post("/loja/newsletter", json={"email": "probe.api@exemplo.pt"})
check("newsletter aceita email válido", subscricao.status_code == 200 and subscricao.json()["subscribed"], subscricao.text[:200])

print("== encomendas do comprador ==")
pagina_conta = cliente.get("/loja/conta")
check("GET /loja/conta", pagina_conta.status_code == 200 and "loja-conta" in pagina_conta.text, pagina_conta.status_code)
check("página explica a consulta de convidado", "Consultar uma encomenda" in pagina_conta.text)
sem_sessao = cliente.get("/loja/conta/encomendas")
check("sem sessão não lista encomendas", sem_sessao.status_code == 401, sem_sessao.status_code)
check("com token inválido também não", cliente.get("/loja/conta/encomendas", headers={"Authorization": "Bearer invalido"}).status_code == 401)
check("cabeçalho com ligação às encomendas", 'href="/loja/conta"' in montra.text)

produtos = cliente.get("/loja/produtos", params={"q": "manual"})
check("pesquisa na loja", produtos.status_code == 200 and "Manual impresso" in produtos.text, produtos.status_code)
check("cabeçalho em todas as páginas (produto e carrinho)",
      all('class="topbar"' in cliente.get(url).text for url in ("/loja/produtos", f"/loja/produto/{dados['products_index'][0]['slug']}", "/loja/carrinho")))

slug = next(item["slug"] for item in dados["products_index"] if item["sku"] == "REL-CP-PT")
ficha_html = cliente.get(f"/loja/produto/{slug}")
check("ficha do produto", ficha_html.status_code == 200 and "data-buy-now" in ficha_html.text, ficha_html.status_code)
check("JSON-LD do produto", '"@type": "Product"' in ficha_html.text)

carrinho = cliente.get("/loja/carrinho")
check("página do carrinho", carrinho.status_code == 200 and 'id="loja-form"' in carrinho.text, carrinho.status_code)

check("404 de produto inexistente", cliente.get("/loja/produto/nao-existe").status_code == 404)
check("sitemap", cliente.get("/loja/sitemap.xml").status_code == 200)
check("robots", "Disallow: /shop" in cliente.get("/loja/robots.txt").text)

print("== cupões ==")
cupao = cliente.post("/loja/cupoes/validar", json={"code": "BEMVINDO10", "items": [{"product_id": produto["id"], "quantity": 1}]})
check("POST /loja/cupoes/validar", cupao.status_code == 200, cupao.text[:200])
check("cupão validado", cupao.json()["valid"] is True, cupao.json())

print("== encomenda ==")
envio = dados["shipping_index"][0]
resposta = cliente.post(
    "/loja/encomendas",
    json={
        "items": [{"product_id": produto["id"], "quantity": 1}],
        "customer": {"name": "Teste API", "email": "teste.api@exemplo.pt"},
        "shipping_address": {"line1": "Rua de Teste 1", "postal_code": "1000-100", "city": "Lisboa"},
        "payment_method": "mbway",
        "shipping_method_id": envio["id"],
    },
)
check("POST /loja/encomendas", resposta.status_code == 200, resposta.text[:400])
encomenda = resposta.json()["order"]
check("número atribuído", encomenda["number"].startswith("EN"), encomenda["number"])
check("total calculado", encomenda["totals"]["total"] > 0, encomenda["totals"])
check("valor guardado", encomenda["total"] == encomenda["totals"]["total"], (encomenda["total"], encomenda["totals"]["total"]))
check("recibo público bloqueado sem email", cliente.get(f"/loja/encomenda/{encomenda['number']}").status_code == 404)
recibo = cliente.get(f"/loja/encomenda/{encomenda['number']}", params={"email": "teste.api@exemplo.pt"})
check("recibo com email", recibo.status_code == 200 and encomenda["number"] in recibo.text, recibo.status_code)

print("== compra como convidado (produto digital, sem morada) ==")
digital = next(item for item in dados["products_index"] if item["type"] == "digital")
fisico = next(item for item in dados["products_index"] if item["sku"] == "MAN-ICP")
sem_morada = cliente.post(
    "/loja/encomendas",
    json={"items": [{"product_id": digital["id"], "quantity": 1}], "customer": {"name": "Convidado API", "email": "convidado.api@exemplo.pt"}},
)
check("digital sem morada é aceite", sem_morada.status_code == 200, sem_morada.text[:300])
solta = sem_morada.json()["order"]
check("entrega digital no recibo", "digital" in str(solta["shipping_method"]["name"]).lower(), solta["shipping_method"])
check("sem portes no digital", solta["shipping_total"] == 0, solta["shipping_total"])
check("cliente guardado", cliente.get("/shop/customers", params={"q": "convidado.api"}).json()["total"] == 1)
falta_morada = cliente.post(
    "/loja/encomendas",
    json={"items": [{"product_id": fisico["id"], "quantity": 1}], "customer": {"name": "Convidado API", "email": "convidado.api@exemplo.pt"}},
)
check("físico exige morada", falta_morada.status_code == 422 and "morada" in falta_morada.text.lower(), falta_morada.text[:200])
email_ma = cliente.post("/loja/encomendas", json={"items": [{"product_id": digital["id"], "quantity": 1}], "customer": {"name": "X", "email": "invalido"}})
check("email inválido recusado no checkout", email_ma.status_code == 422, email_ma.text[:200])

print("== limpeza ==")
import subprocess  # noqa: E402

subprocess.run(["python", "-c", "from api import shop_store as s; s.reset_seed(); print('semente reposta')"], cwd=".", check=False)
print(f"\n{ok} verificações passaram.")
