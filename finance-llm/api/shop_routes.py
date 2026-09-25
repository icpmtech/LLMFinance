"""Rotas da loja online (`/shop/*`) e da vitrine pública (`/loja/*`).

**Gestão** (requer sessão para escrever):

- `GET  /shop/catalogue` — tudo o que o gestor precisa (tipos, estados, índices)
- `GET  /shop/overview` — vendas, encomendas por estado, stock e atividade
- `GET  /shop/search?q=` — pesquisa global na loja
- `GET|PUT /shop/settings` — definições da loja (pagamentos, contactos, tema)
- `GET|POST /shop/{entidade}` e `GET|PATCH|DELETE /shop/{entidade}/{id}`
  (`products`, `categories`, `customers`, `orders`, `coupons`, `shipping`, `reviews`)
- `POST /shop/{entidade}/{id}/duplicate`
- `POST /shop/{entidade}/{id}/publish|unpublish|status`
- `GET  /shop/{entidade}/{id}/revisions` e `POST /shop/revisions/{id}/restore`
- `POST /shop/orders/{id}/status` — muda o estado e repõe stock se for anulada
- `POST /shop/orders/{id}/payment` — regista um pagamento manual
- `POST /shop/orders/{id}/note` — nota interna
- `GET  /shop/orders/{id}/print` — encomenda em HTML, pronta a imprimir
- `POST /shop/media` — carrega um ficheiro para a biblioteca do CMS
- `POST /shop/customers/{id}/crm` — liga o cliente a uma conta do CRM

**Vitrine pública** (sem sessão):

- `GET  /loja` — montra (destaques)
- `GET  /loja/produtos` — catálogo com pesquisa, ordenação e paginação
- `GET  /loja/categoria/{slug}` — catálogo de uma categoria
- `GET  /loja/produto/{slug}` — ficha do produto, com avaliações
- `GET  /loja/carrinho` — carrinho e finalização de compra
- `GET  /loja/encomenda/{numero}` — recibo (exige o email do comprador)
- `POST /loja/encomendas` — cria a encomenda a partir do carrinho
- `POST /loja/cupoes/validar` — valida um cupão
- `POST /loja/avaliacoes` — envia uma avaliação (fica pendente de moderação)
- `GET  /loja/sitemap.xml`, `/loja/robots.txt`
"""
from __future__ import annotations

import logging
from typing import Annotated, Any, Dict, Optional

from fastapi import APIRouter, Body, Depends, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, PlainTextResponse, Response

from api import shop_render as render
from api import shop_store as store
from api.auth_routes import CurrentSession, optional_session

logger = logging.getLogger(__name__)

router = APIRouter(tags=["loja"])

Session = Annotated[Optional[CurrentSession], Depends(optional_session)]

PER_PAGE = store.PER_PAGE


def _writer(session: Optional[CurrentSession]) -> str:
    """Quem escreve (para revisões e auditoria)."""
    if not session:
        raise HTTPException(status_code=401, detail="Entrar na plataforma para gerir a loja.")
    return session.user.email


def _entity(entity: str) -> str:
    if entity not in store.ENTITIES:
        raise HTTPException(
            status_code=404,
            detail=f"Entidade «{entity}» não existe na loja. Válidas: {', '.join(store.ENTITIES)}.",
        )
    return entity


# Secções da interface da loja: `/shop/produtos`, `/shop/encomendas`… Estas rotas
# colidem com `GET /shop/{entidade}`, pelo que uma **navegação do browser** (que
# pede HTML) tem de devolver a SPA construída — senão recarregar dava JSON.
UI_SECTION_SLUGS = frozenset({"produtos", "vitrine", "categorias", "encomendas", "clientes", "promocoes", "envios", "avaliacoes", "definicoes"})


def _is_browser_navigation(request: Request) -> bool:
    return "text/html" in request.headers.get("accept", "")


def _spa_response() -> Response:
    """A SPA construída (import tardio: `api.main` importa este módulo)."""
    from api.main import spa_index_response

    return spa_index_response()


# ==========================================================================
# Catálogo, panorama e pesquisa
# ==========================================================================
@router.get("/shop/catalogue")
def shop_catalogue() -> Dict[str, Any]:
    """Tipos, estados, índices de produtos/categorias/clientes e definições."""
    return store.catalogue()


