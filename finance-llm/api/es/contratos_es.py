"""Contratos públicos de Espanha.

Módulo do pacote :mod:`api.es` — ver `api/elasticsearch_client.py`,
que continua a expor a API pública (os coletores/serviços importam de lá).
"""
import json
import logging
import re
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from elasticsearch import Elasticsearch
from elasticsearch.helpers import bulk
from api.es.core import ROOT, _text_search, get_es_client
from api.es.indices import CONTRATOS_ES_INDEX
from api.es.mappings import ensure_indices

logger = logging.getLogger(__name__)




# --- Contratos públicos de Espanha (PLACSP) ---------------------------------
# Documentos produzidos por `collectors/contratos_es.py`. O `_id` do documento é
# `fonte|DIR3 do órgão|n.º de expediente`, pelo que reprocessar um ano atualiza em
# vez de duplicar (a publicação mais recente vence).

CONTRATOS_ES_FACET_FIELDS: Dict[str, str] = {
    "ano": "ano",
    "fonte": "fonte",
    "tipo": "tipo_contrato_label",
    "tipo_codigo": "tipo_contrato",
    "estado": "estado_label",
    "localidad": "localidad",
    "nuts": "nuts",
    "procedimiento": "procedimiento_label",
    "resultado": "resultado_label",
    "organo": "organo_nombre.keyword",
    "adjudicatario": "adjudicatario_nombre.keyword",
}




def index_contratos_es(
    docs: List[Dict[str, Any]],
    es: Optional[Elasticsearch] = None,
) -> Dict[str, Any]:
    """Indexa documentos de contratos de Espanha no índice `contratos_es`."""
    client = es or get_es_client()
    if not client:
        return {"error": "Elasticsearch indisponível", "indexed_count": 0}

    ensure_indices(client)
    actions = []
    for doc in docs:
        doc_id = str(doc.get("doc_id") or "")
        if not doc_id:
            continue
        actions.append({"_op_type": "index", "_index": CONTRATOS_ES_INDEX, "_id": doc_id, **doc})

    if not actions:
        return {"indexed_count": 0, "total": 0}

    try:
        success, errors = bulk(client, actions, raise_on_error=False, refresh=False)
        return {"indexed_count": success, "total": len(actions), "errors": len(errors)}
    except Exception as exc:
        return {"error": str(exc), "indexed_count": 0, "total": len(actions)}




def bulk_index_contratos_es_from_jsonl(
    jsonl_path: Path,
    chunk_size: int = 2000,
    max_records: Optional[int] = None,
    es: Optional[Elasticsearch] = None,
) -> Dict[str, Any]:
    """Indexa um JSONL de contratos de Espanha em blocos (bulk)."""
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
                    res = index_contratos_es(chunk, client)
                    success_total += res.get("indexed_count", 0)
                    error_total += res.get("errors", 0) or (len(chunk) if res.get("error") else 0)
                    chunk = []
                    if total % (chunk_size * 10) == 0:
                        rate = total / max(time.time() - started, 1e-6)
                        print(f"[contratos_es] {total:,} docs · {rate:,.0f} docs/s", flush=True)
        if chunk:
            res = index_contratos_es(chunk, client)
            success_total += res.get("indexed_count", 0)
            error_total += res.get("errors", 0) or (len(chunk) if res.get("error") else 0)
        client.indices.refresh(index=CONTRATOS_ES_INDEX)
        return {
            "indexed_count": success_total,
            "total": total,
            "errors": error_total,
            "seconds": round(time.time() - started, 1),
        }
    except Exception as exc:
        return {"error": str(exc), "indexed_count": success_total, "total": total}




