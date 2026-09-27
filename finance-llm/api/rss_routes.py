"""Rotas do leitor RSS (`/rss/*`).

**Leitura** (público, como o resto das aplicações de trabalho):

- `GET  /rss/catalogue` — pastas, fontes, etiquetas, estados e definições
- `GET  /rss/overview` — panorama, fontes com erro, temas e atividade
- `GET  /rss/search?q=` — pesquisa em artigos e fontes
- `GET  /rss/articles` — lista com filtros (fonte, pasta, texto, não lidos, favoritos, guardados)
- `GET  /rss/articles/{id}` — artigo completo (`?mark_read=1` marca como lido)
- `GET  /rss/feeds`, `GET /rss/feeds/{id}`, `GET /rss/folders`
- `GET  /rss/suggestions` — catálogo de feeds sugeridos
- `GET  /rss/schedule` — estado do agendador e próximas recolhas
- `GET  /rss/rules` — regras automáticas (termo → guardar/favorito/lido e etiquetas)
- `GET  /rss/tags` — etiquetas das fontes e dos artigos, com contagens
- `GET  /rss/export?format=csv|md` — exportar os artigos (com os filtros da lista)
- `GET  /rss/opml` — descarregar a lista de fontes em OPML

**Escrita** (requer sessão — o leitor é espaço de trabalho do utilizador):

- `POST|PATCH|DELETE /rss/feeds…`, `POST|PATCH|DELETE /rss/folders…`
- `PATCH /rss/articles/{id}` — lido/favorito/guardado
- `POST /rss/articles/read-all`, `POST /rss/articles/purge-read`
- `POST /rss/feeds/{id}/fetch` e `POST /rss/fetch` — recolher uma ou todas
- `POST /rss/feeds/{id}/purge-read`
- `POST /rss/opml/import`, `POST /rss/suggestions/subscribe`
- `PUT  /rss/rules` e `POST /rss/rules/apply` — regras automáticas
- `PUT  /rss/schedule` — gravar a agenda e recarregar os jobs
- `POST /rss/articles/{id}/office|sentiment|crm|rag|digest` — integrações
- `POST /rss/articles/digest` — boletim por IA de vários artigos
"""
from __future__ import annotations

import logging
from typing import Annotated, Any, Dict, Optional

from fastapi import APIRouter, Body, Depends, HTTPException, Query
from fastapi.responses import PlainTextResponse, Response

from api import rss_service as service
from api import rss_store as store
from api.auth_routes import CurrentSession, optional_session

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/rss", tags=["rss"])

Session = Annotated[Optional[CurrentSession], Depends(optional_session)]


def _writer(session: Optional[CurrentSession]) -> CurrentSession:
    if not session:
        raise HTTPException(status_code=401, detail="Entrar na plataforma para alterar o leitor de RSS.")
    return session


def _author(session: Optional[CurrentSession]) -> str:
    return session.user.email if session else ""


def _owner(session: CurrentSession) -> Dict[str, Any]:
    return {"id": session.user.id, "email": session.user.email, "see_all": (session.user.role or "member") == "admin"}


def _query_text(value: Any) -> Optional[str]:
    """Texto de um parâmetro de consulta (qualquer outra coisa = «sem filtro»)."""
    return value if isinstance(value, str) and value.strip() else None


def _query_bool(value: Any) -> Optional[bool]:
    return value if isinstance(value, bool) else None


# ==========================================================================
# Catálogo, panorama e pesquisa
# ==========================================================================
@router.get("/catalogue")
def rss_catalogue() -> Dict[str, Any]:
    """Pastas, fontes, etiquetas, estados e definições de recolha."""
    catalogue = store.catalogue()
    catalogue["suggestions"] = service.suggestions()["categories"]
    return catalogue


@router.get("/overview")
def rss_overview() -> Dict[str, Any]:
    """Panorama do leitor: contagens, fontes com erro, temas e atividade."""
    from api import rss_scheduler

    payload = store.overview()
    payload["trending"] = service.trending_terms()
    payload["schedule"] = rss_scheduler.status()
    payload["folders_detail"] = store.list_folders()
    return payload


@router.get("/search")
def rss_search(
    q: str = Query("", description="Texto a procurar (título, resumo, autor, fonte)."),
    limit: int = Query(30, ge=1, le=100),
) -> Dict[str, Any]:
    """Pesquisa em artigos e fontes."""
    return store.search(q, limit=limit)


