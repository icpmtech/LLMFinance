"""Insolvências e revitalizações (CIRE): indexação, pesquisa e analítica.

Módulo do pacote :mod:`api.es` — ver `api/elasticsearch_client.py`,
que continua a expor a API pública (os coletores/serviços importam de lá).
"""
import logging
from datetime import datetime
from typing import Any, Dict, List, Optional

from elasticsearch import Elasticsearch
from api.es.core import get_es_client
from api.es.entidades import _bulk_index_docs
from api.es.indices import CIRE_INDEX
from api.es.mappings import ensure_indices
from api.es.societario import _delete_stale_docs

logger = logging.getLogger(__name__)




# --- CIRE: publicidade da insolvência e da revitalização de empresas ---

def cire_existing_ids(
    pub_ids: List[str],
    es: Optional[Elasticsearch] = None,
) -> Dict[str, Any]:
    """Devolve quais dos ``pub_ids`` já existem no índice do CIRE.

    Serve para a importação **não reescrever** documentos que já lá estão: uma
    recolha repetida do mesmo período só acrescenta o que é novo. A consulta é
    feita em blocos (o ``terms`` tem limite prático de 10 000 valores).
    """
    client = es or get_es_client()
    if not client or not pub_ids:
        return {"found": [], "known": 0, "checked": 0, "index": CIRE_INDEX}

    unique = list(dict.fromkeys(str(item) for item in pub_ids if item))
    found: List[str] = []
    chunk_size = 5000
    try:
        ensure_indices(client)
        for start in range(0, len(unique), chunk_size):
            chunk = unique[start: start + chunk_size]
            resp = client.search(
                index=CIRE_INDEX,
                body={
                    "size": len(chunk),
                    "track_total_hits": False,
                    "_source": ["pub_id"],
                    "query": {"terms": {"pub_id": chunk}},
                },
            )
            for hit in resp.get("hits", {}).get("hits", []):
                # O `_id` do documento leva o prefixo do índice (`finance_cire:<pub_id>`),
                # por isso o valor tem de vir do campo `pub_id`.
                valor = (hit.get("_source") or {}).get("pub_id")
                if not valor:
                    valor = str(hit.get("_id", "")).split(":", 1)[-1]
                found.append(str(valor))
    except Exception as exc:
        return {"error": str(exc), "found": [], "known": 0, "checked": len(unique), "index": CIRE_INDEX}

    return {
        "found": found,
        "known": len(found),
        "checked": len(unique),
        "index": CIRE_INDEX,
    }




def index_cire_items(
    items: List[Dict[str, Any]],
    run_id: Optional[str] = None,
    replace_for_referencias: Optional[List[str]] = None,
    skip_existing: bool = True,
    es: Optional[Elasticsearch] = None,
) -> Dict[str, Any]:
    """Indexa publicações do CIRE no índice ``CIRE_INDEX``.

    O ``_id`` é o ``pub_id`` (sha1 de referência + processo + data + ato). Com
    ``skip_existing`` (por omissão) os documentos **que já existem no índice são
    ignorados** — recolher de novo o mesmo período só acrescenta o que é novo e
    não reescreve nada (o número de ignorados vem em ``skipped_existing``). Use
    ``skip_existing=False`` para forçar a atualização dos existentes.

    Se ``replace_for_referencias`` for dado, os documentos dessas referências que
    já não constem da lista são apagados (a lista considera **todos** os itens
    recebidos, mesmo os ignorados por já existirem).
    """
    client = es or get_es_client()
    if not client:
        return {"error": "Elasticsearch indisponível", "indexed_count": 0, "total": 0}

    preparados: List[Dict[str, Any]] = []
    referencias_por_pub: Dict[str, str] = {}
    for item in items:
        doc = {k: v for k, v in item.items() if not k.startswith("_") and v is not None}
        if not doc.get("pub_id"):
            continue
        doc["source"] = doc.get("source") or "citius_cire"
        if run_id:
            doc["run_id"] = run_id
        preparados.append(doc)
        if doc.get("referencia") is not None:
            referencias_por_pub[str(doc["pub_id"])] = str(doc["referencia"])

    ignorados: List[str] = []
    if skip_existing and preparados:
        existentes = cire_existing_ids([str(d["pub_id"]) for d in preparados], es=client)
        ja_no_indice = set(existentes.get("found") or [])
        ignorados = [str(d["pub_id"]) for d in preparados if str(d["pub_id"]) in ja_no_indice]
        preparados = [d for d in preparados if str(d["pub_id"]) not in ja_no_indice]
        if existentes.get("error"):
            logger.warning("Não foi possível verificar duplicados do CIRE: %s", existentes["error"])

    now = datetime.utcnow().isoformat()
    docs = [{**doc, "ingested_at": now} for doc in preparados]
    result = _bulk_index_docs(CIRE_INDEX, docs, id_field="pub_id", es=client)
    result["received"] = len(items)
    result["indexed_count"] = result.get("indexed_count", 0)
    result["skipped_existing"] = len(ignorados)
    result["candidates"] = len(preparados)

    if replace_for_referencias:
        deleted = 0
        for referencia in replace_for_referencias:
            keep_ids = [
                f"{CIRE_INDEX}:{pub_id}"
                for pub_id, ref in referencias_por_pub.items()
                if ref == str(referencia)
            ]
            deleted += _delete_stale_docs(
                CIRE_INDEX, "referencia", str(referencia), keep_ids, es=client
            )
        result["deleted_stale"] = deleted
    return result




