"""Preços, notícias, tickers e traduções (mercado acionista).

Módulo do pacote :mod:`api.es` — ver `api/elasticsearch_client.py`,
que continua a expor a API pública (os coletores/serviços importam de lá).
"""
import logging
from datetime import datetime
from typing import Any, Dict, List, Optional

from elasticsearch import Elasticsearch, NotFoundError
from elasticsearch.helpers import bulk
from api.es.core import _as_float, _as_int, _slug, _today, get_es_client
from api.es.mappings import ensure_indices

logger = logging.getLogger(__name__)




def index_price_points(ticker: str, points: List[Dict[str, Any]], period: str = "1y", es: Optional[Elasticsearch] = None) -> Dict[str, Any]:
    """Indexa pontos de preço no Elasticsearch.

    Args:
        ticker: símbolo normalizado do ticker.
        points: lista de dicts com date, open, high, low, close, volume.
        period: período de onde os dados vieram.
        es: cliente Elasticsearch opcional.

    Returns:
        dict com ticker, indexed_count, total_points.
    """
    client = es or get_es_client()
    if not client:
        return {"ticker": ticker, "error": "Elasticsearch indisponível", "indexed_count": 0}

    ensure_indices(client)
    ticker = ticker.upper()
    actions = []
    sem_data = 0
    for p in points:
        # Uma linha sem `date` não é um ponto da série: o histórico já veio vazio
        # (tudo a `null`) e ficava indexada como `_id="TICKER-None"` — um documento
        # «stub» que depois fazia rebentar quem o lesse (o modelo exige `date`).
        if not p.get("date"):
            sem_data += 1
            continue
        doc = {
            "_op_type": "index",
            "_index": "finance_prices",
            "_id": f"{ticker}-{p.get('date')}",
            "ticker": ticker,
            "date": p.get("date"),
            "open": _as_float(p.get("open")),
            "high": _as_float(p.get("high")),
            "low": _as_float(p.get("low")),
            "close": _as_float(p.get("close")),
            "volume": _as_int(p.get("volume")),
            "period": period,
            "ingested_at": _today(),
        }
        actions.append(doc)

    if sem_data:
        logger.warning("finance_prices: %d ponto(s) de %s sem `date` ignorados", sem_data, ticker)

    if not actions:
        return {"ticker": ticker, "indexed_count": 0, "total_points": 0}

    try:
        success, errors = bulk(client, actions, raise_on_error=False, refresh=True)
        return {"ticker": ticker, "indexed_count": success, "total_points": len(actions), "errors": len(errors)}
    except Exception as e:
        return {"ticker": ticker, "error": str(e), "indexed_count": 0, "total_points": len(actions)}




def index_news_items(
    ticker: str,
    items: List[Dict[str, Any]],
    es: Optional[Elasticsearch] = None,
    topic: Optional[str] = None,
) -> Dict[str, Any]:
    """Indexa notícias no Elasticsearch.

    Args:
        ticker: símbolo normalizado do ticker ("" quando a recolha é por **tema**).
        items: lista de notícias com title, summary, publisher, published, url.
        es: cliente Elasticsearch opcional.
        topic: termo de pesquisa livre que trouxe a notícia (ex.: «obras públicas»).

    Returns:
        dict com ticker, indexed_count, total_items.
    """
    client = es or get_es_client()
    if not client:
        return {"ticker": ticker, "error": "Elasticsearch indisponível", "indexed_count": 0}

    ensure_indices(client)
    ticker = ticker.upper()
    topic = _topic_key(topic)
    actions = []
    for i, item in enumerate(items):
        published = item.get("published") or item.get("pubDate")
        if published and isinstance(published, datetime):
            published = published.isoformat()
        doc_id = _news_doc_id(ticker, topic, item, i)
        doc = {
            "_op_type": "index",
            "_index": "finance_news",
            "_id": doc_id,
            "ticker": ticker,
            "topic": topic,
            "title": item.get("title") or item.get("summary"),
            "summary": item.get("summary") or item.get("title"),
            "publisher": item.get("publisher") or item.get("provider"),
            "published": published,
            "url": item.get("url") or item.get("link"),
            "source": item.get("source", "yfinance"),
            "ingested_at": _today(),
        }
        actions.append(doc)

    if not actions:
        return {"ticker": ticker, "indexed_count": 0, "total_items": 0,
                "topic": topic, "errors": 0}

    try:
        success, errors = bulk(client, actions, raise_on_error=False, refresh=True)
        return {
            "ticker": ticker,
            "topic": topic,
            "indexed_count": success,
            "total_items": len(actions),
            "errors": len(errors),
        }
    except Exception as e:
        return {"ticker": ticker, "topic": topic, "error": str(e), "indexed_count": 0, "total_items": len(actions)}




