"""Contratos públicos de França.

Módulo do pacote :mod:`api.es` — ver `api/elasticsearch_client.py`,
que continua a expor a API pública (os coletores/serviços importam de lá).
"""
import json
import logging
import re
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from elasticsearch import Elasticsearch, NotFoundError
from elasticsearch.helpers import bulk
from api.es.contratos_es import _cpv_label_from_bucket
from api.es.core import ROOT, get_es_client
from api.es.indices import CONTRATOS_FR_INDEX
from api.es.mappings import ensure_indices

logger = logging.getLogger(__name__)




# --- Contratos públicos de França (DECP / data.gouv.fr) ------------------
# Documentos produzidos por `collectors/contratos_fr.py`. Índice plano com os
# mesmos princípios do PLACSP: um documento por registo DECP, facetas diretas
# por campos simples e suporte a nested apenas para CPV e titulaires.

CONTRATOS_FR_FACET_FIELDS: Dict[str, str] = {
    "ano": "ano",
    "nature": "nature",
    "procedure": "procedure",
    "forme_prix": "forme_prix",
    "lieu_execution_type": "lieu_execution_type",
    "acheteur": "acheteur_nom.keyword",
    "adjudicatario": "adjudicatario_nom.keyword",
}




def index_contratos_fr(
    docs: List[Dict[str, Any]],
    es: Optional[Elasticsearch] = None,
) -> Dict[str, Any]:
    """Indexa documentos de contratos de França no índice `contratos_fr`."""
    client = es or get_es_client()
    if not client:
        return {"error": "Elasticsearch indisponível", "indexed_count": 0}

    ensure_indices(client)
    actions = []
    for doc in docs:
        doc_id = str(doc.get("doc_id") or "")
        if not doc_id:
            continue
        actions.append({"_op_type": "index", "_index": CONTRATOS_FR_INDEX, "_id": doc_id, **doc})

    if not actions:
        return {"indexed_count": 0, "total": 0}

    try:
        success, errors = bulk(client, actions, raise_on_error=False, refresh=False)
        return {"indexed_count": success, "total": len(actions), "errors": len(errors)}
    except Exception as exc:
        return {"error": str(exc), "indexed_count": 0, "total": len(actions)}




def bulk_index_contratos_fr_from_jsonl(
    jsonl_path: Path,
    chunk_size: int = 2000,
    max_records: Optional[int] = None,
    es: Optional[Elasticsearch] = None,
) -> Dict[str, Any]:
    """Indexa um JSONL de contratos de França em blocos (bulk)."""
    client = es or get_es_client()
    if not client:
        return {"error": "Elasticsearch indisponível", "indexed_count": 0}

    ensure_indices(client)
    total = success_total = error_total = 0
    chunk: List[Dict[str, Any]] = []
    resolved = Path(jsonl_path)
    started = time.time()

    try:
        with open(resolved, "r", encoding="utf-8") as fh:
            for line in fh:
                if max_records and total >= max_records:
                    break
                line = line.strip()
                if not line:
                    continue
                try:
                    chunk.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
                total += 1
                if len(chunk) >= chunk_size:
                    res = index_contratos_fr(chunk, client)
                    success_total += res.get("indexed_count", 0)
                    error_total += res.get("errors", 0) or (len(chunk) if res.get("error") else 0)
                    chunk = []
                    if total % (chunk_size * 10) == 0:
                        rate = total / max(time.time() - started, 1e-6)
                        print(f"[contratos_fr] {total:,} docs · {rate:,.0f} docs/s", flush=True)
        if chunk:
            res = index_contratos_fr(chunk, client)
            success_total += res.get("indexed_count", 0)
            error_total += res.get("errors", 0) or (len(chunk) if res.get("error") else 0)
        client.indices.refresh(index=CONTRATOS_FR_INDEX)
        return {
            "indexed_count": success_total,
            "total": total,
            "errors": error_total,
            "seconds": round(time.time() - started, 1),
        }
    except Exception as exc:
        return {"error": str(exc), "indexed_count": success_total, "total": total}