@router.get("/shop/overview")
def shop_overview() -> Dict[str, Any]:
    """Panorama da loja: vendas, encomendas, stock baixo, avaliações e atividade."""
    return store.overview()


@router.get("/shop/activity")
def shop_activity(limit: int = Query(40, ge=1, le=400)) -> Dict[str, Any]:
    """Registo de atividade da loja (mais recente primeiro)."""
    items = store.activity(limit)
    return {"total": len(items), "items": items}


@router.get("/shop/search")
def shop_search(q: str = Query("", description="Texto a procurar."), limit: int = Query(30, ge=1, le=100)) -> Dict[str, Any]:
    """Pesquisa global na loja (produtos, encomendas, clientes, cupões e avaliações)."""
    return store.search(q, limit=limit)


@router.get("/shop/taxonomy")
def shop_taxonomy() -> Dict[str, Any]:
    """Categorias e etiquetas, com contagem de produtos publicados."""
    return {"categories": store.public_categories(), **store.tags_index()}


# ==========================================================================
# Definições
# ==========================================================================
@router.get("/shop/settings")
def shop_get_settings() -> Dict[str, Any]:
    """Definições da loja (nome, contactos, pagamentos, tema e SEO)."""
    return {"settings": store.get_settings(), "payment_methods": store.PAYMENT_METHODS}


@router.put("/shop/settings")
def shop_put_settings(payload: Dict[str, Any] = Body(...), session: Session = None) -> Dict[str, Any]:
    """Guarda as definições (só os campos enviados são alterados)."""
    author = _writer(session)
    return {"saved": True, "settings": store.save_settings(payload, author)}


# ==========================================================================
# Vitrine (tema) — o editor do backoffice lê e grava isto
# ==========================================================================
@router.get("/shop/theme")
def shop_get_theme() -> Dict[str, Any]:
    """Tema da vitrine: secções, aviso e tipos de secção disponíveis."""
    return store.theme_catalogue()


@router.put("/shop/theme")
def shop_put_theme(payload: Dict[str, Any] = Body(...), session: Session = None) -> Dict[str, Any]:
    """Grava o tema da vitrine (o editor grava sozinho, a cada alteração)."""
    author = _writer(session)
    return {"saved": True, "theme": store.save_theme(payload, author), "preview_url": "/loja?preview=1"}


@router.post("/shop/theme/reset")
def shop_reset_theme(session: Session = None) -> Dict[str, Any]:
    """Repõe a vitrine predefinida."""
    author = _writer(session)
    return {"saved": True, "theme": store.reset_theme(author)}


# ==========================================================================
# Media (biblioteca do CMS)
# ==========================================================================
@router.post("/shop/media")
def shop_upload_media(payload: Dict[str, Any] = Body(...), session: Session = None) -> Dict[str, Any]:
    """Carrega um ficheiro (base64) ou registra um URL na biblioteca do CMS."""
    author = _writer(session)
    try:
        from api import cms_store

        item = cms_store.save_media(payload, author)
    except ImportError as exc:  # pragma: no cover - o CMS faz parte da plataforma
        raise HTTPException(status_code=503, detail=f"Biblioteca de media indisponível ({exc}).")
    except (ValueError, KeyError) as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    return {"saved": True, "item": item, "url": item.get("url")}


# ==========================================================================
# Encomendas: ações próprias (declaradas antes do CRUD genérico)
# ==========================================================================
@router.post("/shop/orders/{item_id}/status")
def shop_order_status(item_id: str, payload: Dict[str, Any] = Body(...), session: Session = None) -> Dict[str, Any]:
    """Muda o estado de uma encomenda (e repõe o stock se for anulada)."""
    author = _writer(session)
    try:
        return {"saved": True, "item": store.set_order_status(item_id, str(payload.get("status") or ""), author, str(payload.get("note") or ""))}
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))


