"""Orquestração do leitor RSS: recolher, resumir e integrar.

Junta as três peças do módulo:

* `api/rss_feed.py` — vai à rede buscar e analisar o XML;
* `api/rss_store.py` — guarda feeds e artigos no documento JSON;
* as outras aplicações da plataforma — Office (`office_store`), sentimento
  (`sentiment_service`), CRM (`crm_service`), RAG (`rag_service`) e os
  fornecedores de IA (`scraper_ai.pick_provider` + `cloud_chat`).

Todas as integrações usam **import tardio** e nunca deixam a recolha falhar: se
o Office ou o CRM não estiverem disponíveis, a mensagem de erro é devolvida ao
utilizador e o artigo mantém-se intacto.
"""
from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Dict, List, Optional, Sequence

from api import rss_feed as feed_tools
from api import rss_store as store

logger = logging.getLogger(__name__)

MAX_DIGEST_INPUT = 14_000
_rag_executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="rss_rag_")


# --------------------------------------------------------------------------
# Recolha
# --------------------------------------------------------------------------
def _feed_meta_patch(feed: Dict[str, Any], parsed: Dict[str, Any], final_url: str) -> Dict[str, Any]:
    """Metadados que a recolha aprende do próprio feed (sem apagar o que o utilizador escreveu)."""
    patch: Dict[str, Any] = {}
    title = str(parsed.get("title") or "").strip()
    current = str(feed.get("title") or "").strip()
    if title and (not current or current == str(feed.get("url") or "")):
        patch["title"] = title
    if parsed.get("site_url") and not feed.get("site_url"):
        patch["site_url"] = parsed["site_url"]
    if parsed.get("description") and not feed.get("description"):
        patch["description"] = parsed["description"]
    if parsed.get("language") and not feed.get("language"):
        patch["language"] = parsed["language"]
    if parsed.get("icon_url") and not feed.get("icon_url"):
        patch["icon_url"] = parsed["icon_url"]
    if final_url and final_url != feed.get("url"):
        patch["site_url"] = patch.get("site_url") or final_url
    return patch


def refresh_feed(feed_id: str, *, actor: str = "", force: bool = False) -> Dict[str, Any]:
    """Recolhe uma fonte. `force` ignora o `ETag`/`Last-Modified` guardados."""
    try:
        feed = store.get_feed(feed_id)
    except KeyError as exc:
        return {"feed_id": feed_id, "status": "erro", "error": str(exc), "added": 0, "updated": 0}
    result = feed_tools.fetch_and_parse(
        feed["url"],
        etag=None if force else feed.get("etag"),
        last_modified=None if force else feed.get("last_modified"),
    )
    status = result.get("status")
    now = feed_tools.now_iso()
    if status == "error":
        state = store.feed_state(
            feed_id,
            {"last_status": "erro", "last_error": str(result.get("error") or "Falha na recolha."), "last_fetch_at": now},
        )
        return {"feed_id": feed_id, "status": "erro", "error": state.get("last_error"), "added": 0, "updated": 0, "feed": state}
    if status == "not_modified":
        state = store.feed_state(feed_id, {"last_status": "nao_modificado", "last_error": "", "last_fetch_at": now})
        return {"feed_id": feed_id, "status": "nao_modificado", "error": None, "added": 0, "updated": 0, "feed": state}

    parsed = result.get("feed") or {}
    try:
        counts = store.store_articles(feed_id, parsed.get("entries") or [])
    except KeyError as exc:
        return {"feed_id": feed_id, "status": "erro", "error": str(exc), "added": 0, "updated": 0}
    patch = _feed_meta_patch(feed, parsed, str(result.get("url") or feed["url"]))
    patch.update(
        {
            "last_status": "ok" if counts["added"] else "sem_novidades",
            "last_error": "",
            "last_fetch_at": now,
        }
    )
    if result.get("etag"):
        patch["etag"] = result["etag"]
    if result.get("last_modified"):
        patch["last_modified"] = result["last_modified"]
    state = store.feed_state(feed_id, patch)
    return {
        "feed_id": feed_id,
        "status": patch["last_status"],
        "error": None,
        "added": counts["added"],
        "updated": counts["updated"],
        "articles": counts["total"],
        "rule_hits": counts.get("rule_hits", 0),
        "feed": state,
    }