def _topic_key(topic: Optional[str]) -> Optional[str]:
    """Chave do tema: minúsculas e sem espaços nas pontas.

    Normalizar na **escrita** é o que permite à pesquisa casar o tema por igualdade
    exata (`term`) sem depender de analisadores nem de `case_insensitive`, que nem
    todas as versões do Elasticsearch suportam.
    """
    text = str(topic or "").strip().lower()
    return text or None




def _news_doc_id(ticker: str, topic: Optional[str], item: Dict[str, Any], index: int) -> str:
    """Id do documento de notícia — o **mesmo** na indexação e na análise.

    Ticker vazio significa recolha por tema (a notícia não é de nenhum ativo):
    nesse caso o prefixo é o tema, para duas recolhas não colidirem.
    """
    code = str(ticker or "").upper()
    label = code or (f"tema-{_slug(topic)}" if topic else "noticias")
    return f"{label}-{_news_id(item, index)}"




def _news_id(item: Dict[str, Any], index: int) -> str:
    """Gera ID estável para uma notícia baseada no URL ou no conteúdo."""
    import hashlib
    url = item.get("url") or item.get("link") or ""
    if url:
        return hashlib.md5(url.encode("utf-8")).hexdigest()[:20]
    content = (item.get("title") or "") + (item.get("summary") or "") + str(index)
    return hashlib.md5(content.encode("utf-8")).hexdigest()[:20]




def search_prices(
    ticker: str,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    size: int = 1000,
    es: Optional[Elasticsearch] = None,
) -> Dict[str, Any]:
    """Pesquisa preços de um ticker por intervalo de datas."""
    client = es or get_es_client()
    if not client:
        return {"ticker": ticker, "error": "Elasticsearch indisponível", "points": []}

    query: Dict[str, Any] = {
        "bool": {
            "must": [
                {"term": {"ticker": ticker.upper()}},
                # Documentos «stub» (tudo a `null`, sem `date`) existem no índice, de
                # ingestões que não trouxeram dados. Não são pontos de série e
                # faziam a rota rebentar na validação da resposta (o modelo exige
                # `date`). Excluem-se na consulta, para o `total` bater certo com o
                # que se devolve.
                {"exists": {"field": "date"}},
            ]
        }
    }
    range_filter = {}
    if start_date:
        range_filter["gte"] = start_date
    if end_date:
        range_filter["lte"] = end_date
    if range_filter:
        query["bool"]["filter"] = [{"range": {"date": range_filter}}]

    try:
        resp = client.search(
            index="finance_prices",
            body={
                "query": query,
                "sort": [{"date": {"order": "asc"}}],
                "size": size,
            },
        )
        points = [hit["_source"] for hit in resp["hits"]["hits"]]
        # Rede de segurança: um cliente/índice que devolva o documento sem `date`
        # (apesar do filtro) não pode voltar a derrubar a rota.
        usaveis = [ponto for ponto in points if ponto.get("date")]
        if len(usaveis) != len(points):
            logger.warning(
                "finance_prices: %d documento(s) de %s sem `date` ignorados na leitura",
                len(points) - len(usaveis),
                ticker.upper(),
            )
        return {
            "ticker": ticker.upper(),
            # `total` continua a ser o que o índice diz que casa (paginação), mesmo
            # que a rede de segurança acima tenha deixado algum ponto de fora.
            "total": resp["hits"]["total"]["value"],
            "points": usaveis,
            "start_date": start_date,
            "end_date": end_date,
        }
    except Exception as e:
        return {"ticker": ticker.upper(), "error": str(e), "points": []}




