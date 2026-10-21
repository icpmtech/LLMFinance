"""Publicações societárias do Ministério da Justiça.

Módulo do pacote :mod:`api.es` — ver `api/elasticsearch_client.py`,
que continua a expor a API pública (os coletores/serviços importam de lá).
"""
import logging
import re
from datetime import datetime
from typing import Any, Dict, Iterable, List, Optional

from elasticsearch import Elasticsearch
from api.es.core import get_es_client
from api.es.indices import CONTRACTS_INDEX, ENTITIES_INDEX, SOCIETARIO_INDEX
from api.es.mappings import ensure_indices

logger = logging.getLogger(__name__)




# --- Publicações de atos societários (Ministério da Justiça) ---------------
#
# O portal `publicacoes.mj.pt` publica os atos de registo comercial das entidades
# portuguesas. A pesquisa exige reCAPTCHA (ver `collectors/publicacoes_mj.py`),
# pelo que a recolha é assistida: uma pessoa resolve o captcha e o coletor trata
# da paginação, do detalhe e da ingestão. Este índice guarda o resultado.


def _delete_stale_docs(
    index: str,
    field: str,
    value: str,
    keep_ids: List[str],
    es: Optional[Elasticsearch] = None,
) -> int:
    """Remove documentos de um índice cujo campo ``field`` == ``value`` e que já não constam.

    Evita acumular registos obsoletos quando uma entidade é recolhida de novo com
    um conjunto de resultados diferente (ex.: publicações entretanto removidas).
    """
    client = es or get_es_client()
    if not client or not value:
        return 0
    try:
        body: Dict[str, Any] = {
            "query": {"bool": {"filter": [{"term": {field: str(value)}}]}}
        }
        if keep_ids:
            body["query"]["bool"]["must_not"] = [{"ids": {"values": keep_ids}}]
        resp = client.delete_by_query(index=index, body=body, refresh=True, conflicts="proceed")
        return resp.get("deleted", 0)
    except Exception as exc:
        logger.warning("Falha a remover documentos obsoletos de %s=%s em %s: %s", field, value, index, exc)
        return 0




def index_societario_items(
    items: List[Dict[str, Any]],
    replace_for_nif: Optional[str] = None,
    drop_stale: bool = True,
    es: Optional[Elasticsearch] = None,
) -> Dict[str, Any]:
    """Indexa publicações de atos societários no índice SOCIETARIO_INDEX.

    ``replace_for_nif`` (NIF) identifica a entidade da recolha e ``drop_stale``
    ativa a limpeza dos registos dessa entidade que **já não constam** da
    recolha atual. Essa limpeza só é segura quando a recolha é **completa**
    (sem janela de datas): uma recolha parcial apagaria todas as publicações
    fora da janela.
    """
    client = es or get_es_client()
    if not client:
        return {"error": "Elasticsearch indisponível", "indexed_count": 0, "total": 0}

    now = datetime.utcnow().isoformat()
    docs: List[Dict[str, Any]] = []
    for item in items:
        doc = {k: v for k, v in item.items() if not k.startswith("_") and v is not None}
        if not doc.get("pub_id"):
            continue
        doc["source"] = doc.get("source") or "publicacoes_mj"
        doc["ingested_at"] = now
        docs.append(doc)

    result = _bulk_index_docs(SOCIETARIO_INDEX, docs, id_field="pub_id", es=client)
    if not drop_stale:
        return result
    target_nif = replace_for_nif or (docs[0].get("nif") if docs and _single_nif(docs) else None)
    if target_nif:
        keep_ids = [f"{SOCIETARIO_INDEX}:{d['pub_id']}" for d in docs if d.get("nif") == target_nif]
        result["deleted_stale"] = _delete_stale_docs(
            SOCIETARIO_INDEX, "nif", str(target_nif), keep_ids, es=client
        )
    return result




def _single_nif(docs: List[Dict[str, Any]]) -> bool:
    """Indica se todos os documentos pertencem à mesma entidade."""
    nifs = {str(d.get("nif")) for d in docs if d.get("nif")}
    return len(nifs) == 1