def refresh_all(*, actor: str = "", only_enabled: bool = True, force: bool = False) -> Dict[str, Any]:
    """Recolhe todas as fontes (respeitando um intervalo de cortesia entre pedidos)."""
    feeds = store.list_feeds()
    if only_enabled:
        feeds = [feed for feed in feeds if feed.get("enabled")]
    items: List[Dict[str, Any]] = []
    added = 0
    errors = 0
    rule_hits = 0
    for index, feed in enumerate(feeds):
        if index:
            feed_tools.sleep(0.4)
        result = refresh_feed(feed["id"], actor=actor, force=force)
        added += int(result.get("added") or 0)
        rule_hits += int(result.get("rule_hits") or 0)
        if result.get("status") == "erro":
            errors += 1
        items.append(
            {
                "feed_id": feed["id"],
                "title": feed.get("title") or feed.get("url"),
                "status": result.get("status"),
                "added": result.get("added") or 0,
                "error": result.get("error"),
            }
        )
    return {"feeds": len(feeds), "added": added, "errors": errors, "rule_hits": rule_hits, "items": items}


# --------------------------------------------------------------------------
# Subscrição e OPML
# --------------------------------------------------------------------------
def subscribe(
    url: str,
    *,
    folder_id: Optional[str] = None,
    title: Optional[str] = None,
    tags: Optional[Sequence[str]] = None,
    actor: str = "",
    fetch: bool = True,
    discover: bool = True,
) -> Dict[str, Any]:
    """Subscreve um feed: descobre o endereço (se for uma página), cria e recolhe."""
    target = (url or "").strip()
    if not target:
        return {"ok": False, "error": "Indique o endereço do feed."}
    discovered: Optional[Dict[str, Any]] = None
    feed_url = target
    if discover:
        discovered = feed_tools.discover(target)
        if discovered.get("feed_url"):
            feed_url = str(discovered["feed_url"])
        else:
            return {"ok": False, "error": discovered.get("error") or "Não foi possível encontrar o feed.", "candidates": discovered.get("candidates") or []}
    existing = store.find_feed_by_url(feed_url)
    if existing:
        return {"ok": False, "error": f"Esse feed já está subscrito («{existing.get('title')}»).", "feed": existing}

    parsed: Dict[str, Any] = {}
    if fetch:
        result = feed_tools.fetch_and_parse(feed_url)
        if result.get("status") == "ok":
            parsed = result.get("feed") or {}
    try:
        feed = store.save_feed(
            {
                "url": feed_url,
                "title": (title or "").strip() or str(parsed.get("title") or "").strip() or feed_tools.host_of(feed_url),
                "site_url": str(parsed.get("site_url") or "").strip(),
                "description": parsed.get("description") or "",
                "language": parsed.get("language") or "",
                "icon_url": parsed.get("icon_url") or "",
                "folder_id": folder_id,
                "tags": list(tags or []),
                "enabled": True,
            },
            actor,
        )
    except (ValueError, KeyError) as exc:
        return {"ok": False, "error": str(exc)}

    added = 0
    if fetch and parsed.get("entries"):
        counts = store.store_articles(feed["id"], parsed["entries"])
        added = counts["added"]
    if fetch:
        store.feed_state(
            feed["id"],
            {"last_status": "ok" if added else "sem_novidades", "last_error": "", "last_fetch_at": feed_tools.now_iso()},
        )
    return {
        "ok": True,
        "feed": store.get_feed(feed["id"]),
        "added": added,
        "feed_url": feed_url,
        "discovered": bool(discovered and discovered.get("feed_url") and discovered["feed_url"] != target),
        "candidates": (discovered or {}).get("candidates") or [],
    }