def search_news(
    ticker: str,
    q: Optional[str] = None,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    size: int = 50,
    es: Optional[Elasticsearch] = None,
) -> Dict[str, Any]:
    """Pesquisa notícias por ticker e texto opcional."""
    client = es or get_es_client()
    if not client:
        return {"ticker": ticker, "error": "Elasticsearch indisponível", "items": []}

    must: List[Dict[str, Any]] = [{"term": {"ticker": ticker.upper()}}]
    if q:
        must.append({
            "multi_match": {
                "query": q,
                "fields": ["title^2", "summary", "publisher"],
                "type": "best_fields",
                # Sem isto, uma pesquisa de duas palavras devolvia notícias que
                # casavam só uma delas.
                "operator": "and",
            }
        })

    query: Dict[str, Any] = {"bool": {"must": must}}
    range_filter = {}
    if start_date:
        range_filter["gte"] = start_date
    if end_date:
        range_filter["lte"] = end_date
    if range_filter:
        query["bool"]["filter"] = [{"range": {"published": range_filter}}]

    try:
        resp = client.search(
            index="finance_news",
            body={
                "query": query,
                "sort": [{"published": {"order": "desc"}}, "_score"],
                "size": size,
            },
        )
        items = [hit["_source"] for hit in resp["hits"]["hits"]]
        return {
            "ticker": ticker.upper(),
            "total": resp["hits"]["total"]["value"],
            "items": items,
        }
    except Exception as e:
        return {"ticker": ticker.upper(), "error": str(e), "items": []}




def _news_terms(aggregations: Dict[str, Any], name: str) -> List[Dict[str, Any]]:
    """Buckets de uma agregação de termos, sem chaves vazias (notícias só por tema)."""
    buckets = ((aggregations.get(name) or {}).get("buckets")) or []
    return [
        {"value": bucket.get("key"), "count": int(bucket.get("doc_count") or 0)}
        for bucket in buckets
        if bucket.get("key") not in (None, "")
    ]




# Campos por onde a pesquisa livre procura (o `^n` é o peso de cada um).
NEWS_SEARCH_FIELDS = [
    "title^3",
    "translated_title^3",
    "summary^2",
    "summary_pt^2",
    "translated_summary",
    "publisher^2",
    "topics^2",
    "entities.name^2",
]




def _news_theme_clause(terms: List[str]) -> Optional[Dict[str, Any]]:
    """Notícias que falam de **um tema da plataforma**.

    Cada expressão do tema (``api.news_themes``) é procurada nos mesmos campos da
    pesquisa livre, com **todas as palavras obrigatórias** (`operator: and`), e
    também no **tema exato** com que a notícia foi recolhida — é o que faz
    aparecer uma notícia recolhida por «contratação pública» mesmo quando o
    título não repete as palavras.

    Sem expressões (ou só vazias) devolve `None`: o tema não filtra nada.
    """
    should: List[Dict[str, Any]] = []
    for term in terms or []:
        text = str(term or "").strip()
        if not text:
            continue
        should.append(
            {
                "multi_match": {
                    "query": text,
                    "fields": NEWS_SEARCH_FIELDS,
                    "type": "best_fields",
                    "operator": "and",
                    "lenient": True,
                }
            }
        )
        should.append({"term": {"topic": text.lower()}})
    if not should:
        return None
    return {"bool": {"should": should, "minimum_should_match": 1}}