def contratos_es_status(es: Optional[Elasticsearch] = None) -> Dict[str, Any]:
    """Volumetria do índice `contratos_es` (total, anos e fontes indexadas)."""
    client = es or get_es_client()
    if not client:
        return {"error": "Elasticsearch indisponível", "total": 0, "years": [], "fontes": []}

    ensure_indices(client)
    try:
        if not client.indices.exists(index=CONTRATOS_ES_INDEX):
            return {"total": 0, "years": [], "fontes": [], "available": False}
        total = client.count(index=CONTRATOS_ES_INDEX).get("count", 0)
        resp = client.search(
            index=CONTRATOS_ES_INDEX,
            body={
                "size": 0,
                "aggs": {
                    "years": {"terms": {"field": "ano", "size": 40, "order": {"_key": "desc"}}},
                    "fontes": {"terms": {"field": "fonte", "size": 10}},
                },
            },
        )
        aggs = resp.get("aggregations", {})
        years = [
            {"year": b["key"], "count": b["doc_count"]}
            for b in aggs.get("years", {}).get("buckets", [])
            if isinstance(b["key"], int)
        ]
        fontes = [{"fonte": b["key"], "count": b["doc_count"]} for b in aggs.get("fontes", {}).get("buckets", [])]
        return {
            "available": True,
            "total": total,
            "years": [y["year"] for y in years],
            "years_detail": years,
            "fontes": fontes,
        }
    except Exception as exc:
        return {"error": str(exc), "total": 0, "years": [], "fontes": []}




def contratos_es_years_available() -> List[int]:
    """Anos com JSONL normalizado em `data/processed/contratos-es`."""
    years: set[int] = set()
    for path in (ROOT / "data" / "processed" / "contratos-es").glob("*.jsonl"):
        match = re.search(r"_(\d{4})\.jsonl$", path.name)
        if match:
            years.add(int(match.group(1)))
    return sorted(years)




def _contratos_es_value_range(
    min_value: Optional[float],
    max_value: Optional[float],
) -> Optional[Dict[str, Any]]:
    """Filtro de valor: usa o valor adjudicado e, na sua falta, o valor base."""
    if min_value is None and max_value is None:
        return None
    budget: Dict[str, Any] = {"gte": min_value, "lte": max_value}
    budget = {k: v for k, v in budget.items() if v is not None}
    return {
        "bool": {
            "should": [
                {"range": {"valor_adjudicado": budget}},
                {
                    "bool": {
                        "must": [
                            {"bool": {"must_not": {"exists": {"field": "valor_adjudicado"}}}},
                            {"range": {"valor_base": budget}},
                        ]
                    }
                },
            ],
            "minimum_should_match": 1,
        }
    }




def _build_contratos_es_query(
    q: Optional[str] = None,
    ano: Optional[int] = None,
    fonte: Optional[str] = None,
    tipo: Optional[str] = None,
    estado: Optional[str] = None,
    procedimiento: Optional[str] = None,
    organo: Optional[str] = None,
    organismo_id: Optional[str] = None,
    adjudicatario: Optional[str] = None,
    adjudicatario_nif: Optional[str] = None,
    localidad: Optional[str] = None,
    nuts: Optional[str] = None,
    cpv_code: Optional[str] = None,
    min_value: Optional[float] = None,
    max_value: Optional[float] = None,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    date_field: Optional[str] = None,
    solo_menores: Optional[bool] = None,
) -> Dict[str, Any]:
    """Constrói a query de pesquisa de contratos de Espanha."""
    must: List[Dict[str, Any]] = []
    filters: List[Dict[str, Any]] = []

    if q and q.strip():
        text = q.strip()
        must.append(
            {
                "bool": {
                    "should": [
                        {"multi_match": {"query": text, "fields": ["objeto^3", "adjudicatario_nombre^2", "organo_nombre^2", "descripcion", "search_text"], "type": "best_fields"}},
                        {"multi_match": {"query": text, "fields": ["objeto^4", "search_text"], "type": "phrase", "boost": 2}},
                    ],
                    "minimum_should_match": 1,
                }
            }
        )

    if ano is not None:
        filters.append({"term": {"ano": ano}})
    if fonte:
        filters.append({"term": {"fonte": fonte}})
    if tipo:
        filters.append({"term": {"tipo_contrato": tipo}} if tipo.isdigit() else {"term": {"tipo_contrato_label": tipo}})
    if estado:
        filters.append({"term": {"estado": estado}} if len(estado) <= 5 and estado.isupper() else {"term": {"estado_label": estado}})
    if procedimiento:
        filters.append({"term": {"procedimiento": procedimiento}} if procedimiento.isdigit() else {"term": {"procedimiento_label": procedimiento}})
    if organismo_id:
        filters.append({"term": {"organo_id": organismo_id}})
    if organo:
        filters.append(
            {
                "bool": {
                    "should": [
                        {"match_phrase": {"organo_nombre": organo}},
                        {"term": {"organo_nombre.keyword": organo}},
                    ],
                    "minimum_should_match": 1,
                }
            }
        )
    if adjudicatario_nif:
        filters.append({"term": {"adjudicatario_nif": adjudicatario_nif}})
    if adjudicatario:
        filters.append(
            {
                "bool": {
                    "should": [
                        {"match_phrase": {"adjudicatario_nombre": adjudicatario}},
                        {"term": {"adjudicatario_nombre.keyword": adjudicatario}},
                    ],
                    "minimum_should_match": 1,
                }
            }
        )
    if localidad:
        filters.append({"term": {"localidad": localidad}})
    if nuts:
        filters.append({"term": {"nuts": nuts}})
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
    if solo_menores is not None:
        filters.append({"term": {"es_menor": solo_menores}})

    value_range = _contratos_es_value_range(min_value, max_value)
    if value_range:
        filters.append(value_range)

    field = date_field if date_field in ("fecha_publicacion", "fecha_adjudicacion", "fecha_actualizacion") else "fecha_publicacion"
    date_range = {k: v for k, v in (("gte", start_date), ("lte", end_date)) if v}
    if date_range:
        filters.append({"range": {field: date_range}})

    return {"bool": {"must": must, "filter": filters}}