def import_opml(text: str, *, actor: str = "", folder_id: Optional[str] = None, fetch_limit: int = 12) -> Dict[str, Any]:
    """Importa uma lista OPML: cria pastas e fontes e recolhe as primeiras `fetch_limit`."""
    parsed = feed_tools.parse_opml(text or "")
    if parsed.get("error"):
        return {"ok": False, "error": parsed["error"]}
    if not parsed["feeds"]:
        return {"ok": False, "error": "A lista OPML não tem feeds."}

    folders_by_name = {str(folder.get("name") or "").lower(): folder for folder in store.list_folders()}
    folders_created = 0
    feeds_created = 0
    skipped: List[str] = []
    created: List[Dict[str, Any]] = []
    for entry in parsed["feeds"]:
        target = str(entry.get("url") or "").strip()
        if not target or store.find_feed_by_url(target):
            if target:
                skipped.append(target)
            continue
        target_folder = folder_id
        name = str(entry.get("folder") or "").strip()
        if not target_folder and name:
            known = folders_by_name.get(name.lower())
            if not known:
                known = store.save_folder({"name": name}, actor)
                folders_by_name[name.lower()] = known
                folders_created += 1
            target_folder = known["id"]
        try:
            created_feed = store.save_feed(
                {
                    "url": target,
                    "title": str(entry.get("title") or "").strip() or target,
                    "site_url": str(entry.get("site_url") or "").strip(),
                    "folder_id": target_folder,
                    "enabled": True,
                },
                actor,
            )
        except (ValueError, KeyError, TypeError):
            skipped.append(target)
            continue
        feeds_created += 1
        created.append(created_feed)

    fetched = 0
    for created_feed in created[: max(0, fetch_limit)]:
        result = refresh_feed(created_feed["id"], actor=actor)
        if result.get("status") in ("ok", "sem_novidades", "nao_modificado"):
            fetched += 1
        feed_tools.sleep(0.2)

    return {
        "ok": True,
        "folders_created": folders_created,
        "feeds_created": feeds_created,
        "fetched": fetched,
        "pending": max(0, feeds_created - fetched),
        "skipped": skipped[:20],
        "skipped_total": len(skipped),
    }


def export_opml() -> str:
    return feed_tools.build_opml(store.list_feeds(), store.list_folders())


def suggestions() -> Dict[str, Any]:
    """Catálogo de sugestões, marcando as que já estão subscritas."""
    subscribed = {str(feed.get("url") or "").strip().rstrip("/").lower() for feed in store.list_feeds()}
    items = []
    for item in feed_tools.suggestions():
        items.append({**item, "subscribed": item["url"].strip().rstrip("/").lower() in subscribed})
    return {"categories": feed_tools.suggestions_meta()["categories"], "total": len(items), "items": items}


# --------------------------------------------------------------------------
# Integração com as outras aplicações
# --------------------------------------------------------------------------
def _article_source(article: Dict[str, Any]) -> str:
    parts = [str(article.get("feed_title") or article.get("feed_url") or "")]
    if article.get("published_at"):
        parts.append(str(article["published_at"])[:10])
    if article.get("url"):
        parts.append(str(article["url"]))
    return " · ".join(part for part in parts if part)


def article_plain_text(article: Dict[str, Any], limit: int = 20_000) -> str:
    body = store.clean_text(article.get("content") or article.get("summary"), limit)
    return "\n\n".join(
        part
        for part in (
            str(article.get("title") or ""),
            _article_source(article),
            str(article.get("summary") or "")[:1200],
            body,
        )
        if part
    )