def search_societario(
    q: Optional[str] = None,
    nif: Optional[str] = None,
    entidade: Optional[str] = None,
    acto: Optional[str] = None,
    tipo: Optional[str] = None,
    distrito: Optional[str] = None,
    concelho: Optional[str] = None,
    natureza_juridica: Optional[str] = None,
    data_from: Optional[str] = None,
    data_to: Optional[str] = None,
    has_documento: Optional[bool] = None,
    size: int = 20,
    from_: int = 0,
    es: Optional[Elasticsearch] = None,
) -> Dict[str, Any]:
    """Pesquisa publicações de atos societários indexadas.

    ``q`` procura em texto livre (entidade/firma/acto/texto integral); os restantes
    parâmetros são filtros exatos (exceto as datas, que são intervalos inclusivos).
    """
    client = es or get_es_client()
    if not client:
        return {"error": "Elasticsearch indisponível", "items": [], "total": 0}

    ensure_indices(client)

    must: List[Dict[str, Any]] = []
    filters: List[Dict[str, Any]] = []
    if q:
        must.append(
            {
                "multi_match": {
                    "query": q,
                    "fields": ["entidade^3", "firma^3", "acto^2", "texto", "requerente"],
                    "operator": "and",
                }
            }
        )
    if nif:
        filters.append({"term": {"nif": str(nif)}})
    if entidade:
        filters.append({"match_phrase": {"entidade": entidade}})
    if acto:
        filters.append({"match_phrase": {"acto": acto}})
    if tipo:
        filters.append({"term": {"tipo": str(tipo)}})
    if distrito:
        filters.append({"term": {"distrito": distrito}})
    if concelho:
        filters.append({"term": {"concelho": concelho}})
    if natureza_juridica:
        filters.append({"term": {"natureza_juridica": natureza_juridica}})
    if has_documento is not None:
        filters.append({"term": {"has_documento": bool(has_documento)}})
    if data_from or data_to:
        interval: Dict[str, str] = {}
        if data_from:
            interval["gte"] = data_from
        if data_to:
            interval["lte"] = data_to
        filters.append({"range": {"data_publicacao": interval}})

    query: Dict[str, Any]
    if must or filters:
        query = {"bool": {}}
        if must:
            query["bool"]["must"] = must
        if filters:
            query["bool"]["filter"] = filters
    else:
        query = {"match_all": {}}

    body: Dict[str, Any] = {
        "query": query,
        "from": max(0, from_),
        "size": max(1, min(size, 200)),
        "track_total_hits": True,
        "sort": [{"data_publicacao": {"order": "desc", "missing": "_last"}}, "_score"],
        "aggs": {
            "by_acto": {"terms": {"field": "acto.keyword", "size": 15}},
            "by_tipo": {"terms": {"field": "tipo", "size": 10}},
            "by_distrito": {"terms": {"field": "distrito", "size": 25}},
            "by_ano": {"date_histogram": {"field": "data_publicacao", "calendar_interval": "year", "format": "yyyy"}},
            "by_natureza": {"terms": {"field": "natureza_juridica", "size": 15}},
        },
    }

    try:
        resp = client.search(index=SOCIETARIO_INDEX, body=body)
        aggs = resp.get("aggregations", {})
        return {
            "query": q,
            "total": resp["hits"]["total"]["value"],
            "items": [{**hit["_source"], "doc_id": hit["_id"]} for hit in resp["hits"]["hits"]],
            "from": from_,
            "size": size,
            "facets": {
                "acto": [{"key": b["key"], "count": b["doc_count"]} for b in aggs.get("by_acto", {}).get("buckets", [])],
                "tipo": [{"key": b["key"], "count": b["doc_count"]} for b in aggs.get("by_tipo", {}).get("buckets", [])],
                "distrito": [{"key": b["key"], "count": b["doc_count"]} for b in aggs.get("by_distrito", {}).get("buckets", [])],
                "ano": [
                    {"key": b.get("key_as_string"), "count": b["doc_count"]}
                    for b in aggs.get("by_ano", {}).get("buckets", [])
                ],
                "natureza_juridica": [
                    {"key": b["key"], "count": b["doc_count"]} for b in aggs.get("by_natureza", {}).get("buckets", [])
                ],
            },
        }
    except Exception as exc:
        return {"error": str(exc), "items": [], "total": 0}




