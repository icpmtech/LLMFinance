"""Itens recolhidos (diretório, notícias), fontes não-notícia e Iberinform.

Módulo do pacote :mod:`api.es` — ver `api/elasticsearch_client.py`,
que continua a expor a API pública (os coletores/serviços importam de lá).
"""
import logging
from typing import Any, Dict, Iterable, List, Optional, Tuple

from elasticsearch import Elasticsearch
from elasticsearch.helpers import bulk
from api.es.core import _clean_flattened, _today, get_es_client
from api.es.indices import SCRAPED_INDEX
from api.es.mappings import ensure_indices

logger = logging.getLogger(__name__)




def index_scraped_items(
    source_id: str,
    source_name: str,
    run_id: str,
    items: List[Dict[str, Any]],
    trigger: str = "manual",
    es: Optional[Elasticsearch] = None,
) -> Dict[str, Any]:
    """Indexa itens recolhidos em `finance_scraped`.

    O `_id` do documento é o `item_id` calculado pelo `scraper_service`, pelo que
    re-executar uma fonte **atualiza** os itens já conhecidos em vez de os
    duplicar (a identidade do item é definida na definição da fonte).
    """
    client = es or get_es_client()
    if not client:
        return {"error": "Elasticsearch indisponível", "indexed_count": 0, "error_count": 0}

    ensure_indices(client)
    now = _today()
    actions: List[Dict[str, Any]] = []
    for item in items or []:
        item_id = str(item.get("item_id") or "").strip()
        if not item_id:
            continue
        tags = item.get("tags")
        if isinstance(tags, str):
            tags = [tags]
        sentimento = item.get("sentiment") if isinstance(item.get("sentiment"), dict) else {}
        doc = {
            "source_id": source_id,
            "source_name": source_name or source_id,
            "run_id": run_id,
            "item_id": item_id,
            "url": str(item.get("url") or "")[:1024],
            "title": str(item.get("title") or "")[:1024],
            "summary": str(item.get("summary") or "")[:20000],
            "text": str(item.get("text") or "")[:100000],
            "tags": [str(t) for t in (tags or []) if t not in (None, "")][:64],
            "data": _clean_flattened(item.get("data") or {}) or {},
            "scraped_at": str(item.get("scraped_at") or now),
            "trigger": trigger or "manual",
        }
        label = str(sentimento.get("label") or "").strip().lower()
        if label:
            doc["sentiment"] = label
            doc["sentiment_engine"] = str(sentimento.get("engine") or "")[:32]
            try:
                doc["sentiment_score"] = float(sentimento.get("polarity") or 0.0)
            except (TypeError, ValueError):
                doc["sentiment_score"] = 0.0
        actions.append({"_index": SCRAPED_INDEX, "_id": item_id, "_source": doc})

    if not actions:
        return {"indexed_count": 0, "error_count": 0}

    try:
        success, errors = bulk(client, actions, raise_on_error=False, stats_only=False, refresh=True)
        error_list = errors if isinstance(errors, list) else []
        if error_list:
            logger.warning("Recolha: %s de %s itens falharam na indexação", len(error_list), len(actions))
        return {
            "indexed_count": int(success),
            "error_count": len(error_list),
            "errors": [str(e.get("index", {}).get("error", e))[:300] for e in error_list[:5]],
        }
    except Exception as exc:
        return {"error": str(exc), "indexed_count": 0, "error_count": len(actions)}




#: Índice de diretório: campos textuais (pesquisa livre + subcampo `keyword`) e
#: campos exatos (facetas/filtros). O resto do documento entra por *dynamic
#: mapping* e as fichas estruturadas ficam em `flattened`.
DIRECTORY_TEXT_FIELDS: Tuple[str, ...] = (
    "nome",
    "title",
    "localizacao",
    "morada",
    "atividade",
    "acerca",
    "summary",
)


DIRECTORY_KEYWORD_FIELDS: Tuple[str, ...] = (
    "nif",
    "concelho",
    "distrito",
    "forma_juridica",
    "cae",
    "estado",
    "constituicao",
    "telefone",
    "email",
    "site",
    "url",
)


DIRECTORY_NUMERIC_FIELDS: Tuple[str, ...] = ("capital_social_eur",)