def to_office(article_id: str, *, author: str = "", force_new: bool = False) -> Dict[str, Any]:
    """Cria um documento no Office com o artigo (Markdown com a origem e o link)."""
    try:
        article = store.get_article(article_id)
    except KeyError as exc:
        return {"ok": False, "error": str(exc)}
    try:
        from api import office_store
    except Exception as exc:  # pragma: no cover - import
        return {"ok": False, "error": f"Office indisponível: {exc}"}
    markdown = store.article_markdown(article)
    tags = ["rss", *[str(tag) for tag in (article.get("tags") or [])[:4]]]
    try:
        document = office_store.save_document(
            {
                "title": str(article.get("title") or "Artigo RSS")[:180],
                "kind": "nota",
                "markdown": markdown,
                "tags": tags,
                "source": {"kind": "rss", "article_id": article_id, "url": article.get("url") or ""},
            },
            author=author or None,
            force_new=force_new,
        )
    except Exception as exc:
        logger.warning("RSS → Office falhou: %s", exc)
        return {"ok": False, "error": str(exc)}
    store.update_article(article_id, {"saved": True})
    return {"ok": True, "document": document, "document_id": document.get("id")}


def analyze_sentiment(article_id: str) -> Dict[str, Any]:
    """Analisa o sentimento do artigo com o motor do módulo de sentimento."""
    try:
        article = store.get_article(article_id)
    except KeyError as exc:
        return {"ok": False, "error": str(exc)}
    try:
        from api import sentiment_service
    except Exception as exc:  # pragma: no cover - import
        return {"ok": False, "error": f"Sentimento indisponível: {exc}"}
    try:
        analysis = sentiment_service.analyze_text(article_plain_text(article))
    except Exception as exc:
        logger.warning("RSS → sentimento falhou: %s", exc)
        return {"ok": False, "error": str(exc)}
    return {"ok": True, "analysis": analysis, "title": article.get("title") or "", "url": article.get("url") or ""}


def to_crm(article_id: str, *, owner: Dict[str, Any], account_id: Optional[str] = None) -> Dict[str, Any]:
    """Registra o artigo como atividade (nota) numa conta do CRM."""
    try:
        article = store.get_article(article_id)
    except KeyError as exc:
        return {"ok": False, "error": str(exc)}
    try:
        from api import crm_service
    except Exception as exc:  # pragma: no cover - import
        return {"ok": False, "error": f"CRM indisponível: {exc}"}
    payload = {
        "subject": f"Notícia: {str(article.get('title') or '')}"[:200],
        "type": "nota",
        "status": "concluida",
        "done": True,
        "priority": "baixa",
        "account_id": account_id or None,
        "notes": "\n".join(
            part
            for part in (
                _article_source(article),
                "",
                str(article.get("summary") or "")[:1500],
            )
            if part is not None
        ),
    }
    try:
        result = crm_service.save_record("activity", payload, owner)
    except Exception as exc:
        logger.warning("RSS → CRM falhou: %s", exc)
        return {"ok": False, "error": str(exc)}
    if not result.get("ok"):
        return {"ok": False, "error": result.get("error") or "Não foi possível criar a atividade."}
    store.update_article(article_id, {"saved": True})
    return {"ok": True, "item": result.get("item")}


def ingest_to_rag(article: Dict[str, Any]) -> Dict[str, Any]:
    """Indexa o artigo no RAG (Markdown → chunks → embeddings)."""
    from hashlib import sha256

    from api.rag_service import get_rag_engine
    from rag.ingestion.chunker import chunk_markdown, save_chunks
    from rag.paths import MARKDOWN_DIR
    from rag.storage.document_store import DocumentEntry

    doc_id = f"rss-{article['id']}"
    title = str(article.get("title") or "Artigo RSS")
    markdown = store.article_markdown(article)
    MARKDOWN_DIR.mkdir(parents=True, exist_ok=True)
    md_path = MARKDOWN_DIR / f"{doc_id}.md"
    md_path.write_text(markdown, encoding="utf-8")
    chunks = chunk_markdown(md_path, doc_id=doc_id, doc_title=title)
    chunk_file = md_path.parent / f"{doc_id}_chunks.jsonl"
    save_chunks(chunks, chunk_file)
    engine = get_rag_engine()
    try:
        engine.vector_store.delete_by_doc_id(doc_id)
    except Exception:  # pragma: no cover - índice novo
        pass
    engine.document_store.add(
        DocumentEntry(
            doc_id=doc_id,
            title=title,
            filename=md_path.name,
            pages=1,
            size_bytes=len(markdown.encode("utf-8")),
            hash=sha256(markdown.encode("utf-8")).hexdigest(),
            md_path=str(md_path),
            chunk_file=str(chunk_file),
            indexed=True,
            converter="rss",
            extra={"source": "rss", "article_id": article["id"], "url": article.get("url") or "", "feed": article.get("feed_title") or ""},
        )
    )
    engine.vector_store.add(
        [
            {
                "chunk_id": chunk.chunk_id,
                "doc_id": chunk.doc_id,
                "doc_title": chunk.doc_title,
                "page": chunk.page,
                "text": chunk.text,
            }
            for chunk in chunks
        ]
    )
    engine.document_store.set_indexed(doc_id, True)
    engine.document_store.add_history(doc_id, "ingest", f"artigo RSS {article['id']}")
    return {"ok": True, "doc_id": doc_id, "title": title, "chunks": len(chunks), "url": article.get("url") or ""}