def search_all_news(
    q: Optional[str] = None,
    tickers: Optional[List[str]] = None,
    publisher: Optional[str] = None,
    topic: Optional[str] = None,
    sentiment: Optional[str] = None,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    analyzed: Optional[bool] = None,
    theme_terms: Optional[List[str]] = None,
    theme_buckets: Optional[List[Dict[str, Any]]] = None,
    sort: str = "recent",
    page: int = 1,
    size: int = 20,
    es: Optional[Elasticsearch] = None,
) -> Dict[str, Any]:
    """Pesquisa nas notícias indexadas — **todas**, não só as de um ticker.

    Devolve a página pedida e as facetas (tickers, fontes, sentimentos, temas e
    dias) calculadas sobre o **mesmo** conjunto filtrado, para os números dos
    filtros corresponderem sempre ao que está à vista. `sort` aceita `recent`
    (mais recentes), `oldest` e `relevance` (só faz sentido com `q`).

    Com `theme_terms` (as expressões de um tema da plataforma, ver
    `api/news_themes`) a pesquisa fica limitada a esse tema. Com `theme_buckets`
    (todos os temas) a resposta traz também `facets["themes"]` — a contagem de
    cada tema **sem** o filtro do tema ativo, para se poder saltar de um para o
    outro sem os restantes aparecerem a zero.
    """
    client = es or get_es_client()
    if not client:
        return {"error": "Elasticsearch indisponível", "items": [], "total": 0, "facets": {}, "page": 1, "pages": 0}

    must: List[Dict[str, Any]] = []
    filters: List[Dict[str, Any]] = []
    if q:
        # Os termos têm de coexistir (AND) — mas o **tema exato** conta como
        # resultado válido: é o que faz uma notícia recolhida por tema aparecer
        # mesmo quando o título não repete as palavras do tema.
        must.append(
            {
                "bool": {
                    "should": [
                        {
                            "multi_match": {
                                "query": q,
                                "fields": NEWS_SEARCH_FIELDS,
                                "type": "best_fields",
                                "operator": "and",
                                "lenient": True,
                            }
                        },
                        # O `boost` vai **dentro** do valor: um `term` não aceita
                        # chaves irmãs (`found [topic] and [boost]` → 400).
                        {"term": {"topic": {"value": str(q).strip().lower(), "boost": 4}}},
                    ],
                    "minimum_should_match": 1,
                }
            }
        )
    codes = [str(code).strip().upper() for code in (tickers or []) if str(code).strip()]
    if codes:
        filters.append({"terms": {"ticker": codes}})
    if topic:
        filters.append({"term": {"topic": topic}})
    if publisher:
        filters.append({"term": {"publisher": publisher}})
    if sentiment:
        filters.append({"term": {"sentiment": sentiment}})
    window: Dict[str, Any] = {}
    if start_date:
        window["gte"] = str(start_date)[:10]
    if end_date:
        window["lte"] = f"{str(end_date)[:10]}T23:59:59"
    if window:
        filters.append({"range": {"published": window}})
    if analyzed is True:
        filters.append({"exists": {"field": "analyzed_at"}})
    elif analyzed is False:
        filters.append({"bool": {"must_not": [{"exists": {"field": "analyzed_at"}}]}})

    # O filtro do tema entra **depois** de guardar os filtros anteriores: a
    # contagem por tema não pode ser feita já dentro do tema ativo (daria zero em
    # todos os outros).
    previous_filters = list(filters)
    theme_clause = _news_theme_clause(theme_terms or [])
    if theme_clause:
        filters.append(theme_clause)

    query: Dict[str, Any] = {"match_all": {}}
    if must or filters:
        query = {"bool": {}}
        if must:
            query["bool"]["must"] = must
        if filters:
            query["bool"]["filter"] = filters

    safe_page = max(1, int(page or 1))
    safe_size = max(1, min(int(size or 20), 100))
    if sort == "oldest":
        ordering: List[Any] = [{"published": {"order": "asc"}}]
    elif sort == "relevance" and q:
        ordering = [{"_score": {"order": "desc"}}, {"published": {"order": "desc"}}]
    else:
        ordering = [{"published": {"order": "desc"}}, "_score"]

    aggs = {
        "tickers": {"terms": {"field": "ticker", "size": 40}},
        "publishers": {"terms": {"field": "publisher", "size": 40}},
        "sentiments": {"terms": {"field": "sentiment", "size": 10}},
        "topics": {"terms": {"field": "topic", "size": 30}},
        "labels": {"terms": {"field": "topics", "size": 25}},
        "by_day": {
            "date_histogram": {
                "field": "published",
                "calendar_interval": "day",
                "format": "yyyy-MM-dd",
                "min_doc_count": 1,
            }
        },
    }

    theme_filter_aggs: Dict[str, Any] = {}
    for entry in theme_buckets or []:
        clause = _news_theme_clause(entry.get("terms") or [])
        key = str(entry.get("id") or "").strip()
        if clause and key:
            theme_filter_aggs[key] = {"bool": {"filter": [*previous_filters, clause]}}
    if theme_filter_aggs:
        aggs["themes"] = {"filters": {"filters": theme_filter_aggs}}

    try:
        resp = client.search(
            index="finance_news",
            body={
                "query": query,
                "sort": ordering,
                "from": (safe_page - 1) * safe_size,
                "size": safe_size,
                "track_total_hits": True,
                "aggs": aggs,
            },
        )
    except Exception as exc:
        return {
            "error": str(exc),
            "items": [],
            "total": 0,
            "facets": {},
            "page": safe_page,
            "size": safe_size,
            "pages": 0,
        }

    hits = resp.get("hits") or {}
    items: List[Dict[str, Any]] = []
    for hit in hits.get("hits") or []:
        source = dict(hit.get("_source") or {})
        source["id"] = hit.get("_id")
        source["score"] = hit.get("_score")
        items.append(source)
    total = int(((hits.get("total") or {}).get("value")) or 0)
    aggregations = resp.get("aggregations") or {}
    facets = {
        "tickers": _news_terms(aggregations, "tickers"),
        "publishers": _news_terms(aggregations, "publishers"),
        "sentiments": _news_terms(aggregations, "sentiments"),
        "topics": _news_terms(aggregations, "topics"),
        "labels": _news_terms(aggregations, "labels"),
        "days": [
            {"value": bucket.get("key_as_string"), "count": int(bucket.get("doc_count") or 0)}
            for bucket in (((aggregations.get("by_day") or {}).get("buckets")) or [])
        ],
    }
    if theme_filter_aggs:
        counts = {
            str(key): int((bucket or {}).get("doc_count") or 0)
            for key, bucket in (((aggregations.get("themes") or {}).get("buckets")) or {}).items()
        }
        # A ordem é a do catálogo (o Elasticsearch devolve os baldes por nome).
        facets["themes"] = [
            {"value": key, "count": counts.get(key, 0)} for key in theme_filter_aggs
        ]
    return {
        "total": total,
        "page": safe_page,
        "size": safe_size,
        "pages": (total + safe_size - 1) // safe_size if safe_size else 0,
        "items": items,
        "facets": facets,
    }