def _cire_query(
    *,
    q: Optional[str] = None,
    referencia: Optional[str] = None,
    processo: Optional[str] = None,
    nif: Optional[str] = None,
    tribunal: Optional[str] = None,
    tribunal_comarca: Optional[str] = None,
    tipo: Optional[str] = None,
    ato: Optional[str] = None,
    especie: Optional[str] = None,
    insolvente: Optional[str] = None,
    papel: Optional[str] = None,
    data_from: Optional[str] = None,
    data_to: Optional[str] = None,
    has_documento: Optional[bool] = None,
) -> Dict[str, Any]:
    """Query `bool` do CIRE a partir dos filtros (partilhada por pesquisa e analítica)."""
    must: List[Dict[str, Any]] = []
    filters: List[Dict[str, Any]] = []
    if q:
        must.append(
            {
                "multi_match": {
                    "query": q,
                    "fields": [
                        "insolvente^3",
                        "intervenientes.nome^3",
                        "referencia^3",
                        "processo^2",
                        "processo_numero^2",
                        "tribunal^2",
                        "ato^2",
                        "especie",
                        "texto",
                    ],
                    "operator": "and",
                }
            }
        )
    if referencia:
        filters.append({"term": {"referencia": str(referencia)}})
    if processo:
        filters.append({"match_phrase": {"processo": processo}})
    if nif:
        filters.append({"term": {"nifs": str(nif)}})
    if tribunal:
        filters.append({"match_phrase": {"tribunal": tribunal}})
    if tribunal_comarca:
        filters.append({"term": {"tribunal_comarca": tribunal_comarca}})
    if tipo:
        filters.append({"term": {"tipo": tipo}})
    if ato:
        filters.append({"match_phrase": {"ato": ato}})
    if especie:
        filters.append({"match_phrase": {"especie": especie}})
    if insolvente:
        filters.append({"match_phrase": {"insolvente": insolvente}})
    if papel:
        filters.append(
            {"nested": {"path": "intervenientes", "query": {"term": {"intervenientes.papel": papel}}}}
        )
    if has_documento is not None:
        filters.append({"term": {"has_documento": bool(has_documento)}})
    if data_from or data_to:
        interval: Dict[str, str] = {}
        if data_from:
            interval["gte"] = data_from
        if data_to:
            interval["lte"] = data_to
        filters.append({"range": {"data_publicacao": interval}})

    if must or filters:
        query: Dict[str, Any] = {"bool": {}}
        if must:
            query["bool"]["must"] = must
        if filters:
            query["bool"]["filter"] = filters
        return query
    return {"match_all": {}}