def to_rag(article_id: str) -> Dict[str, Any]:
    """Indexa um artigo no RAG (a ingestão é pesada: corre num executor próprio)."""
    try:
        article = store.get_article(article_id)
    except KeyError as exc:
        return {"ok": False, "error": str(exc)}
    try:
        return _rag_executor.submit(ingest_to_rag, article).result(timeout=180)
    except Exception as exc:
        logger.warning("RSS → RAG falhou: %s", exc)
        return {"ok": False, "error": str(exc)}


# --------------------------------------------------------------------------
# Digest / resumo por IA
# --------------------------------------------------------------------------
ARTICLE_PROMPT = """És um analista que resume notícias para uma equipa de finanças.
Escreve em português de Portugal, em Markdown, com:
- um título curto (##);
- 3 a 5 pontos-chave (frases curtas, sem repetir o título);
- uma linha final «Porque importa: …» com a implicação prática.

Não inventes números nem factos que não estejam no texto. Se o texto for
insuficiente, diz exatamente o que falta.

Fonte: {source}
Título: {title}

Texto:
{text}
"""

DIGEST_PROMPT = """És um analista que prepara um boletim de imprensa para uma equipa de finanças.
Escreve em português de Portugal, em Markdown, com:
- um título (##) com o tema comum (ou «Boletim de notícias»);
- um parágrafo de abertura de 2 frases a ligar os temas;
- uma lista com os pontos mais relevantes, cada um a começar pelo nome da fonte;
- uma secção final «## A acompanhar» com 2 a 4 temas a vigiar.

Usa apenas o que está nos artigos; não inventes factos.

Artigos:
{articles}
"""

WINDOW_WORDS = [
    "dólar", "euro", "juros", "inflação", "energia", "tecnologia", "banca", "imobiliário",
    "títulos", "petróleo", "mercados", "regulação", "ia", "inteligência artificial",
]


def _pick(user_id: Optional[str], provider: Optional[str], model: Optional[str]) -> Any:
    from api.scraper_ai import pick_provider

    return pick_provider(user_id, provider, model)


def _complete(prompt: str, *, user_id: Optional[str], provider: Optional[str], model: Optional[str], max_tokens: int = 900) -> Dict[str, Any]:
    provider_id, spec, model_id, key = _pick(user_id, provider, model)
    if not provider_id or not spec:
        return {"ok": False, "error": "Nenhum fornecedor de IA configurado. Defina uma chave em Definições → Fornecedores de IA."}
    import asyncio

    from api import cloud_chat

    async def run() -> str:
        return await cloud_chat.complete_answer(
            provider=provider_id,
            spec=spec,
            model=model_id or spec.get("default_model") or "",
            messages=[{"role": "user", "content": prompt}],
            api_key=key,
            temperature=0.2,
            max_tokens=max_tokens,
        )

    try:
        answer = asyncio.run(run())
    except RuntimeError:
        # Já existe um ciclo de eventos (rota async): corre num ciclo próprio.
        import concurrent.futures

        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
            answer = pool.submit(lambda: asyncio.run(run())).result(timeout=180)
    except Exception as exc:
        logger.warning("Digest por IA falhou (%s): %s", provider_id, exc)
        return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}
    text = str(answer or "").strip()
    if not text:
        return {"ok": False, "error": "O modelo não devolveu resposta."}
    return {"ok": True, "digest": text, "ai": {"provider": provider_id, "provider_label": spec.get("label") or provider_id, "model": model_id}}


