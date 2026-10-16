"""Módulo de notícias (`/news/*`) — recolha para o Elasticsearch e pesquisa.

**Leitura** (público, como o resto da pesquisa):

- `GET  /news/stats`  — volume do índice, tickers, fontes, janela temporal e análise
- `GET  /news/search` — pesquisa livre com filtros e facetas (tickers, fontes, temas,
  sentimentos e dias), calculadas sobre o **mesmo** conjunto filtrado
- `GET  /news/themes` — temas da plataforma (contratação pública, contratos, fundos
  europeus…) com o vocabulário com que filtram as notícias

**Escrita** (requer sessão):

- `POST /news/collect` — vai ao Yahoo buscar notícias por **ticker** e por **tema** e indexa-as
- `POST /news/publish` — cria no blog um **artigo rascunho** a partir de uma notícia
  do índice (a mesma notícia não é publicada duas vezes)

Tudo fica no índice `finance_news`, o mesmo que o sentimento de mercado, a Pesquisa
total e o RAG usam: recolher aqui alimenta também esses módulos.

Nota de custo: por ticker a notícia é enriquecida com o NLP completo (sentimento,
tradução PT, tópicos e entidades), que é lento porque traduz os títulos. Por tema
usa-se o léxico bilingue imediato — mais rápido e sem tradução — e é isso que o
campo `analyzed_at` deixa à vista.
"""
from __future__ import annotations

import asyncio
import logging
import re
from types import SimpleNamespace
from typing import Annotated, Any, Dict, List, Optional

from fastapi import APIRouter, Body, Depends, HTTPException, Query

from api import cms_store
from api import news_themes
from api import news_traducao
from api import sentiment_market as market
from api.auth_routes import CurrentSession, optional_session
from api.elasticsearch_client import (
    get_news_item,
    index_analyzed_news_items,
    index_news_items,
    news_stats,
    save_news_translation,
    search_all_news,
)
from api.tools import search_news_terms

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/news", tags=["news"])

Session = Annotated[Optional[CurrentSession], Depends(optional_session)]

MAX_COLLECT_TICKERS = 12
MAX_COLLECT_TOPICS = 6

#: Campos da notícia que o editor pode corrigir no pedido de publicação: o que
#: vier no corpo do pedido sobrepõe-se ao que está no índice.
CAMPOS_EDITAVEIS = (
    "title",
    "translated_title",
    "summary",
    "summary_pt",
    "translated_summary",
    "publisher",
    "published",
    "url",
    "sentiment",
    "ticker",
    "language",
)

#: Limites de SEO do artigo (o blog acrescenta o nome da marca ao título).
LIMITE_TITULO_SEO = 60
LIMITE_DESCRICAO_SEO = 160


def _text(value: Any) -> Optional[str]:
    """Texto de um parâmetro (qualquer outra coisa = «sem valor»)."""
    return value.strip() if isinstance(value, str) and value.strip() else None


def _clamp(value: Any, minimum: int, maximum: int, fallback: int) -> int:
    try:
        number = int(value)
    except (TypeError, ValueError):
        return fallback
    return max(minimum, min(maximum, number))


def _topic_analysis(item: Dict[str, Any]) -> SimpleNamespace:
    """Enriquecimento mínimo e imediato de uma notícia recolhida por tema.

    Usa o léxico bilingue (PT/EN) do `news_nlp` em vez do pipeline completo: sem
    tradução, a recolha de temas fica utilizável em segundos em vez de minutos, e
    a etiqueta de sentimento continua a poder filtrar-se na pesquisa.
    """
    from api.news_nlp import keyword_sentiment

    verdict = keyword_sentiment(f"{item.get('title') or ''} {item.get('summary') or ''}")
    return SimpleNamespace(
        sentiment=verdict["label"],
        language=None,
        translated_title=None,
        translated_summary=None,
        summary_pt=None,
        topics=[],
        entities=[],
    )


@router.get("/stats")
def news_index_stats() -> Dict[str, Any]:
    """Panorama do índice de notícias (volume, tickers, fontes, janela e análise)."""
    return news_stats()