def _contratos_es_sort(sort_by: Optional[str], sort_order: Optional[str]) -> List[Any]:
    order = sort_order if sort_order in ("asc", "desc") else "desc"
    if sort_by in ("valor_adjudicado", "valor_base", "valor_presupuesto"):
        return [{sort_by: {"order": order, "missing": "_last", "unmapped_type": "float"}}, "_score"]
    if sort_by in ("fecha_adjudicacion", "fecha_publicacion", "fecha_actualizacion"):
        return [{sort_by: {"order": order, "missing": "_last", "unmapped_type": "date"}}, "_score"]
    if sort_by == "num_ofertas":
        return [{"num_ofertas": {"order": order, "missing": "_last", "unmapped_type": "integer"}}, "_score"]
    if sort_by == "ano":
        return [{"ano": {"order": order, "missing": "_last", "unmapped_type": "integer"}}, "_score"]
    if sort_by == "relevancia":
        return ["_score", {"fecha_publicacion": {"order": "desc"}}]
    return [{"fecha_publicacion": {"order": "desc", "missing": "_last"}}, "_score"]




def _contratos_es_aggs(cpv_size: int = 15, terms_size: int = 15) -> Dict[str, Any]:
    """Facetas usadas pela página de pesquisa (incluem os rótulos em espanhol)."""
    aggs: Dict[str, Any] = {
        name: {"terms": {"field": field, "size": terms_size}} for name, field in CONTRATOS_ES_FACET_FIELDS.items()
    }
    aggs["anos"] = {"terms": {"field": "ano", "size": 40, "order": {"_key": "desc"}}}
    aggs["cpv_codes"] = {
        "nested": {"path": "cpv"},
        "aggs": {
            "codes": {
                "terms": {"field": "cpv.code", "size": cpv_size},
                "aggs": {"nombre": {"top_hits": {"size": 1, "_source": ["cpv.code", "cpv.nombre"]}}},
            }
        },
    }
    aggs["valor_adjudicado"] = {
        "filter": {"exists": {"field": "valor_adjudicado"}},
        "aggs": {"sum": {"sum": {"field": "valor_adjudicado"}}, "avg": {"avg": {"field": "valor_adjudicado"}}},
    }
    aggs["valor_base"] = {
        "filter": {"exists": {"field": "valor_base"}},
        "aggs": {"sum": {"sum": {"field": "valor_base"}}},
    }
    return aggs