def digest_article(
    article_id: str,
    *,
    user_id: Optional[str] = None,
    provider: Optional[str] = None,
    model: Optional[str] = None,
    save: bool = True,
) -> Dict[str, Any]:
    """Resume um artigo com IA e guarda o resumo no próprio artigo."""
    try:
        article = store.get_article(article_id)
    except KeyError as exc:
        return {"ok": False, "error": str(exc)}
    prompt = ARTICLE_PROMPT.format(
        source=_article_source(article) or "—",
        title=article.get("title") or "(sem título)",
        text=article_plain_text(article, MAX_DIGEST_INPUT) or "(sem texto)",
    )
    result = _complete(prompt, user_id=user_id, provider=provider, model=model, max_tokens=900)
    if not result.get("ok"):
        return result
    if save:
        store.update_article(article_id, {"digest": result["digest"]})
    return {**result, "article_id": article_id, "title": article.get("title") or ""}


def digest_collection(
    *,
    article_ids: Optional[Sequence[str]] = None,
    feed_id: Optional[str] = None,
    folder_id: Optional[str] = None,
    q: Optional[str] = None,
    unread: Optional[bool] = True,
    limit: int = 12,
    user_id: Optional[str] = None,
    provider: Optional[str] = None,
    model: Optional[str] = None,
) -> Dict[str, Any]:
    """Boletim a partir de vários artigos (por ids ou pelos filtros da lista)."""
    articles: List[Dict[str, Any]] = []
    if article_ids:
        for article_id in list(article_ids)[:limit]:
            try:
                articles.append(store.get_article(article_id))
            except KeyError:
                continue
    else:
        listing = store.list_articles(feed_id=feed_id, folder_id=folder_id, q=q, unread=unread, limit=limit)
        for summary in listing["items"]:
            try:
                articles.append(store.get_article(summary["id"]))
            except KeyError:
                continue
    if not articles:
        return {"ok": False, "error": "Não há artigos para resumir com esses filtros.", "articles": 0}
    blocks: List[str] = []
    for index, article in enumerate(articles, start=1):
        blocks.append(
            "\n".join(
                [
                    f"[{index}] {article.get('title') or '(sem título)'}",
                    f"Fonte: {article.get('feed_title') or ''}",
                    f"Data: {str(article.get('published_at') or '')[:10]}",
                    store.clean_text(article.get("summary") or article.get("content") or article.get("digest"), 1200),
                    "",
                ]
            )
        )
    prompt = DIGEST_PROMPT.format(articles="\n".join(blocks)[:MAX_DIGEST_INPUT])
    result = _complete(prompt, user_id=user_id, provider=provider, model=model, max_tokens=1400)
    if not result.get("ok"):
        return result
    return {
        **result,
        "articles": len(articles),
        "article_ids": [article["id"] for article in articles],
        "markdown": store.digest_markdown(articles, note=result["digest"]),
    }


def save_digest_to_office(markdown: str, *, title: str = "Digest de notícias", author: str = "") -> Dict[str, Any]:
    """Guarda um boletim no Office como relatório."""
    try:
        from api import office_store

        document = office_store.save_document(
            {"title": title, "kind": "relatorio", "markdown": markdown, "tags": ["rss", "digest"], "source": {"kind": "rss", "digest": True}},
            author=author or None,
        )
    except Exception as exc:
        logger.warning("RSS → Office (digest) falhou: %s", exc)
        return {"ok": False, "error": str(exc)}
    return {"ok": True, "document": document, "document_id": document.get("id")}