@router.post("/shop/orders/{item_id}/payment")
def shop_order_payment(item_id: str, payload: Dict[str, Any] = Body(...), session: Session = None) -> Dict[str, Any]:
    """Regista um pagamento manual (MB Way, transferência, numerário…)."""
    author = _writer(session)
    try:
        return {"saved": True, "item": store.register_payment(item_id, payload, author)}
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))


@router.post("/shop/orders/{item_id}/note")
def shop_order_note(item_id: str, payload: Dict[str, Any] = Body(...), session: Session = None) -> Dict[str, Any]:
    """Acrescenta uma nota à encomenda (interna por omissão)."""
    author = _writer(session)
    try:
        item = store.add_order_note(item_id, str(payload.get("note") or ""), author, internal=bool(payload.get("internal", True)))
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    return {"saved": True, "item": item}


@router.get("/shop/orders/{item_id}/print", response_class=HTMLResponse)
def shop_order_print(item_id: str, session: Session = None) -> HTMLResponse:
    """Encomenda em HTML, pronta a imprimir ou guardar em PDF."""
    _writer(session)
    try:
        order = store.get_item("orders", item_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    order["totals"] = store.order_totals(order)
    return HTMLResponse(render.render_order(order), headers={"Cache-Control": "no-store, must-revalidate"})


# ==========================================================================
# Clientes: ligação ao CRM
# ==========================================================================
@router.post("/shop/customers/{item_id}/crm")
def shop_customer_crm(item_id: str, payload: Optional[Dict[str, Any]] = Body(None), session: Session = None) -> Dict[str, Any]:
    """Liga o cliente a uma conta do CRM (cria a conta se não for indicada)."""
    author = _writer(session)
    account = str((payload or {}).get("account_id") or "")
    try:
        return {"saved": True, "item": store.link_customer_to_crm(item_id, account, author)}
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))


# ==========================================================================
# CRUD genérico por entidade
# ==========================================================================
@router.get("/shop/{entity}")
def shop_list(
    entity: str,
    request: Request,
    status: Optional[str] = Query(None, description="`all` ou lista separada por vírgulas."),
    payment_status: Optional[str] = Query(None),
    q: Optional[str] = Query(None),
    category_id: Optional[str] = Query(None),
    tag: Optional[str] = Query(None),
    product_id: Optional[str] = Query(None),
    customer_id: Optional[str] = Query(None),
    stock: Optional[str] = Query(None, description="`low` ou `out`."),
    limit: int = Query(300, ge=1, le=500),
    light: bool = Query(False, description="Resumo leve, sem corpo nem linhas."),
) -> Any:
    """Lista uma entidade da loja, com filtros por estado, texto, categoria e stock."""
    if entity in UI_SECTION_SLUGS and _is_browser_navigation(request):
        return _spa_response()
    _entity(entity)
    return store.list_items(
        entity,
        status=status,
        query=q,
        category_id=category_id,
        tag=tag,
        product_id=product_id,
        customer_id=customer_id,
        payment_status=payment_status,
        stock=stock,
        limit=limit,
        light=light,
    )


@router.post("/shop/{entity}")
def shop_create(entity: str, payload: Dict[str, Any] = Body(...), session: Session = None) -> Dict[str, Any]:
    """Cria um documento da loja (produto, categoria, cliente, encomenda, cupão…)."""
    _entity(entity)
    author = _writer(session)
    try:
        doc = store.save_item(entity, payload, author)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    return {"saved": True, "item": doc}


@router.get("/shop/{entity}/{item_id}")
def shop_get(entity: str, item_id: str) -> Dict[str, Any]:
    """Documento completo da loja."""
    _entity(entity)
    try:
        return {"item": store.get_item(entity, item_id)}
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


@router.patch("/shop/{entity}/{item_id}")
def shop_patch(entity: str, item_id: str, payload: Dict[str, Any] = Body(...), session: Session = None) -> Dict[str, Any]:
    """Alteração parcial de um documento da loja."""
    _entity(entity)
    author = _writer(session)
    try:
        doc = store.save_item(entity, {**payload, "id": item_id}, author)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    return {"saved": True, "item": doc}


@router.delete("/shop/{entity}/{item_id}")
def shop_delete(entity: str, item_id: str, session: Session = None) -> Dict[str, Any]:
    """Apaga um documento da loja."""
    _entity(entity)
    author = _writer(session)
    try:
        return store.delete_item(entity, item_id, author)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