def directory_index_mapping(flattened_fields: Iterable[str] = ()) -> Dict[str, Any]:
    """Mapeamento de um índice de diretório (fichas de empresas, cadastros)."""
    properties: Dict[str, Any] = {
        "source_id": {"type": "keyword"},
        "source_name": {"type": "keyword"},
        "run_id": {"type": "keyword"},
        "item_id": {"type": "keyword"},
        "url": {"type": "keyword"},
        "scraped_at": {"type": "date"},
        "trigger": {"type": "keyword"},
        "data": {"type": "flattened"},
    }
    for name in DIRECTORY_TEXT_FIELDS:
        properties[name] = {"type": "text", "fields": {"keyword": {"type": "keyword", "ignore_above": 256}}}
    for name in DIRECTORY_KEYWORD_FIELDS:
        properties[name] = {"type": "keyword"}
    for name in DIRECTORY_NUMERIC_FIELDS:
        properties[name] = {"type": "double"}
    for name in ("ficha", *(flattened_fields or ())):
        properties[str(name)] = {"type": "flattened"}
    return {"dynamic": True, "properties": properties}




def ensure_directory_index(
    client: Elasticsearch, index: str, flattened_fields: Iterable[str] = ()
) -> None:
    """Cria o índice de diretório se ainda não existir (não altera o existente)."""
    if client.indices.exists(index=index):
        return
    client.indices.create(
        index=index,
        settings={"number_of_shards": 1, "number_of_replicas": 0},
        mappings=directory_index_mapping(flattened_fields),
    )




def index_directory_items(
    index: str,
    *,
    source_id: str,
    source_name: str,
    run_id: str,
    items: List[Dict[str, Any]],
    trigger: str = "manual",
    flattened_fields: Iterable[str] = (),
    es: Optional[Elasticsearch] = None,
) -> Dict[str, Any]:
    """Indexa os itens de uma recolha num **índice de diretório** (fichas).

    Ao contrário de `finance_scraped` — onde os campos variáveis ficam todos em
    `data` (`flattened`, só pesquisável por texto — aqui os campos escalares
    sobem a campos de topo, com tipo próprio: é o que permite **facetas**
    (`distrito`, `concelho`, `forma_juridica`…) e filtros numéricos
    (`capital_social_eur`). As fichas rótulo/valor mantêm-se intactas, em
    `flattened`, para não multiplicar o mapeamento por cada rótulo da ficha.
    """
    client = es or get_es_client()
    if not client:
        return {"error": "Elasticsearch indisponível", "indexed_count": 0, "error_count": 0}

    ensure_directory_index(client, index, flattened_fields)
    now = _today()
    actions: List[Dict[str, Any]] = []
    for item in items or []:
        item_id = str(item.get("item_id") or "").strip()
        if not item_id:
            continue
        data = item.get("data") if isinstance(item.get("data"), dict) else {}
        doc: Dict[str, Any] = {
            "source_id": source_id,
            "source_name": source_name or source_id,
            "run_id": run_id,
            "item_id": item_id,
            "url": str(item.get("url") or "")[:1024],
            "title": str(item.get("title") or "")[:1024],
            "scraped_at": str(item.get("scraped_at") or now),
            "trigger": trigger or "manual",
            "data": _clean_flattened(data) or {},
        }
        for name, value in data.items():
            cleaned = _clean_flattened(value)
            if cleaned is None or (isinstance(cleaned, (list, dict)) and not cleaned):
                continue
            doc[str(name)] = cleaned
        actions.append({"_index": index, "_id": item_id, "_source": doc})

    if not actions:
        return {"indexed_count": 0, "error_count": 0}
    try:
        success, errors = bulk(client, actions, raise_on_error=False, stats_only=False, refresh=True)
        error_list = errors if isinstance(errors, list) else []
        if error_list:
            logger.warning("Diretório %s: %s de %s itens falharam na indexação", index, len(error_list), len(actions))
        return {
            "indexed_count": int(success),
            "error_count": len(error_list),
            "errors": [str(e.get("index", {}).get("error", e))[:300] for e in error_list[:5]],
        }
    except Exception as exc:
        return {"error": str(exc), "indexed_count": 0, "error_count": len(actions)}