def get_news_item(doc_id: str, es: Optional[Elasticsearch] = None) -> Optional[Dict[str, Any]]:
    """Uma notícia do índice pelo seu `_id` (o `id` que a pesquisa devolve).

    Serve para reconstruir a notícia inteira a partir do que a interface tem à
    mão (o cartão traz o `id`), sem depender de o cliente reenviar todos os
    campos. Devolve `None` quando o documento já não existe.
    """
    wanted = str(doc_id or "").strip()
    if not wanted:
        return None
    client = es or get_es_client()
    if not client:
        return None
    try:
        hit = client.get(index="finance_news", id=wanted)
    except NotFoundError:
        return None
    except Exception as exc:  # noqa: BLE001 - a publicação segue sem o documento
        logger.warning("Não foi possível ler a notícia %s: %s", wanted, exc)
        return None
    # O cliente do Elasticsearch devolve `ObjectApiResponse` (um `Mapping`, não um
    # `dict`): testar `isinstance(..., dict)` rejeitava todas as notícias.
    document = hit.get("_source") if hasattr(hit, "get") else None
    if not isinstance(document, dict):
        return None
    source = dict(document)
    source["id"] = hit.get("_id") or wanted
    return source




def save_news_translation(
    doc_id: str,
    *,
    title: Optional[str] = None,
    summary: Optional[str] = None,
    es: Optional[Elasticsearch] = None,
) -> bool:
    """Guarda a tradução PT na notícia (os campos que o NLP já usa na recolha).

    Escreve `translated_title`/`translated_summary` — os mesmos campos que o
    módulo de notícias mostra e pesquisa —, para a tradução feita a pedido ficar
    na ficha da notícia em vez de se perder no fim do pedido. Não toca em
    `analyzed_at`: traduzir não é passar pelo NLP da recolha, e o filtro
    «com/sem análise» da pesquisa tem de continuar a dizer a verdade.
    """
    wanted = str(doc_id or "").strip()
    documento: Dict[str, Any] = {}
    if title and str(title).strip():
        documento["translated_title"] = str(title).strip()
    if summary and str(summary).strip():
        documento["translated_summary"] = str(summary).strip()
    if not wanted or not documento:
        return False
    client = es or get_es_client()
    if not client:
        return False
    try:
        client.update(index="finance_news", id=wanted, doc=documento)
    except NotFoundError:
        return False
    except Exception as exc:  # noqa: BLE001 - a tradução devolvida vale por si
        logger.warning("Não foi possível guardar a tradução da notícia %s: %s", wanted, exc)
        return False
    return True