def contratos_fr_status(es: Optional[Elasticsearch] = None) -> Dict[str, Any]:
    """Volumetria do índice `contratos_fr`."""
    client = es or get_es_client()
    if not client:
        return {"error": "Elasticsearch indisponível", "total": 0, "years": [], "natures": []}

    ensure_indices(client)
    try:
        if not client.indices.exists(index=CONTRATOS_FR_INDEX):
            return {"total": 0, "years": [], "natures": [], "available": False}
        total = client.count(index=CONTRATOS_FR_INDEX).get("count", 0)
        resp = client.search(
            index=CONTRATOS_FR_INDEX,
            body={
                "size": 0,
                "aggs": {
                    "years": {"terms": {"field": "ano", "size": 40, "order": {"_key": "desc"}}},
                    "natures": {"terms": {"field": "nature", "size": 10}},
                },
            },
        )
        aggs = resp.get("aggregations", {})
        years = [
            {"year": b["key"], "count": b["doc_count"]}
            for b in aggs.get("years", {}).get("buckets", [])
            if isinstance(b["key"], int)
        ]
        natures = [{"nature": b["key"], "count": b["doc_count"]} for b in aggs.get("natures", {}).get("buckets", [])]
        return {
            "available": True,
            "total": total,
            "years": [y["year"] for y in years],
            "years_detail": years,
            "natures": natures,
        }
    except Exception as exc:
        return {"error": str(exc), "total": 0, "years": [], "natures": []}




def contratos_fr_years_available() -> List[int]:
    """Anos com JSONL normalizado em `data/processed/contratos-franca`."""
    years: set[int] = set()
    for path in (ROOT / "data" / "processed" / "contratos-franca").glob("*.jsonl"):
        match = re.search(r"_(\d{4})_\d{2}\.jsonl$", path.name)
        if match:
            years.add(int(match.group(1)))
    return sorted(years)




