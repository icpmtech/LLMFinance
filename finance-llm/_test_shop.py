"""Teste da loja online em processo: catálogo, cupões, encomendas, stock e vitrine."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from api import shop_render as render  # noqa: E402
from api import shop_routes as routes  # noqa: E402
from api import shop_store as store  # noqa: E402

ok = 0


def check(label: str, condition: bool, detail: object = "") -> None:
    global ok
    if condition:
        ok += 1
        print(f"  OK  {label}")
    else:
        print(f" FAIL {label} :: {detail}")
        raise SystemExit(1)


print("== semente e panorama ==")
reset = store.reset_seed()
check("produtos semeados", reset["products"] == 9, reset)
check("encomendas semeadas", reset["orders"] == 4, reset)
panorama = store.overview()
check("produtos publicados = 8", panorama["products"]["published"] == 8, panorama["products"])
check("produtos em rascunho = 1", panorama["products"]["drafts"] == 1, panorama["products"])
check("clientes semeados", panorama["customers"]["total"] == 3, panorama["customers"])
check("4 encomendas", panorama["orders"]["total"] == 4, panorama["orders"])
check("há receita paga", panorama["revenue"]["total"] > 1000, panorama["revenue"])
check("3 encomendas pagas", panorama["revenue"]["paid_orders"] == 3, panorama["revenue"]["paid_orders"])
check("stock baixo detetado", any(item["sku"] == "MAN-ICP" for item in panorama["products"]["low_stock"]), panorama["products"]["low_stock"])
check("série de 14 dias", len(panorama["series"]) == 14, len(panorama["series"]))
check("5 avaliações", panorama["reviews"]["total"] == 5, panorama["reviews"])
check("1 avaliação pendente", panorama["reviews"]["pending"] == 1, panorama["reviews"])
check("2 cupões", panorama["coupons"]["total"] == 2, panorama["coupons"])

print("== catálogo e produto ==")
catalogue = store.catalogue()
check("índice de produtos", len(catalogue["products_index"]) == 9, len(catalogue["products_index"]))
check("catálogo traz categorias", len(catalogue["categories_index"]) == 4, len(catalogue["categories_index"]))
check("métodos de envio no índice", len(catalogue["shipping_index"]) == 3, catalogue["shipping_index"])
check("URL da vitrine", catalogue["store_url"] == "/loja")

product = store.save_item(
    "products",
    {
        "name": "Curso avançado de licitações",
        "type": "servico",
        "price": 300,
        "compare_at_price": 250,
        "stock": 10,
        "track_stock": True,
        "category_ids": [catalogue["categories_index"][3]["id"]],
        "tags": ["formação", "avançado"],
    },
    author="teste@iqos.pt",
)
check("slug gerado", product["slug"] == "curso-avancado-de-licitacoes", product["slug"])
check("SKU automático", product["sku"].startswith("CURSOAVANC"), product["sku"])
check("preço comparado inválido é limpo", product["compare_at_price"] == 0, product["compare_at_price"])
check("unidade por omissão", product["unit"] == "un")
check("nasce como rascunho", product["status"] == "rascunho")
check("rascunho fora da vitrine", store.product_by_slug(product["slug"]) is None)
check("criação sem revisões", store.revisions_of("products", product["id"]) == [])

published = store.publish_item("products", product["id"], "teste@iqos.pt")
check("publicado", published["status"] == "publicado")
check("publicação gera revisão", len(store.revisions_of("products", product["id"])) == 1, store.revisions_of("products", product["id"]))
check("visível na vitrine", store.product_by_slug(product["slug"]) is not None)
check("disponível", store.is_available(published))
check("etiqueta indexada", any(item["tag"] == "avançado" for item in store.tags_index()["tags"]), store.tags_index()["tags"])

clone = store.duplicate_item("products", product["id"], "teste@iqos.pt")
check("cópia nasce rascunho", clone["status"] == "rascunho", clone["status"])
check("cópia com slug próprio", clone["slug"] != product["slug"], clone["slug"])
check("cópia sem SKU herdado", clone["sku"] != product["sku"], clone["sku"])

try:
    store.save_item("products", {"price": 10})
    raise SystemExit("FAIL devia exigir nome")
except ValueError:
    ok += 1
    print("  OK  produto sem nome é recusado")

print("== categorias e listagens ==")
category = store.save_item("categories", {"name": "Parcerias"}, author="teste@iqos.pt")
check("slug da categoria", category["slug"] == "parcerias", category["slug"])
check("categoria publicada por omissão", category["status"] == "publicado")
filtered = store.list_items("products", category_id=category["id"])
check("filtro por categoria vazio", filtered["total"] == 0, filtered["total"])
out_stock = store.list_items("products", stock="out")
check("filtro sem stock", all(item["stock"] <= 0 for item in out_stock["items"]), out_stock["total"])

print("== cupões ==")
items = [{"product_id": product["id"], "unit_price": 300.0, "quantity": 1, "sku": product["sku"]}]
bemvindo = store.validate_coupon("BEMVINDO10", items, 300.0)
check("cupão de 10% válido", bemvindo["valid"] and bemvindo["discount"] == 30.0, bemvindo)
portes = store.validate_coupon("PORTES2026", items, 300.0)
check("cupão de portes grátis", portes["valid"] and portes["free_shipping"], portes)
check("cupão inexistente", not store.validate_coupon("NAOEXISTE", items, 300.0)["valid"])
check("mínimo do cupão", not store.validate_coupon("PORTES2026", items, 10.0)["valid"])

print("== encomenda na vitrine ==")
physical = next(method for method in store.public_shipping_methods() if not method["digital"])
manual = next(item for item in store.list_items("products", query="Manual impresso")["items"] if item["sku"] == "MAN-ICP")
stock_before = manual["stock"]
usos_antes = next(item for item in store.list_items("coupons")["items"] if item["code"] == "BEMVINDO10")["uses"]
order = store.checkout(
    {
        "items": [{"product_id": manual["id"], "quantity": 2}],
        "customer": {"name": "Rita Nunes", "email": "rita.nunes@exemplo.pt", "phone": "+351 915 000 004"},
        "shipping_address": {"line1": "Rua Nova 3", "postal_code": "4000-100", "city": "Porto"},
        "billing": {"line1": "Rua Nova 3", "postal_code": "4000-100", "city": "Porto"},
        "payment_method": "mbway",
        "shipping_method_id": physical["id"],
        "coupon_code": "BEMVINDO10",
    },
    actor="teste@iqos.pt",
)
check("número da encomenda", order["number"].startswith("EN"), order["number"])
check("estado pendente", order["status"] == "pendente", order["status"])
check("subtotal = 90", order["subtotal"] == 90.0, order["subtotal"])
check("desconto de 9 €", order["discount_total"] == 9.0, order["discount_total"])
check("total = 81", order["total"] == 81.0, order["total"])
check("cliente criado", store.customer_by_email("rita.nunes@exemplo.pt") is not None)
check("stock descontado", store.get_item("products", manual["id"])["stock"] == stock_before - 2, manual["stock"])
check("cupão contabilizado", next(item for item in store.list_items("coupons")["items"] if item["code"] == "BEMVINDO10")["uses"] == usos_antes + 1)
check("cupão guardado na encomenda", (store.get_item("orders", order["id"]).get("coupon") or {}).get("code") == "BEMVINDO10", store.get_item("orders", order["id"]).get("coupon"))
check("sem notas internas no recibo", "internal_notes" not in order, list(order.keys()))
check("email no recibo", order["customer"]["email"] == "rita.nunes@exemplo.pt", order["customer"])

try:
    store.checkout({"items": [{"product_id": manual["id"], "quantity": 99}], "customer": {"email": "x@y.pt"}, "shipping_address": {"line1": "Rua 1"}})
    raise SystemExit("FAIL devia recusar stock insuficiente")
except ValueError as exc:
    ok += 1
    print(f"  OK  stock insuficiente recusado ({exc})")

try:
    store.checkout({"items": [{"product_id": manual["id"], "quantity": 1}], "shipping_address": {"line1": "Rua 1"}})
    raise SystemExit("FAIL devia exigir email")
except ValueError:
    ok += 1
    print("  OK  email obrigatório no checkout")

try:
    store.checkout({"items": [], "customer": {"email": "x@y.pt"}, "shipping_address": {"line1": "Rua 1"}})
    raise SystemExit("FAIL devia recusar carrinho vazio")
except ValueError:
    ok += 1
    print("  OK  carrinho vazio recusado")

print("== pagamento e estado ==")
paid = store.register_payment(order["id"], {"method": "mbway", "amount": 81.0, "reference": "MB-123"}, "teste@iqos.pt")
check("pagamento pago", paid["payment"]["status"] == "pago", paid["payment"])
check("encomenda passa a paga", paid["status"] == "pago", paid["status"])
check("histórico de pagamento", len(paid["payment"]["history"]) == 1, paid["payment"]["history"])
advanced = store.set_order_status(order["id"], "enviado", "teste@iqos.pt", note="Saiu do armazém")
check("estado enviado", advanced["status"] == "enviado", advanced["status"])
check("seguimento com 3 passos", len(advanced["timeline"]) == 3, advanced["timeline"])
noted = store.add_order_note(order["id"], "Cliente pediu fatura com NIF.", "teste@iqos.pt")
check("nota interna registada", "NIF" in noted["internal_notes"], noted["internal_notes"])
cancelled = store.set_order_status(order["id"], "cancelado", "teste@iqos.pt", note="Pedido do cliente")
check("stock reposto", store.get_item("products", manual["id"])["stock"] == stock_before, store.get_item("products", manual["id"])["stock"])
check("pagamento reembolsado", cancelled["payment"]["status"] == "reembolsado", cancelled["payment"]["status"])
try:
    store.set_order_status(order["id"], "inexistente", "teste@iqos.pt")
    raise SystemExit("FAIL devia recusar estado inválido")
except ValueError:
    ok += 1
    print("  OK  estado inválido recusado")

print("== avaliações ==")
review = store.create_review({"product_slug": product["slug"], "customer_name": "Pedro Sá", "rating": 4, "title": "Bom", "body": "Útil."})
check("avaliação pendente", review["status"] == "pendente", review["status"])
check("produto preenchido pela slug", review["product_id"] == product["id"], review["product_id"])
check("vista pública vazia", store.approved_reviews(product["id"]) == [])
store.save_item("reviews", {"id": review["id"], "status": "aprovada"}, "teste@iqos.pt")
check("aprovada aparece", len(store.approved_reviews(product["id"])) == 1)
check("nota média atualizada", store.get_item("products", product["id"])["rating_avg"] == 4.0, store.get_item("products", product["id"])["rating_avg"])
check("campo privado escondido", "email" not in routes.loja_review({"product_slug": product["slug"], "customer_name": "X", "rating": 5})["review"])

print("== pesquisa e atividade ==")
hits = store.search("mbway")
check("pesquisa encontra", hits["total"] >= 1, hits["total"])
check("pesquisa sem termo", store.search("")["total"] == 0)
check("atividade registada", len(store.activity(5)) == 5, store.activity(5))

print("== vitrine (HTML) ==")
settings = store.get_settings()
catalogue_html = render.render_catalogue(store.public_products(limit=50), settings=settings)
check("nome da loja no HTML", settings["store_name"] in catalogue_html)
check("botão de carrinho", "data-add-to-cart" in catalogue_html)
check("dados do carrinho embutidos", 'id="loja-dados"' in catalogue_html)
check("preço formatado", "€" in catalogue_html and "249,00" in catalogue_html, "preço em falta")

product_html = render.render_product(store.product_by_slug(product["slug"]), settings=settings)
check("ficha com JSON-LD", '"@type": "Product"' in product_html, "JSON-LD em falta")
check("ficha com comprar", "data-buy-now" in product_html)
check("ficha com avaliações", "Avaliações de clientes" in product_html)
check("ficha com formulário de avaliação", 'id="loja-avaliacao"' in product_html)

cart_html = render.render_cart(settings=settings)
check("carrinho com formulário", 'id="loja-form"' in cart_html)
check("carrinho com pagamentos", "MB Way" in cart_html and "Transferência bancária" in cart_html)
check("carrinho com envios", "Correio registado" in cart_html)
check("carrinho noindex", "noindex" in cart_html)

order_html = render.render_order(store.get_item("orders", order["id"]), settings=settings)
check("recibo com número", cancelled["number"] in order_html)
check("recibo com seguimento", "Seguimento" in order_html)
check("sitemap com produtos", "/loja/produto/" in render.render_sitemap(settings=settings))
check("robots bloqueia gestão", "Disallow: /shop" in render.render_robots(settings=settings))
check("404 amigável", "Não encontrámos" in render.render_not_found(settings=settings))

print("== rotas ==")
paths = [getattr(route, "path", "") for route in routes.router.routes]
check("catálogo antes do CRUD genérico", paths.index("/shop/catalogue") < paths.index("/shop/{entity}"), paths[:6])
check("media antes do CRUD genérico", paths.index("/shop/media") < paths.index("/shop/{entity}"))
check("ação de encomenda antes do CRUD", paths.index("/shop/orders/{item_id}/status") < paths.index("/shop/{entity}/{item_id}"))
for path in ("/loja", "/loja/produtos", "/loja/produto/{slug}", "/loja/carrinho", "/loja/encomendas", "/loja/cupoes/validar", "/loja/avaliacoes"):
    check(f"rota {path} registada", path in paths)
check("guardas da SPA", "encomendas" in routes.UI_SECTION_SLUGS and "catalogue" not in routes.UI_SECTION_SLUGS)

print("== definições ==")
saved = store.save_settings({"store_name": "Loja IQ OS", "low_stock_threshold": 7, "payments": {"numerario": True}}, "teste@iqos.pt")
check("definições guardadas", saved["low_stock_threshold"] == 7, saved["low_stock_threshold"])
check("pagamentos preservados", saved["payments"]["mbway"] is True and saved["payments"]["numerario"] is True, saved["payments"])
check("campo desconhecido ignorado", store.save_settings({"inventado": 1}, "teste@iqos.pt").get("inventado") is None)

print("== limpeza ==")
store.reset_seed()
check("semente reposta", store.overview()["products"]["total"] == 9, store.overview()["products"]["total"])

print(f"\n{ok} verificações passaram.")