def search_cire(
    q: Optional[str] = None,
    referencia: Optional[str] = None,
    processo: Optional[str] = None,
    nif: Optional[str] = None,
    tribunal: Optional[str] = None,
    tribunal_comarca: Optional[str] = None,
    tipo: Optional[str] = None,
    ato: Optional[str] = None,
    especie: Optional[str] = None,
    insolvente: Optional[str] = None,
    papel: Optional[str] = None,
    data_from: Optional[str] = None,
    data_to: Optional[str] = None,
    has_documento: Optional[bool] = None,
    size: int = 20,
    from_: int = 0,
    es: Optional[Elasticsearch] = None,
) -> Dict[str, Any]:
    """Pesquisa publicações do CIRE (insolvências e revitalizações).

    ``q`` procura em texto livre (interveniente, tribunal, processo, ato). Os
    restantes parâmetros são filtros exatos, exceto as datas (intervalo
    inclusivo sobre a data de publicação) e ``papel`` (papel do interveniente).
    """
    client = es or get_es_client()
    if not client:
        return {"error": "Elasticsearch indisponível", "items": [], "total": 0}

    ensure_indices(client)

    query = _cire_query(
        q=q,
        referencia=referencia,
        processo=processo,
        nif=nif,
        tribunal=tribunal,
        tribunal_comarca=tribunal_comarca,
        tipo=tipo,
        ato=ato,
        especie=especie,
        insolvente=insolvente,
        papel=papel,
        data_from=data_from,
        data_to=data_to,
        has_documento=has_documento,
    )

    body: Dict[str, Any] = {
        "query": query,
        "from": max(0, from_),
        "size": max(1, min(size, 200)),
        "track_total_hits": True,
        "sort": [{"data_publicacao": {"order": "desc", "missing": "_last"}}, "_score"],
        "aggs": {
            "by_tipo": {"terms": {"field": "tipo", "size": 10}},
            "by_comarca": {"terms": {"field": "tribunal_comarca", "size": 25}},
            "by_tribunal": {"terms": {"field": "tribunal.keyword", "size": 25}},
            "by_especie": {"terms": {"field": "especie.keyword", "size": 15}},
            "by_ato": {"terms": {"field": "ato.keyword", "size": 20}},
            "by_ano": {
                "date_histogram": {"field": "data_publicacao", "calendar_interval": "year", "format": "yyyy"}
            },
            "by_mes": {
                "date_histogram": {"field": "data_publicacao", "calendar_interval": "month", "format": "yyyy-MM"}
            },
            "by_papel": {
                "nested": {"path": "intervenientes"},
                "aggs": {"papel": {"terms": {"field": "intervenientes.papel", "size": 15}}},
            },
        },
    }

    try:
        resp = client.search(index=CIRE_INDEX, body=body)
        aggs = resp.get("aggregations", {})
        return {
            "query": q,
            "total": resp["hits"]["total"]["value"],
            "items": [{**hit["_source"], "doc_id": hit["_id"]} for hit in resp["hits"]["hits"]],
            "from": from_,
            "size": size,
            "facets": {
                "tipo": [{"key": b["key"], "count": b["doc_count"]} for b in aggs.get("by_tipo", {}).get("buckets", [])],
                "tribunal_comarca": [
                    {"key": b["key"], "count": b["doc_count"]} for b in aggs.get("by_comarca", {}).get("buckets", [])
                ],
                "tribunal": [
                    {"key": b["key"], "count": b["doc_count"]} for b in aggs.get("by_tribunal", {}).get("buckets", [])
                ],
                "especie": [
                    {"key": b["key"], "count": b["doc_count"]} for b in aggs.get("by_especie", {}).get("buckets", [])
                ],
                "ato": [{"key": b["key"], "count": b["doc_count"]} for b in aggs.get("by_ato", {}).get("buckets", [])],
                "ano": [
                    {"key": b.get("key_as_string"), "count": b["doc_count"]}
                    for b in aggs.get("by_ano", {}).get("buckets", [])
                ],
                "mes": [
                    {"key": b.get("key_as_string"), "count": b["doc_count"]}
                    for b in aggs.get("by_mes", {}).get("buckets", [])
                ],
                "papel": [
                    {"key": b["key"], "count": b["doc_count"]}
                    for b in aggs.get("by_papel", {}).get("papel", {}).get("buckets", [])
                ],
            },
        }
    except Exception as exc:
        return {"error": str(exc), "items": [], "total": 0}