def _build_contratos_fr_query(
    q: Optional[str] = None,
    ano: Optional[int] = None,
    nature: Optional[str] = None,
    procedure: Optional[str] = None,
    acheteur: Optional[str] = None,
    acheteur_id: Optional[str] = None,
    adjudicatario: Optional[str] = None,
    adjudicatario_id: Optional[str] = None,
    cpv_code: Optional[str] = None,
    lieu_execution_code: Optional[str] = None,
    lieu_execution_type: Optional[str] = None,
    min_value: Optional[float] = None,
    max_value: Optional[float] = None,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    date_field: Optional[str] = None,
) -> Dict[str, Any]:
    """Constrói a query de pesquisa de contratos de França."""
    must: List[Dict[str, Any]] = []
    filters: List[Dict[str, Any]] = []

    if q and q.strip():
        text = q.strip()
        must.append(
            {
                "bool": {
                    "should": [
                        {"multi_match": {"query": text, "fields": ["objet^3", "adjudicatario_nom^2", "acheteur_nom^2", "search_text"], "type": "best_fields"}},
                        {"multi_match": {"query": text, "fields": ["objet^4", "search_text"], "type": "phrase", "boost": 2}},
                    ],
                    "minimum_should_match": 1,
                }
            }
        )

    if ano is not None:
        filters.append({"term": {"ano": ano}})
    if nature:
        filters.append({"term": {"nature": nature}})
    if procedure:
        filters.append({"term": {"procedure": procedure}})
    if acheteur_id:
        filters.append({"term": {"acheteur_id": acheteur_id}})
    if acheteur:
        filters.append(
            {
                "bool": {
                    "should": [
                        {"match_phrase": {"acheteur_nom": acheteur}},
                        {"term": {"acheteur_nom.keyword": acheteur}},
                    ],
                    "minimum_should_match": 1,
                }
            }
        )
    if adjudicatario_id:
        filters.append({"term": {"adjudicatario_id": adjudicatario_id}})
    if adjudicatario:
        filters.append(
            {
                "bool": {
                    "should": [
                        {"match_phrase": {"adjudicatario_nom": adjudicatario}},
                        {"term": {"adjudicatario_nom.keyword": adjudicatario}},
                        {"nested": {"path": "titulaires", "query": {"match_phrase": {"titulaires.nom": adjudicatario}}}},
                    ],
                    "minimum_should_match": 1,
                }
            }
        )
    if cpv_code:
        code = cpv_code.strip()
        filters.append(
            {
                "nested": {
                    "path": "cpv",
                    "query": (
                        {"term": {"cpv.code": code}}
                        if re.fullmatch(r"\d{8}(-\d)?", code)
                        else {"prefix": {"cpv.code": code}}
                    ),
                }
            }
        )
    if lieu_execution_code:
        # Prefixo em vez de igualdade: um código de departamento («59») abrange os
        # códigos postais/comunas que começam por ele («59000», «59350»), que é
        # exatamente o que o mapa conta. Um código completo casa só ele próprio.
        filters.append({"prefix": {"lieu_execution_code": lieu_execution_code.strip()}})
    if lieu_execution_type:
        filters.append({"term": {"lieu_execution_type": lieu_execution_type}})

    if min_value is not None or max_value is not None:
        rng: Dict[str, Any] = {k: v for k, v in (("gte", min_value), ("lte", max_value)) if v is not None}
        filters.append(
            {
                "bool": {
                    "should": [
                        {"range": {"montant": rng}},
                        {
                            "bool": {
                                "must": [
                                    {"bool": {"must_not": {"exists": {"field": "montant"}}}},
                                    {"range": {"montant_estime": rng}},
                                ]
                            }
                        },
                    ],
                    "minimum_should_match": 1,
                }
            }
        )

    field = date_field if date_field in ("date_notification", "date_publication") else "date_publication"
    date_range = {k: v for k, v in (("gte", start_date), ("lte", end_date)) if v}
    if date_range:
        filters.append({"range": {field: date_range}})

    return {"bool": {"must": must, "filter": filters}}




def _contratos_fr_sort(sort_by: Optional[str], sort_order: Optional[str]) -> List[Any]:
    order = sort_order if sort_order in ("asc", "desc") else "desc"
    # A página de França chama «valor» ao montante; no índice do DECP o campo
    # chama-se `montant` (o nome `valor` não existe lá e a ordenação ficava sem
    # efeito, porque só se aplicava `unmapped_type`).
    campo = "montant" if sort_by == "valor" else sort_by
    if campo in ("montant", "montant_estime"):
        return [{campo: {"order": order, "missing": "_last", "unmapped_type": "float"}}, "_score"]
    if sort_by in ("date_notification", "date_publication"):
        return [{sort_by: {"order": order, "missing": "_last", "unmapped_type": "date"}}, "_score"]
    if sort_by == "ano":
        return [{"ano": {"order": order, "missing": "_last", "unmapped_type": "integer"}}, "_score"]
    # Relevância: `relevance` é o nome canónico, `relevancia` o rótulo português
    # que a interface usava.
    if sort_by in ("relevance", "relevancia"):
        return ["_score", {"date_publication": {"order": "desc"}}]
    return [{"date_publication": {"order": "desc", "missing": "_last"}}, "_score"]




