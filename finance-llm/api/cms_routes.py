"""Rotas do CMS (`/cms/*`) e do site público (`/site/*`).

**Gestão** (requer sessão para escrever):

- `GET  /cms/catalogue` — tudo o que o editor precisa (blocos, estados, listas)
- `GET  /cms/overview` — panorama, agendamentos e atividade
- `GET  /cms/search?q=` — pesquisa global no CMS
- `GET|PUT /cms/settings` — aparência e ligações do site
- `GET|POST|PATCH|DELETE /cms/menus…`
- `GET|POST /cms/{entidade}` e `GET|PATCH|DELETE /cms/{entidade}/{id}`
  (`pages`, `posts`, `contents`, `media`, `categories`, `templates`, `menus`)
- `POST /cms/{entidade}/{id}/duplicate`
- `POST /cms/{entidade}/{id}/publish|unpublish|status` — publicar, despublicar,
  agendar (`{"at": "…"}`) ou mudar o estado
- `GET  /cms/{entidade}/{id}/revisions` e `POST /cms/revisions/{id}/restore`
- `POST /cms/media` — carregar ficheiro (base64) ou registar URL externo
- `GET  /cms/media/{id}/raw` — servir o binário
- `GET  /cms/preview/{entidade}/{id}` — pré-visualização HTML do rascunho

**Site público** (sem sessão):

- `GET /site` — página inicial
- `GET /site/blog`, `/site/blog/{slug}`, `/site/categoria/{slug}`, `/site/etiqueta/{tag}`
- `GET /site/rss.xml`, `/site/sitemap.xml`, `/site/robots.txt`
- `GET /site/{caminho}` — qualquer página publicada
"""
from __future__ import annotations

import logging
from typing import Annotated, Any, Dict, Optional

from fastapi import APIRouter, Body, Depends, HTTPException, Query, Request
from fastapi.responses import FileResponse, HTMLResponse, PlainTextResponse, RedirectResponse, Response

from api import cms_render as render
from api import cms_store as store
from api.auth_routes import CurrentSession, optional_session

logger = logging.getLogger(__name__)

router = APIRouter(tags=["cms"])

Session = Annotated[Optional[CurrentSession], Depends(optional_session)]

# Os pedidos de escrita identificam quem escreveu (revisões e auditoria).
def _writer(session: Optional[CurrentSession]) -> str:
    if not session:
        raise HTTPException(status_code=401, detail="Entrar na plataforma para escrever no CMS.")
    return session.user.email


def _author(session: Optional[CurrentSession]) -> str:
    return session.user.email if session else ""


def _entity(entity: str) -> str:
    if entity not in store.ENTITIES:
        raise HTTPException(
            status_code=404,
            detail=f"Entidade «{entity}» não existe no CMS. Válidas: {', '.join(store.ENTITIES)}.",
        )
    return entity


# Secções da interface do CMS: `/cms/paginas`, `/cms/media`, `/cms/blog`… Estas
# rotas colidem com `GET /cms/{entidade}` (e `/cms/media` com a listagem dos
# media), pelo que uma **navegação do browser** (que pede HTML) tem de devolver a
# SPA construída — senão recarregar a página dava JSON em vez da aplicação.
UI_SECTION_SLUGS = frozenset({"paginas", "conteudos", "blog", "media", "taxonomia", "modelos", "aparencia"})


def _is_browser_navigation(request: Request) -> bool:
    return "text/html" in request.headers.get("accept", "")


def _spa_response() -> Response:
    """A SPA construída (import tardio: `api.main` importa este módulo)."""
    from api.main import spa_index_response

    return spa_index_response()


# ==========================================================================
# Catálogo, panorama e pesquisa
# ==========================================================================
@router.get("/cms/catalogue")
def cms_catalogue() -> Dict[str, Any]:
    """Tipos de bloco, estados, listas de páginas/categorias/media e URLs do site."""
    return store.catalogue()


@router.get("/cms/overview")
def cms_overview() -> Dict[str, Any]:
    """Panorama do CMS: contagens, agendamentos, alterações recentes e atividade."""
    return store.overview()


@router.get("/cms/taxonomy")
def cms_taxonomy() -> Dict[str, Any]:
    """Categorias e etiquetas do blog, com contagem de artigos publicados."""
    return store.taxonomy()


@router.get("/cms/tree")
def cms_tree(published: bool = Query(False, description="Só páginas publicadas.")) -> Dict[str, Any]:
    """Árvore de páginas (ascendentes → descendentes)."""
    return {"items": store.page_tree(published_only=published)}