def cire_analytics(
    *,
    q: Optional[str] = None,
    nif: Optional[str] = None,
    tipo: Optional[str] = None,
    papel: Optional[str] = None,
    tribunal: Optional[str] = None,
    tribunal_comarca: Optional[str] = None,
    especie: Optional[str] = None,
    ato: Optional[str] = None,
    data_from: Optional[str] = None,
    data_to: Optional[str] = None,
    top: int = 12,
    es: Optional[Elasticsearch] = None,
) -> Dict[str, Any]:
    """Agregações do CIRE para os dashboards da **Analítica** (`GET /cire/analytics`).

    Aplica os **mesmos filtros da pesquisa** e devolve os números de topo
    (documentos, insolventes, processos, NIF/NIPC, período) e as distribuições
    (tipo, comarca, tribunal, espécie, ato, papel, ano e mês) — a par dos
    insolventes e administradores da insolvência com mais publicações. Os
    documentos por mês trazem também os **processos distintos** desse mês.
    """
    client = es or get_es_client(request_timeout=90)
    if not client:
        return {"error": "Elasticsearch indisponível"}
    ensure_indices(client)
    size = max(1, min(int(top or 12), 50))
    query = _cire_query(
        q=q,
        nif=nif,
        tribunal=tribunal,
        tribunal_comarca=tribunal_comarca,
        tipo=tipo,
        ato=ato,
        especie=especie,
        papel=papel,
        data_from=data_from,
        data_to=data_to,
    )
    body: Dict[str, Any] = {
        "size": 0,
        "track_total_hits": True,
        "query": query,
        "aggs": {
            "insolventes": {
                "cardinality": {"field": "insolvente.keyword", "precision_threshold": 40000}
            },
            "processos": {"cardinality": {"field": "referencia", "precision_threshold": 40000}},
            "nifs": {"cardinality": {"field": "nifs", "precision_threshold": 40000}},
            "comarcas": {"cardinality": {"field": "tribunal_comarca"}},
            "tribunais": {"cardinality": {"field": "tribunal.keyword"}},
            "min_date": {"min": {"field": "data_publicacao"}},
            "max_date": {"max": {"field": "data_publicacao"}},
            "by_tipo": {"terms": {"field": "tipo", "size": 10}},
            "by_comarca": {"terms": {"field": "tribunal_comarca", "size": size}},
            "by_tribunal": {"terms": {"field": "tribunal.keyword", "size": size}},
            "by_especie": {"terms": {"field": "especie.keyword", "size": size}},
            "by_ato": {"terms": {"field": "ato.keyword", "size": size}},
            "by_papel": {
                "nested": {"path": "intervenientes"},
                "aggs": {"papel": {"terms": {"field": "intervenientes.papel", "size": 12}}},
            },
            "by_ano": {
                "date_histogram": {
                    "field": "data_publicacao",
                    "calendar_interval": "year",
                    "format": "yyyy",
                }
            },
            "by_mes": {
                "date_histogram": {
                    "field": "data_publicacao",
                    "calendar_interval": "month",
                    "format": "yyyy-MM",
                },
                "aggs": {"processos": {"cardinality": {"field": "referencia"}}},
            },
            "top_insolventes": {"terms": {"field": "insolvente.keyword", "size": size}},
            "top_administradores": {
                "nested": {"path": "intervenientes"},
                "aggs": {
                    "adm": {
                        "filter": {"term": {"intervenientes.papel": "Administrador Insolvência"}},
                        "aggs": {
                            "nomes": {
                                "terms": {"field": "intervenientes.nome.keyword", "size": size}
                            }
                        },
                    }
                },
            },
        },
    }

    def _buckets(agg: Dict[str, Any]) -> List[Dict[str, Any]]:
        return [
            {"key": b.get("key_as_string") or b.get("key"), "count": b.get("doc_count", 0)}
            for b in (agg or {}).get("buckets", [])
        ]

    try:
        resp = client.search(index=CIRE_INDEX, body=body)
    except Exception as exc:
        return {"error": str(exc)}

    aggs = resp.get("aggregations", {})
    total = resp["hits"]["total"]["value"]
    processos = int(aggs.get("processos", {}).get("value") or 0)
    adm = aggs.get("top_administradores", {}).get("adm", {})
    return {
        "total": total,
        "insolventes": int(aggs.get("insolventes", {}).get("value") or 0),
        "processos": processos,
        "nifs": int(aggs.get("nifs", {}).get("value") or 0),
        "comarcas": int(aggs.get("comarcas", {}).get("value") or 0),
        "tribunais": int(aggs.get("tribunais", {}).get("value") or 0),
        "media_documentos_processo": round(total / processos, 2) if processos else None,
        "periodo": {
            "min": aggs.get("min_date", {}).get("value_as_string"),
            "max": aggs.get("max_date", {}).get("value_as_string"),
        },
        "por_tipo": _buckets(aggs.get("by_tipo")),
        "por_comarca": _buckets(aggs.get("by_comarca")),
        "por_tribunal": _buckets(aggs.get("by_tribunal")),
        "por_especie": _buckets(aggs.get("by_especie")),
        "por_ato": _buckets(aggs.get("by_ato")),
        "por_papel": _buckets(aggs.get("by_papel", {}).get("papel")),
        "por_ano": _buckets(aggs.get("by_ano")),
        "por_mes": [
            {
                "key": bucket.get("key_as_string"),
                "count": bucket.get("doc_count", 0),
                "processos": int(bucket.get("processos", {}).get("value") or 0),
            }
            for bucket in (aggs.get("by_mes") or {}).get("buckets", [])
        ],
        "top_insolventes": _buckets(aggs.get("top_insolventes")),
        "top_administradores": _buckets(adm.get("nomes")),
        "filtros": {
            "q": q,
            "nif": nif,
            "tipo": tipo,
            "papel": papel,
            "tribunal": tribunal,
            "tribunal_comarca": tribunal_comarca,
            "especie": especie,
            "ato": ato,
            "data_from": data_from,
            "data_to": data_to,
        },
    }