@router.get("/themes")
def news_theme_catalogue() -> Dict[str, Any]:
    """Temas da plataforma — o vocabulário com que as notícias se filtram.

    São os assuntos que a plataforma cobre (contratação pública, contratos,
    fundos europeus, subvenções, insolvências, Administração Pública, empresas e
    fiscalidade). O catálogo é fixo (vive em `api/news_themes.py`): o que a
    interface mostra em botões é exatamente o que a pesquisa filtra.
    """
    items = news_themes.list_themes()
    return {"total": len(items), "items": items}


@router.get("/search")
def news_search(
    q: Optional[str] = Query(None, description="Texto livre (título, resumo, fonte, temas)."),
    tickers: Optional[str] = Query(None, description="Tickers separados por vírgula."),
    topic: Optional[str] = Query(None, description="Tema exato com que a notícia foi recolhida."),
    theme: Optional[str] = Query(None, description="Tema da plataforma (ver `/news/themes`)."),
    publisher: Optional[str] = Query(None, description="Fonte (publicador)."),
    sentiment: Optional[str] = Query(None, pattern="^(positivo|negativo|neutro)$"),
    start: Optional[str] = Query(None, description="Data inicial (YYYY-MM-DD)."),
    end: Optional[str] = Query(None, description="Data final (YYYY-MM-DD)."),
    analyzed: Optional[bool] = Query(None, description="Só com (true) ou sem (false) análise NLP."),
    sort: str = Query("recent", pattern="^(recent|oldest|relevance)$"),
    page: int = Query(1, ge=1, le=500),
    size: int = Query(20, ge=1, le=100),
) -> Dict[str, Any]:
    """Pesquisa nas notícias indexadas, com facetas sobre o mesmo filtro.

    Com `theme`, a pesquisa fica limitada às expressões desse tema (e ao tema
    exato com que a notícia foi recolhida); as facetas passam a incluir
    `themes` — a contagem de **todos** os temas da plataforma, calculada sem o
    filtro do tema ativo, para se poder saltar de um para o outro.
    """
    codes = [part.strip() for part in (tickers or "").replace(";", ",").split(",") if part.strip()]
    chosen = None
    if _text(theme):
        chosen = news_themes.get_theme(theme)
        if not chosen:
            raise HTTPException(
                status_code=422,
                detail=f"Tema «{theme}» não existe. Válidos: {', '.join(news_themes.theme_ids())}.",
            )
    return search_all_news(
        q=_text(q),
        tickers=codes,
        topic=_text(topic),
        publisher=_text(publisher),
        sentiment=_text(sentiment),
        start_date=_text(start),
        end_date=_text(end),
        analyzed=analyzed,
        theme_terms=news_themes.match_terms(chosen["id"]) if chosen else None,
        theme_buckets=news_themes.theme_buckets(),
        sort=sort,
        page=page,
        size=size,
    )