@router.get("/cms/activity")
def cms_activity(limit: int = Query(40, ge=1, le=400)) -> Dict[str, Any]:
    """Registo de atividade do CMS (mais recente primeiro)."""
    items = store.activity(limit)
    return {"total": len(items), "items": items}


@router.get("/cms/search")
def cms_search(q: str = Query("", description="Texto a procurar (título, slug, corpo, etiquetas)."), limit: int = Query(30, ge=1, le=100)) -> Dict[str, Any]:
    """Pesquisa global no CMS."""
    return store.search(q, limit=limit)


# ==========================================================================
# Definições do site
# ==========================================================================
@router.get("/cms/settings")
def cms_get_settings() -> Dict[str, Any]:
    """Definições do site: nome, descrição, aparência, SEO e ligações."""
    return {"settings": store.get_settings(), "menus": [_menu_summary(menu) for menu in store.list_menus()]}


@router.put("/cms/settings")
def cms_put_settings(payload: Dict[str, Any] = Body(...), session: Session = None) -> Dict[str, Any]:
    """Guarda as definições do site (só os campos enviados são alterados)."""
    author = _writer(session)
    return {"saved": True, "settings": store.save_settings(payload, author)}


# ==========================================================================
# Menus
# ==========================================================================
def _menu_summary(menu: Dict[str, Any]) -> Dict[str, Any]:
    return {key: value for key, value in menu.items() if key != "items"} | {"items": len(menu.get("items") or [])}


@router.get("/cms/menus")
def cms_list_menus() -> Dict[str, Any]:
    """Menus do site (cabeçalho e rodapé) e o resultado já resolvido."""
    menus = store.list_menus()
    return {
        "total": len(menus),
        "items": menus,
        "resolved": {
            location["id"]: store.menu_for(location["id"])
            for location in store.MENU_LOCATIONS
        },
        "locations": store.MENU_LOCATIONS,
    }


@router.post("/cms/menus")
def cms_create_menu(payload: Dict[str, Any] = Body(...), session: Session = None) -> Dict[str, Any]:
    """Cria um menu."""
    author = _writer(session)
    try:
        return {"saved": True, "menu": store.save_item("menus", payload, author)}
    except (ValueError, KeyError) as exc:
        raise HTTPException(status_code=422, detail=str(exc))


@router.patch("/cms/menus/{menu_id}")
def cms_patch_menu(menu_id: str, payload: Dict[str, Any] = Body(...), session: Session = None) -> Dict[str, Any]:
    """Altera um menu (nome, local e itens)."""
    author = _writer(session)
    try:
        return {"saved": True, "menu": store.save_item("menus", {**payload, "id": menu_id}, author)}
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))


@router.delete("/cms/menus/{menu_id}")
def cms_delete_menu(menu_id: str, session: Session = None) -> Dict[str, Any]:
    """Apaga um menu."""
    _writer(session)
    try:
        return store.delete_item("menus", menu_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


# ==========================================================================
# CRUD genérico por entidade
# ==========================================================================
@router.get("/cms/{entity}")
def cms_list(
    entity: str,
    request: Request,
    status: Optional[str] = Query(None, description="`all` ou lista separada por vírgulas."),
    q: Optional[str] = Query(None),
    category_id: Optional[str] = Query(None),
    tag: Optional[str] = Query(None),
    limit: int = Query(200, ge=1, le=500),
    full: bool = Query(True, description="Incluir os blocos/corpo (False = resumo)."),
) -> Any:
    """Lista uma entidade do CMS, com filtros por estado, pesquisa, categoria e etiqueta."""
    if entity in UI_SECTION_SLUGS and _is_browser_navigation(request):
        return _spa_response()
    _entity(entity)
    return store.list_items(entity, status=status, query=q, category_id=category_id, tag=tag, limit=limit, with_blocks=full)


@router.post("/cms/{entity}")
def cms_create(entity: str, payload: Dict[str, Any] = Body(...), session: Session = None) -> Dict[str, Any]:
    """Cria um documento do CMS (no caso dos media, carrega o ficheiro)."""
    _entity(entity)
    author = _writer(session)
    try:
        doc = store.save_media(payload, author) if entity == "media" else store.save_item(entity, payload, author)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    return {"saved": True, "item": doc}


@router.get("/cms/{entity}/{item_id}")
def cms_get(entity: str, item_id: str) -> Dict[str, Any]:
    """Documento completo do CMS."""
    _entity(entity)
    try:
        return {"item": store.get_item(entity, item_id)}
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


@router.patch("/cms/{entity}/{item_id}")
def cms_patch(entity: str, item_id: str, payload: Dict[str, Any] = Body(...), session: Session = None) -> Dict[str, Any]:
    """Alteração parcial de um documento do CMS."""
    _entity(entity)
    author = _writer(session)
    try:
        doc = store.save_media({**payload, "id": item_id}, author) if entity == "media" else store.save_item(entity, {**payload, "id": item_id}, author)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    return {"saved": True, "item": doc}


@router.delete("/cms/{entity}/{item_id}")
def cms_delete(entity: str, item_id: str, session: Session = None) -> Dict[str, Any]:
    """Apaga um documento do CMS."""
    _entity(entity)
    author = _writer(session)
    try:
        return store.delete_item(entity, item_id, author)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


@router.post("/cms/{entity}/{item_id}/duplicate")
def cms_duplicate(entity: str, item_id: str, session: Session = None) -> Dict[str, Any]:
    """Duplica um documento do CMS (a cópia nasce como rascunho)."""
    _entity(entity)
    author = _writer(session)
    try:
        return {"saved": True, "item": store.duplicate_item(entity, item_id, author)}
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


# ==========================================================================
# Publicação, revisões e pré-visualização
# ==========================================================================
@router.post("/cms/{entity}/{item_id}/publish")
def cms_publish(
    entity: str,
    item_id: str,
    payload: Optional[Dict[str, Any]] = Body(None),
    session: Session = None,
) -> Dict[str, Any]:
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


@router.post("/cms/{entity}/{item_id}/unpublish")
def cms_unpublish(entity: str, item_id: str, session: Session = None) -> Dict[str, Any]:
    """Devolve o documento a rascunho (sai imediatamente do site)."""
    _entity(entity)
    author = _writer(session)
    try:
        return {"saved": True, "item": store.unpublish_item(entity, item_id, author)}
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))


