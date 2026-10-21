"""Motor de grafos: agregação de nós/arestas e grafos por empresa.

Módulo do pacote :mod:`api.es` — ver `api/elasticsearch_client.py`,
que continua a expor a API pública (os coletores/serviços importam de lá).
"""
import logging
import re
from typing import Any, Dict, List, Optional

from elasticsearch import Elasticsearch
from api.es.contratos import _build_contract_query, _resolve_agg_target, get_company_contracts
from api.es.core import UNSPECIFIED_LABEL, get_es_client
from api.es.entidades import get_entity_by_nif
from api.es.indices import CONTRACTS_INDEX
from api.es.mappings import ensure_indices
from api.es.pessoas import people_graph_for_company

logger = logging.getLogger(__name__)




# --- Construtor genérico de grafos de contratos ---------------------------------
#
# Cada dimensão descreve uma forma de agrupar contratos em nós. O construtor
# agrega uma amostra de contratos (por valor ou por data) em nós/arestas,
# devolvendo sempre `count` e `total_value`/`value` para a UI poder alternar
# entre a métrica de contratos e a métrica de valor sem novo pedido.

GRAPH_DIMENSIONS: Dict[str, Dict[str, str]] = {
    "adjudicante": {"label": "Entidade adjudicante", "type": "entidade"},
    "adjudicatario": {"label": "Entidade adjudicatária", "type": "entidade"},
    "entidade": {"label": "Entidade (qualquer papel)", "type": "entidade"},
    "concorrente": {"label": "Concorrente", "type": "concorrente"},
    "regiao": {"label": "Região (NUTS)", "type": "regiao"},
    "local_execucao": {"label": "Local de execução", "type": "regiao"},
    "cpv_divisao": {"label": "CPV — divisão (2 dígitos)", "type": "cpv"},
    "cpv_classe": {"label": "CPV — classe (4 dígitos)", "type": "cpv"},
    "procedimento": {"label": "Tipo de procedimento", "type": "processo"},
    "tipo_contrato": {"label": "Tipo de contrato", "type": "processo"},
    "pme": {"label": "Adjudicatário PME", "type": "processo"},
    "ano": {"label": "Ano", "type": "tempo"},
}



_GRAPH_SOURCE_FIELDS = [
    "idcontrato",
    "precoContratual",
    "PrecoTotalEfetivo",
    "Ano",
    "NUTs",
    "localExecucao",
    "tipoprocedimento",
    "tipoContrato",
    "adjudicatarioPMEs",
    "concorrentes",
    "cpv",
    "adjudicantes.parsed",
    "adjudicatarios.parsed",
]



# Separa "500233810-NOME, LDA., 502540249-OUTRA, LDA." em pares NIF/nome.
# O NIF pode vir mascarado como "--" em alguns contratos, daí a alternância.
_COMPETITOR_SPLIT_RE = re.compile(r",?\s*(?=(?:\d{9}|--)\s*-)")


_COMPETITOR_RE = re.compile(r"^(\d{9})\s*-\s*(.+)$")



# Máximo de valores considerados por contrato e por lado (evita explosão combinatória).
_GRAPH_MAX_VALUES_PER_DOC = 10



# Tetos de segurança do servidor. O cliente pode pedir "sem limite" (0), ficando
# sujeito a estes valores — devolvidos em `meta` para serem visíveis na UI.
GRAPH_MAX_SCAN = 400_000


GRAPH_MAX_NODES = 10_000


GRAPH_MAX_EDGES = 30_000


GRAPH_MAX_AGG_BUCKETS = 10_000


# Orçamento de buckets por pedido de agregação (o Elasticsearch falha acima de ~65 mil).
GRAPH_AGG_BUCKET_BUDGET = 20_000



# Dimensões agregáveis por termos (as restantes exigem varredura por documento,
# como `concorrente`, cujo campo textual tem vários valores por contrato).
_GRAPH_AGG_FIELDS: Dict[str, Dict[str, Optional[str]]] = {
    "adjudicante": {
        "nested": "adjudicantes.parsed",
        "field": "adjudicantes.parsed.nif",
        "label": "adjudicantes.parsed.nome",
    },
    "adjudicatario": {
        "nested": "adjudicatarios.parsed",
        "field": "adjudicatarios.parsed.nif",
        "label": "adjudicatarios.parsed.nome",
    },
    "regiao": {"nested": None, "field": "NUTs", "label": None, "missing": True},
    "local_execucao": {"nested": None, "field": "localExecucao", "label": None, "missing": True},
    "cpv_classe": {"nested": "cpv", "field": "cpv.code", "label": None},
    "cpv_divisao": {"nested": "cpv", "field": "cpv.code", "label": None},
    "procedimento": {"nested": None, "field": "tipoprocedimento", "label": None, "missing": True},
    "tipo_contrato": {"nested": None, "field": "tipoContrato", "label": None, "missing": True},
    "pme": {"nested": None, "field": "adjudicatarioPMEs", "label": None, "missing": True},
    "ano": {"nested": None, "field": "Ano", "label": None},
}




def _as_list(value: Any) -> List[Any]:
    """Normaliza valores que o Elasticsearch pode devolver como escalar ou lista."""
    if value is None:
        return []
    if isinstance(value, list):
        return value
    return [value]




def _graph_parties(source: Dict[str, Any], key: str) -> List[Dict[str, str]]:
    """Extrai as entidades de `adjudicantes`/`adjudicatarios` (nested parsed)."""
    block = source.get(key) or {}
    if not isinstance(block, dict):
        return []
    out: List[Dict[str, str]] = []
    for party in _as_list(block.get("parsed")):
        if not isinstance(party, dict):
            continue
        nif = str(party.get("nif") or "").strip()
        nome = str(party.get("nome") or "").strip()
        if not nif and not nome:
            continue
        out.append({"id": nif or nome, "label": nome or nif})
    return out