# ==========================================================================
# Agenda
# ==========================================================================
@router.get("/schedule")
def rss_schedule() -> Dict[str, Any]:
    """Estado do agendador cron e próximas execuções."""
    from api import rss_scheduler

    return rss_scheduler.status()


@router.put("/schedule")
def rss_save_schedule(payload: Dict[str, Any] = Body(...), session: Session = None) -> Dict[str, Any]:
    """Grava a agenda (`cron`, `timezone`, `auto_fetch`, limites) e recarrega os jobs."""
    actor = _writer(session)
    from api import rss_scheduler

    saved = store.save_settings(payload, _author(actor))
    state = rss_scheduler.reload_jobs()
    return {"saved": True, "settings": saved, "schedule": state}


@router.post("/schedule/reload")
def rss_reload_schedule(session: Session = None) -> Dict[str, Any]:
    """Força a releitura das definições no agendador."""
    _writer(session)
    from api import rss_scheduler

    return rss_scheduler.reload_jobs()


# ==========================================================================
# Pastas
# ==========================================================================
@router.get("/folders")
def rss_list_folders() -> Dict[str, Any]:
    """Pastas de feeds, com número de fontes e não lidos."""
    items = store.list_folders()
    return {"total": len(items), "items": items}


@router.post("/folders")
def rss_create_folder(payload: Dict[str, Any] = Body(...), session: Session = None) -> Dict[str, Any]:
    """Cria uma pasta."""
    actor = _writer(session)
    try:
        return {"saved": True, "folder": store.save_folder(payload, _author(actor))}
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))


@router.patch("/folders/{folder_id}")
def rss_patch_folder(folder_id: str, payload: Dict[str, Any] = Body(...), session: Session = None) -> Dict[str, Any]:
    """Altera uma pasta (nome, cor, ordem)."""
    actor = _writer(session)
    try:
        return {"saved": True, "folder": store.save_folder({**payload, "id": folder_id}, _author(actor))}
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))


@router.delete("/folders/{folder_id}")
def rss_delete_folder(folder_id: str, session: Session = None) -> Dict[str, Any]:
    """Apaga uma pasta (as fontes passam a ficar sem pasta)."""
    actor = _writer(session)
    try:
        return store.delete_folder(folder_id, _author(actor))
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


# ==========================================================================
# Recolha, OPML e sugestões (rotas literais antes das parametrizadas)
# ==========================================================================
@router.post("/fetch")
def rss_fetch_all(
    force: bool = Query(False, description="Ignorar ETag/Last-Modified."),
    session: Session = None,
) -> Dict[str, Any]:
    """Recolhe todas as fontes ativas."""
    actor = _writer(session)
    return service.refresh_all(actor=_author(actor), force=force)


@router.get("/opml", response_class=PlainTextResponse)
def rss_export_opml() -> PlainTextResponse:
    """Descarrega as fontes subscritas em OPML."""
    return PlainTextResponse(
        service.export_opml(),
        media_type="text/x-opml; charset=utf-8",
        headers={"content-disposition": 'attachment; filename="iqos-leitor-rss.opml"'},
    )


@router.post("/opml/import")
def rss_import_opml(payload: Dict[str, Any] = Body(...), session: Session = None) -> Dict[str, Any]:
    """Importa uma lista OPML (`{"opml": "<?xml …", "folder_id": null}`)."""
    actor = _writer(session)
    text = str(payload.get("opml") or payload.get("text") or "")
    if not text.strip():
        raise HTTPException(status_code=422, detail="Envie o conteúdo OPML no campo `opml`.")
    limit = payload.get("fetch_limit")
    try:
        fetch_limit = max(0, min(60, int(limit))) if limit is not None else 12
    except (TypeError, ValueError):
        fetch_limit = 12
    result = service.import_opml(
        text,
        actor=_author(actor),
        folder_id=payload.get("folder_id") or None,
        fetch_limit=fetch_limit,
    )
    if not result.get("ok"):
        raise HTTPException(status_code=422, detail=result.get("error"))
    return result


@router.get("/suggestions")
def rss_suggestions() -> Dict[str, Any]:
    """Feeds sugeridos (economia, mercados, reguladores e Portugal)."""
    return service.suggestions()