def company_publicacoes(
    nif: str,
    size: int = 100,
    from_: int = 0,
    es: Optional[Elasticsearch] = None,
) -> Dict[str, Any]:
    """Publicações de atos societários de uma entidade (por NIF)."""
    return search_societario(nif=str(nif), size=size, from_=from_, es=es)




def societario_status(es: Optional[Elasticsearch] = None) -> Dict[str, Any]:
    """Volumetria do índice de publicações (entidades, intervalo de datas, atos)."""
    client = es or get_es_client()
    if not client:
        return {"error": "Elasticsearch indisponível"}
    ensure_indices(client)
    try:
        count = client.count(index=SOCIETARIO_INDEX).get("count", 0)
        out: Dict[str, Any] = {"index": SOCIETARIO_INDEX, "documents": count}
        if not count:
            return out
        resp = client.search(
            index=SOCIETARIO_INDEX,
            body={
                "size": 0,
                "aggs": {
                    "entities": {"cardinality": {"field": "nif"}},
                    "min_date": {"min": {"field": "data_publicacao"}},
                    "max_date": {"max": {"field": "data_publicacao"}},
                    "by_tipo": {"terms": {"field": "tipo", "size": 10}},
                    "by_acto": {"terms": {"field": "acto.keyword", "size": 10}},
                    "by_ano": {"date_histogram": {"field": "data_publicacao", "calendar_interval": "year", "format": "yyyy"}},
                },
            },
        )
        aggs = resp.get("aggregations", {})
        out["entities"] = aggs.get("entities", {}).get("value", 0)
        out["min_date"] = (aggs.get("min_date", {}) or {}).get("value_as_string")
        out["max_date"] = (aggs.get("max_date", {}) or {}).get("value_as_string")
        out["by_tipo"] = [{"key": b["key"], "count": b["doc_count"]} for b in aggs.get("by_tipo", {}).get("buckets", [])]
        out["top_actos"] = [{"key": b["key"], "count": b["doc_count"]} for b in aggs.get("by_acto", {}).get("buckets", [])]
        out["by_ano"] = [
            {"key": b.get("key_as_string"), "count": b["doc_count"]}
            for b in aggs.get("by_ano", {}).get("buckets", [])
        ]
        return out
    except Exception as exc:
        return {"error": str(exc)}




# --- Recolha societária massiva: alvos por ANO de contrato e por empresa -----

def societario_counts_by_nif(nifs: Iterable[str], es: Optional[Elasticsearch] = None) -> Dict[str, int]:
    """Nº de publicações societárias indexadas por NIF.

    Serve para saber o que já está indexado (ex.: indexar só os ficheiros JSON
    exportados que ainda faltam).
    """
    client = es or get_es_client()
    alvo = [str(nif).strip() for nif in nifs if str(nif).strip()]
    if not client or not alvo:
        return {}
    counts: Dict[str, int] = {}
    chunk = 500
    for start in range(0, len(alvo), chunk):
        lote = alvo[start : start + chunk]
        try:
            resp = client.search(
                index=SOCIETARIO_INDEX,
                body={
                    "size": 0,
                    "query": {"terms": {"nif": lote}},
                    "aggs": {"by_nif": {"terms": {"field": "nif", "size": len(lote)}}},
                },
            )
        except Exception as exc:
            logger.debug("Contagem de publicações por NIF falhou: %s", exc)
            continue
        for bucket in (resp.get("aggregations") or {}).get("by_nif", {}).get("buckets", []):
            counts[str(bucket["key"])] = int(bucket.get("doc_count") or 0)
    return counts




#: Caminhos `nested` das partes de um contrato (empresas adjudicatárias/adjudicantes).
_CONTRACT_PARTY_PATHS = ("adjudicatarios.parsed", "adjudicantes.parsed")