def news_stats(es: Optional[Elasticsearch] = None) -> Dict[str, Any]:
    """Panorama do índice de notícias: volume, tickers, fontes, janela e análise.

    É o que o módulo mostra no cabeçalho — quantas notícias há, de quando, de
    quantos tickers/fontes e quantas já passaram pelo NLP.
    """
    client = es or get_es_client()
    if not client:
        return {"error": "Elasticsearch indisponível", "documents": 0, "index": "finance_news"}
    try:
        resp = client.search(
            index="finance_news",
            body={
                "size": 0,
                "track_total_hits": True,
                "aggs": {
                    "tickers": {"cardinality": {"field": "ticker", "precision_threshold": 5000}},
                    "publishers": {"cardinality": {"field": "publisher", "precision_threshold": 5000}},
                    "topics": {"terms": {"field": "topic", "size": 20}},
                    "analyzed": {"filter": {"exists": {"field": "analyzed_at"}}},
                    "with_sentiment": {"filter": {"terms": {"sentiment": ["positivo", "negativo", "neutro"]}}},
                    "sentiments": {"terms": {"field": "sentiment", "size": 10}},
                    "first_published": {"min": {"field": "published"}},
                    "last_published": {"max": {"field": "published"}},
                    "last_ingest": {"max": {"field": "ingested_at"}},
                    "top_tickers": {"terms": {"field": "ticker", "size": 12}},
                    "top_publishers": {"terms": {"field": "publisher", "size": 12}},
                },
            },
        )
    except Exception as exc:
        return {"error": str(exc), "documents": 0, "index": "finance_news"}

    hits = resp.get("hits") or {}
    aggregations = resp.get("aggregations") or {}
    documents = int(((hits.get("total") or {}).get("value")) or 0)

    def _cardinality(name: str) -> int:
        return int(((aggregations.get(name) or {}).get("value")) or 0)

    def _moment(name: str) -> Optional[str]:
        value = (aggregations.get(name) or {}).get("value_as_string")
        if value:
            return value
        raw = (aggregations.get(name) or {}).get("value")
        if raw is None:
            return None
        try:
            return datetime.utcfromtimestamp(float(raw) / 1000).isoformat() + "Z"
        except (TypeError, ValueError, OSError):
            return None

    analyzed = int(((aggregations.get("analyzed") or {}).get("doc_count")) or 0)
    with_sentiment = int(((aggregations.get("with_sentiment") or {}).get("doc_count")) or 0)
    return {
        "index": "finance_news",
        "documents": documents,
        "tickers": _cardinality("tickers"),
        "publishers": _cardinality("publishers"),
        "analyzed": analyzed,
        "analyzed_share": round(analyzed / documents, 4) if documents else None,
        "with_sentiment": with_sentiment,
        "sentiments": _news_terms(aggregations, "sentiments"),
        "topics": _news_terms(aggregations, "topics"),
        "top_tickers": _news_terms(aggregations, "top_tickers"),
        "top_publishers": _news_terms(aggregations, "top_publishers"),
        "first_published": _moment("first_published"),
        "last_published": _moment("last_published"),
        "last_ingest": _moment("last_ingest"),
    }




def index_analyzed_news_items(
    ticker: str,
    items: List[Dict[str, Any]],
    analyses: List[Any],
    es: Optional[Elasticsearch] = None,
    topic: Optional[str] = None,
) -> Dict[str, Any]:
    """Indexa notícias enriquecidas com análise NLP no Elasticsearch.

    Usa o **mesmo** id que o `index_news_items` (`_news_doc_id`), senão a análise
    criava um segundo documento em vez de completar o primeiro.
    """
    client = es or get_es_client()
    if not client:
        return {"ticker": ticker, "error": "Elasticsearch indisponível", "indexed_count": 0}

    ensure_indices(client)
    ticker = ticker.upper()
    topic = _topic_key(topic)
    actions = []
    now = _today()
    for i, (item, analysis) in enumerate(zip(items, analyses)):
        published = item.get("published") or item.get("pubDate")
        if published and isinstance(published, datetime):
            published = published.isoformat()
        doc_id = _news_doc_id(ticker, topic, item, i)
        doc = {
            "_op_type": "index",
            "_index": "finance_news",
            "_id": doc_id,
            "ticker": ticker,
            "topic": topic,
            "title": item.get("title") or item.get("summary"),
            "summary": item.get("summary") or item.get("title"),
            "publisher": item.get("publisher") or item.get("provider"),
            "published": published,
            "url": item.get("url") or item.get("link"),
            "source": item.get("source", "yfinance"),
            "ingested_at": now,
            "analyzed_at": now,
            "sentiment": analysis.sentiment,
            "language": analysis.language,
            "translated_title": analysis.translated_title,
            "translated_summary": analysis.translated_summary,
            "summary_pt": analysis.summary_pt,
            "topics": analysis.topics,
            "entities": analysis.entities,
        }
        actions.append(doc)

    if not actions:
        return {"ticker": ticker, "indexed_count": 0, "total_items": 0}

    try:
        success, errors = bulk(client, actions, raise_on_error=False, refresh=True)
        return {"ticker": ticker, "indexed_count": success, "total_items": len(actions), "errors": len(errors)}
    except Exception as e:
        return {"ticker": ticker, "error": str(e), "indexed_count": 0, "total_items": len(actions)}