def _graph_competitors(source: Dict[str, Any]) -> List[Dict[str, str]]:
    """Extrai os concorrentes do campo textual `concorrentes`."""
    raw = source.get("concorrentes")
    if not raw:
        return []
    chunks: List[str] = []
    for part in _as_list(raw):
        chunks.extend(_COMPETITOR_SPLIT_RE.split(str(part)))
    out: List[Dict[str, str]] = []
    seen: set = set()
    for chunk in chunks:
        text = chunk.strip().strip(",").strip()
        if not text:
            continue
        # Alguns contratos mascaram o NIF como "--"; nesses casos só há nome.
        if text.startswith("--"):
            text = text.lstrip("-").strip()
        match = _COMPETITOR_RE.match(text)
        if match:
            nif, nome = match.group(1), match.group(2).strip()
        else:
            nif, nome = "", text
        node_id = nif or nome
        if not node_id or node_id in seen:
            continue
        seen.add(node_id)
        out.append({"id": node_id, "label": nome or node_id})
    return out




def _dimension_values(source: Dict[str, Any], dimension: str) -> List[Dict[str, Any]]:
    """Devolve os valores de uma dimensão para um contrato: [{id, label, description?}]."""
    if dimension in ("adjudicante", "adjudicatario", "entidade"):
        values: List[Dict[str, Any]] = []
        if dimension in ("adjudicante", "entidade"):
            values.extend(_graph_parties(source, "adjudicantes"))
        if dimension in ("adjudicatario", "entidade"):
            values.extend(_graph_parties(source, "adjudicatarios"))
        return values

    if dimension == "concorrente":
        return _graph_competitors(source)

    if dimension == "regiao":
        out = []
        for nuts in _as_list(source.get("NUTs")):
            text = str(nuts or "").strip()
            if not text:
                continue
            code = text.split(" - ")[0].strip() or text
            out.append({"id": code, "label": text})
        # Contratos sem NUTs entram como "Não especificado" (em vez de desaparecerem).
        return out or [{"id": UNSPECIFIED_LABEL, "label": UNSPECIFIED_LABEL}]

    if dimension == "local_execucao":
        out = []
        for local in _as_list(source.get("localExecucao")):
            text = str(local or "").strip()
            if text:
                out.append({"id": text, "label": text})
        return out or [{"id": UNSPECIFIED_LABEL, "label": UNSPECIFIED_LABEL}]

    if dimension in ("cpv_divisao", "cpv_classe"):
        size = 2 if dimension == "cpv_divisao" else 4
        out = []
        seen_codes: set = set()
        for entry in _as_list(source.get("cpv")):
            if not isinstance(entry, dict):
                continue
            digits = re.sub(r"\D", "", str(entry.get("code") or ""))
            if len(digits) < size:
                continue
            prefix = digits[:size]
            if prefix in seen_codes:
                continue
            seen_codes.add(prefix)
            description = str(entry.get("description") or "").strip()
            if dimension == "cpv_divisao":
                # A descrição ao nível da divisão não é representativa (varia por classe).
                out.append({"id": prefix, "label": f"CPV {prefix}"})
            else:
                out.append({
                    "id": prefix,
                    "label": f"{prefix} — {description}" if description else prefix,
                    "description": description,
                })
        return out

    if dimension == "ano":
        ano = source.get("Ano")
        return [{"id": str(ano), "label": str(ano)}] if ano not in (None, "") else []

    if dimension == "procedimento":
        out = []
        for value in _as_list(source.get("tipoprocedimento")):
            text = str(value or "").strip()
            if text:
                out.append({"id": text, "label": text})
        return out or [{"id": UNSPECIFIED_LABEL, "label": UNSPECIFIED_LABEL}]

    if dimension == "tipo_contrato":
        out = []
        for value in _as_list(source.get("tipoContrato")):
            text = str(value or "").strip()
            if text:
                out.append({"id": text, "label": text})
        return out or [{"id": UNSPECIFIED_LABEL, "label": UNSPECIFIED_LABEL}]

    if dimension == "pme":
        out = []
        for value in _as_list(source.get("adjudicatarioPMEs")):
            text = str(value or "").strip()
            if text:
                out.append({"id": text, "label": text})
        return out or [{"id": UNSPECIFIED_LABEL, "label": UNSPECIFIED_LABEL}]

    return []




def _graph_add_node(
    nodes: Dict[str, Dict[str, Any]],
    descriptions: Dict[str, Dict[str, int]],
    dimension: str,
    item: Dict[str, Any],
    value: float,
) -> str:
    """Acumula um nó (contagem + valor) e devolve o seu id único."""
    node_id = f"{dimension}|{item['id']}"
    node = nodes.get(node_id)
    if node is None:
        node = nodes[node_id] = {
            "id": node_id,
            "key": item["id"],
            "label": item.get("label") or item["id"],
            "dimension": dimension,
            "type": GRAPH_DIMENSIONS[dimension]["type"],
            "role": GRAPH_DIMENSIONS[dimension]["label"],
            "count": 0,
            "total_value": 0.0,
        }
    node["count"] += 1
    node["total_value"] += value
    description = item.get("description")
    if description:
        bucket = descriptions.setdefault(node_id, {})
        bucket[description] = bucket.get(description, 0) + 1
    return node_id




def _graph_add_edge(
    edges: Dict[str, Dict[str, Any]],
    source: str,
    target: str,
    value: float,
    directed: bool,
) -> None:
    """Acumula uma aresta; em grafos não dirigidos os extremos são normalizados."""
    if not directed and target < source:
        source, target = target, source
    key = f"{source}->{target}"
    edge = edges.get(key)
    if edge is None:
        edge = edges[key] = {"source": source, "target": target, "count": 0, "value": 0.0}
    edge["count"] += 1
    edge["value"] += value