def contract_years(es: Optional[Elasticsearch] = None) -> Dict[str, Any]:
    """Anos com contratos indexados (faceta do filtro por ano).

    A recolha societária vai buscar as publicações das empresas que contratam;
    este é o eixo temporal disponível para escolher os alvos («ir pelos anos dos
    contratos»).
    """
    client = es or get_es_client()
    if not client:
        return {"years": [], "error": "Elasticsearch indisponível"}
    try:
        resp = client.search(
            index=CONTRACTS_INDEX,
            body={
                "size": 0,
                "aggs": {"years": {"terms": {"field": "Ano", "size": 60, "order": {"_key": "desc"}}}},
            },
        )
    except Exception as exc:
        logger.warning("Faceta de anos de contratos falhou: %s", exc)
        return {"years": [], "error": str(exc)}
    buckets = (resp.get("aggregations") or {}).get("years", {}).get("buckets", [])
    years = [
        {"year": int(bucket["key"]), "contracts": int(bucket.get("doc_count") or 0)}
        for bucket in buckets
        if bucket.get("key") is not None
    ]
    return {
        "years": years,
        "min": years[-1]["year"] if years else None,
        "max": years[0]["year"] if years else None,
    }




def companies_with_contracts_in_years(
    ano_ini: Optional[int] = None,
    ano_fim: Optional[int] = None,
    *,
    papel: str = "ambos",
    size: int = 1000,
    es: Optional[Elasticsearch] = None,
) -> Dict[str, Any]:
    """Empresas com contratos num intervalo de anos (NIF → nº contratos e valor).

    Agrega `adjudicatarios.parsed.nif` e `adjudicantes.parsed.nif` no intervalo de
    `Ano` indicado. Devolve o conjunto de candidatos usado para filtrar as
    entidades alvo da recolha societária pelos **anos dos contratos**.

    ``papel`` escolhe o lado do contrato: ``ambos`` (por omissão),
    ``adjudicatario`` (empresas que ganham contratos) ou ``adjudicante`` (quem
    contrata, sobretudo entidades públicas).

    Nota: o valor somado é o `precoContratual` (via `reverse_nested`, porque o
    valor vive no documento pai) e conta uma vez por parte envolvida.
    """
    client = es or get_es_client()
    if not client:
        return {"items": {}, "total": 0, "error": "Elasticsearch indisponível"}

    filtros: List[Dict[str, Any]] = []
    span: Dict[str, Any] = {}
    if ano_ini:
        span["gte"] = int(ano_ini)
    if ano_fim:
        span["lte"] = int(ano_fim)
    if span:
        filtros.append({"range": {"Ano": span}})

    def party_agg(path: str) -> Dict[str, Any]:
        return {
            "nested": {"path": path},
            "aggs": {
                "por_nif": {
                    "terms": {"field": f"{path}.nif", "size": max(1, min(int(size or 1000), 5000))},
                    "aggs": {"valor": {"reverse_nested": {}, "aggs": {"soma": {"sum": {"field": "precoContratual"}}}}},
                }
            },
        }

    escolha = str(papel or "ambos").strip().lower()
    if escolha in {"adjudicatario", "adjudicatarios", "adjudicatária", "adjudicatárias"}:
        lados = ["adjudicatarios"]
    elif escolha in {"adjudicante", "adjudicantes"}:
        lados = ["adjudicantes"]
    else:
        lados = ["adjudicatarios", "adjudicantes"]
    aggs = {lado: party_agg(f"{lado}.parsed") for lado in lados}

    body: Dict[str, Any] = {
        "size": 0,
        "query": {"bool": {"filter": filtros}} if filtros else {"match_all": {}},
        "aggs": aggs,
    }
    try:
        resp = client.search(index=CONTRACTS_INDEX, body=body)
    except Exception as exc:
        logger.warning("Agregação de empresas por anos falhou: %s", exc)
        return {"items": {}, "total": 0, "error": str(exc)}

    items: Dict[str, Dict[str, float]] = {}
    for papel_agg in lados:
        buckets = (((resp.get("aggregations") or {}).get(papel_agg) or {}).get("por_nif") or {}).get("buckets", [])
        for bucket in buckets:
            nif = str(bucket.get("key") or "").strip()
            if not nif:
                continue
            entry = items.setdefault(nif, {"contracts": 0.0, "value": 0.0})
            entry["contracts"] += int(bucket.get("doc_count") or 0)
            entry["value"] += float(((bucket.get("valor") or {}).get("soma") or {}).get("value") or 0.0)
    return {"items": items, "total": len(items), "ano_ini": ano_ini, "ano_fim": ano_fim, "papel": papel}