@router.post("/suggestions/subscribe")
def rss_subscribe_suggestions(payload: Dict[str, Any] = Body(...), session: Session = None) -> Dict[str, Any]:
    """Subscreve feeds sugeridos (`{"ids": ["eco", …]}` ou `{"urls": [...]}`)."""
    actor = _writer(session)
    wanted = [str(value) for value in (payload.get("ids") or [])]
    urls = [str(value) for value in (payload.get("urls") or [])]
    catalog = {item["id"]: item for item in service.suggestions()["items"]}
    targets = [catalog[item_id]["url"] for item_id in wanted if item_id in catalog] + urls
    if not targets:
        raise HTTPException(status_code=422, detail="Indique os feeds a subscrever (`ids` ou `urls`).")
    folder_id = payload.get("folder_id") or None
    results = []
    for target in targets:
        results.append(service.subscribe(target, folder_id=folder_id, actor=_author(actor), discover=False))
    return {
        "subscribed": sum(1 for item in results if item.get("ok")),
        "failed": [item.get("error") for item in results if not item.get("ok")],
        "items": results,
    }


# ==========================================================================
# Regras automáticas e etiquetas
# ==========================================================================
@router.get("/rules")
def rss_list_rules() -> Dict[str, Any]:
    """Regras automáticas e as ações que cada uma pode aplicar."""
    return {"total": len(store.rules()), "items": store.rules(), "actions": [dict(action) for action in store.RULE_ACTIONS]}


@router.put("/rules")
def rss_save_rules(payload: Dict[str, Any] = Body(...), session: Session = None) -> Dict[str, Any]:
    """Grava as regras (`{"rules": [...], "apply_now": true}`)."""
    actor = _writer(session)
    result = store.save_rules(payload.get("rules") or [], _author(actor), apply_now=bool(payload.get("apply_now")))
    return {"saved": True, **result}


@router.post("/rules/apply")
def rss_apply_rules(payload: Dict[str, Any] = Body(default={}), session: Session = None) -> Dict[str, Any]:
    """Aplica as regras atuais aos artigos já guardados (por omissão só aos não lidos)."""
    actor = _writer(session)
    return store.apply_rules(_author(actor), only_unread=payload.get("only_unread", True) is not False)


@router.get("/tags")
def rss_tags() -> Dict[str, Any]:
    """Etiquetas usadas nas fontes e nos artigos."""
    items = store.tags()
    return {"total": len(items), "items": items}


# ==========================================================================
# Exportação
# ==========================================================================
@router.get("/export")
def rss_export(
    format: str = Query("csv", pattern="^(csv|md)$"),
    feed_id: Optional[str] = Query(None),
    folder_id: Optional[str] = Query(None),
    q: Optional[str] = Query(None),
    unread: Optional[bool] = Query(None),
    favorite: Optional[bool] = Query(None),
    saved: Optional[bool] = Query(None),
    tag: Optional[str] = Query(None),
    since: Optional[str] = Query(None),
    limit: int = Query(500, ge=1, le=5000),
) -> Response:
    """Exporta os artigos que correspondem aos filtros (CSV para Excel, Markdown para ler)."""
    search = _query_text(q)
    label = _query_text(tag)
    start = _query_text(since)
    only_unread = _query_bool(unread)
    only_favorite = _query_bool(favorite)
    only_saved = _query_bool(saved)
    rows = store.export_articles(
        feed_id=feed_id,
        folder_id=folder_id,
        q=search,
        unread=only_unread,
        favorite=only_favorite,
        saved=only_saved,
        tag=label,
        since=start,
        limit=limit,
    )
    note = " · ".join(
        part
        for part in (
            f"texto: {search}" if search else "",
            "só por ler" if only_unread else "",
            "favoritos" if only_favorite else "",
            "guardados" if only_saved else "",
            f"etiqueta: {label}" if label else "",
            f"desde {start}" if start else "",
        )
        if part
    )
    if format == "md":
        content = service.export_articles_markdown(rows, note=note)
        return Response(
            content=content,
            media_type="text/markdown; charset=utf-8",
            headers={"content-disposition": 'attachment; filename="leitor-rss.md"'},
        )
    payload = service.export_articles_csv(rows, note=note)
    return Response(
        content=payload["content"],
        media_type=payload["media_type"],
        headers={"content-disposition": f'attachment; filename="{payload["filename"]}"'},
    )


# ==========================================================================
# Fontes
# ==========================================================================
@router.get("/feeds")
def rss_list_feeds(
    folder_id: Optional[str] = Query(None, description="`all`, `root` (sem pasta) ou o id da pasta."),
    q: Optional[str] = Query(None),
) -> Dict[str, Any]:
    """Fontes subscritas, com não lidos e estado da última recolha."""
    items = store.list_feeds(folder_id=folder_id, query=q)
    return {"total": len(items), "items": items}