def _directory_field(name: str, *, exact: bool) -> str:
    """Nome do campo a usar numa faceta/filtro (`nome` → `nome.keyword`)."""
    if not exact:
        return name
    return f"{name}.keyword" if name in DIRECTORY_TEXT_FIELDS else name




def search_directory(
    index: str,
    *,
    q: Optional[str] = None,
    filters: Optional[Dict[str, Any]] = None,
    min_capital: Optional[float] = None,
    max_capital: Optional[float] = None,
    sort: str = "relevance",
    size: int = 20,
    offset: int = 0,
    facet_fields: Iterable[str] = (),
    facet_size: int = 25,
    search_fields: Optional[Iterable[str]] = None,
    es: Optional[Elasticsearch] = None,
) -> Dict[str, Any]:
    """Pesquisa num índice de diretório, com filtros exatos e facetas.

    `filters` são igualdades exatas nos campos (`{"distrito": "Lisboa"}`) e
    `facet_fields` devolve a contagem por valor (para os dropdowns da UI).
    """
    client = es or get_es_client()
    if not client:
        return {"error": "Elasticsearch indisponível", "total": 0, "items": [], "facets": {}}

    must: List[Dict[str, Any]] = []
    term = (q or "").strip()
    if term:
        fields = list(search_fields or ("nome^3", "title^2", "nif", "morada", "atividade", "acerca", "localizacao", "data.*"))
        must.append({"query_string": {"query": term, "fields": fields, "default_operator": "and"}})
    for name, value in (filters or {}).items():
        if value in (None, "", []):
            continue
        if isinstance(value, (list, tuple, set)):
            values = [v for v in value if v not in (None, "")]
            if values:
                must.append({"terms": {_directory_field(str(name), exact=True): values}})
            continue
        must.append({"term": {_directory_field(str(name), exact=True): value}})
    capital_range: Dict[str, float] = {}
    if min_capital is not None:
        capital_range["gte"] = float(min_capital)
    if max_capital is not None:
        capital_range["lte"] = float(max_capital)
    if capital_range:
        must.append({"range": {"capital_social_eur": capital_range}})

    query: Dict[str, Any] = {"bool": {"must": must or [{"match_all": {}}]}}
    sort_spec: List[Dict[str, Any]]
    if sort == "recent":
        sort_spec = [{"scraped_at": "desc"}, {"_score": "desc"}]
    elif sort == "oldest":
        sort_spec = [{"scraped_at": "asc"}]
    elif sort == "nome":
        sort_spec = [{"nome.keyword": "asc"}, {"_score": "desc"}]
    elif sort == "capital":
        sort_spec = [{"capital_social_eur": "desc"}, {"_score": "desc"}]
    else:
        sort_spec = ["_score", {"scraped_at": "desc"}]

    aggs: Dict[str, Any] = {}
    for name in facet_fields or ():
        aggs[str(name)] = {"terms": {"field": _directory_field(str(name), exact=True), "size": facet_size}}

    body: Dict[str, Any] = {
        "query": query,
        "sort": sort_spec,
        "size": max(1, min(int(size), 200)),
        "from": max(0, int(offset)),
        "track_total_hits": True,
    }
    if aggs:
        body["aggs"] = aggs
    try:
        resp = client.search(index=index, body=body, ignore_unavailable=True)
    except Exception as exc:
        return {"error": str(exc), "total": 0, "items": [], "facets": {}}

    hits = resp.get("hits", {})
    total = hits.get("total", {})
    items = [{**hit.get("_source", {}), "item_id": hit.get("_id")} for hit in hits.get("hits", [])]
    facets: Dict[str, List[Dict[str, Any]]] = {}
    for name, agg in (resp.get("aggregations") or {}).items():
        facets[name] = [
            {"value": bucket.get("key"), "count": bucket.get("doc_count")}
            for bucket in agg.get("buckets", [])
        ]
    return {
        "total": total.get("value", 0) if isinstance(total, dict) else total,
        "items": items,
        "facets": facets,
    }





#: Fontes do índice da recolha que **não são notícias**: cadastro de empresas e
#: registos Iberinform/Racius (fichas com dezenas de campos cada) e dados de
#: ensaio. Ficam de fora quando a recolha é usada como **fonte de notícias**; o
#: resto do índice é imprensa (SAPO, Lusa, Jornal Económico, Observador, ECO, …).
NON_NEWS_SOURCE_PREFIXES: Tuple[str, ...] = ("empresas-", "iberinform-", "racius-", "tmp-")