def societario_targets_filtered(
    *,
    ano_ini: Optional[int] = None,
    ano_fim: Optional[int] = None,
    q: Optional[str] = None,
    nifs: Optional[Iterable[str]] = None,
    min_contracts: int = 1,
    min_value: Optional[float] = None,
    papel: str = "ambos",
    period_size: int = 3000,
    exclude_collected: bool = True,
    limit: int = 50,
    from_: int = 0,
    es: Optional[Elasticsearch] = None,
) -> Dict[str, Any]:
    """Entidades alvo da recolha societária, filtradas por **ano de contrato** e por **empresa**.

    Mantém a mesma base do `societario_targets` (`finance_entities`, Portugal, com
    NIF) e acrescenta:

    - ``ano_ini``/``ano_fim``: só entidades com contratos nesses anos (agregação no
      índice de contratos, ver `companies_with_contracts_in_years`);
    - ``q``: firma/denominação (ou NIF, se forem 9 dígitos);
    - ``nifs``: lista explícita de empresas (interseção com os restantes filtros).

    Cada item diz quantos contratos **do período** a empresa tem
    (``period_contracts``/``period_value``), além do total no cadastro e das
    publicações societárias já indexadas.
    """
    client = es or get_es_client()
    if not client:
        return {"error": "Elasticsearch indisponível", "items": [], "total": 0}

    executar = [str(n).strip() for n in (nifs or []) if str(n).strip()]
    period: Dict[str, Dict[str, float]] = {}
    if ano_ini or ano_fim:
        agg = companies_with_contracts_in_years(ano_ini, ano_fim, papel=papel, size=period_size, es=client)
        if agg.get("error"):
            return {"error": agg["error"], "items": [], "total": 0}
        period = dict(agg.get("items") or {})
        if not period:
            return {"items": [], "total": 0, "from": from_, "size": limit, "period_entities": 0}

    filters: List[Dict[str, Any]] = [
        {"term": {"country_code": "PT"}},
        {"term": {"has_nif": True}},
        {"range": {"contracts_count": {"gte": max(1, int(min_contracts or 1))}}},
    ]
    if min_value:
        filters.append({"range": {"total_value": {"gte": float(min_value)}}})

    candidatos = executar or (list(period.keys()) if period else None)
    if candidatos:
        filters.append({"terms": {"nif": candidatos}})

    must: List[Dict[str, Any]] = []
    termo = (q or "").strip()
    if termo:
        if re.fullmatch(r"\d{9}", termo):
            must.append({"term": {"nif": termo}})
        else:
            must.append(
                {
                    "bool": {
                        "should": [
                            {"match": {"name": {"query": termo, "operator": "and", "boost": 3}}},
                            {"match": {"name.autocomplete": {"query": termo, "operator": "and"}}},
                        ],
                        "minimum_should_match": 1,
                    }
                }
            )

    query: Dict[str, Any] = {"bool": {"filter": filters}}
    if must:
        query["bool"]["must"] = must

    try:
        resp = client.search(
            index=ENTITIES_INDEX,
            body={
                "query": query,
                "from": max(0, from_),
                "size": max(1, min(int(limit or 50), 500)),
                "track_total_hits": False,
                "_source": ["nif", "name", "contracts_count", "total_value", "as_adjudicante_count", "as_adjudicatario_count"],
                "sort": [{"contracts_count": {"order": "desc", "missing": "_last"}}],
            },
        )
        rows = [hit["_source"] for hit in resp["hits"]["hits"]]
    except Exception as exc:
        logger.warning("Listagem de alvos societários falhou: %s", exc)
        return {"error": str(exc), "items": [], "total": 0}

    alvo_nifs = [str(r.get("nif")) for r in rows if r.get("nif")]
    counts: Dict[str, int] = {}
    if alvo_nifs:
        try:
            agg = client.search(
                index=SOCIETARIO_INDEX,
                body={
                    "size": 0,
                    "query": {"terms": {"nif": alvo_nifs}},
                    "aggs": {"by_nif": {"terms": {"field": "nif", "size": len(alvo_nifs)}}},
                },
            )
            counts = {
                b["key"]: b["doc_count"]
                for b in agg.get("aggregations", {}).get("by_nif", {}).get("buckets", [])
            }
        except Exception:
            counts = {}

    items: List[Dict[str, Any]] = []
    for row in rows:
        nif = str(row.get("nif") or "").strip()
        if not nif:
            continue
        metrics = period.get(nif) or {}
        items.append(
            {
                "nif": nif,
                "name": row.get("name"),
                "contracts_count": row.get("contracts_count"),
                "total_value": row.get("total_value"),
                "period_contracts": int(metrics.get("contracts") or 0) if period else None,
                "period_value": round(float(metrics.get("value") or 0.0), 2) if period else None,
                "publications_count": counts.get(nif, 0),
            }
        )
    if period:
        # Com filtro de anos, ordenar pelo volume no período é mais útil.
        items.sort(key=lambda item: (item.get("period_contracts") or 0), reverse=True)
    if exclude_collected:
        items = [item for item in items if not item["publications_count"]]
    return {
        "items": items,
        "total": len(items),
        "from": from_,
        "size": limit,
        "period_entities": len(period) if period else None,
        "period_truncated": bool(period) and len(period) >= int(period_size or 0),
        "period_size": period_size if period else None,
        "filters": {
            "ano_ini": ano_ini,
            "ano_fim": ano_fim,
            "papel": papel,
            "q": termo or None,
            "nifs": executar or None,
            "min_contracts": min_contracts,
            "min_value": min_value,
            "exclude_collected": exclude_collected,
        },
    }