def _aggregate_dimension_buckets(
    client: Elasticsearch,
    query: Dict[str, Any],
    target: str,
    metric: str,
    size: int,
    with_description: bool,
) -> Optional[Dict[str, Any]]:
    """Agrega uma dimensão em termos (exato sobre todos os contratos filtrados)."""
    spec = _GRAPH_AGG_FIELDS.get(target)
    if not spec:
        return None

    field = spec["field"] or ""
    runtime: Optional[Dict[str, Any]] = None
    if spec["nested"] is None:
        resolved = _resolve_agg_target(client, field)
        field = resolved["field"]
        runtime = resolved.get("runtime")

    order: Dict[str, Any] = {"valor": "desc"} if metric == "valor" else {"_count": "desc"}
    bucket_aggs: Dict[str, Any] = {}
    if spec["nested"]:
        bucket_aggs["valor"] = {
            "reverse_nested": {},
            "aggs": {"total": {"sum": {"field": "precoContratual"}}},
        }
    else:
        bucket_aggs["valor"] = {"sum": {"field": "precoContratual"}}
    if spec["label"]:
        bucket_aggs["rotulo"] = {"terms": {"field": spec["label"], "size": 1}}
    if with_description and spec["nested"] == "cpv":
        # `cpv.description` é texto (fielddata desativada): só é recolhido quando há
        # poucos buckets, para não devolver milhares de documentos.
        bucket_aggs["amostra"] = {"top_hits": {"size": 1, "_source": ["cpv"]}}

    terms_agg: Dict[str, Any] = {
        "terms": {"field": field, "size": size, "order": order},
        "aggs": bucket_aggs,
    }
    if spec.get("missing"):
        # Contratos sem valor no campo formam o grupo "Não especificado".
        terms_agg["terms"]["missing"] = UNSPECIFIED_LABEL
    agg_body: Dict[str, Any] = (
        {"nested": {"path": spec["nested"]}, "aggs": {"buckets": terms_agg}}
        if spec["nested"]
        else terms_agg
    )

    body: Dict[str, Any] = {
        "size": 0,
        "track_total_hits": True,
        "query": query,
        "aggs": {"dim": agg_body, "total_value": {"sum": {"field": "precoContratual"}}},
    }
    if runtime:
        body["runtime_mappings"] = runtime

    resp = client.search(index=CONTRACTS_INDEX, body=body)
    node = resp["aggregations"]["dim"]
    if spec["nested"]:
        node = node["buckets"]
    total_block = resp.get("hits", {}).get("total") or {}
    return {
        "buckets": node.get("buckets", []),
        "other_doc_count": node.get("sum_other_doc_count", 0),
        "documents_matching": total_block.get("value", 0) if isinstance(total_block, dict) else 0,
        "documents_value": resp["aggregations"]["total_value"].get("value") or 0.0,
    }




def aggregate_graph_nodes(
    client: Elasticsearch,
    query: Dict[str, Any],
    dimension: str,
    metric: str,
    limit: int,
    max_buckets: int = GRAPH_MAX_AGG_BUCKETS,
) -> Optional[Dict[str, Any]]:
    """Grafo de um nível calculado por agregações: exato sobre TODOS os contratos.

    Devolve `None` quando a dimensão não é agregável (ex.: concorrentes), para o
    chamador fazer a varredura por documento.
    """
    targets = ["adjudicante", "adjudicatario"] if dimension == "entidade" else [dimension]
    if not targets or any(target not in _GRAPH_AGG_FIELDS for target in targets):
        return None

    requested = limit if limit else max_buckets
    size = max(10, min(requested * (2 if len(targets) > 1 else 1), max_buckets))
    with_description = size <= 400
    use_prefix = dimension in ("cpv_classe", "cpv_divisao")
    prefix_size = 4 if dimension == "cpv_classe" else 2

    aggregated: Dict[str, Dict[str, Any]] = {}
    other_doc_count = 0
    documents_matching = 0
    documents_value = 0.0

    for target in targets:
        result = _aggregate_dimension_buckets(client, query, target, metric, size, with_description)
        if result is None:
            return None
        other_doc_count += result["other_doc_count"]
        documents_matching = max(documents_matching, result["documents_matching"])
        documents_value = max(documents_value, result["documents_value"])

        for bucket in result["buckets"]:
            raw_key = str(bucket["key"])
            if not raw_key:
                if not spec.get("missing"):
                    continue
                raw_key = UNSPECIFIED_LABEL
            if raw_key == "N/A":
                continue
            label = raw_key
            description = ""
            rotulo = bucket.get("rotulo", {}).get("buckets") or []
            if rotulo:
                label = str(rotulo[0]["key"])
            if use_prefix:
                digits = re.sub(r"\D", "", raw_key)
                if len(digits) < prefix_size:
                    continue
                key = digits[:prefix_size]
                label = f"CPV {key}"
                samples = (bucket.get("amostra", {}).get("hits", {}).get("hits") or [])
                if samples:
                    for entry in _as_list((samples[0].get("_source") or {}).get("cpv")):
                        if not isinstance(entry, dict):
                            continue
                        code = re.sub(r"\D", "", str(entry.get("code") or ""))
                        if code.startswith(key):
                            description = str(entry.get("description") or "").strip()
                            if description:
                                break
            elif dimension == "regiao":
                key = raw_key.split(" - ")[0].strip() or raw_key
                label = raw_key
            elif dimension == "ano":
                key = raw_key
                label = raw_key
            else:
                key = raw_key

            value = bucket.get("valor")
            value = value.get("total", {}).get("value") if isinstance(value, dict) and "total" in value else value
            value = value.get("value") if isinstance(value, dict) else value
            entry = aggregated.get(key)
            if entry is None:
                entry = aggregated[key] = {
                    "id": f"{dimension}|{key}",
                    "key": key,
                    "label": label,
                    "dimension": dimension,
                    "type": GRAPH_DIMENSIONS[dimension]["type"],
                    "role": GRAPH_DIMENSIONS[dimension]["label"],
                    "count": 0,
                    "total_value": 0.0,
                }
            entry["count"] += int(bucket.get("doc_count") or 0)
            entry["total_value"] += float(value or 0)
            if use_prefix and description and " — " not in entry["label"]:
                entry["label"] = f"{key} — {description}"

    metric_key = "total_value" if metric == "valor" else "count"
    ordered = sorted(aggregated.values(), key=lambda node: node.get(metric_key) or 0, reverse=True)
    kept = ordered[:limit] if limit else ordered
    kept_value = sum(node["total_value"] for node in kept)
    kept_count = sum(node["count"] for node in kept)

    notes = ["Valores exatos para todos os contratos que correspondem aos filtros (sem amostragem)."]
    if len(ordered) > len(kept):
        notes.append(f"Mostrados {len(kept)} de {len(ordered)} nós agregados.")
    if other_doc_count:
        notes.append("Existem agrupamentos além dos apresentados (limite de buckets do Elasticsearch).")
    if use_prefix and not with_description and len(kept) > 400:
        notes.append("Descrições CPV omitidas acima de 400 nós.")

    return {
        "nodes": kept,
        "edges": [],
        "meta": {
            "dimension_a": dimension,
            "dimension_b": None,
            "metric": metric,
            "mode": "exato",
            "complete": len(ordered) <= len(kept) and other_doc_count == 0,
            "sample_order": "exato",
            "sample_limit": None,
            "documents_scanned": documents_matching,
            "documents_matching": documents_matching,
            "scanned_value": round(documents_value, 2),
            "nodes_total": len(ordered),
            "edges_total": 0,
            "kept_nodes": len(kept),
            "kept_edges": 0,
            "omitted_edges": 0,
            "coverage_value_share": round(kept_value / documents_value, 4) if documents_value else None,
            "coverage_count_share": None if not documents_matching else round(kept_count / max(documents_matching, 1), 4),
            "directed": False,
            "limits": {
                "max_scan": GRAPH_MAX_SCAN,
                "max_nodes": GRAPH_MAX_NODES,
                "max_edges": GRAPH_MAX_EDGES,
                "max_buckets": max_buckets,
            },
            "notes": notes,
            "filters": {"query": None},
        },
    }