def _contratos_fr_aggs(cpv_size: int = 15, terms_size: int = 15) -> Dict[str, Any]:
    """Facetas usadas pela página de pesquisa francesa."""
    aggs: Dict[str, Any] = {
        name: {"terms": {"field": field, "size": terms_size}} for name, field in CONTRATOS_FR_FACET_FIELDS.items()
    }
    aggs["anos"] = {"terms": {"field": "ano", "size": 40, "order": {"_key": "desc"}}}
    aggs["cpv_codes"] = {
        "nested": {"path": "cpv"},
        "aggs": {
            "codes": {
                "terms": {"field": "cpv.code", "size": cpv_size},
                "aggs": {"nom": {"top_hits": {"size": 1, "_source": ["cpv.code", "cpv.nom"]}}},
            }
        },
    }
    aggs["valor"] = {
        "filter": {"exists": {"field": "montant"}},
        "aggs": {"sum": {"sum": {"field": "montant"}}, "avg": {"avg": {"field": "montant"}}},
    }
    aggs["valor_estime"] = {
        "filter": {"exists": {"field": "montant_estime"}},
        "aggs": {"sum": {"sum": {"field": "montant_estime"}}},
    }
    return aggs




def search_contratos_fr(
    q: Optional[str] = None,
    ano: Optional[int] = None,
    nature: Optional[str] = None,
    procedure: Optional[str] = None,
    acheteur: Optional[str] = None,
    acheteur_id: Optional[str] = None,
    adjudicatario: Optional[str] = None,
    adjudicatario_id: Optional[str] = None,
    cpv_code: Optional[str] = None,
    lieu_execution_code: Optional[str] = None,
    lieu_execution_type: Optional[str] = None,
    min_value: Optional[float] = None,
    max_value: Optional[float] = None,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    date_field: Optional[str] = None,
    size: int = 20,
    from_: int = 0,
    sort_by: Optional[str] = None,
    sort_order: Optional[str] = None,
    with_facets: bool = True,
    es: Optional[Elasticsearch] = None,
) -> Dict[str, Any]:
    """Pesquisa contratos de França com filtros e facetas."""
    client = es or get_es_client()
    if not client:
        return {"error": "Elasticsearch indisponível", "items": []}

    query = _build_contratos_fr_query(
        q=q,
        ano=ano,
        nature=nature,
        procedure=procedure,
        acheteur=acheteur,
        acheteur_id=acheteur_id,
        adjudicatario=adjudicatario,
        adjudicatario_id=adjudicatario_id,
        cpv_code=cpv_code,
        lieu_execution_code=lieu_execution_code,
        lieu_execution_type=lieu_execution_type,
        min_value=min_value,
        max_value=max_value,
        start_date=start_date,
        end_date=end_date,
        date_field=date_field,
    )
    body: Dict[str, Any] = {
        "query": query,
        "sort": _contratos_fr_sort(sort_by, sort_order),
        "from": max(from_, 0),
        "size": size,
        "track_total_hits": True,
    }
    if with_facets:
        body["aggs"] = _contratos_fr_aggs()

    try:
        resp = client.search(index=CONTRATOS_FR_INDEX, body=body)
        items = []
        for hit in resp["hits"]["hits"]:
            source = hit["_source"]
            source["score"] = hit.get("_score")
            source["doc_id"] = hit.get("_id")
            items.append(source)

        result: Dict[str, Any] = {
            "query": q,
            "total": resp["hits"]["total"]["value"],
            "items": items,
            "from": from_,
            "size": size,
        }
        if with_facets:
            aggs = resp.get("aggregations", {})
            facets: Dict[str, List[Dict[str, Any]]] = {}
            for name in CONTRATOS_FR_FACET_FIELDS:
                buckets = aggs.get(name, {}).get("buckets", [])
                if isinstance(buckets, dict):
                    buckets = buckets.get("codes", {}).get("buckets", [])
                facets[name] = [{"value": b["key"], "count": b["doc_count"]} for b in buckets]
            facets["cpv"] = []
            for bucket in aggs.get("cpv_codes", {}).get("codes", {}).get("buckets", []):
                facets["cpv"].append(
                    {
                        "value": bucket["key"],
                        "count": bucket["doc_count"],
                        "label": _cpv_label_from_bucket(bucket, bucket["key"]),
                    }
                )
            result["facets"] = facets
            result["stats"] = {
                "valor_sum": aggs.get("valor", {}).get("sum", {}).get("value"),
                "valor_avg": aggs.get("valor", {}).get("avg", {}).get("value"),
                "valor_docs": aggs.get("valor", {}).get("doc_count"),
                "valor_estime_sum": aggs.get("valor_estime", {}).get("sum", {}).get("value"),
                "valor_estime_docs": aggs.get("valor_estime", {}).get("doc_count"),
            }
        return result
    except Exception as exc:
        return {"error": str(exc), "items": []}