NON_NEWS_SOURCE_IDS: Tuple[str, ...] = ("quotes-demo", "padroes-empresa")




def _news_source_exclusions(
    exclude_prefixes: Optional[Iterable[str]] = None,
    exclude_ids: Optional[Iterable[str]] = None,
) -> List[Dict[str, Any]]:
    """Cláusulas `must_not` que afastam da recolha o que não é notícia.

    Usa-se `prefix` em `source_id` (o id da fonte de recolha, ex. `sapo-e47529`)
    porque é aí que se distingue cadastro de imprensa — os artigos não têm
    nenhum campo que os marque como notícia.
    """
    clauses: List[Dict[str, Any]] = []
    for prefix in exclude_prefixes or []:
        prefix = str(prefix).strip()
        if prefix:
            clauses.append({"prefix": {"source_id": prefix}})
    ids = [str(item).strip() for item in (exclude_ids or []) if str(item).strip()]
    if ids:
        clauses.append({"terms": {"source_id": ids}})
    return clauses




def _scraped_query(
    q: Optional[str] = None,
    source_id: Optional[str] = None,
    tags: Optional[List[str]] = None,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    sentiments: Optional[List[str]] = None,
    exclude_prefixes: Optional[Iterable[str]] = None,
    exclude_ids: Optional[Iterable[str]] = None,
) -> Dict[str, Any]:
    """Constrói a query de pesquisa de itens recolhidos."""
    must: List[Dict[str, Any]] = []
    if q:
        # `data.*` cobre todos os campos extraídos (índice `flattened`).
        must.append(
            {
                "query_string": {
                    "query": q,
                    "fields": ["title^3", "summary^2", "text", "url", "data.*"],
                    "default_operator": "and",
                    "lenient": True,
                    "analyze_wildcard": True,
                }
            }
        )
    filters: List[Dict[str, Any]] = []
    if source_id:
        filters.append({"term": {"source_id": source_id}})
    if tags:
        filters.append({"terms": {"tags": tags}})
    etiquetas = [str(s).strip().lower() for s in (sentiments or []) if str(s).strip()]
    if etiquetas:
        filters.append({"terms": {"sentiment": etiquetas}})
    if date_from or date_to:
        rng: Dict[str, Any] = {}
        if date_from:
            rng["gte"] = date_from
        if date_to:
            rng["lte"] = date_to
        filters.append({"range": {"scraped_at": rng}})

    bool_query: Dict[str, Any] = {"must": must or [{"match_all": {}}]}
    if filters:
        bool_query["filter"] = filters
    exclusions = _news_source_exclusions(exclude_prefixes, exclude_ids)
    if exclusions:
        bool_query["must_not"] = exclusions
    return {"bool": bool_query}




#: Letras base → formas acentuadas possíveis (português e espanhol).
_ACCENT_VARIANTS = {
    "a": "aàáâãä",
    "c": "cç",
    "e": "eèéêë",
    "i": "iìíîï",
    "n": "nñ",
    "o": "oòóôõö",
    "u": "uùúûü",
}




def _accent_fold_terms(q: str) -> Optional[str]:
    """Versão da pesquisa tolerante a acentos, para quem escreve sem eles.

    O analisador padrão do Elasticsearch **não** dobra acentos: «obras publicas»
    não encontra «obras públicas» e a pesquisa devolvia zero. Aqui cada letra que
    possa vir acentuada passa a `?` («publicas» → «publ?c?s»), que casa as duas
    formas sem obrigar a reindexar com um analisador novo. Devolve `None` quando
    a pesquisa já tem acentos ou não há nada a variar (nesse caso não se repete).
    """
    if not q or any(ord(char) > 127 for char in q):
        return None
    changed = False
    terms: List[str] = []
    for token in q.split():
        letters = list(token)
        for index, char in enumerate(letters):
            if _ACCENT_VARIANTS.get(char.lower()):
                letters[index] = "?"
                changed = True
        terms.append("".join(letters))
    return " ".join(terms) if changed else None