def _resolve_dimension_spec(client: Elasticsearch, dimension: str) -> Optional[Dict[str, Any]]:
    """Resolve o campo agregável de uma dimensão (campo/subcampo/runtime) ou None."""
    spec = _GRAPH_AGG_FIELDS.get(dimension)
    if not spec:
        return None
    resolved = dict(spec)
    if spec["nested"] is None:
        target = _resolve_agg_target(client, spec["field"] or "")
        resolved["field"] = target["field"]
        resolved["runtime"] = target.get("runtime")
    return resolved




def _terms_block(spec: Dict[str, Any], metric: str, size: int, with_label: bool) -> Dict[str, Any]:
    """Bloco de agregação de termos com contagem de contratos e soma de valor."""
    order: Dict[str, Any] = {"valor": "desc"} if metric == "valor" else {"_count": "desc"}
    aggs: Dict[str, Any] = {}
    if spec["nested"]:
        aggs["valor"] = {"reverse_nested": {}, "aggs": {"total": {"sum": {"field": "precoContratual"}}}}
    else:
        aggs["valor"] = {"sum": {"field": "precoContratual"}}
    if with_label and spec.get("label"):
        aggs["rotulo"] = {"terms": {"field": spec["label"], "size": 1}}
    if with_label and spec.get("nested") == "cpv" and size <= 400:
        # `cpv.description` é texto (fielddata desativada): recolhido só com poucos buckets.
        aggs["amostra"] = {"top_hits": {"size": 1, "_source": ["cpv"]}}
    block: Dict[str, Any] = {
        "terms": {"field": spec["field"], "size": size, "order": order},
        "aggs": aggs,
    }
    if spec.get("missing"):
        # Contratos sem valor no campo passam a formar o grupo "Não especificado".
        block["terms"]["missing"] = UNSPECIFIED_LABEL
    if spec["nested"]:
        return {"nested": {"path": spec["nested"]}, "aggs": {"buckets": block}}
    return block




def _graph_key_for(dimension: str, raw_key: str) -> Optional[str]:
    """Normaliza a chave de um valor agregado (prefixo CPV, código NUTS) — igual em nós e arestas."""
    if dimension in ("cpv_classe", "cpv_divisao"):
        size = 4 if dimension == "cpv_classe" else 2
        digits = re.sub(r"\D", "", raw_key)
        return digits[:size] if len(digits) >= size else None
    if dimension == "regiao":
        return raw_key.split(" - ")[0].strip() or raw_key
    return raw_key




def _descriptions_from_bucket(bucket: Dict[str, Any], key: str) -> str:
    """Extrai a descrição CPV (top_hits) correspondente ao prefixo do bucket."""
    samples = bucket.get("amostra", {}).get("hits", {}).get("hits") or []
    for sample in samples:
        for entry in _as_list((sample.get("_source") or {}).get("cpv")):
            if not isinstance(entry, dict):
                continue
            code = re.sub(r"\D", "", str(entry.get("code") or ""))
            if code.startswith(key):
                description = str(entry.get("description") or "").strip()
                if description:
                    return description
    return ""




def _extract_buckets(node: Any) -> List[Dict[str, Any]]:
    """Extrai a lista de buckets de um bloco de termos (aceita wrappers de `nested`)."""
    for _hop in range(3):
        if isinstance(node, dict) and isinstance(node.get("buckets"), dict):
            node = node["buckets"]
            continue
        break
    if isinstance(node, dict):
        node = node.get("buckets")
    return node if isinstance(node, list) else []




def _bucket_value(bucket: Dict[str, Any]) -> float:
    value = bucket.get("valor")
    if isinstance(value, dict) and "total" in value and isinstance(value["total"], dict):
        value = value["total"].get("value")
    elif isinstance(value, dict):
        value = value.get("value")
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0




def _nodes_from_buckets(
    block: Dict[str, Any],
    dimension: str,
    spec: Dict[str, Any],
    total: Dict[str, Dict[str, Any]],
) -> None:
    """Acumula buckets de termos no dicionário de nós (chave, rótulo, contagem, valor)."""
    buckets = block.get("buckets") if spec.get("nested") else block
    buckets = _extract_buckets(buckets)
    use_prefix = dimension in ("cpv_classe", "cpv_divisao")
    prefix_size = 4 if dimension == "cpv_classe" else 2

    for bucket in buckets:
        raw_key = str(bucket.get("key"))
        if raw_key == "N/A":
            continue
        if not raw_key:
            # Campo presente mas vazio: conta como "Não especificado".
            if not spec.get("missing"):
                continue
            raw_key = UNSPECIFIED_LABEL
        key = _graph_key_for(dimension, raw_key)
        if not key:
            continue
        label = raw_key
        rotulo = (bucket.get("rotulo") or {}).get("buckets") or []
        if rotulo:
            label = str(rotulo[0]["key"])
        if use_prefix:
            label = f"CPV {key}" if dimension == "cpv_divisao" else key
            description = _descriptions_from_bucket(bucket, key)
            if description and dimension == "cpv_classe":
                label = f"{key} — {description}"
        elif dimension == "regiao":
            label = raw_key

        node = total.get(key)
        if node is None:
            node = total[key] = {
                "id": f"{dimension}|{key}",
                "key": key,
                "label": label,
                "dimension": dimension,
                "type": GRAPH_DIMENSIONS[dimension]["type"],
                "role": GRAPH_DIMENSIONS[dimension]["label"],
                "count": 0,
                "total_value": 0.0,
            }
        node["count"] += int(bucket.get("doc_count") or 0)
        node["total_value"] += _bucket_value(bucket)