def _cpv_label_from_bucket(bucket: Dict[str, Any], code: str) -> str:
    """Descrição de um código CPV a partir do `top_hits` de um *bucket* aninhado.

    Dependendo da versão do Elasticsearch, o `top_hits` dentro de uma agregação
    `nested` devolve o objeto aninhado (`{"code":..., "nombre":...}`) ou o documento
    pai com a lista `cpv`. Ambos os formatos são aceites.
    """
    hits = bucket.get("nombre", {}).get("hits", {}).get("hits", [])
    if not hits:
        return code
    source = hits[0].get("_source") or {}
    cpvs = source.get("cpv")
    if isinstance(cpvs, list):
        for entry in cpvs:
            if isinstance(entry, dict) and entry.get("code") == code and entry.get("nombre"):
                return entry["nombre"]
    if isinstance(source, dict) and source.get("nombre"):
        return source["nombre"]
    return code




def search_contratos_es(
    q: Optional[str] = None,
    ano: Optional[int] = None,
    fonte: Optional[str] = None,
    tipo: Optional[str] = None,
    estado: Optional[str] = None,
    procedimiento: Optional[str] = None,
    organo: Optional[str] = None,
    organismo_id: Optional[str] = None,
    adjudicatario: Optional[str] = None,
    adjudicatario_nif: Optional[str] = None,
    localidad: Optional[str] = None,
    nuts: Optional[str] = None,
    cpv_code: Optional[str] = None,
    min_value: Optional[float] = None,
    max_value: Optional[float] = None,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    date_field: Optional[str] = None,
    solo_menores: Optional[bool] = None,
    size: int = 20,
    from_: int = 0,
    sort_by: Optional[str] = None,
    sort_order: Optional[str] = None,
    with_facets: bool = True,
    es: Optional[Elasticsearch] = None,
) -> Dict[str, Any]:
    """Pesquisa contratos de Espanha com filtros e facetas."""
    client = es or get_es_client()
    if not client:
        return {"error": "Elasticsearch indisponível", "items": []}

    query = _build_contratos_es_query(
        q=q,
        ano=ano,
        fonte=fonte,
        tipo=tipo,
        estado=estado,
        procedimiento=procedimiento,
        organo=organo,
        organismo_id=organismo_id,
        adjudicatario=adjudicatario,
        adjudicatario_nif=adjudicatario_nif,
        localidad=localidad,
        nuts=nuts,
        cpv_code=cpv_code,
        min_value=min_value,
        max_value=max_value,
        start_date=start_date,
        end_date=end_date,
        date_field=date_field,
        solo_menores=solo_menores,
    )
    body: Dict[str, Any] = {
        "query": query,
        "sort": _contratos_es_sort(sort_by, sort_order),
        "from": max(from_, 0),
        "size": size,
        "track_total_hits": True,
    }
    if with_facets:
        body["aggs"] = _contratos_es_aggs()

    try:
        resp = _text_search(client, index=CONTRATOS_ES_INDEX, body=body, q=q)
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
            for name in CONTRATOS_ES_FACET_FIELDS:
                buckets = aggs.get(name, {}).get("buckets", [])
                if isinstance(buckets, dict):  # agregações por outra via (ex.: cpv)
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
                "valor_adjudicado_sum": aggs.get("valor_adjudicado", {}).get("sum", {}).get("value"),
                "valor_adjudicado_avg": aggs.get("valor_adjudicado", {}).get("avg", {}).get("value"),
                "valor_adjudicado_docs": aggs.get("valor_adjudicado", {}).get("doc_count"),
                "valor_base_sum": aggs.get("valor_base", {}).get("sum", {}).get("value"),
                "valor_base_docs": aggs.get("valor_base", {}).get("doc_count"),
            }
        return result
    except Exception as exc:
        return {"error": str(exc), "items": []}