def _sentiment_summary(aggs: Dict[str, Any], total: int) -> Dict[str, Any]:
    """Resumo do sentimento do conjunto de resultados (não só da página).

    É isto que dá «um sentimento à pesquisa»: a distribuição por etiqueta e a
    polaridade média dos itens classificados, com a cobertura (quantos dos
    resultados têm sentimento) para não confundir «neutro» com «sem análise».
    """
    buckets = {b["key"]: b["doc_count"] for b in aggs.get("sentiment", {}).get("buckets", [])}
    media = aggs.get("sentiment_avg", {}).get("value")
    analisados = sum(buckets.values())
    polaridade = round(float(media), 3) if isinstance(media, (int, float)) else 0.0
    label = "sem dados"
    if analisados:
        label = "positivo" if polaridade >= 0.15 else "negativo" if polaridade <= -0.15 else "neutro"
    return {
        "positivo": int(buckets.get("positivo", 0)),
        "neutro": int(buckets.get("neutro", 0)),
        "negativo": int(buckets.get("negativo", 0)),
        "analyzed": int(analisados),
        "total": int(total),
        "polarity": polaridade,
        "label": label,
        "coverage": round(analisados / total, 3) if total else 0.0,
    }




def search_scraped(
    q: Optional[str] = None,
    source_id: Optional[str] = None,
    tags: Optional[List[str]] = None,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    sentiments: Optional[List[str]] = None,
    size: int = 20,
    from_: int = 0,
    sort: str = "recent",
    exclude_prefixes: Optional[Iterable[str]] = None,
    exclude_ids: Optional[Iterable[str]] = None,
    es: Optional[Elasticsearch] = None,
) -> Dict[str, Any]:
    """Pesquisa itens recolhidos, com facetas por fonte, etiqueta, dia e sentimento.

    `exclude_prefixes`/`exclude_ids` deixam de fora fontes que não interessam ao
    chamador: na Pesquisa total usa-se para separar imprensa de cadastro de
    empresas (`empresas-*`, `iberinform-*`) e de dados de ensaio (`tmp-*`).
    """
    client = es or get_es_client()
    if not client:
        return {"error": "Elasticsearch indisponível", "total": 0, "items": [], "facets": {}}

    ensure_indices(client)

    sort_spec: List[Any]
    if sort == "oldest":
        sort_spec = [{"scraped_at": {"order": "asc"}}]
    elif sort == "relevance" and q:
        sort_spec = [{"_score": {"order": "desc"}}, {"scraped_at": {"order": "desc"}}]
    else:
        sort_spec = [{"scraped_at": {"order": "desc"}}]

    body: Dict[str, Any] = {
        "size": max(0, min(int(size), 200)),
        "from": max(0, int(from_)),
        "query": _scraped_query(
            q, source_id, tags, date_from, date_to, sentiments, exclude_prefixes, exclude_ids
        ),
        "sort": sort_spec,
        "track_total_hits": True,
        "aggs": {
            "sources": {"terms": {"field": "source_id", "size": 50}},
            # Nome legível do jornal (`source_id` é um slug do tipo
            # `jornal-econ-mico-2e59cd`, ilegível na interface). Cada bucket
            # leva o id da fonte para se poder filtrar por ela.
            "publishers": {
                "terms": {"field": "source_name", "size": 50},
                "aggs": {"ids": {"terms": {"field": "source_id", "size": 1}}},
            },
            "tags": {"terms": {"field": "tags", "size": 50}},
            "days": {"date_histogram": {"field": "scraped_at", "calendar_interval": "day", "min_doc_count": 0}},
            # Sentimento do conjunto de resultados (não só da página).
            "sentiment": {"terms": {"field": "sentiment", "size": 10}},
            "sentiment_avg": {"avg": {"field": "sentiment_score"}},
        },
    }

    try:
        resp = client.search(index=SCRAPED_INDEX, body=body)
    except Exception as exc:
        # Alguns campos de texto podem não existir (índice criado por versão
        # anterior): repete a pesquisa apenas sobre os campos garantidos.
        logger.debug("Pesquisa de recolha falhou (%s); a repetir sem `data.*`: %s", q, exc)
        if not q:
            return {"error": str(exc), "total": 0, "items": [], "facets": {}}
        fallback = dict(body)
        # A repetição tem de manter as exclusões: sem elas, uma pesquisa que
        # falha por causa de `data.*` voltava a trazer cadastro como notícia.
        fallback["query"] = _scraped_query(
            None, source_id, tags, date_from, date_to, sentiments, exclude_prefixes, exclude_ids
        )
        fallback["query"] = {
            "bool": {
                "must": [{"multi_match": {"query": q, "fields": ["title", "summary", "text"], "lenient": True}}],
                "filter": fallback["query"]["bool"].get("filter", []),
                "must_not": fallback["query"]["bool"].get("must_not", []),
            }
        }
        try:
            resp = client.search(index=SCRAPED_INDEX, body=fallback)
        except Exception as inner:
            return {"error": str(inner), "total": 0, "items": [], "facets": {}}

    # Última tentativa, tolerante a acentos: quem escreve «obras publicas» não
    # encontrava «obras públicas» (o analisador padrão não dobra acentos). Só
    # corre quando a pesquisa normal não devolveu nada.
    if q and not resp.get("hits", {}).get("hits"):
        folded = _accent_fold_terms(q)
        if folded and folded != q:
            retry = dict(body)
            retry["query"] = _scraped_query(
                folded, source_id, tags, date_from, date_to, sentiments, exclude_prefixes, exclude_ids
            )
            try:
                resp = client.search(index=SCRAPED_INDEX, body=retry)
            except Exception as exc:  # pragma: no cover - salvaguarda
                logger.debug("Segunda tentativa da recolha (sem acentos) falhou: %s", exc)

    aggs = resp.get("aggregations", {}) or {}
    total = resp.get("hits", {}).get("total", 0)
    total_value = total.get("value", 0) if isinstance(total, dict) else total
    return {
        "total": int(total_value or 0),
        "items": [hit.get("_source") or {} for hit in resp.get("hits", {}).get("hits", [])],
        "facets": {
            "sources": [
                {"key": b["key"], "count": b["doc_count"]} for b in aggs.get("sources", {}).get("buckets", [])
            ],
            "publishers": [
                {
                    "key": b["key"],
                    "count": b["doc_count"],
                    "id": next(
                        (sub["key"] for sub in b.get("ids", {}).get("buckets", []) if sub.get("key")),
                        "",
                    ),
                }
                for b in aggs.get("publishers", {}).get("buckets", [])
                if b.get("key")
            ],
            "tags": [{"key": b["key"], "count": b["doc_count"]} for b in aggs.get("tags", {}).get("buckets", [])],
            "days": [
                {"key": b.get("key_as_string"), "count": b["doc_count"]}
                for b in aggs.get("days", {}).get("buckets", [])
                if b.get("doc_count")
            ],
            "sentiment": [
                {"key": b["key"], "count": b["doc_count"]} for b in aggs.get("sentiment", {}).get("buckets", [])
            ],
        },
        "sentiment": _sentiment_summary(aggs, int(total_value or 0)),
    }