@router.post("/cms/{entity}/{item_id}/status")
def cms_status(entity: str, item_id: str, payload: Dict[str, Any] = Body(...), session: Session = None) -> Dict[str, Any]:
    """Muda o estado de publicação (`rascunho`, `agendado`, `publicado`, `arquivado`)."""
    _entity(entity)
    author = _writer(session)
    target = str(payload.get("status") or "")
    if target not in store.STATUSES:
        raise HTTPException(status_code=422, detail=f"Estado inválido «{target}». Válidos: {', '.join(store.STATUSES)}.")
    try:
        return {"saved": True, "item": store.set_status(entity, item_id, target, author)}
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))


@router.get("/cms/{entity}/{item_id}/revisions")
def cms_revisions(entity: str, item_id: str, limit: int = Query(20, ge=1, le=100)) -> Dict[str, Any]:
    """Histórico de revisões de um documento."""
    _entity(entity)
    items = store.revisions_of(entity, item_id, limit=limit)
    return {"total": len(items), "items": items}


@router.post("/cms/revisions/{revision_id}/restore")
def cms_restore(revision_id: str, session: Session = None) -> Dict[str, Any]:
    """Restaura um documento a partir de uma revisão."""
    author = _writer(session)
    try:
        return {"saved": True, "item": store.restore_revision(revision_id, author)}
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