def cire_interveniente(nif: str, size: int = 100, from_: int = 0, es: Optional[Elasticsearch] = None) -> Dict[str, Any]:
    """Publicações do CIRE em que um NIF/NIPC é interveniente (qualquer papel)."""
    return search_cire(nif=str(nif), size=size, from_=from_, es=es)




def cire_status(es: Optional[Elasticsearch] = None) -> Dict[str, Any]:
    """Volumetria do índice do CIRE (documentos, NIFs, datas e distribuições)."""
    client = es or get_es_client()
    if not client:
        return {"error": "Elasticsearch indisponível"}
    ensure_indices(client)
    try:
        count = client.count(index=CIRE_INDEX).get("count", 0)
        out: Dict[str, Any] = {"index": CIRE_INDEX, "documents": count}
        if not count:
            return out
        resp = client.search(
            index=CIRE_INDEX,
            body={
                "size": 0,
                "aggs": {
                    "nifs": {"cardinality": {"field": "nifs"}},
                    "insolventes": {"cardinality": {"field": "insolvente.keyword"}},
                    "referencias": {"cardinality": {"field": "referencia"}},
                    "min_date": {"min": {"field": "data_publicacao"}},
                    "max_date": {"max": {"field": "data_publicacao"}},
                    "by_tipo": {"terms": {"field": "tipo", "size": 10}},
                    "by_comarca": {"terms": {"field": "tribunal_comarca", "size": 15}},
                    "by_tribunal": {"terms": {"field": "tribunal.keyword", "size": 15}},
                    "by_ato": {"terms": {"field": "ato.keyword", "size": 15}},
                    "by_especie": {"terms": {"field": "especie.keyword", "size": 15}},
                    "by_ano": {
                        "date_histogram": {
                            "field": "data_publicacao", "calendar_interval": "year", "format": "yyyy"
                        }
                    },
                    "by_mes": {
                        "date_histogram": {
                            "field": "data_publicacao", "calendar_interval": "month", "format": "yyyy-MM"
                        }
                    },
                    "com_documento": {"filter": {"term": {"has_documento": True}}},
                },
            },
        )
        aggs = resp.get("aggregations", {})

        def _buckets(name: str) -> List[Dict[str, Any]]:
            return [
                {"key": b["key"], "count": b["doc_count"]}
                for b in aggs.get(name, {}).get("buckets", [])
            ]

        out["nifs"] = aggs.get("nifs", {}).get("value", 0)
        out["insolventes"] = aggs.get("insolventes", {}).get("value", 0)
        out["referencias"] = aggs.get("referencias", {}).get("value", 0)
        out["min_date"] = (aggs.get("min_date", {}) or {}).get("value_as_string")
        out["max_date"] = (aggs.get("max_date", {}) or {}).get("value_as_string")
        out["with_documento"] = aggs.get("com_documento", {}).get("doc_count", 0)
        out["by_tipo"] = _buckets("by_tipo")
        out["top_comarcas"] = _buckets("by_comarca")
        out["top_tribunais"] = _buckets("by_tribunal")
        out["top_actos"] = _buckets("by_ato")
        out["by_especie"] = _buckets("by_especie")
        out["by_ano"] = [
            {"key": b.get("key_as_string"), "count": b["doc_count"]}
            for b in aggs.get("by_ano", {}).get("buckets", [])
        ]
        out["by_mes"] = [
            {"key": b.get("key_as_string"), "count": b["doc_count"]}
            for b in aggs.get("by_mes", {}).get("buckets", [])
        ]
        return out
    except Exception as exc:
        return {"error": str(exc)}




def cire_runs_summary(run_ids: List[str], es: Optional[Elasticsearch] = None) -> Dict[str, int]:
    """Número de documentos indexados por ``run_id`` (para a lista de recolhas)."""
    client = es or get_es_client()
    if not client or not run_ids:
        return {}
    try:
        resp = client.search(
            index=CIRE_INDEX,
            body={
                "size": 0,
                "query": {"terms": {"run_id": run_ids}},
                "aggs": {"by_run": {"terms": {"field": "run_id", "size": len(run_ids)}}},
            },
        )
        return {
            b["key"]: b["doc_count"]
            for b in resp.get("aggregations", {}).get("by_run", {}).get("buckets", [])
        }
    except Exception:
        return {}