@router.post("/feeds")
def rss_create_feed(payload: Dict[str, Any] = Body(...), session: Session = None) -> Dict[str, Any]:
    """Subscreve um feed (`{"url": …, "folder_id": …, "tags": [...]}`)."""
    actor = _writer(session)
    result = service.subscribe(
        str(payload.get("url") or ""),
        folder_id=payload.get("folder_id") or None,
        title=payload.get("title"),
        tags=payload.get("tags"),
        actor=_author(actor),
        fetch=bool(payload.get("fetch", True)),
        discover=bool(payload.get("discover", True)),
    )
    if not result.get("ok"):
        raise HTTPException(status_code=422, detail=result.get("error"))
    return result


@router.get("/feeds/{feed_id}")
def rss_get_feed(feed_id: str) -> Dict[str, Any]:
    """Fonte completa."""
    try:
        return {"feed": store.get_feed(feed_id)}
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


@router.patch("/feeds/{feed_id}")
def rss_patch_feed(feed_id: str, payload: Dict[str, Any] = Body(...), session: Session = None) -> Dict[str, Any]:
    """Altera uma fonte (título, pasta, etiquetas, ativa/inativa)."""
    actor = _writer(session)
    try:
        feed = store.save_feed({**payload, "id": feed_id}, _author(actor))
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    from api import rss_scheduler

    rss_scheduler.reload_jobs()
    return {"saved": True, "feed": feed}


@router.delete("/feeds/{feed_id}")
def rss_delete_feed(feed_id: str, session: Session = None) -> Dict[str, Any]:
    """Apaga uma fonte e os seus artigos."""
    actor = _writer(session)
    try:
        return store.delete_feed(feed_id, _author(actor))
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


@router.post("/feeds/{feed_id}/fetch")
def rss_fetch_feed(
    feed_id: str,
    force: bool = Query(False, description="Ignorar ETag/Last-Modified."),
    session: Session = None,
) -> Dict[str, Any]:
    """Recolhe uma fonte."""
    actor = _writer(session)
    result = service.refresh_feed(feed_id, actor=_author(actor), force=force)
    if result.get("status") == "erro" and not result.get("feed"):
        raise HTTPException(status_code=404, detail=result.get("error"))
    return result