def contratos_es_autocomplete(q: str, size: int = 10, es: Optional[Elasticsearch] = None) -> Dict[str, Any]:
    """Sugestões de órgãos, adjudicatários, objetos e CPV para a pesquisa espanhola."""
    client = es or get_es_client()
    if not client:
        return {"error": "Elasticsearch indisponível", "suggestions": []}

    text = (q or "").strip()
    if len(text) < 2:
        return {"suggestions": []}

    try:
        resp = client.search(
            index=CONTRATOS_ES_INDEX,
            body={
                "size": 0,
                "query": {
                    "bool": {
                        "should": [
                            {"match_phrase_prefix": {"organo_nombre": text}},
                            {"match_phrase_prefix": {"adjudicatario_nombre": text}},
                            {"match_phrase_prefix": {"objeto": text}},
                        ],
                        "minimum_should_match": 1,
                    }
                },
                "aggs": {
                    "organos": {"terms": {"field": "organo_nombre.keyword", "size": size}},
                    "adjudicatarios": {"terms": {"field": "adjudicatario_nombre.keyword", "size": size}},
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
        for kind, key in (("organo", "organos"), ("adjudicatario", "adjudicatarios")):
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




# Entidades do PLACSP. Cada documento do índice é **um contrato**, pelo que as
# entidades (órgãos adjudicantes e empresas adjudicatárias) são obtidas por
# agregação sobre o nome — é a forma de «pesquisar entidades» nos dados espanhóis.
CONTRATOS_ES_ENTITY_FIELDS: Dict[str, Dict[str, str]] = {
    "organo": {"field": "organo_nombre.keyword", "label": "Órgão adjudicante"},
    "adjudicatario": {"field": "adjudicatario_nombre.keyword", "label": "Empresa adjudicatária"},
}



CONTRATOS_ES_ENTITY_SAMPLE_FIELDS = [
    "organo_ciudad",
    "organo_id",
    "organo_tipo",
    "nuts",
    "adjudicatario_nif",
    "adjudicatario_nuts",
]




def _contratos_es_entity_filter(field: str, text: str) -> Dict[str, Any]:
    """Filtro de documentos cujo nome de entidade casa com o texto.

    Aceita a frase exata (`match_phrase`) e o prefixo da última palavra
    (`match_phrase_prefix`), para «Renfe» encontrar «Dirección General de Renfe
    Viajeros…» sem exigir o nome completo.
    """
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




def search_contratos_es_entities(
    q: Optional[str] = None,
    *,
    kind: Optional[str] = None,
    ano: Optional[int] = None,
    min_count: int = 1,
    size: int = 20,
    from_: int = 0,
    es: Optional[Elasticsearch] = None,
) -> Dict[str, Any]:
    """Entidades de Espanha (órgãos adjudicantes e adjudicatárias) por nome.

    Agrega os contratos por nome de entidade e devolve, para cada uma, o número
    de contratos, o valor adjudicado somado, a cidade, o NIF/DIR3 quando exista e
    o ano do último contrato. Sem texto devolve o diretório por volume; com texto
    filtra os nomes que casam com o termo.
    """
    client = es or get_es_client()
    if not client:
        return {"error": "Elasticsearch indisponível", "items": [], "total": 0}

    text = (q or "").strip()
    kinds = [kind] if kind in CONTRATOS_ES_ENTITY_FIELDS else list(CONTRATOS_ES_ENTITY_FIELDS)
    wanted = max(1, min(int(size), 100))
    offset = max(0, int(from_))
    # Os `terms` não têm paginação: pede-se o topo (offset + página) de cada tipo.
    bucket_size = min(300, offset + wanted)

    filters: List[Dict[str, Any]] = []
    if ano is not None:
        filters.append({"term": {"ano": ano}})

    aggs: Dict[str, Any] = {}
    for name in kinds:
        field = CONTRATOS_ES_ENTITY_FIELDS[name]["field"]
        aggs[name] = {
            "filter": _contratos_es_entity_filter(field, text),
            "aggs": {
                "entities": {
                    "terms": {"field": field, "size": bucket_size, "order": {"_count": "desc"}},
                    "aggs": {
                        # Mesma soma robusta da analítica: `max(valor_adjudicado, valor_base)`.
                        "valor": {"sum": _contratos_es_value_source()},
                        "ultimo_ano": {"max": {"field": "ano"}},
                        "sample": {"top_hits": {"size": 1, "_source": CONTRATOS_ES_ENTITY_SAMPLE_FIELDS}},
                    },
                }
            },
        }

    try:
        resp = client.search(
            index=CONTRATOS_ES_INDEX,
            body={
                "size": 0,
                "track_total_hits": False,
                "query": {"bool": {"filter": filters}} if filters else {"match_all": {}},
                "aggs": aggs,
            },
        )
    except Exception as exc:
        return {"error": str(exc), "items": [], "total": 0}

    floor = max(1, int(min_count))
    pages: Dict[str, List[Dict[str, Any]]] = {}
    counts: Dict[str, int] = {}
    for name in kinds:
        info = CONTRATOS_ES_ENTITY_FIELDS[name]
        bucket_group = resp.get("aggregations", {}).get(name, {})
        entries: List[Dict[str, Any]] = []
        for bucket in bucket_group.get("entities", {}).get("buckets", []):
            if bucket["doc_count"] < floor:
                continue
            sample = ((bucket.get("sample", {}).get("hits", {}).get("hits") or [{}])[0].get("_source")) or {}
            is_organo = name == "organo"
            entries.append(
                {
                    "kind": name,
                    "kind_label": info["label"],
                    "name": bucket["key"],
                    "count": bucket["doc_count"],
                    # A cidade e o NUTS do documento são os do **órgão**; para a
                    # adjudicatária só o NUTS da empresa faz sentido.
                    "city": (sample.get("organo_ciudad") or "") if is_organo else "",
                    "nuts": ((sample.get("nuts") if is_organo else sample.get("adjudicatario_nuts")) or ""),
                    "nif": (sample.get("adjudicatario_nif") or "") if not is_organo else "",
                    "organo_id": (sample.get("organo_id") or "") if is_organo else "",
                    "organo_tipo": (sample.get("organo_tipo") or "") if is_organo else "",
                    "total_value": bucket.get("valor", {}).get("value"),
                    # O `max` do ano chega como float (`2024.0`): arredonda para o badge.
                    "last_year": (
                        int(bucket["ultimo_ano"]["value"])
                        if isinstance(bucket.get("ultimo_ano", {}).get("value"), (int, float))
                        else None
                    ),
                }
            )
        counts[name] = len(entries)
        pages[name] = entries[offset : offset + wanted]

    # Intercala os dois tipos (1.º órgão, 1.ª adjudicatária, 2.º órgão, …) para
    # que a página mostre sempre entidades contratantes e empresas adjudicatárias.
    items: List[Dict[str, Any]] = []
    depth = max((len(entries) for entries in pages.values()), default=0)
    for index in range(depth):
        for entries in pages.values():
            if index < len(entries):
                items.append(entries[index])

    return {
        "query": q,
        "total": sum(counts.values()),
        "by_kind": counts,
        "items": items[:wanted],
        "from": offset,
        "size": wanted,
    }




def get_contrato_es(doc_id: str, es: Optional[Elasticsearch] = None) -> Dict[str, Any]:
    """Devolve um contrato de Espanha pelo respetivo `_id`."""
    client = es or get_es_client()
    if not client:
        return {"error": "Elasticsearch indisponível"}
    try:
        resp = client.get(index=CONTRATOS_ES_INDEX, id=doc_id)
        source = resp.get("_source", {})
        source["doc_id"] = resp.get("_id")
        return source
    except Exception as exc:
        return {"error": str(exc)}




def _contratos_es_value_source(field: str = "valor_adjudicado") -> Dict[str, Any]:
    """Devolve um `sum`/`avg`/`max` robusto para o valor adjudicado/base espanhol.

    A maior parte dos documentos tem `valor_adjudicado`, mas alguns (ou algumas
    versões do feed) só trazem `valor_base`. Usamos um `script` simples para
    escolher o primeiro disponível sem criar runtime_mappings no índice.
    """
    return {
        "script": {
            "source": "Math.max(doc.containsKey(params.adj) && !doc[params.adj].empty ? doc[params.adj].value : 0.0, doc.containsKey(params.base) && !doc[params.base].empty ? doc[params.base].value : 0.0)",
            "params": {"adj": field, "base": "valor_base"},
            "lang": "painless",
        }
    }




def _top_hit_cpv_es_name(agg: Optional[Dict[str, Any]], code: Any) -> str:
    """Lê a descrição espanhola de um CPV a partir de `top_hits`."""
    hits = (agg or {}).get("hits", {}).get("hits", []) or []
    for hit in hits:
        source = hit.get("_source") if isinstance(hit, dict) else None
        if not isinstance(source, dict):
            continue
        entries = source.get("cpv")
        if entries is None:
            entries = source
        if isinstance(entries, dict):
            entries = [entries]
        if not isinstance(entries, list):
            continue
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            if code is None or entry.get("code") == code:
                name = entry.get("nombre")
                if isinstance(name, str) and name.strip():
                    return name.strip()
    return str(code) if code is not None else ""




def get_contratos_es_analytics(
    q: Optional[str] = None,
    ano: Optional[int] = None,
    fonte: Optional[str] = None,
    tipo: Optional[str] = None,
    estado: Optional[str] = None,
    procedimiento: Optional[str] = None,
    organo: Optional[str] = None,
    organismo_id: Optional[str] = None,
    adjudicatario: Optional[str] = None,
    adjudicatario_nif: Optional[str] = None,
    localidad: Optional[str] = None,
    nuts: Optional[str] = None,
    cpv_code: Optional[str] = None,
    min_value: Optional[float] = None,
    max_value: Optional[float] = None,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    date_field: Optional[str] = None,
    solo_menores: Optional[bool] = None,
    top_organs: int = 8,
    top_adjudicatarios: int = 8,
    top_cpv: int = 8,
    value_buckets: int = 7,
    es: Optional[Elasticsearch] = None,
) -> Dict[str, Any]:
    """Devolve agregações analíticas para o dashboard de contratos de Espanha."""
    client = es or get_es_client(request_timeout=90)
    if not client:
        return {"error": "Elasticsearch indisponível"}

    ensure_indices(client)

    base_query = _build_contratos_es_query(
        q=q,
        ano=ano,
        fonte=fonte,
        tipo=tipo,
        estado=estado,
        procedimiento=procedimiento,
        organo=organo,
        organismo_id=organismo_id,
        adjudicatario=adjudicatario,
        adjudicatario_nif=adjudicatario_nif,
        localidad=localidad,
        nuts=nuts,
        cpv_code=cpv_code,
        min_value=min_value,
        max_value=max_value,
        start_date=start_date,
        end_date=end_date,
        date_field=date_field,
        solo_menores=solo_menores,
    )

    value_source = _contratos_es_value_source("valor_adjudicado")

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
                    "field": "fecha_publicacion",
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
            "top_organos": {
                "terms": {
                    "field": "organo_nombre.keyword",
                    "size": top_organs,
                    "order": {"total_value": "desc"},
                },
                "aggs": {"total_value": {"sum": value_source}},
            },
            "top_adjudicatarios": {
                "terms": {
                    "field": "adjudicatario_nombre.keyword",
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
                            "nombre": {"top_hits": {"size": 1, "_source": ["cpv.code", "cpv.nombre"]}},
                            "total_value": {
                                "reverse_nested": {},
                                "aggs": {"value": {"sum": value_source}},
                            },
                        },
                    }
                },
            },
            "procedure_types": {
                "terms": {"field": "procedimiento_label", "size": 20, "missing": "N/A"}
            },
            "contract_types": {
                "terms": {"field": "tipo_contrato_label", "size": 20, "missing": "N/A"}
            },
        },
    }

    try:
        resp = client.search(index=CONTRATOS_ES_INDEX, body=analytics_body)
        aggs = resp["aggregations"]

        def fmt_money(v):
            return round(v, 2) if v is not None else None

        def read_value(bucket_total_value: Dict[str, Any]) -> Optional[float]:
            value = bucket_total_value.get("value", {})
            return value.get("value") if isinstance(value, dict) else value

        organo_rows = []
        for b in aggs.get("top_organos", {}).get("buckets", []):
            organo_rows.append({
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
                "description": _top_hit_cpv_es_name(b.get("nombre"), b["key"]),
            })

        # Histograma pode ter valores negativos (correções); ignoramos bins < 0.
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
            "top_entities": organo_rows + adjudicatario_rows,
            "top_cpv": cpv_rows,
            "procedure_types": [{"key": b["key"], "count": b["doc_count"]} for b in aggs["procedure_types"]["buckets"]],
            "contract_types": [{"key": b["key"], "count": b["doc_count"]} for b in aggs["contract_types"]["buckets"]],
            "year": ano,
        }
    except Exception as exc:
        return {"error": str(exc)}
