"""Módulo de notícias (`/news/*`) — recolha para o Elasticsearch e pesquisa.

**Leitura** (público, como o resto da pesquisa):

- `GET  /news/stats`  — volume do índice, tickers, fontes, janela temporal e análise
- `GET  /news/search` — pesquisa livre com filtros e facetas (tickers, fontes, temas,
  sentimentos e dias), calculadas sobre o **mesmo** conjunto filtrado

**Escrita** (requer sessão — a recolha escreve no índice):

- `POST /news/collect` — vai ao Yahoo buscar notícias por **ticker** e por **tema** e indexa-as

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
from types import SimpleNamespace
from typing import Annotated, Any, Dict, List, Optional

from fastapi import APIRouter, Body, Depends, HTTPException, Query

from api import sentiment_market as market
from api.auth_routes import CurrentSession, optional_session
from api.elasticsearch_client import (
    index_analyzed_news_items,
    index_news_items,
    news_stats,
    search_all_news,
)
from api.tools import search_news_terms

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/news", tags=["news"])

Session = Annotated[Optional[CurrentSession], Depends(optional_session)]

MAX_COLLECT_TICKERS = 12
MAX_COLLECT_TOPICS = 6


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


@router.get("/search")
def news_search(
    q: Optional[str] = Query(None, description="Texto livre (título, resumo, fonte, temas)."),
    tickers: Optional[str] = Query(None, description="Tickers separados por vírgula."),
    topic: Optional[str] = Query(None, description="Tema exato com que a notícia foi recolhida."),
    publisher: Optional[str] = Query(None, description="Fonte (publicador)."),
    sentiment: Optional[str] = Query(None, pattern="^(positivo|negativo|neutro)$"),
    start: Optional[str] = Query(None, description="Data inicial (YYYY-MM-DD)."),
    end: Optional[str] = Query(None, description="Data final (YYYY-MM-DD)."),
    analyzed: Optional[bool] = Query(None, description="Só com (true) ou sem (false) análise NLP."),
    sort: str = Query("recent", pattern="^(recent|oldest|relevance)$"),
    page: int = Query(1, ge=1, le=500),
    size: int = Query(20, ge=1, le=100),
) -> Dict[str, Any]:
    """Pesquisa nas notícias indexadas, com facetas sobre o mesmo filtro."""
    codes = [part.strip() for part in (tickers or "").replace(";", ",").split(",") if part.strip()]
    return search_all_news(
        q=_text(q),
        tickers=codes,
        topic=_text(topic),
        publisher=_text(publisher),
        sentiment=_text(sentiment),
        start_date=_text(start),
        end_date=_text(end),
        analyzed=analyzed,
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