def aggregate_graph_edges(
    client: Elasticsearch,
    query: Dict[str, Any],
    dimension_a: str,
    dimension_b: str,
    metric: str,
    limit: int,
    edge_limit: int,
) -> Optional[Dict[str, Any]]:
    """Grafo de dois níveis exato (todos os contratos) por agregações.

    Corre três agregações no mesmo pedido: nós do lado A, nós do lado B (ambas
    exatas) e os pares A→B. Devolve `None` quando alguma dimensão não é agregável.
    """
    spec_a = _resolve_dimension_spec(client, dimension_a)
    spec_b = _resolve_dimension_spec(client, dimension_b)
    if not spec_a or not spec_b:
        return None

    node_size = min(limit or GRAPH_MAX_AGG_BUCKETS, GRAPH_MAX_AGG_BUCKETS)
    pair_budget = max(5, GRAPH_AGG_BUCKET_BUDGET // max(node_size, 1))
    pair_size = max(5, min(edge_limit or 200, pair_budget))

    edges_agg = _terms_block(spec_a, metric, node_size, with_label=False)
    inner = _terms_block(spec_b, metric, pair_size, with_label=False)
    if spec_a["nested"]:
        # `reverse_nested` volta ao documento pai: é aí que a dimensão B tem de viver.
        edges_agg["aggs"]["buckets"]["aggs"]["valor"]["aggs"]["links"] = inner
    else:
        edges_agg["aggs"]["links"] = inner

    runtime_mappings: Dict[str, Any] = {}
    for spec in (spec_a, spec_b):
        if spec.get("runtime"):
            runtime_mappings.update(spec["runtime"])

    body: Dict[str, Any] = {
        "size": 0,
        "track_total_hits": True,
        "query": query,
        "aggs": {
            "nodes_a": _terms_block(spec_a, metric, node_size, with_label=True),
            "nodes_b": _terms_block(spec_b, metric, node_size, with_label=True),
            "edges": edges_agg,
            "total_value": {"sum": {"field": "precoContratual"}},
        },
    }
    if runtime_mappings:
        body["runtime_mappings"] = runtime_mappings

    try:
        resp = client.search(index=CONTRACTS_INDEX, body=body)
    except Exception:
        # Por exemplo, acima do teto de buckets: o chamador cai para a varredura.
        return None
    aggregations = resp["aggregations"]

    nodes_a: Dict[str, Dict[str, Any]] = {}
    nodes_b: Dict[str, Dict[str, Any]] = {}
    _nodes_from_buckets(aggregations["nodes_a"], dimension_a, spec_a, nodes_a)
    _nodes_from_buckets(aggregations["nodes_b"], dimension_b, spec_b, nodes_b)

    metric_key = "total_value" if metric == "valor" else "count"
    ordered_a = sorted(nodes_a.values(), key=lambda node: node.get(metric_key) or 0, reverse=True)
    ordered_b = sorted(nodes_b.values(), key=lambda node: node.get(metric_key) or 0, reverse=True)
    kept_a = ordered_a[:limit] if limit else ordered_a
    kept_b = ordered_b[:limit] if limit else ordered_b
    kept_ids = {node["id"] for node in kept_a} | {node["id"] for node in kept_b}

    edges: Dict[str, Dict[str, Any]] = {}
    edges_block = aggregations["edges"]
    a_buckets = _extract_buckets(edges_block.get("buckets") if spec_a["nested"] else edges_block)
    for a_bucket in a_buckets:
        a_key = _graph_key_for(dimension_a, str(a_bucket.get("key")))
        if not a_key:
            continue
        a_id = f"{dimension_a}|{a_key}"
        if a_id not in kept_ids:
            continue
        links = a_bucket["valor"].get("links") if spec_a["nested"] else a_bucket.get("links")
        if not links:
            continue
        for b_bucket in _extract_buckets(links):
            b_key = _graph_key_for(dimension_b, str(b_bucket.get("key")))
            if not b_key:
                continue
            b_id = f"{dimension_b}|{b_key}"
            if b_id not in kept_ids:
                continue
            key = f"{a_id}->{b_id}"
            edge = edges.get(key)
            if edge is None:
                edge = edges[key] = {"source": a_id, "target": b_id, "count": 0, "value": 0.0}
            edge["count"] += int(b_bucket.get("doc_count") or 0)
            edge["value"] += _bucket_value(b_bucket)

    edge_metric = "value" if metric == "valor" else "count"
    ordered_edges = sorted(edges.values(), key=lambda edge: edge.get(edge_metric) or 0, reverse=True)
    dropped_edges = max(0, len(ordered_edges) - edge_limit) if edge_limit else 0
    kept_edges = ordered_edges[:edge_limit] if edge_limit else ordered_edges

    total_value = aggregations["total_value"].get("value") or 0.0
    total_block = resp.get("hits", {}).get("total") or {}
    documents_matching = total_block.get("value", 0) if isinstance(total_block, dict) else 0
    kept_value = sum(node["total_value"] for node in kept_a)
    kept_count = sum(node["count"] for node in kept_a)

    notes = ["Valores exatos para todos os contratos que correspondem aos filtros (sem amostragem)."]
    if len(ordered_a) > len(kept_a) or len(ordered_b) > len(kept_b):
        notes.append(
            f"Mostrados {len(kept_a)} nós de {len(ordered_a)} no lado A e "
            f"{len(kept_b)} de {len(ordered_b)} no lado B."
        )
    if pair_size < (edge_limit or 200):
        notes.append(
            f"Cada nó mostra até {pair_size} ligações por pedido de agregação "
            "(aumente as arestas ou reduza os nós para ver pares adicionais)."
        )
    if dropped_edges:
        notes.append(f"{dropped_edges} arestas omitidas por limite (aumente 'arestas' ou reduza os nós).")

    return {
        "nodes": kept_a + kept_b,
        "edges": kept_edges,
        "meta": {
            "dimension_a": dimension_a,
            "dimension_b": dimension_b,
            "metric": metric,
            "mode": "exato",
            "complete": len(ordered_a) <= len(kept_a) and len(ordered_b) <= len(kept_b) and not dropped_edges,
            "sample_order": "exato",
            "sample_limit": None,
            "documents_scanned": documents_matching,
            "documents_matching": documents_matching,
            "scanned_value": round(total_value, 2),
            "nodes_total": len(ordered_a) + len(ordered_b),
            "edges_total": len(ordered_edges),
            "kept_nodes": len(kept_a) + len(kept_b),
            "kept_edges": len(kept_edges),
            "omitted_edges": dropped_edges,
            "coverage_value_share": round(kept_value / total_value, 4) if total_value else None,
            "coverage_count_share": round(kept_count / max(documents_matching, 1), 4) if documents_matching else None,
            "directed": True,
            "limits": {
                "max_scan": GRAPH_MAX_SCAN,
                "max_nodes": GRAPH_MAX_NODES,
                "max_edges": GRAPH_MAX_EDGES,
                "max_buckets": GRAPH_MAX_AGG_BUCKETS,
            },
            "notes": notes,
            "filters": {"query": None},
        },
    }




def build_contract_graph(
    dimension_a: str,
    dimension_b: Optional[str] = None,
    metric: str = "valor",
    mode: str = "auto",
    q: Optional[str] = None,
    year: Optional[int] = None,
    region: Optional[str] = None,
    cpv_code: Optional[str] = None,
    min_value: Optional[float] = None,
    max_value: Optional[float] = None,
    limit: int = 60,
    edge_limit: int = 400,
    sample: int = 3000,
    sample_order: str = "valor",
    es: Optional[Elasticsearch] = None,
) -> Dict[str, Any]:
    """Constrói um grafo de contratos segundo duas dimensões (nós e arestas).

    - `dimension_b` igual a `dimension_a` → rede de co-ocorrência (ex.: concorrentes
      que participam nos mesmos contratos).
    - `dimension_b` nulo → apenas nós (para treemaps, rankings e mapas).
    - `metric` decide que nós/arestas são mantidos nos limites pedidos; os dois
      valores (contratos e valor) são sempre devolvidos.
    - `mode`:
      - `exato`: sem amostragem. Com uma só dimensão usa agregações do Elasticsearch
        (todos os contratos que correspondem aos filtros); com arestas percorre todos
        os contratos até ao teto do servidor.
      - `amostra`: percorre apenas `sample` contratos (ordem `sample_order`).
      - `auto` (por omissão): `exato` quando não há dimensão B.
    - `limit`, `edge_limit` e `sample` aceitam 0 = "todos" (sujeito aos tetos
      `GRAPH_MAX_NODES`, `GRAPH_MAX_EDGES` e `GRAPH_MAX_SCAN`, devolvidos em `meta`).
    """
    client = es or get_es_client()
    if not client:
        return {"error": "Elasticsearch indisponível", "nodes": [], "edges": []}
    if dimension_a not in GRAPH_DIMENSIONS:
        return {"error": f"Dimensão desconhecida: {dimension_a}", "nodes": [], "edges": []}
    if dimension_b and dimension_b not in GRAPH_DIMENSIONS:
        return {"error": f"Dimensão desconhecida: {dimension_b}", "nodes": [], "edges": []}

    dimension_b = dimension_b or None
    metric = metric if metric in ("valor", "contratos") else "valor"
    mode = mode if mode in ("auto", "exato", "amostra") else "auto"
    same_dimension = dimension_b == dimension_a

    query = _build_contract_query(
        q=q,
        year=year,
        region=region,
        cpv_code=cpv_code,
        min_price=min_value,
        max_price=max_value,
    )

    # Caminho exato (sem amostragem) para grafos de um só nível.
    if mode in ("auto", "exato") and not dimension_b:
        exact = aggregate_graph_nodes(
            client,
            query,
            dimension_a,
            metric,
            limit=0 if int(limit) <= 0 else max(2, min(int(limit), GRAPH_MAX_NODES)),
        )
        if exact is not None:
            exact["meta"]["filters"] = {
                "q": q,
                "year": year,
                "region": region,
                "cpv_code": cpv_code,
                "min_value": min_value,
                "max_value": max_value,
            }
            return exact

    # Caminho exato com arestas: agregações de dois níveis (todos os contratos).
    if mode in ("auto", "exato") and dimension_b and not same_dimension:
        exact_edges = aggregate_graph_edges(
            client,
            query,
            dimension_a,
            dimension_b,
            metric,
            limit=0 if int(limit) <= 0 else max(2, min(int(limit), GRAPH_MAX_NODES)),
            edge_limit=0 if int(edge_limit) <= 0 else max(0, min(int(edge_limit), GRAPH_MAX_EDGES)),
        )
        if exact_edges is not None:
            exact_edges["meta"]["filters"] = {
                "q": q,
                "year": year,
                "region": region,
                "cpv_code": cpv_code,
                "min_value": min_value,
                "max_value": max_value,
            }
            return exact_edges

    all_documents = int(sample) <= 0
    scan_ceiling = GRAPH_MAX_SCAN
    sample = scan_ceiling if all_documents else max(100, min(int(sample), scan_ceiling))
    limit = 0 if int(limit) <= 0 else max(2, min(int(limit), GRAPH_MAX_NODES))
    edge_limit = 0 if int(edge_limit) <= 0 else max(0, min(int(edge_limit), GRAPH_MAX_EDGES))
    page_size = 5000 if all_documents else min(1000, sample)

    if sample_order == "recentes":
        sort: List[Any] = [
            {"dataPublicacao": {"order": "desc", "unmapped_type": "date"}},
            {"idcontrato": {"order": "asc"}},
        ]
    else:
        sort = [
            {"precoContratual": {"order": "desc", "unmapped_type": "float"}},
            {"idcontrato": {"order": "asc"}},
        ]

    nodes: Dict[str, Dict[str, Any]] = {}
    edges: Dict[str, Dict[str, Any]] = {}
    descriptions: Dict[str, Dict[str, int]] = {}
    scanned = 0
    scanned_value = 0.0
    total_hits = 0
    scan_capped = False

    try:
        search_after: Optional[List[Any]] = None
        while all_documents or scanned < sample:
            remaining = scan_ceiling - scanned
            if remaining <= 0:
                scan_capped = True
                break
            page = min(page_size, remaining)
            body: Dict[str, Any] = {
                "size": page,
                "query": query,
                "sort": sort,
                "_source": _GRAPH_SOURCE_FIELDS,
                "track_total_hits": True,
            }
            if search_after:
                body["search_after"] = search_after
            resp = client.search(index=CONTRACTS_INDEX, body=body)
            hits = resp.get("hits", {}).get("hits", [])
            total_block = resp.get("hits", {}).get("total") or {}
            total_hits = total_block.get("value", total_hits) if isinstance(total_block, dict) else total_hits
            if not hits:
                break

            for hit in hits:
                source = hit.get("_source") or {}
                scanned += 1
                raw_value = source.get("precoContratual") or source.get("PrecoTotalEfetivo") or 0
                try:
                    value = float(raw_value)
                except (TypeError, ValueError):
                    value = 0.0
                scanned_value += value

                values_a = _dimension_values(source, dimension_a)
                if not values_a:
                    continue
                ids_a = list(
                    dict.fromkeys(
                        _graph_add_node(nodes, descriptions, dimension_a, item, value)
                        for item in values_a[:_GRAPH_MAX_VALUES_PER_DOC]
                    )
                )
                if not dimension_b:
                    continue
                if same_dimension:
                    # Co-ocorrência: liga todos os pares presentes no mesmo contrato.
                    for index, left in enumerate(ids_a):
                        for right in ids_a[index + 1:]:
                            _graph_add_edge(edges, left, right, value, directed=False)
                    continue
                values_b = _dimension_values(source, dimension_b)
                ids_b = list(
                    dict.fromkeys(
                        _graph_add_node(nodes, descriptions, dimension_b, item, value)
                        for item in values_b[:_GRAPH_MAX_VALUES_PER_DOC]
                    )
                )
                for left in ids_a:
                    for right in ids_b:
                        _graph_add_edge(edges, left, right, value, directed=True)

            if len(hits) < page:
                break
            last_sort = hits[-1].get("sort")
            if not last_sort:
                break
            search_after = last_sort
    except Exception as exc:
        return {"error": str(exc), "nodes": [], "edges": []}

    # Rótulo descritivo mais frequente (ex.: classe CPV "4521 — Construção de edifícios").
    for node_id, bucket in descriptions.items():
        node = nodes.get(node_id)
        if not node or not bucket:
            continue
        best = max(bucket.items(), key=lambda kv: kv[1])[0]
        if best:
            node["label"] = f"{node['key']} — {best}"

    metric_key = "total_value" if metric == "valor" else "count"
    scored_nodes = sorted(nodes.values(), key=lambda node: (node.get(metric_key) or 0), reverse=True)
    kept_nodes = scored_nodes[:limit] if limit else scored_nodes
    kept_ids = {node["id"] for node in kept_nodes}
    kept_edges = [
        edge for edge in edges.values() if edge["source"] in kept_ids and edge["target"] in kept_ids
    ]
    edge_metric = "value" if metric == "valor" else "count"
    kept_edges.sort(key=lambda edge: (edge.get(edge_metric) or 0), reverse=True)
    dropped_edges = max(0, len(kept_edges) - edge_limit) if edge_limit else 0
    if edge_limit:
        kept_edges = kept_edges[:edge_limit]

    # Cobertura: independentemente do lado, usa os nós do lado A para reportar
    # quanto do valor/contratos ficou representado.
    side_a = [node for node in nodes.values() if node["dimension"] == dimension_a]
    side_a_total_count = sum(node["count"] for node in side_a) or 0
    side_a_total_value = sum(node["total_value"] for node in side_a) or 0.0
    kept_a = [node for node in kept_nodes if node["dimension"] == dimension_a]
    kept_a_count = sum(node["count"] for node in kept_a)
    kept_a_value = sum(node["total_value"] for node in kept_a)

    sampled = scanned < total_hits or scan_capped
    complete = not sampled and len(kept_nodes) == len(nodes) and not dropped_edges

    notes = []
    if scan_capped:
        notes.append(
            f"Varredura limitada a {scanned} de {total_hits} contratos (teto do servidor: "
            f"{GRAPH_MAX_SCAN}). Aplique filtros (ano, região, valor mínimo) para reduzir o conjunto."
        )
    elif sampled:
        notes.append(
            f"Amostra de {scanned} de {total_hits} contratos "
            f"({'maior valor' if sample_order == 'valor' else 'mais recentes'}). "
            "Use o modo exato ou 'todos os contratos' para valores completos."
        )
    else:
        notes.append(f"Todos os {total_hits} contratos do filtro foram analisados (sem amostragem).")
    if len(nodes) > len(kept_nodes):
        notes.append(f"Mostrados {len(kept_nodes)} de {len(nodes)} nós agregados.")
    if dropped_edges:
        notes.append(f"{dropped_edges} arestas omitidas por limite.")
    if same_dimension:
        notes.append("Arestas representam co-ocorrência no mesmo contrato; o valor é o total desses contratos.")

    return {
        "nodes": kept_nodes,
        "edges": kept_edges,
        "meta": {
            "dimension_a": dimension_a,
            "dimension_b": dimension_b,
            "metric": metric,
            "mode": "varredura-total" if all_documents else "amostra",
            "complete": complete,
            "scan_capped": scan_capped,
            "sample_order": sample_order,
            "sample_limit": None if all_documents else sample,
            "documents_scanned": scanned,
            "documents_matching": total_hits,
            "scanned_value": round(scanned_value, 2),
            "nodes_total": len(nodes),
            "edges_total": len(edges),
            "kept_nodes": len(kept_nodes),
            "kept_edges": len(kept_edges),
            "omitted_edges": dropped_edges,
            "coverage_value_share": round(kept_a_value / side_a_total_value, 4) if side_a_total_value else None,
            "coverage_count_share": round(kept_a_count / side_a_total_count, 4) if side_a_total_count else None,
            "directed": bool(dimension_b) and not same_dimension,
            "limits": {
                "max_scan": GRAPH_MAX_SCAN,
                "max_nodes": GRAPH_MAX_NODES,
                "max_edges": GRAPH_MAX_EDGES,
            },
            "notes": notes,
            "filters": {
                "q": q,
                "year": year,
                "region": region,
                "cpv_code": cpv_code,
                "min_value": min_value,
                "max_value": max_value,
            },
        },
    }




_UNIFIED_GRAPH_MAX_CONTRACTS = 200


_UNIFIED_GRAPH_MAX_PEOPLE = 100




def combined_graph_for_company(
    company_nif: str,
    include_people: bool = True,
    include_contracts: bool = True,
    contract_limit: int = 60,
    es: Optional[Elasticsearch] = None,
) -> Dict[str, Any]:
    """Grafo unificado: pessoas/cargos, contratos e entidades para um NIF.

    - Nó central: `company:<nif>` (empresa do cadastro).
    - Pessoas: nós `person:<nif>` ligadas por cargos/sócios.
    - Contratos: nós `entity:<nif>` de adjudicantes/adjudicatários ligados por
      arestas `contrato`, agregando valor e contagem.
    - Entidade: metadados do cadastro enriquecem o nó central.
    """
    client = es or get_es_client()
    if not client:
        return {"error": "Elasticsearch indisponível", "nodes": [], "edges": []}
    ensure_indices(client)

    nodes: Dict[str, Dict[str, Any]] = {}
    edges: Dict[str, Dict[str, Any]] = {}

    company_nif = str(company_nif)
    company_id = f"company:{company_nif}"

    # Enriquece com cadastro de entidades (melhor nome, contagem de contratos, etc.)
    entity = get_entity_by_nif(company_nif, es=client)
    company_name = entity.get("name") or company_nif
    if entity.get("error"):
        company_name = company_nif

    nodes[company_id] = {
        "id": company_id,
        "type": "company",
        "label": company_name,
        "nif": company_nif,
        "is_company": True,
        "entity": {
            "name": company_name,
            "country": entity.get("country"),
            "contracts_count": entity.get("contracts_count"),
            "as_adjudicante_count": entity.get("as_adjudicante_count"),
            "as_adjudicatario_count": entity.get("as_adjudicatario_count"),
            "total_value": entity.get("total_value"),
            "has_nif": entity.get("has_nif", True),
        },
    }

    total_people_edges = 0
    total_contract_nodes = 0
    total_contract_edges = 0
    contract_value_total = 0.0
    contract_count_total = 0

    if include_people:
        people = people_graph_for_company(company_nif, es=client)
        total_people_edges = people.get("edge_count", 0)
        for node in people.get("nodes", []):
            node_id = node["id"]
            if node_id in nodes:
                continue
            nodes[node_id] = {
                "id": node_id,
                "type": node.get("type", "person"),
                "label": node.get("label", node_id),
                "nif": node.get("nif"),
                "is_company": node.get("is_company", False),
            }
        for edge in people.get("edges", []):
            edge_id = f"{edge['source']}->{edge['target']}|{edge.get('role','')}"
            if edge_id not in edges:
                edges[edge_id] = {
                    "source": edge["source"],
                    "target": edge["target"],
                    "label": edge.get("label", ""),
                    "type": "role",
                    "role": edge.get("role"),
                    "role_org": edge.get("role_org"),
                    "event": edge.get("event"),
                    "date": edge.get("date"),
                    "acto": edge.get("acto"),
                    "quota": edge.get("quota"),
                    "count": 1,
                    "value": 0.0,
                }
            else:
                edges[edge_id]["count"] = edges[edge_id].get("count", 0) + 1

    if include_contracts:
        contract_data = get_company_contracts(
            nif=company_nif,
            role="all",
            size=_UNIFIED_GRAPH_MAX_CONTRACTS,
            es=client,
        )
        for contract in contract_data.get("items", [])[:_UNIFIED_GRAPH_MAX_CONTRACTS]:
            value = float(contract.get("precoContratual") or contract.get("PrecoTotalEfetivo") or 0)
            contract_count_total += 1
            contract_value_total += value
            other_role = None
            other_nif = None
            other_name = None
            # Determina o lado oposto da empresa central
            sides = []
            for party in contract.get("adjudicantes", {}).get("parsed", []):
                if party.get("nif") != company_nif:
                    sides.append(("adjudicante", party.get("nif"), party.get("nome")))
            for party in contract.get("adjudicatarios", {}).get("parsed", []):
                if party.get("nif") != company_nif:
                    sides.append(("adjudicatario", party.get("nif"), party.get("nome")))
            for role_side, onif, oname in sides:
                if not onif:
                    continue
                other_nif = onif
                other_name = oname or onif
                other_role = role_side
                entity_id = f"entity:{onif}"
                if entity_id in nodes:
                    existing = nodes[entity_id]
                    existing["contract_count"] = existing.get("contract_count", 0) + 1
                    existing["total_value"] = existing.get("total_value", 0.0) + value
                else:
                    total_contract_nodes += 1
                    nodes[entity_id] = {
                        "id": entity_id,
                        "type": "entity",
                        "label": other_name,
                        "nif": onif,
                        "is_company": True,
                        "role_side": other_role,
                        "contract_count": 1,
                        "total_value": value,
                    }
                edge_id = f"{company_id}<->{entity_id}"
                if edge_id not in edges:
                    edges[edge_id] = {
                        "source": company_id,
                        "target": entity_id,
                        "label": "contrato",
                        "type": "contract",
                        "count": 1,
                        "value": value,
                    }
                    total_contract_edges += 1
                else:
                    edges[edge_id]["count"] = edges[edge_id].get("count", 0) + 1
                    edges[edge_id]["value"] = edges[edge_id].get("value", 0.0) + value

    return {
        "company_nif": company_nif,
        "company_name": company_name,
        "nodes": list(nodes.values()),
        "edges": list(edges.values()),
        "node_count": len(nodes),
        "edge_count": len(edges),
        "meta": {
            "include_people": include_people,
            "include_contracts": include_contracts,
            "people_edge_count": total_people_edges,
            "contract_nodes": total_contract_nodes,
            "contract_edges": total_contract_edges,
            "contract_count_total": contract_count_total,
            "contract_value_total": round(contract_value_total, 2),
            "contract_limit": _UNIFIED_GRAPH_MAX_CONTRACTS,
            "notes": [
                "Grafo combinado: pessoas/cargos, contratos públicos e entidades.",
                f"Contratos analisados: {contract_count_total} (limite {_UNIFIED_GRAPH_MAX_CONTRACTS}).",
            ],
        },
    }