def contratos_fr_autocomplete(q: str, size: int = 10, es: Optional[Elasticsearch] = None) -> Dict[str, Any]:
    """Sugestões de compradores, adjudicatários, objetos e CPV para França."""
    client = es or get_es_client()
    if not client:
        return {"error": "Elasticsearch indisponível", "suggestions": []}

    text = (q or "").strip()
    if len(text) < 2:
        return {"suggestions": []}

    try:
        resp = client.search(
            index=CONTRATOS_FR_INDEX,
            body={
                "size": 0,
                "query": {
                    "bool": {
                        "should": [
                            {"match_phrase_prefix": {"acheteur_nom": text}},
                            {"match_phrase_prefix": {"adjudicatario_nom": text}},
                            {"match_phrase_prefix": {"objet": text}},
                        ],
                        "minimum_should_match": 1,
                    }
                },
                "aggs": {
                    "acheteurs": {"terms": {"field": "acheteur_nom.keyword", "size": size}},
                    "adjudicatarios": {"terms": {"field": "adjudicatario_nom.keyword", "size": size}},
                    "cpv_codes": {
                        "nested": {"path": "cpv"},
                        "aggs": {
                            "codes": {
                                "terms": {
                                    "field": "cpv.code",
                                    "size": size,
                                    **({"include": f"{text}.*"} if text.isdigit() else {}),
                                }
                            }
                        },
                    },
                },
            },
        )
        aggs = resp.get("aggregations", {})
        suggestions: List[Dict[str, Any]] = []
        seen: set[str] = set()
        for kind, key in (("acheteur", "acheteurs"), ("adjudicatario", "adjudicatarios")):
            for bucket in aggs.get(key, {}).get("buckets", []):
                if bucket["key"] and bucket["key"] not in seen:
                    seen.add(bucket["key"])
                    suggestions.append({"text": bucket["key"], "type": kind, "count": bucket["doc_count"]})
        for bucket in aggs.get("cpv_codes", {}).get("codes", {}).get("buckets", []):
            if bucket["key"] and bucket["key"] not in seen:
                seen.add(bucket["key"])
                suggestions.append({"text": bucket["key"], "type": "cpv", "count": bucket["doc_count"]})
        return {"suggestions": suggestions[: size * 2]}
    except Exception as exc:
        return {"error": str(exc), "suggestions": []}




CONTRATOS_FR_ENTITY_FIELDS: Dict[str, Dict[str, str]] = {
    "acheteur": {"field": "acheteur_nom.keyword", "label": "Acheteur public"},
    "adjudicatario": {"field": "adjudicatario_nom.keyword", "label": "Titulaire"},
}




CONTRATOS_FR_ENTITY_SAMPLE_FIELDS = [
    "acheteur_id",
    "adjudicatario_type_identifiant",
    "lieu_execution_code",
    "lieu_execution_type",
]




def _contratos_fr_entity_filter(field: str, text: str) -> Dict[str, Any]:
    source = field[: -len(".keyword")] if field.endswith(".keyword") else field
    if not text:
        return {"match_all": {}}
    return {
        "bool": {
            "should": [
                {"match_phrase": {source: text}},
                {"match_phrase_prefix": {source: text}},
            ],
            "minimum_should_match": 1,
        }
    }