@router.post("/shop/{entity}/{item_id}/duplicate")
def shop_duplicate(entity: str, item_id: str, session: Session = None) -> Dict[str, Any]:
    """Duplica um documento (a cópia nasce como rascunho, quando aplicável)."""
    _entity(entity)
    author = _writer(session)
    try:
        return {"saved": True, "item": store.duplicate_item(entity, item_id, author)}
    except (KeyError, ValueError) as exc:
        raise HTTPException(status_code=422 if isinstance(exc, ValueError) else 404, detail=str(exc))


# ==========================================================================
# Publicação e revisões
# ==========================================================================
@router.post("/shop/{entity}/{item_id}/publish")
def shop_publish(entity: str, item_id: str, payload: Optional[Dict[str, Any]] = Body(None), session: Session = None) -> Dict[str, Any]:
    """Publica agora ou agenda (`{"at": "2026-10-01T09:00"}`)."""
    _entity(entity)
    author = _writer(session)
    body = payload or {}
    try:
        doc = store.publish_item(entity, item_id, author, at=body.get("at") or body.get("scheduled_at"))
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    return {"saved": True, "item": doc}


@router.post("/shop/{entity}/{item_id}/unpublish")
def shop_unpublish(entity: str, item_id: str, session: Session = None) -> Dict[str, Any]:
    """Devolve o documento a rascunho (sai imediatamente da vitrine)."""
    _entity(entity)
    author = _writer(session)
    try:
        return {"saved": True, "item": store.unpublish_item(entity, item_id, author)}
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))


@router.post("/shop/{entity}/{item_id}/status")
def shop_status(entity: str, item_id: str, payload: Dict[str, Any] = Body(...), session: Session = None) -> Dict[str, Any]:
    """Muda o estado de publicação (`rascunho`, `agendado`, `publicado`, `arquivado`)."""
    _entity(entity)
    author = _writer(session)
    target = str(payload.get("status") or "")
    if target not in store.PRODUCT_STATUSES:
        raise HTTPException(status_code=422, detail=f"Estado inválido «{target}». Válidos: {', '.join(store.PRODUCT_STATUSES)}.")
    try:
        return {"saved": True, "item": store.set_status(entity, item_id, target, author)}
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))


@router.get("/shop/{entity}/{item_id}/revisions")
def shop_revisions(entity: str, item_id: str, limit: int = Query(20, ge=1, le=100)) -> Dict[str, Any]:
    """Histórico de revisões de um documento."""
    _entity(entity)
    items = store.revisions_of(entity, item_id, limit=limit)
    return {"total": len(items), "items": items}


@router.post("/shop/revisions/{revision_id}/restore")
def shop_restore(revision_id: str, session: Session = None) -> Dict[str, Any]:
    """Restaura um documento a partir de uma revisão."""
    author = _writer(session)
    try:
        return {"saved": True, "item": store.restore_revision(revision_id, author)}
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


# ==========================================================================
# Vitrine pública
# ==========================================================================
_PUBLIC_HEADERS = {"Cache-Control": "public, max-age=15, must-revalidate"}