def societario_targets(
    limit: int = 50,
    from_: int = 0,
    min_contracts: int = 1,
    exclude_collected: bool = True,
    es: Optional[Elasticsearch] = None,
) -> Dict[str, Any]:
    """Entidades portuguesas com contratos no Portal BASE, ordenadas por volume.

    Serve para escolher os alvos da recolha assistida: por omissão devolve só as
    entidades que ainda não têm publicações no índice societário.
    """
    client = es or get_es_client()
    if not client:
        return {"error": "Elasticsearch indisponível", "items": [], "total": 0}

    try:
        resp = client.search(
            index=ENTITIES_INDEX,
            body={
                "query": {
                    "bool": {
                        "filter": [
                            {"term": {"country_code": "PT"}},
                            {"term": {"has_nif": True}},
                            {"range": {"contracts_count": {"gte": max(1, min_contracts)}}},
                        ]
                    }
                },
                "from": max(0, from_),
                "size": max(1, min(limit, 200)),
                "track_total_hits": False,
                "_source": ["nif", "name", "contracts_count", "total_value", "country"],
                "sort": [{"contracts_count": {"order": "desc", "missing": "_last"}}],
            },
        )
        rows = [hit["_source"] for hit in resp["hits"]["hits"]]
    except Exception as exc:
        return {"error": str(exc), "items": [], "total": 0}

    nifs = [str(r.get("nif")) for r in rows if r.get("nif")]
    counts: Dict[str, int] = {}
    if nifs:
        try:
            agg = client.search(
                index=SOCIETARIO_INDEX,
                body={
                    "size": 0,
                    "query": {"terms": {"nif": nifs}},
                    "aggs": {"by_nif": {"terms": {"field": "nif", "size": len(nifs)}}},
                },
            )
            counts = {
                b["key"]: b["doc_count"]
                for b in agg.get("aggregations", {}).get("by_nif", {}).get("buckets", [])
            }
        except Exception:
            counts = {}

    items = [
        {
            "nif": str(row.get("nif")),
            "name": row.get("name"),
            "contracts_count": row.get("contracts_count"),
            "total_value": row.get("total_value"),
            "publications_count": counts.get(str(row.get("nif")), 0),
        }
        for row in rows
        if row.get("nif")
    ]
    if exclude_collected:
        items = [item for item in items if not item["publications_count"]]
    return {"items": items, "total": len(items), "from": from_, "size": limit}

# Importações no fim do módulo: evitam ciclos de importação
# (os nomes já estão definidos quando estes módulos são carregados).
from api.es.entidades import _bulk_index_docs  # noqa: E402