def search_contratos_fr_entities(
    q: Optional[str] = None,
    *,
    kind: Optional[str] = None,
    ano: Optional[int] = None,
    min_count: int = 1,
    size: int = 20,
    from_: int = 0,
    es: Optional[Elasticsearch] = None,
) -> Dict[str, Any]:
    """Entidades de França (acheteurs e titulaires) por nome."""
    client = es or get_es_client()
    if not client:
        return {"error": "Elasticsearch indisponível", "items": []}

    text = (q or "").strip()
    selected = []
    if kind:
        selected = [kind] if kind in CONTRATOS_FR_ENTITY_FIELDS else []
    if not selected:
        selected = list(CONTRATOS_FR_ENTITY_FIELDS.keys())

    all_items: List[Dict[str, Any]] = []
    for k in selected:
        cfg = CONTRATOS_FR_ENTITY_FIELDS[k]
        filters: List[Dict[str, Any]] = [_contratos_fr_entity_filter(cfg["field"], text)]
        if ano is not None:
            filters.append({"term": {"ano": ano}})

        agg_body = {
            "size": 0,
            "query": {"bool": {"filter": filters}},
            "aggs": {
                "entities": {
                    "terms": {"field": cfg["field"], "size": from_ + size, "min_doc_count": min_count},
                    "aggs": {
                        "total_value": {"sum": {"field": "valor"}},
                        "avg_value": {"avg": {"field": "valor"}},
                        "max_value": {"max": {"field": "valor"}},
                        "sample": {"top_hits": {"size": 1, "_source": CONTRATOS_FR_ENTITY_SAMPLE_FIELDS}},
                        "last_year": {"max": {"field": "ano"}},
                    },
                }
            },
        }

        try:
            resp = client.search(index=CONTRATOS_FR_INDEX, body=agg_body)
        except Exception as exc:
            return {"error": str(exc), "items": []}

        buckets = resp.get("aggregations", {}).get("entities", {}).get("buckets", [])
        for bucket in buckets[from_: from_ + size]:
            sample = (bucket.get("sample", {}).get("hits", {}).get("hits", []) or [{}])[0].get("_source", {})
            all_items.append(
                {
                    "type": k,
                    "label": cfg["label"],
                    "name": bucket["key"],
                    "count": bucket["doc_count"],
                    "total_value": bucket.get("total_value", {}).get("value"),
                    "avg_value": bucket.get("avg_value", {}).get("value"),
                    "max_value": bucket.get("max_value", {}).get("value"),
                    "last_year": bucket.get("last_year", {}).get("value"),
                    "id": sample.get("acheteur_id") if k == "acheteur" else sample.get("adjudicatario_id"),
                    "id_type": sample.get("adjudicatario_type_identifiant"),
                    "lieu_execution_code": sample.get("lieu_execution_code"),
                    "lieu_execution_type": sample.get("lieu_execution_type"),
                }
            )

    all_items.sort(key=lambda x: (x["total_value"] or 0), reverse=True)
    return {
        "total": len(all_items),
        "items": all_items[:size],
        "query": q,
        "kind": kind,
        "from": from_,
        "size": size,
    }




def get_contrato_fr(doc_id: str, es: Optional[Elasticsearch] = None) -> Dict[str, Any]:
    """Devolve um contrato francês pelo `doc_id` do índice."""
    client = es or get_es_client()
    if not client:
        return {"error": "Elasticsearch indisponível"}

    try:
        resp = client.get(index=CONTRATOS_FR_INDEX, id=doc_id)
        source = resp.get("_source", {})
        source["doc_id"] = resp.get("_id")
        return source
    except NotFoundError:
        return {"error": "Contrato não encontrado"}
    except Exception as exc:
        return {"error": str(exc)}




def _contratos_fr_value_source(field: str = "montant") -> Dict[str, Any]:
    """Fonte de valores francesa: usa `montant` e, se ausente, `montant_estime`."""
    return {
        "script": {
            "source": f"""
                double v = doc['{field}'].size() != 0 ? doc['{field}'].value : 0.0;
                if (v == 0.0 && doc['montant_estime'].size() != 0) {{
                    v = doc['montant_estime'].value;
                }}
                return v;
            """,
        }
    }