def search_iberinform(
    q: Optional[str] = None,
    size: int = 20,
    from_: int = 0,
    sort: str = "recent",
    es: Optional[Elasticsearch] = None,
) -> Dict[str, Any]:
    """Pesquisa empresas recolhidas do Iberinform no índice `finance_scraped`.

    Os documentos desta fonte têm `source_id` com prefixo `empresas-` e os
    dados estruturados da empresa vivem em `data` (`nome`, `nif`, `url`,
    `distrito`, `concelho`). A pesquisa cobre nome, NIF e texto recolhido.
    """
    client = es or get_es_client()
    if not client:
        return {"error": "Elasticsearch indisponível", "total": 0, "items": []}

    ensure_indices(client)

    sort_spec: List[Any]
    if sort == "relevance" and q:
        sort_spec = [{"_score": {"order": "desc"}}, {"scraped_at": {"order": "desc"}}]
    else:
        sort_spec = [{"scraped_at": {"order": "desc"}}]

    clauses: List[Dict[str, Any]] = []
    token = (q or "").strip()
    if token:
        # NIF exacto (9 dígitos) ou pesquisa de texto livre.
        if token.isdigit():
            clauses.append({"term": {"data.nif": token}})
        else:
            clauses.append({"multi_match": {"query": token, "fields": ["data.nome", "title", "summary", "text"], "lenient": True}})

    query: Dict[str, Any] = {
        "bool": {
            "filter": [{"wildcard": {"source_id": "empresas-*"}}],
            "must": clauses or [{"match_all": {}}],
        }
    }

    body = {
        "size": max(0, min(int(size), 200)),
        "from": max(0, int(from_)),
        "query": query,
        "sort": sort_spec,
        "track_total_hits": True,
    }

    try:
        resp = client.search(index=SCRAPED_INDEX, body=body)
    except Exception as exc:
        logger.warning("Pesquisa Iberinform falhou: %s", exc)
        return {"error": str(exc), "total": 0, "items": []}

    total = resp.get("hits", {}).get("total", 0)
    total_value = total.get("value", 0) if isinstance(total, dict) else total
    return {
        "total": int(total_value or 0),
        "items": [hit.get("_source") or {} for hit in resp.get("hits", {}).get("hits", [])],
    }