@router.post("/feeds/{feed_id}/read-all")
def rss_feed_read_all(feed_id: str, session: Session = None) -> Dict[str, Any]:
    """Marca como lidos todos os artigos de uma fonte."""
    actor = _writer(session)
    try:
        store.get_feed(feed_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    return store.mark_all_read(feed_id=feed_id, actor=_author(actor))


@router.post("/feeds/{feed_id}/purge-read")
def rss_feed_purge_read(feed_id: str, session: Session = None) -> Dict[str, Any]:
    """Remove os artigos já lidos de uma fonte (favoritos e guardados ficam)."""
    actor = _writer(session)
    try:
        store.get_feed(feed_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    return store.purge_read(feed_id=feed_id, actor=_author(actor))


# ==========================================================================
# Artigos
# ==========================================================================
@router.get("/articles")
def rss_list_articles(
    feed_id: Optional[str] = Query(None),
    folder_id: Optional[str] = Query(None, description="`all`, `root` ou o id da pasta."),
    q: Optional[str] = Query(None),
    unread: Optional[bool] = Query(None),
    favorite: Optional[bool] = Query(None),
    saved: Optional[bool] = Query(None),
    tag: Optional[str] = Query(None),
    since: Optional[str] = Query(None, description="Data ISO mínima."),
    order: str = Query("desc", pattern="^(asc|desc)$"),
    limit: int = Query(40, ge=1, le=200),
    offset: int = Query(0, ge=0),
) -> Dict[str, Any]:
    """Artigos (resumos) com filtros e contagens por fonte."""
    return store.list_articles(
        feed_id=feed_id,
        folder_id=folder_id,
        q=q,
        unread=unread,
        favorite=favorite,
        saved=saved,
        tag=tag,
        since=since,
        order=order,
        limit=limit,
        offset=offset,
    )


@router.post("/articles/read-all")
def rss_read_all(payload: Dict[str, Any] = Body(default={}), session: Session = None) -> Dict[str, Any]:
    """Marca como lidos os artigos que correspondem aos filtros enviados."""
    actor = _writer(session)
    return store.mark_all_read(
        feed_id=payload.get("feed_id") or None,
        folder_id=payload.get("folder_id") or None,
        q=payload.get("q") or None,
        actor=_author(actor),
    )


@router.post("/articles/purge-read")
def rss_purge_read(payload: Dict[str, Any] = Body(default={}), session: Session = None) -> Dict[str, Any]:
    """Remove os artigos lidos (favoritos e guardados ficam)."""
    actor = _writer(session)
    return store.purge_read(feed_id=payload.get("feed_id") or None, actor=_author(actor))


@router.post("/articles/digest")
def rss_articles_digest(payload: Dict[str, Any] = Body(...), session: Session = None) -> Dict[str, Any]:
    """Boletim por IA dos artigos indicados (ids) ou dos filtros da lista."""
    actor = _writer(session)
    result = service.digest_collection(
        article_ids=payload.get("article_ids"),
        feed_id=payload.get("feed_id") or None,
        folder_id=payload.get("folder_id") or None,
        q=payload.get("q") or None,
        unread=True if payload.get("unread") is not False else None,
        limit=max(1, min(24, int(payload.get("limit") or 12))),
        user_id=actor.user.id,
        provider=payload.get("provider"),
        model=payload.get("model"),
    )
    if not result.get("ok"):
        raise HTTPException(status_code=502, detail=result.get("error"))
    if payload.get("save_to_office"):
        saved = service.save_digest_to_office(str(result.get("markdown") or ""), author=_author(actor))
        result["office"] = saved
    return result


@router.get("/articles/{article_id}")
def rss_get_article(
    article_id: str,
    mark_read: bool = Query(False, description="Marca o artigo como lido ao abrir."),
) -> Dict[str, Any]:
    """Artigo completo (conteúdo, resumo de IA e origem)."""
    try:
        article = store.get_article(article_id, mark_read=mark_read)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    return {"article": article, "related": store.related_articles(article_id, limit=5)}


@router.patch("/articles/{article_id}")
def rss_patch_article(article_id: str, payload: Dict[str, Any] = Body(...), session: Session = None) -> Dict[str, Any]:
    """Altera os estados do artigo (`read`, `favorite`, `saved`) e as suas etiquetas."""
    _writer(session)
    try:
        return {"saved": True, "article": store.update_article(article_id, payload)}
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


@router.get("/articles/{article_id}/related")
def rss_related(article_id: str, limit: int = Query(5, ge=1, le=20)) -> Dict[str, Any]:
    """Artigos do mesmo tema (categorias e palavras do título em comum)."""
    try:
        items = store.related_articles(article_id, limit=limit)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    return {"total": len(items), "items": items}


# ==========================================================================
# Integrações
# ==========================================================================
@router.post("/articles/{article_id}/office")
def rss_to_office(article_id: str, session: Session = None) -> Dict[str, Any]:
    """Cria um documento no Office com o artigo."""
    actor = _writer(session)
    result = service.to_office(article_id, author=_author(actor))
    if not result.get("ok"):
        raise HTTPException(status_code=502, detail=result.get("error"))
    return result


@router.post("/articles/{article_id}/sentiment")
def rss_to_sentiment(article_id: str) -> Dict[str, Any]:
    """Analisa o sentimento do artigo."""
    result = service.analyze_sentiment(article_id)
    if not result.get("ok"):
        raise HTTPException(status_code=502, detail=result.get("error"))
    return result


@router.post("/articles/{article_id}/crm")
def rss_to_crm(article_id: str, payload: Dict[str, Any] = Body(default={}), session: Session = None) -> Dict[str, Any]:
    """Regista o artigo como nota numa conta do CRM."""
    actor = _writer(session)
    result = service.to_crm(article_id, owner=_owner(actor), account_id=payload.get("account_id") or None)
    if not result.get("ok"):
        raise HTTPException(status_code=502, detail=result.get("error"))
    return result


@router.post("/articles/{article_id}/rag")
def rss_to_rag(article_id: str, session: Session = None) -> Dict[str, Any]:
    """Indexa o artigo no RAG (Markdown → chunks → embeddings)."""
    _writer(session)
    result = service.to_rag(article_id)
    if not result.get("ok"):
        raise HTTPException(status_code=502, detail=result.get("error"))
    return result


@router.post("/articles/{article_id}/digest")
def rss_digest_article(article_id: str, payload: Dict[str, Any] = Body(default={}), session: Session = None) -> Dict[str, Any]:
    """Resume o artigo com IA e guarda o resumo no artigo."""
    actor = _writer(session)
    result = service.digest_article(
        article_id,
        user_id=actor.user.id,
        provider=payload.get("provider"),
        model=payload.get("model"),
        save=payload.get("save") is not False,
    )
    if not result.get("ok"):
        raise HTTPException(status_code=502, detail=result.get("error"))
    return result