def _top_hit_cpv_fr_name(top_hits: Dict[str, Any], code: str) -> str:
    hits = top_hits.get("hits", {}).get("hits", [])
    if not hits:
        return code
    source = hits[0].get("_source") or {}
    cpvs = source.get("cpv")
    if isinstance(cpvs, list):
        for entry in cpvs:
            if isinstance(entry, dict) and entry.get("code") == code and entry.get("nom"):
                return entry["nom"]
    if isinstance(source, dict) and source.get("nom"):
        return source["nom"]
    return code




def get_contratos_fr_analytics(
    q: Optional[str] = None,
    ano: Optional[int] = None,
    nature: Optional[str] = None,
    procedure: Optional[str] = None,
    acheteur: Optional[str] = None,
    acheteur_id: Optional[str] = None,
    adjudicatario: Optional[str] = None,
    adjudicatario_id: Optional[str] = None,
    cpv_code: Optional[str] = None,
    lieu_execution_code: Optional[str] = None,
    lieu_execution_type: Optional[str] = None,
    min_value: Optional[float] = None,
    max_value: Optional[float] = None,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    date_field: Optional[str] = None,
    top_acheteurs: int = 10,
    top_adjudicatarios: int = 10,
    top_cpv: int = 10,
    value_buckets: int = 10,
    es: Optional[Elasticsearch] = None,
) -> Dict[str, Any]:
    """Dashboard/analytics de contratos de França."""
    client = es or get_es_client(request_timeout=90)
    if not client:
        return {"error": "Elasticsearch indisponível"}

    base_query = _build_contratos_fr_query(
        q=q,
        ano=ano,
        nature=nature,
        procedure=procedure,
        acheteur=acheteur,
        acheteur_id=acheteur_id,
        adjudicatario=adjudicatario,
        adjudicatario_id=adjudicatario_id,
        cpv_code=cpv_code,
        lieu_execution_code=lieu_execution_code,
        lieu_execution_type=lieu_execution_type,
        min_value=min_value,
        max_value=max_value,
        start_date=start_date,
        end_date=end_date,
        date_field=date_field,
    )

    value_source = _contratos_fr_value_source("montant")

    analytics_body: Dict[str, Any] = {
        "size": 0,
        "track_total_hits": True,
        "query": base_query,
        "aggs": {
            "total_value": {"sum": value_source},
            "avg_value": {"avg": value_source},
            "max_value": {"max": value_source},
            "by_year": {
                "terms": {"field": "ano", "size": 50, "order": {"_key": "desc"}},
                "aggs": {"total_value": {"sum": value_source}},
            },
            "by_month": {
                "date_histogram": {
                    "field": "date_publication",
                    "calendar_interval": "month",
                    "format": "yyyy-MM",
                    "min_doc_count": 1,
                    "missing": "2000-01",
                }
            },
            "value_distribution": {
                "histogram": {
                    "script": value_source["script"],
                    "interval": 100000,
                    "min_doc_count": 1,
                }
            },
            "top_acheteurs": {
                "terms": {
                    "field": "acheteur_nom.keyword",
                    "size": top_acheteurs,
                    "order": {"total_value": "desc"},
                },
                "aggs": {"total_value": {"sum": value_source}},
            },
            "top_adjudicatarios": {
                "terms": {
                    "field": "adjudicatario_nom.keyword",
                    "size": top_adjudicatarios,
                    "order": {"total_value": "desc"},
                },
                "aggs": {"total_value": {"sum": value_source}},
            },
            "top_cpv": {
                "nested": {"path": "cpv"},
                "aggs": {
                    "codes": {
                        "terms": {"field": "cpv.code", "size": top_cpv, "order": {"total_value": "desc"}},
                        "aggs": {
                            "nom": {"top_hits": {"size": 1, "_source": ["cpv.code", "cpv.nom"]}},
                            "total_value": {
                                "reverse_nested": {},
                                "aggs": {"value": {"sum": value_source}},
                            },
                        },
                    }
                },
            },
            "procedures": {
                "terms": {"field": "procedure", "size": 20, "missing": "N/A"}
            },
            "formes_prix": {
                "terms": {"field": "forme_prix", "size": 20, "missing": "N/A"}
            },
            "lieu_execution_types": {
                "terms": {"field": "lieu_execution_type", "size": 20, "missing": "N/A"}
            },
            "lieu_execution_codes": {
                "terms": {"field": "lieu_execution_code", "size": 20, "missing": "N/A"},
                "aggs": {"total_value": {"sum": value_source}},
            },
        },
    }

    try:
        resp = client.search(index=CONTRATOS_FR_INDEX, body=analytics_body)
        aggs = resp["aggregations"]

        def fmt_money(v):
            return round(v, 2) if v is not None else None

        def read_value(bucket_total_value: Dict[str, Any]) -> Optional[float]:
            value = bucket_total_value.get("value", {})
            return value.get("value") if isinstance(value, dict) else value

        acheteur_rows = []
        for b in aggs.get("top_acheteurs", {}).get("buckets", []):
            acheteur_rows.append({
                "key": b["key"],
                "count": b["doc_count"],
                "total_value": fmt_money(read_value(b.get("total_value", {}))),
                "description": b["key"],
            })

        adjudicatario_rows = []
        for b in aggs.get("top_adjudicatarios", {}).get("buckets", []):
            adjudicatario_rows.append({
                "key": b["key"],
                "count": b["doc_count"],
                "total_value": fmt_money(read_value(b.get("total_value", {}))),
                "description": b["key"],
            })

        cpv_rows = []
        for b in aggs.get("top_cpv", {}).get("codes", {}).get("buckets", []):
            cpv_rows.append({
                "key": b["key"],
                "count": b["doc_count"],
                "total_value": fmt_money(read_value(b.get("total_value", {}))),
                "description": _top_hit_cpv_fr_name(b.get("nom"), b["key"]),
            })

        value_distribution = []
        for b in aggs.get("value_distribution", {}).get("buckets", []):
            if b.get("key") is None or b["key"] < 0:
                continue
            value_distribution.append({
                "key": f"{int(b['key'])} - {int(b['key']) + 100000}",
                "count": b["doc_count"],
            })
            if len(value_distribution) >= value_buckets:
                break

        return {
            "total_contracts": resp["hits"]["total"]["value"],
            "total_value": fmt_money(aggs["total_value"].get("value")),
            "avg_value": fmt_money(aggs["avg_value"].get("value")),
            "max_value": fmt_money(aggs["max_value"].get("value")),
            "by_year": [{"key": str(b["key"]), "count": b["doc_count"], "total_value": fmt_money(read_value(b.get("total_value", {})))} for b in aggs["by_year"]["buckets"]],
            "by_month": [{"key": b["key_as_string"], "count": b["doc_count"]} for b in aggs["by_month"]["buckets"]],
            "value_distribution": value_distribution,
            "top_entities": acheteur_rows + adjudicatario_rows,
            "top_cpv": cpv_rows,
            "procedures": [{"key": b["key"], "count": b["doc_count"]} for b in aggs["procedures"]["buckets"]],
            "formes_prix": [{"key": b["key"], "count": b["doc_count"]} for b in aggs["formes_prix"]["buckets"]],
            "localizacao": {
                "types": [{"key": b["key"], "count": b["doc_count"]} for b in aggs.get("lieu_execution_types", {}).get("buckets", [])],
                "codes": [{"key": b["key"], "count": b["doc_count"], "total_value": fmt_money(read_value(b.get("total_value", {})))} for b in aggs.get("lieu_execution_codes", {}).get("buckets", [])],
            },
            "year": ano,
        }
    except Exception as exc:
        return {"error": str(exc)}