def update_scraped_sentiment(rows: List[Dict[str, Any]], es: Optional[Elasticsearch] = None) -> Dict[str, Any]:
    """Actualiza só o sentimento de itens já indexados (análise à posteriori).

    `rows` são `{item_id, sentiment}`; a atualização é parcial para não reescrever
    o texto nem os campos extraídos de cada documento.
    """
    client = es or get_es_client()
    if not client:
        return {"error": "Elasticsearch indisponível", "updated": 0}
    actions: List[Dict[str, Any]] = []
    for row in rows or []:
        item_id = str(row.get("item_id") or "").strip()
        sentimento = row.get("sentiment") if isinstance(row.get("sentiment"), dict) else None
        if not item_id or not sentimento or not sentimento.get("label"):
            continue
        try:
            score = float(sentimento.get("polarity") or 0.0)
        except (TypeError, ValueError):
            score = 0.0
        actions.append(
            {
                "_op_type": "update",
                "_index": SCRAPED_INDEX,
                "_id": item_id,
                "doc": {
                    "sentiment": str(sentimento["label"]).lower(),
                    "sentiment_score": score,
                    "sentiment_engine": str(sentimento.get("engine") or "")[:32],
                    "sentiment_model": str(sentimento.get("model") or "")[:80],
                    "sentiment_at": str(sentimento.get("analyzed_at") or _today()),
                },
            }
        )
    if not actions:
        return {"updated": 0, "error_count": 0}
    try:
        success, errors = bulk(client, actions, raise_on_error=False, stats_only=False, refresh=True)
        error_list = errors if isinstance(errors, list) else []
        return {"updated": int(success), "error_count": len(error_list)}
    except Exception as exc:
        return {"error": str(exc), "updated": 0, "error_count": len(actions)}




def scraped_status(es: Optional[Elasticsearch] = None) -> Dict[str, Any]:
    """Volumetria do índice de recolha (total e por fonte)."""
    client = es or get_es_client()
    if not client:
        return {"available": False, "total": 0, "sources": []}

    ensure_indices(client)
    try:
        resp = client.search(
            index=SCRAPED_INDEX,
            body={
                "size": 0,
                "track_total_hits": True,
                "aggs": {"sources": {"terms": {"field": "source_id", "size": 50}}},
            },
        )
        total = resp.get("hits", {}).get("total", 0)
        total_value = total.get("value", 0) if isinstance(total, dict) else total
        return {
            "available": True,
            "total": int(total_value or 0),
            "sources": [
                {"key": b["key"], "count": b["doc_count"]}
                for b in resp.get("aggregations", {}).get("sources", {}).get("buckets", [])
            ],
        }
    except Exception as exc:
        return {"available": False, "total": 0, "sources": [], "error": str(exc)}




def delete_scraped_source(source_id: str, es: Optional[Elasticsearch] = None) -> Dict[str, Any]:
    """Remove do índice todos os itens de uma fonte."""
    client = es or get_es_client()
    if not client:
        return {"error": "Elasticsearch indisponível"}
    ensure_indices(client)
    try:
        resp = client.delete_by_query(
            index=SCRAPED_INDEX,
            body={"query": {"term": {"source_id": source_id}}},
            refresh=True,
            conflicts="proceed",
        )
        return {"ok": True, "deleted": resp.get("deleted", 0)}
    except Exception as exc:
        return {"error": str(exc)}