def fetch_news_for_analysis(
    ticker: str,
    q: Optional[str] = None,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    size: int = 100,
    es: Optional[Elasticsearch] = None,
) -> List[Dict[str, Any]]:
    """Recupera notícias indexadas para serem (re)analisadas."""
    result = search_news(ticker, q, start_date, end_date, size, es)
    return result.get("items", [])




def save_news_graph(
    ticker: str,
    graph: Dict[str, Any],
    es: Optional[Elasticsearch] = None,
) -> Dict[str, Any]:
    """Persiste grafo de notícias/entidades num índice dedicado."""
    client = es or get_es_client()
    if not client:
        return {"ticker": ticker, "error": "Elasticsearch indisponível"}

    graph_mappings = {
        "properties": {
            "ticker": {"type": "keyword"},
            "graph_type": {"type": "keyword"},
            "nodes": {"type": "object"},
            "edges": {"type": "object"},
            "created_at": {"type": "date"},
        }
    }
    if not client.indices.exists(index="finance_graphs"):
        client.indices.create(
            index="finance_graphs",
            body={"mappings": graph_mappings, "settings": {"number_of_shards": 1, "number_of_replicas": 0}},
        )

    try:
        client.index(
            index="finance_graphs",
            id=f"{ticker.upper()}-news",
            body={
                "ticker": ticker.upper(),
                "graph_type": "news_entities",
                "nodes": graph.get("nodes", []),
                "edges": graph.get("edges", []),
                "created_at": _today(),
            },
        )
        return {"ticker": ticker.upper(), "saved": True, "node_count": len(graph.get("nodes", [])), "edge_count": len(graph.get("edges", []))}
    except Exception as e:
        return {"ticker": ticker.upper(), "error": str(e)}




def load_news_graph(ticker: str, es: Optional[Elasticsearch] = None) -> Optional[Dict[str, Any]]:
    """Carrega grafo de notícias/entidades persistido."""
    client = es or get_es_client()
    if not client:
        return None
    try:
        resp = client.get(index="finance_graphs", id=f"{ticker.upper()}-news")
        return resp.get("_source")
    except Exception:
        return None




def search_all_tickers(
    q: str,
    from_: int = 0,
    size: int = 50,
    source: Optional[str] = None,
    sentiment: Optional[str] = None,
    topic: Optional[str] = None,
    es: Optional[Elasticsearch] = None,
) -> Dict[str, Any]:
    """Pesquisa notícias de todos os tickers por texto, com filtros e paginação."""
    client = es or get_es_client()
    if not client:
        return {"error": "Elasticsearch indisponível", "items": []}

    must = {
        "multi_match": {
            "query": q,
            "fields": ["ticker^3", "title^2", "summary", "publisher"],
            "type": "best_fields",
        }
    }
    filters = []
    if source:
        filters.append({"wildcard": {"publisher": f"*{source.lower()}*"}})
    if sentiment:
        filters.append({"term": {"sentiment": sentiment.lower()}})
    if topic:
        filters.append({"wildcard": {"topics": f"*{topic.lower()}*"}})

    query: Dict[str, Any] = {"bool": {"must": [must], "filter": filters}}

    try:
        resp = client.search(
            index="finance_news",
            body={
                "query": query,
                "sort": [{"published": {"order": "desc"}}, "_score"],
                "from": from_,
                "size": size,
                "track_scores": True,
                "track_total_hits": True,
            },
        )
        items = []
        for hit in resp["hits"]["hits"]:
            source = hit["_source"]
            source["score"] = hit.get("_score")
            items.append(source)
        return {"total": resp["hits"]["total"]["value"], "items": items}
    except Exception as e:
        return {"error": str(e), "items": []}