@router.get("/cms/media/{item_id}/usage")
def cms_media_usage(item_id: str) -> Dict[str, Any]:
    """Onde é que este media é usado."""
    try:
        store.get_item("media", item_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    items = store.media_usage(item_id)
    return {"total": len(items), "items": items}


@router.get("/cms/media/{item_id}/raw")
def cms_media_raw(item_id: str) -> Response:
    """Serve o binário de um media (ficheiro local ou reencaminha para o URL externo)."""
    try:
        doc = store.get_item("media", item_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    if doc.get("storage") == "externo":
        url = str(doc.get("url") or "")
        if not url:
            raise HTTPException(status_code=404, detail="Media sem URL.")
        return RedirectResponse(url)
    try:
        path, mime = store.media_file(item_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    return FileResponse(path, media_type=mime, headers={"Cache-Control": "public, max-age=600"})


@router.get("/cms/preview/{entity}/{item_id}")
def cms_preview(entity: str, item_id: str, session: Session = None) -> HTMLResponse:
    """Pré-visualização HTML do rascunho (iframe do editor)."""
    _entity(entity)
    if entity not in ("pages", "posts"):
        raise HTTPException(status_code=422, detail="Só páginas e artigos têm pré-visualização.")
    try:
        doc = store.get_item(entity, item_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    settings = store.get_settings()
    html = render.render_page(doc, preview=True, settings=settings) if entity == "pages" else render.render_post(doc, preview=True, settings=settings)
    return HTMLResponse(html, headers={"Cache-Control": "no-store, must-revalidate"})


# ==========================================================================
# Site público
# ==========================================================================
_PUBLIC_HEADERS = {"Cache-Control": "public, max-age=15, must-revalidate"}


def _home_page() -> Optional[Dict[str, Any]]:
    settings = store.get_settings()
    home_id = settings.get("home_page_id")
    if home_id:
        try:
            page = store.get_item("pages", str(home_id))
        except KeyError:
            page = None
        if page and page.get("status") == "publicado":
            return page
    pages = store.published_pages()
    for page in pages:
        if page.get("template") == "pagina-inicial":
            return page
    for page in pages:
        if not page.get("path"):
            return page
    return pages[0] if pages else None


@router.get("/site", response_class=HTMLResponse)
def site_home() -> HTMLResponse:
    """Página inicial do site."""
    settings = store.get_settings()
    page = _home_page()
    html = render.render_page(page, settings=settings) if page else render.render_index(settings=settings)
    return HTMLResponse(html, headers=_PUBLIC_HEADERS)


@router.get("/site/blog", response_class=HTMLResponse)
def site_blog(page: int = Query(1, ge=1)) -> HTMLResponse:
    """Índice do blog (ou a página «Blog» definida no CMS, na primeira página)."""
    settings = store.get_settings()
    blog_page_id = settings.get("blog_page_id")
    if blog_page_id and page == 1:
        try:
            doc = store.get_item("pages", str(blog_page_id))
        except KeyError:
            doc = None
        if doc and doc.get("status") == "publicado" and doc.get("path"):
            return HTMLResponse(render.render_page(doc, settings=settings), headers=_PUBLIC_HEADERS)
    return HTMLResponse(render.render_blog(page_no=page, settings=settings), headers=_PUBLIC_HEADERS)


@router.get("/site/blog/{slug}", response_class=HTMLResponse)
def site_post(slug: str) -> HTMLResponse:
    """Artigo de blog publicado."""
    settings = store.get_settings()
    post = store.resolve_post_by_slug(slug, published_only=True)
    if not post:
        return HTMLResponse(render.render_not_found(settings=settings), status_code=404, headers=_PUBLIC_HEADERS)
    return HTMLResponse(render.render_post(post, settings=settings), headers=_PUBLIC_HEADERS)


@router.get("/site/categoria/{slug}", response_class=HTMLResponse)
def site_category(slug: str, page: int = Query(1, ge=1)) -> HTMLResponse:
    """Artigos de uma categoria."""
    settings = store.get_settings()
    category = store.category_by_slug(slug)
    if not category:
        return HTMLResponse(render.render_not_found(settings=settings), status_code=404, headers=_PUBLIC_HEADERS)
    return HTMLResponse(render.render_blog(page_no=page, category=category, settings=settings), headers=_PUBLIC_HEADERS)


@router.get("/site/etiqueta/{tag}", response_class=HTMLResponse)
def site_tag(tag: str, page: int = Query(1, ge=1)) -> HTMLResponse:
    """Artigos com uma etiqueta."""
    settings = store.get_settings()
    return HTMLResponse(render.render_blog(page_no=page, tag=tag, settings=settings), headers=_PUBLIC_HEADERS)


@router.get("/site/rss.xml")
def site_rss() -> Response:
    """Feed RSS dos artigos publicados."""
    return Response(render.render_rss(store.get_settings()), media_type="application/rss+xml; charset=utf-8", headers=_PUBLIC_HEADERS)


@router.get("/site/sitemap.xml")
def site_sitemap() -> Response:
    """Sitemap XML das páginas e artigos publicados."""
    return Response(render.render_sitemap(store.get_settings()), media_type="application/xml; charset=utf-8", headers=_PUBLIC_HEADERS)


@router.get("/site/robots.txt", response_class=PlainTextResponse)
def site_robots() -> PlainTextResponse:
    """`robots.txt` do site (bloqueia a área de gestão)."""
    return PlainTextResponse(render.render_robots(store.get_settings()), headers=_PUBLIC_HEADERS)


@router.get("/site/{path:path}", response_class=HTMLResponse)
def site_page(path: str) -> HTMLResponse:
    """Qualquer página publicada, pelo seu caminho (pode ter várias pastas)."""
    settings = store.get_settings()
    page = store.resolve_page_by_path(path, published_only=True)
    if not page:
        return HTMLResponse(render.render_not_found(settings=settings), status_code=404, headers=_PUBLIC_HEADERS)
    return HTMLResponse(render.render_page(page, settings=settings), headers=_PUBLIC_HEADERS)