def trending_terms(limit: int = 8) -> List[Dict[str, Any]]:
    """Palavras-tema mais frequentes nos artigos guardados (painel)."""
    counts: Dict[str, int] = {}
    for article in store.all_articles():
        haystack = f"{article.get('title') or ''} {article.get('summary') or ''}".lower()
        for word in WINDOW_WORDS:
            if word in haystack:
                counts[word] = counts.get(word, 0) + 1
    items = [{"term": term, "articles": count} for term, count in counts.items()]
    items.sort(key=lambda item: (-item["articles"], item["term"]))
    return items[:limit]


def counts(feed_id: Optional[str] = None) -> Dict[str, int]:
    listing = store.list_articles(feed_id=feed_id, limit=1)
    return {"total": listing["total"], "unread": listing["unread"]}


# --------------------------------------------------------------------------
# Exportação (CSV e Markdown)
# --------------------------------------------------------------------------
CSV_COLUMNS: Sequence[tuple] = (
    ("title", "Título"),
    ("feed", "Fonte"),
    ("author", "Autor"),
    ("published_at", "Publicado"),
    ("reading_minutes", "Minutos"),
    ("read", "Lido"),
    ("favorite", "Favorito"),
    ("saved", "Guardado"),
    ("tags", "Etiquetas"),
    ("categories", "Categorias"),
    ("url", "Ligação"),
    ("has_digest", "Tem resumo IA"),
    ("summary", "Resumo"),
    ("digest", "Resumo IA"),
    ("content", "Texto"),
)


def export_articles_csv(rows: Sequence[Dict[str, Any]], *, note: str = "") -> Dict[str, Any]:
    """CSV (separador `;`, BOM, pronto para Excel pt-PT) dos artigos indicados."""
    import csv
    import io

    buffer = io.StringIO()
    writer = csv.writer(buffer, delimiter=";", lineterminator="\n")
    writer.writerow(["# Leitor RSS — IQ OS"])
    writer.writerow(["# Artigos", len(rows)])
    writer.writerow(["# Filtros", note or "todos"])
    writer.writerow(["# Gerado em", store.now()])
    writer.writerow([label for _key, label in CSV_COLUMNS])
    for row in rows:
        writer.writerow([_csv_cell(row.get(key)) for key, _label in CSV_COLUMNS])
    stamp = store.now()[:16].replace("-", "").replace(":", "").replace("T", "_")
    return {
        "filename": f"leitor-rss_{stamp}.csv",
        "content": ("\ufeff" + buffer.getvalue()).encode("utf-8"),
        "media_type": "text/csv; charset=utf-8",
    }


def _csv_cell(value: Any) -> Any:
    if isinstance(value, bool):
        return "sim" if value else "não"
    if value is None:
        return ""
    text = str(value)
    # O Excel corta células muito grandes: o texto completo vai em Markdown.
    return text[:32_000]


def export_articles_markdown(rows: Sequence[Dict[str, Any]], *, title: str = "Leitor RSS — artigos", note: str = "") -> str:
    """Markdown com os artigos completos (título, origem, resumo IA e texto)."""
    lines = [f"# {title}", "", f"_{len(rows)} artigo(s)_{f' · {note}' if note else ''}", ""]
    for row in rows:
        lines.append(f"## [{row.get('title') or '(sem título)'}]({row.get('url') or '#'})")
        details = [str(row.get("feed") or ""), str(row.get("published_at") or "")[:16].replace("T", " ")]
        if row.get("author"):
            details.append(str(row["author"]))
        if row.get("tags"):
            details.append("etiquetas: " + str(row["tags"]))
        lines.append("_" + " · ".join(part for part in details if part) + "_")
        lines.append("")
        if row.get("digest"):
            lines.extend(["### Resumo (IA)", "", str(row["digest"]), ""])
        elif row.get("summary"):
            lines.extend([str(row["summary"]), ""])
        if row.get("content"):
            lines.extend([str(row["content"]), ""])
        lines.extend(["---", ""])
    return "\n".join(lines).strip() + "\n"