@router.post("/collect")
async def news_collect(payload: Dict[str, Any] = Body(default={}), session: Session = None) -> Dict[str, Any]:
    """Recolhe notícias do Yahoo para o Elasticsearch (por ticker e por tema).

    Sem `tickers` nem `topics`, recolhe para os **favoritos** guardados no painel
    de mercado — é o caminho normal: marcar os ativos que interessam e mandar
    recolher. Cada alvo devolve o que correu mal, se algo correr mal.
    """
    if not session:
        raise HTTPException(status_code=401, detail="Entrar na plataforma para recolher notícias.")

    raw_tickers = payload.get("tickers") or []
    if isinstance(raw_tickers, str):
        raw_tickers = raw_tickers.replace(";", ",").split(",")
    raw_topics = payload.get("topics") or []
    if isinstance(raw_topics, str):
        raw_topics = raw_topics.split(",")
    max_items = _clamp(payload.get("max_items"), 5, 50, 20)

    tickers: List[str] = []
    for candidate in raw_tickers:
        try:
            code = market.normalise_ticker(str(candidate))
        except KeyError:
            continue
        if code not in tickers:
            tickers.append(code)
    topics = [str(item).strip() for item in raw_topics if str(item).strip()]

    if not tickers and not topics:
        tickers = market.watchlist()[:MAX_COLLECT_TICKERS]
    if not tickers and not topics:
        raise HTTPException(
            status_code=422,
            detail="Indique tickers ou temas (ou guarde favoritos no painel de mercado).",
        )
    tickers = tickers[:MAX_COLLECT_TICKERS]
    topics = topics[:MAX_COLLECT_TOPICS]

    from api.elasticsearch_ingest import ingest_ticker_news

    results: List[Dict[str, Any]] = []
    indexed_total = 0
    analyzed_total = 0

    for code in tickers:
        try:
            outcome = await ingest_ticker_news(code)
            indexed = int(getattr(outcome, "indexed_count", 0) or 0)
            analyzed = int(getattr(outcome, "analyzed_count", 0) or 0)
            indexed_total += indexed
            analyzed_total += analyzed
            results.append(
                {
                    "target": code,
                    "kind": "ticker",
                    "indexed": indexed,
                    "total": int(getattr(outcome, "total_items", 0) or 0),
                    "analyzed": analyzed,
                    "error": getattr(outcome, "error", None),
                }
            )
        except Exception as exc:  # noqa: BLE001 - um alvo falhado não pode parar a recolha
            logger.warning("Recolha de notícias de %s falhou: %s", code, exc)
            results.append(
                {"target": code, "kind": "ticker", "indexed": 0, "total": 0, "analyzed": 0, "error": str(exc)}
            )

    for term in topics:
        try:
            items = await asyncio.to_thread(search_news_terms, term, max_items)
            if not items:
                results.append(
                    {
                        "target": term,
                        "kind": "topic",
                        "indexed": 0,
                        "total": 0,
                        "analyzed": 0,
                        "error": (
                            f"O Yahoo não devolveu notícias para «{term}». A pesquisa de notícias do Yahoo "
                            "liga os termos a empresas e ativos: funciona bem com nomes («Galp», «edp») ou "
                            "termos em inglês («renewable energy»), e devolve zero em expressões genéricas."
                        ),
                    }
                )
                continue
            stored = await asyncio.to_thread(index_news_items, "", items, None, term)
            verdicts = [_topic_analysis(item) for item in items]
            analyzed = int(
                (await asyncio.to_thread(index_analyzed_news_items, "", items, verdicts, None, term)).get("indexed_count")
                or 0
            )
            indexed = int(stored.get("indexed_count") or 0)
            indexed_total += indexed
            analyzed_total += analyzed
            results.append(
                {
                    "target": term,
                    "kind": "topic",
                    "indexed": indexed,
                    "total": int(stored.get("total_items") or 0),
                    "analyzed": analyzed,
                    "error": stored.get("error"),
                }
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("Recolha de notícias do tema «%s» falhou: %s", term, exc)
            results.append(
                {"target": term, "kind": "topic", "indexed": 0, "total": 0, "analyzed": 0, "error": str(exc)}
            )

    return {
        "ok": not [item for item in results if item.get("error")],
        "tickers": tickers,
        "topics": topics,
        "max_items": max_items,
        "indexed": indexed_total,
        "analyzed": analyzed_total,
        "results": results,
        "stats": news_stats(),
    }


@router.post("/{news_id}/traduzir")
def news_translate(
    news_id: str,
    payload: Dict[str, Any] = Body(default_factory=dict),
    session: Session = None,
) -> Dict[str, Any]:
    """Traduz a notícia para PT com o **fornecedor de IA configurado**.

    Traduz o título e o resumo (o que a notícia não tiver já em português) e, por
    omissão, guarda-os na ficha da notícia — a partir daí o cartão mostra a
    tradução e a pesquisa encontra-a, sem repetir a chamada ao modelo (a cache é
    persistente). Sem fornecedor configurado responde 409 com a instrução para o
    definir: nunca devolve o original a passar por tradução.
    """
    if not session:
        raise HTTPException(status_code=401, detail="Entrar na plataforma para traduzir notícias.")
    noticia = get_news_item(news_id)
    if not noticia:
        raise HTTPException(status_code=404, detail="Notícia não encontrada no índice.")

    resultado = news_traducao.traduzir_noticia(
        noticia,
        user_id=getattr(session.user, "id", None) or session.user.email,
        provider=_text(payload.get("provider")),
        model=_text(payload.get("model")),
    )
    if resultado.get("error"):
        raise HTTPException(status_code=409, detail=resultado["error"])

    guardada = False
    if payload.get("guardar", True):
        guardada = save_news_translation(
            news_id,
            title=resultado.get("titulo"),
            summary=resultado.get("resumo"),
        )
    return {
        "id": news_id,
        **resultado,
        "guardada": guardada,
        "resumo_curto": (
            f"Notícia traduzida para português ({resultado.get('ia', {}).get('provider_label') or 'IA'})."
            if resultado.get("traduzido")
            else "A notícia já estava em português."
        ),
    }


# ==========================================================================
# Publicar uma notícia como artigo de blog
# ==========================================================================
def _noticia_do_pedido(payload: Dict[str, Any]) -> Dict[str, Any]:
    """A notícia do índice (quando o pedido traz o `id`) com as correções do editor.

    O cartão da interface traz o `id` da notícia, pelo que o pedido pode limitar-se
    a ele; os campos que o editor escrever no corpo do pedido sobrepõem-se ao que
    está indexado — é a mesma liberdade que o blog dá a qualquer artigo.
    """
    news_id = _text(payload.get("id"))
    noticia: Dict[str, Any] = (get_news_item(news_id) or {}) if news_id else {}
    if news_id:
        noticia.setdefault("id", news_id)
    merged = dict(noticia)
    for field in CAMPOS_EDITAVEIS:
        value = payload.get(field)
        if isinstance(value, str) and value.strip():
            merged[field] = value.strip()
    topics = payload.get("topics")
    if isinstance(topics, list) and topics:
        merged["topics"] = [str(item).strip() for item in topics if str(item).strip()]
    return merged


def _etiquetas_da_noticia(payload: Dict[str, Any], noticia: Dict[str, Any], tema: Optional[Dict[str, Any]]) -> List[str]:
    """Etiquetas do artigo: as do editor, ou as que a notícia sugere.

    A última é sempre a **marca da notícia** (`noticia-<id>`): é por ela que a
    publicação reconhece o que já foi publicado, para a mesma notícia não dar
    dois artigos.
    """
    explicitas = payload.get("tags")
    if isinstance(explicitas, str):
        explicitas = _dividir_etiquetas(explicitas)
    tags: List[str] = []
    if isinstance(explicitas, list):
        tags = [str(item).strip() for item in explicitas if str(item).strip()]
    if not tags:
        for value in (noticia.get("publisher"), noticia.get("ticker")):
            text = _text(value)
            if text and text not in tags:
                tags.append(text)
        for value in news_themes.suggested_tags(tema["id"] if tema else None):
            if value not in tags:
                tags.append(value)
        for value in noticia.get("topics") or []:
            text = _text(value)
            if text and text not in tags:
                tags.append(text)
    marca = _marca_da_noticia(noticia, payload)
    if marca and marca not in tags:
        tags.append(marca)
    return tags[:20]


def _dividir_etiquetas(value: str) -> List[str]:
    """Divide uma lista de etiquetas escrita à mão (`a, b; c`)."""
    return [part.strip() for part in str(value or "").replace(";", ",").split(",") if part.strip()]


def _marca_da_noticia(noticia: Dict[str, Any], payload: Dict[str, Any]) -> str:
    """Etiqueta que identifica a notícia de origem (`""` quando não há `id`)."""
    news_id = _text(noticia.get("id")) or _text(payload.get("id"))
    if not news_id:
        return ""
    return f"noticia-{news_id}"[:120]


def _palavras_chave_da_noticia(noticia: Dict[str, Any], tema: Optional[Dict[str, Any]]) -> List[str]:
    """Palavras-chave do artigo para os motores de busca.

    Saem da própria notícia — fonte, ticker e tópicos do NLP — e do tema da
    plataforma que o editor escolheu. São as que ainda não estão no título (uma
    palavra-chave repetida não acrescenta nada a quem procura).
    """
    candidatos: List[str] = []
    for valor in (
        noticia.get("publisher"),
        noticia.get("ticker"),
        *(noticia.get("topics") or []),
        *news_themes.suggested_tags(tema["id"] if tema else None),
    ):
        texto = _text(valor)
        if texto and texto not in candidatos:
            candidatos.append(texto)
    return candidatos[:8]


def _cortar_em_palavras(texto: str, limite: int) -> str:
    """Corta um texto no limite **sem partir palavras** (para título/descrição SEO)."""
    limpo = re.sub(r"\s+", " ", str(texto or "")).strip()
    if len(limpo) <= limite:
        return limpo
    corte = limpo[:limite].rsplit(" ", 1)[0].rstrip(" ,;:.-–—")
    return f"{corte}…" if corte else limpo[:limite]


def _artigo_da_noticia(
    noticia: Dict[str, Any],
    payload: Dict[str, Any],
    tema: Optional[Dict[str, Any]],
) -> Dict[str, Any]:
    """Rascunho do artigo de blog a partir de uma notícia (título, resumo e fonte).

    O que se publica é a **notícia**, não o índice: o corpo traz o resumo em
    português (quando existe), o crédito da fonte com a ligação para o original e
    uma nota de rascunho com o rasto da plataforma (tema, tom e ticker). O texto
    e o título são editáveis no blog como em qualquer artigo — isto são os
    valores de partida.
    """
    titulo_original = _text(noticia.get("title")) or ""
    titulo = (
        _text(payload.get("title"))
        or _text(noticia.get("translated_title"))
        or titulo_original
        or "Notícia sem título"
    )
    resumo = (
        _text(payload.get("excerpt"))
        or _text(noticia.get("summary_pt"))
        or _text(noticia.get("translated_summary"))
        or _text(noticia.get("summary"))
        or ""
    )
    fonte = _text(noticia.get("publisher"))
    url = _text(noticia.get("url"))
    dia = (_text(noticia.get("published")) or "")[:10]
    ticker = _text(noticia.get("ticker"))
    tom = _text(noticia.get("sentiment"))

    paragrafos: List[str] = []
    if resumo:
        paragrafos += [resumo, ""]
    credito = " · ".join(part for part in (fonte, dia) if part)
    if url:
        paragrafos.append((f"**Fonte:** {credito} — " if credito else "") + f"[ler a notícia original]({url})")
    elif credito:
        paragrafos.append(f"**Fonte:** {credito}")
    rasto = [
        texto
        for texto in (
            f"tema «{tema['label']}»" if tema else "",
            f"tom {tom}" if tom else "",
            f"ticker {ticker}" if ticker else "",
        )
        if texto
    ]
    nota = "_Rascunho criado a partir de uma notícia do índice `finance_news`"
    nota += f" ({'; '.join(rasto)})" if rasto else ""
    nota += ". Revise o texto e acrescente a análise antes de publicar._"
    paragrafos += ["", nota]

    corpo = _text(payload.get("markdown")) or "\n".join(paragrafos)
    return {
        "title": titulo,
        "slug": _text(payload.get("slug")) or news_themes.slugify(titulo, limit=64),
        "status": "rascunho",
        "excerpt": resumo or titulo,
        "markdown": corpo,
        "tags": _etiquetas_da_noticia(payload, noticia, tema),
        # SEO: o título do artigo tem de caber no que os motores de busca mostram
        # (o site acrescenta o nome da marca) e a descrição é o resumo cortado em
        # palavras. As palavras-chave vêm da notícia e do tema escolhido.
        "seo": {
            "title": _cortar_em_palavras(titulo, LIMITE_TITULO_SEO),
            "description": _cortar_em_palavras(resumo or titulo, LIMITE_DESCRICAO_SEO),
            "keywords": _palavras_chave_da_noticia(noticia, tema),
        },
    }


def _categorias_do_artigo(payload: Dict[str, Any], tema: Optional[Dict[str, Any]]) -> List[str]:
    """Categorias do artigo: as do editor, ou a que o tema sugere (quando existe)."""
    explicitas = payload.get("category_ids")
    if isinstance(explicitas, list):
        ids = [str(item).strip() for item in explicitas if str(item).strip()]
        if ids:
            return ids
    slug = news_themes.suggested_category(tema["id"] if tema else None)
    if not slug:
        return []
    categoria = cms_store.category_by_slug(slug)
    return [str(categoria["id"])] if categoria and categoria.get("id") else []


def _artigo_existente(marca: str) -> Optional[Dict[str, Any]]:
    """O artigo já criado a partir desta notícia (`None` se ainda não houver)."""
    if not marca:
        return None
    try:
        encontrados = cms_store.list_items("posts", tag=marca, limit=1, with_blocks=False)
    except Exception as exc:  # noqa: BLE001 - a falta de CMS não impede ver o erro no log
        logger.warning("Não foi possível verificar publicações anteriores: %s", exc)
        return None
    items = encontrados.get("items") or []
    return items[0] if items else None


@router.post("/publish")
def news_publish(payload: Dict[str, Any] = Body(default_factory=dict), session: Session = None) -> Dict[str, Any]:
    """Publica uma notícia do índice como **artigo de blog** (rascunho).

    O artigo nasce **rascunho** — publica-se no editor do blog — com o título, o
    resumo e a fonte da notícia, as etiquetas do tema e a ligação para o
    original. A mesma notícia não dá dois artigos: a segunda tentativa devolve o
    artigo que já existe (`duplicado: true`), e a interface liga para lá.

    Basta o `id` da notícia (é o que o cartão da lista traz); os campos escritos
    no pedido — `title`, `excerpt`, `markdown`, `tags`, `category_ids` — passam à
    frente do que está indexado.
    """
    if not session:
        raise HTTPException(status_code=401, detail="Entrar na plataforma para publicar notícias no blog.")
    author = session.user.email

    tema = None
    if _text(payload.get("theme")):
        tema = news_themes.get_theme(payload.get("theme"))
        if not tema:
            raise HTTPException(
                status_code=422,
                detail=f"Tema «{payload.get('theme')}» não existe. Válidos: {', '.join(news_themes.theme_ids())}.",
            )

    noticia = _noticia_do_pedido(payload)
    if not (noticia.get("title") or noticia.get("translated_title") or _text(payload.get("title"))):
        raise HTTPException(
            status_code=422,
            detail="Indique a notícia (`id`) ou, no mínimo, o título do artigo.",
        )

    # Tradução: o artigo nasce em português sem o editor ter de pedir a tradução
    # primeiro. Só acontece quando a notícia ainda não tem texto em PT (o NLP da
    # recolha já traduz as notícias de ticker) e nunca impede a publicação — se o
    # fornecedor de IA falhar, o artigo sai com o original e o aviso.
    traducao: Dict[str, Any] = {}
    if payload.get("traduzir", True):
        traducao = news_traducao.traduzir_noticia(
            noticia,
            user_id=getattr(session.user, "id", None) or session.user.email,
            provider=_text(payload.get("provider")),
            model=_text(payload.get("model")),
        )
        if not traducao.get("error"):
            novo_titulo = str(traducao.get("titulo") or "").strip()
            novo_resumo = str(traducao.get("resumo") or "").strip()
            ja_tinha = novo_titulo == str(noticia.get("translated_title") or "").strip() and novo_resumo == str(
                noticia.get("translated_summary") or ""
            ).strip()
            noticia = {**noticia, "translated_title": novo_titulo, "translated_summary": novo_resumo}
            if traducao.get("ia") and not ja_tinha:
                save_news_translation(noticia.get("id"), title=novo_titulo, summary=novo_resumo)

    marca = _marca_da_noticia(noticia, payload)
    existente = _artigo_existente(marca)
    if existente:
        return {
            "saved": False,
            "duplicado": True,
            "artigo": existente,
            "url": f"/cms/blog?id={existente['id']}",
            "resumo": f"A notícia já tinha sido publicada como «{existente.get('title')}» (rascunho no blog).",
        }

    corpo = _artigo_da_noticia(noticia, payload, tema)
    corpo["category_ids"] = _categorias_do_artigo(payload, tema)
    corpo["author"] = author
    try:
        artigo = cms_store.save_item("posts", corpo, author)
    except (ValueError, KeyError) as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    return {
        "saved": True,
        "duplicado": False,
        "artigo": artigo,
        "url": f"/cms/blog?id={artigo['id']}",
        "tema": tema["id"] if tema else None,
        "traduzido": bool(traducao.get("traduzido")),
        "ia": traducao.get("ia") or {},
        "aviso": traducao.get("error") or "",
        "resumo": f"Notícia publicada como artigo «{artigo['title']}» (rascunho no blog).",
    }