def autocomplete_suggestions(q: str, size: int = 12, es: Optional[Elasticsearch] = None) -> Dict[str, Any]:
    """Gera sugestões de autocomplete a partir de tickers, títulos, publishers e tópicos indexados."""
    client = es or get_es_client()
    if not client:
        return {"error": "Elasticsearch indisponível", "suggestions": []}

    q = q.strip()
    if not q:
        return {"suggestions": []}

    lower_q = q.lower()
    upper_q = q.upper()

    try:
        resp = client.search(
            index="finance_news",
            body={
                "size": 0,
                "query": {
                    "bool": {
                        "should": [
                            {"wildcard": {"ticker": f"{upper_q}*"}},
                            {"match_phrase_prefix": {"title": q}},
                            {"wildcard": {"publisher": f"*{lower_q}*"}},
                            {"wildcard": {"topics": f"*{lower_q}*"}},
                        ],
                        "minimum_should_match": 1,
                    }
                },
                "aggs": {
                    "tickers": {
                        "terms": {
                            "field": "ticker",
                            "size": 5,
                            "include": f"{upper_q}.*",
                            "order": {"_count": "desc"},
                        }
                    },
                    "publishers": {
                        "terms": {
                            "field": "publisher",
                            "size": 5,
                            "include": f".*{lower_q}.*",
                            "order": {"_count": "desc"},
                        }
                    },
                    "topics": {
                        "terms": {
                            "field": "topics",
                            "size": 5,
                            "include": f".*{lower_q}.*",
                            "order": {"_count": "desc"},
                        }
                    },
                    "title_hits": {
                        "terms": {
                            "field": "title.keyword",
                            "size": 5,
                            "include": f".*{lower_q}.*",
                            "order": {"_count": "desc"},
                        }
                    },
                },
            },
        )

        suggestions = []
        seen = set()

        for bucket in resp["aggregations"]["tickers"]["buckets"]:
            text = bucket["key"]
            if text not in seen:
                seen.add(text)
                suggestions.append({"text": text, "type": "ticker", "count": bucket["doc_count"]})

        for bucket in resp["aggregations"]["publishers"]["buckets"]:
            text = bucket["key"]
            if text and text not in seen:
                seen.add(text)
                suggestions.append({"text": text, "type": "publisher", "count": bucket["doc_count"]})

        for bucket in resp["aggregations"]["topics"]["buckets"]:
            text = bucket["key"]
            if text and text not in seen:
                seen.add(text)
                suggestions.append({"text": text, "type": "topic", "count": bucket["doc_count"]})

        for bucket in resp["aggregations"]["title_hits"]["buckets"]:
            text = bucket["key"]
            if text and text not in seen:
                seen.add(text)
                suggestions.append({"text": text, "type": "title", "count": bucket["doc_count"]})

        suggestions = suggestions[:size]
        return {"suggestions": suggestions}
    except Exception as e:
        return {"error": str(e), "suggestions": []}




def delete_ticker_data(ticker: str, es: Optional[Elasticsearch] = None) -> Dict[str, Any]:
    """Apaga todos os dados de preços e notícias de um ticker."""
    client = es or get_es_client()
    if not client:
        return {"ticker": ticker, "error": "Elasticsearch indisponível"}

    ticker = ticker.upper()
    try:
        prices_resp = client.delete_by_query(
            index="finance_prices",
            body={"query": {"term": {"ticker": ticker}}},
        )
        news_resp = client.delete_by_query(
            index="finance_news",
            body={"query": {"term": {"ticker": ticker}}},
        )
        return {
            "ticker": ticker,
            "prices_deleted": prices_resp.get("deleted", 0),
            "news_deleted": news_resp.get("deleted", 0),
        }
    except Exception as e:
        return {"ticker": ticker, "error": str(e)}




def list_indexed_tickers(es: Optional[Elasticsearch] = None) -> List[str]:
    """Devolve a lista de tickers que já têm dados indexados."""
    client = es or get_es_client()
    if not client:
        return []

    try:
        resp = client.search(
            index="finance_prices",
            body={
                "size": 0,
                "aggs": {"tickers": {"terms": {"field": "ticker", "size": 1000}}},
            },
        )
        return [bucket["key"] for bucket in resp["aggregations"]["tickers"]["buckets"]]
    except Exception:
        return []




def list_elastic_indices(es: Optional[Elasticsearch] = None) -> List[Dict[str, Any]]:
    """Lista todos os índices da plataforma com contagem de documentos e estado.

    Filtra apenas índices internos (prefixo finance_* e os índices de contratos).
    """
    client = es or get_es_client()
    if not client:
        return []

    try:
        indices = client.cat.indices(format="json", bytes="b")
    except Exception:
        return []

    def is_platform_index(name: str) -> bool:
        if name.startswith("finance_"):
            return True
        if name.startswith("."):
            return False
        return name in {"contratos", "contratos_es"}

    result: List[Dict[str, Any]] = []
    for idx in indices:
        name = idx.get("index", "")
        if not is_platform_index(name):
            continue
        result.append({
            "index": name,
            "label": name,
            "docs": _as_int(idx.get("docs.count")),
            "size": idx.get("store.size"),
            "health": idx.get("health"),
            "status": idx.get("status"),
        })
    return sorted(result, key=lambda x: x["index"])