def _catalogue_page(
    *,
    category: Optional[Dict[str, Any]] = None,
    query: str = "",
    tag: str = "",
    page: int = 1,
    sort: str = "destaque",
    title: str = "Produtos",
    description: str = "",
    featured_only: bool = False,
    current_path: str = "",
) -> HTMLResponse:
    settings = store.get_settings()
    catalogue = store.public_products(
        category_id=(category or {}).get("id"),
        query=query,
        tag=tag,
        sort=sort,
        featured_only=featured_only,
        limit=500,
    )
    pages = max(1, (len(catalogue) + PER_PAGE - 1) // PER_PAGE)
    current = min(max(1, page), pages)
    window = catalogue[(current - 1) * PER_PAGE : current * PER_PAGE]
    body = render.render_catalogue(
        window,
        settings=settings,
        categories=store.public_categories(),
        current_category=category,
        query=query,
        tag=tag,
        page=current,
        pages=pages,
        sort=sort,
        title=title or str(settings.get("store_name") or "Loja"),
        description=description or str(settings.get("description") or ""),
        all_products=catalogue,
        current_path=current_path,
    )
    return HTMLResponse(body, headers=_PUBLIC_HEADERS)


@router.get("/loja", response_class=HTMLResponse)
def loja_home(
    page: int = Query(1, ge=1),
    ordenar: str = Query("destaque"),
    q: str = Query(""),
    categoria: str = Query(""),
    preview: int = Query(0, description="1 = pré-visualização do editor de vitrine (sem cache)."),
) -> HTMLResponse:
    """Montra pública: as secções configuradas no editor de vitrine."""
    settings = store.get_settings()
    if preview:
        html = render.render_home(settings=settings, theme=store.get_theme(), preview=True)
        return HTMLResponse(html, headers={"Cache-Control": "no-store, must-revalidate"})
    # Com filtros (pesquisa, categoria, página, ordenação) mostra-se o catálogo clássico.
    if q or categoria or page > 1 or ordenar != "destaque":
        category = store.category_by_slug(categoria) if categoria else None
        if category is not None and category.get("status") != "publicado":
            category = None
        return _catalogue_page(
            category=category,
            query=q,
            page=page,
            sort=ordenar,
            title=str(settings.get("store_name") or "Loja"),
            description=str(settings.get("description") or ""),
            current_path="/loja",
        )
    return HTMLResponse(render.render_home(settings=settings), headers=_PUBLIC_HEADERS)


@router.get("/loja/produtos", response_class=HTMLResponse)
def loja_products(
    page: int = Query(1, ge=1),
    ordenar: str = Query("destaque"),
    q: str = Query(""),
    etiqueta: str = Query(""),
    categoria: str = Query(""),
) -> HTMLResponse:
    """Catálogo completo, com pesquisa, ordenação e paginação."""
    category = store.category_by_slug(categoria) if categoria else None
    if category is not None and category.get("status") != "publicado":
        category = None
    return _catalogue_page(category=category, query=q, tag=etiqueta, page=page, sort=ordenar, title="Todos os produtos", current_path="/loja/produtos")


@router.get("/loja/categoria/{slug}", response_class=HTMLResponse)
def loja_category(slug: str, page: int = Query(1, ge=1), ordenar: str = Query("destaque"), q: str = Query("")) -> HTMLResponse:
    """Produtos de uma categoria."""
    settings = store.get_settings()
    category = store.category_by_slug(slug)
    if not category or category.get("status") != "publicado":
        return HTMLResponse(render.render_not_found(settings=settings, message="Esta categoria já não existe."), status_code=404, headers=_PUBLIC_HEADERS)
    return _catalogue_page(
        category=category,
        query=q,
        page=page,
        sort=ordenar,
        title=str(category.get("name") or "Categoria"),
        description=str(category.get("description") or ""),
        current_path=f'/loja/categoria/{category.get("slug")}',
    )


@router.get("/loja/produto/{slug}", response_class=HTMLResponse)
def loja_product(slug: str) -> HTMLResponse:
    """Ficha de um produto publicado, com avaliações e sugestões."""
    settings = store.get_settings()
    product = store.product_by_slug(slug, published_only=True)
    if not product:
        return HTMLResponse(render.render_not_found(settings=settings, message="Este produto já não está à venda."), status_code=404, headers=_PUBLIC_HEADERS)
    return HTMLResponse(render.render_product(product, settings=settings), headers=_PUBLIC_HEADERS)


@router.get("/loja/carrinho", response_class=HTMLResponse)
def loja_cart() -> HTMLResponse:
    """Carrinho e finalização de compra (a página é desenhada pelo browser)."""
    settings = store.get_settings()
    return HTMLResponse(render.render_cart(settings=settings), headers={"Cache-Control": "no-store, must-revalidate"})


@router.get("/loja/conta", response_class=HTMLResponse)
def loja_account() -> HTMLResponse:
    """As minhas encomendas: lista com sessão IQ OS ou consulta de convidado."""
    settings = store.get_settings()
    return HTMLResponse(render.render_account(settings=settings), headers={"Cache-Control": "no-store, must-revalidate"})


@router.get("/loja/conta/encomendas")
def loja_account_orders(session: Session = None, limit: int = Query(50, ge=1, le=200)) -> Dict[str, Any]:
    """Encomendas do utilizador autenticado (a vitrine envia o token da plataforma)."""
    if session is None:
        raise HTTPException(status_code=401, detail="Entre na plataforma IQ OS para ver todas as suas encomendas.")
    orders = store.orders_for_email(session.user.email, limit=limit)
    return {
        "email": session.user.email,
        "name": getattr(session.user, "name", "") or "",
        "total": len(orders),
        "orders": orders,
    }


@router.get("/loja/encomenda/{number}", response_class=HTMLResponse)
def loja_order(number: str, email: str = Query("")) -> HTMLResponse:
    """Recibo de uma encomenda (é preciso indicar o email do comprador)."""
    settings = store.get_settings()
    order = store.find_order_by_number(number)
    wanted = str(email or "").strip().lower()
    buyer = str((order or {}).get("customer", {}).get("email") or "").strip().lower()
    if not order or not wanted or wanted != buyer:
        return HTMLResponse(
            render.render_not_found(settings=settings, message="Confirme o número da encomenda e o email usado na compra."),
            status_code=404,
            headers={"Cache-Control": "no-store, must-revalidate"},
        )
    return HTMLResponse(render.render_order(order, settings=settings), headers={"Cache-Control": "no-store, must-revalidate"})


@router.post("/loja/encomendas")
def loja_checkout(payload: Dict[str, Any] = Body(...)) -> Dict[str, Any]:
    """Cria a encomenda a partir do carrinho (preços e stock validados pelo servidor)."""
    try:
        order = store.checkout(payload, actor="loja")
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    logger.info("Encomenda %s criada na loja (%s)", order.get("number"), order.get("total"))
    return {"saved": True, "order": order, "store_url": "/loja/produtos", "receipt_url": f'/loja/encomenda/{order.get("number")}?email={order.get("customer", {}).get("email", "")}'}


@router.post("/loja/cupoes/validar")
def loja_validate_coupon(payload: Dict[str, Any] = Body(...)) -> Dict[str, Any]:
    """Valida um cupão para o carrinho atual (sem o consumir)."""
    items = payload.get("items") if isinstance(payload.get("items"), list) else []
    lines: Dict[str, Dict[str, Any]] = {}
    for raw in items:
        if not isinstance(raw, dict):
            continue
        product = None
        reference = str(raw.get("product_id") or raw.get("id") or raw.get("slug") or "")
        try:
            product = store.get_item("products", reference)
        except KeyError:
            product = store.product_by_slug(reference, published_only=False)
        if product is None:
            continue
        lines[str(product.get("id"))] = {
            "product_id": product.get("id"),
            "unit_price": store.money(product.get("price")),
            "quantity": max(1, store._int(raw.get("quantity"), 1, minimum=1)),
        }
    return store.validate_coupon(str(payload.get("code") or ""), list(lines.values()))


@router.post("/loja/avaliacoes")
def loja_review(payload: Dict[str, Any] = Body(...)) -> Dict[str, Any]:
    """Envia uma avaliação de produto (entra pendente de moderação)."""
    try:
        review = store.create_review(payload)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    return {"saved": True, "review": {key: value for key, value in review.items() if key != "email"}}


@router.post("/loja/newsletter")
def loja_newsletter(payload: Dict[str, Any] = Body(...)) -> Dict[str, Any]:
    """Email deixado na vitrine: fica como cliente com autorização de marketing."""
    try:
        return store.newsletter_signup(payload)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))


@router.get("/loja/sitemap.xml")
def loja_sitemap() -> Response:
    """Sitemap XML do catálogo publicado."""
    return Response(render.render_sitemap(), media_type="application/xml; charset=utf-8", headers=_PUBLIC_HEADERS)


@router.get("/loja/robots.txt", response_class=PlainTextResponse)
def loja_robots() -> PlainTextResponse:
    """`robots.txt` da loja (bloqueia a gestão, o carrinho e os recibos)."""
    return PlainTextResponse(render.render_robots(), headers=_PUBLIC_HEADERS)
