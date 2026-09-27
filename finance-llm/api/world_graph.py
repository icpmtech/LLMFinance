"""Graph / Temporal Engine — relações, eventos, timestamps e causalidade.

O World Model deixa o mundo em três índices; este módulo responde às perguntas
de **grafo** e de **tempo** sobre esse estado:

- **Grafo** — `build_graph` (subgrafo em torno de uma entidade, para desenhar),
  `centrality` (entidades mais centrais por grau/valor) e `paths` (caminhos mais
  curtos entre duas entidades, por BFS sobre as arestas).
- **Tempo** — `temporal_profile` (série mensal de eventos e valores por
  entidade) e `causality` (pares de eventos temporalmente próximos em entidades
  **ligadas** entre si).

Sobre a causalidade (importante): não há aqui inferência causal estatística. O
que se calcula é uma **influência temporal candidata**: dois eventos de
entidades ligadas, separados por menos de `window_days`, com uma pontuação

    score = peso_relação × proximidade_temporal × severidade_origem

O resultado é uma **hipótese** (marcada como tal no relatório do agente de
investigação), útil para orientar a investigação — nunca apresentada como causa
provada.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

from elasticsearch import Elasticsearch

from api import world_model as model
from api.elasticsearch_client import (
    WORLD_EVENTS_INDEX,
    WORLD_RELATIONS_INDEX,
    WORLD_STATE_INDEX,
    get_es_client,
)

logger = logging.getLogger(__name__)

#: Dimensões disponíveis para construir grafos (a UI usa esta lista).
GRAPH_DIMENSIONS: List[Dict[str, Any]] = [
    {"id": "adjudicou", "label": "Adjudicações (entidade pública → empresa)", "kind": "relacao"},
    {"id": "cargo_em", "label": "Cargos (pessoa → empresa)", "kind": "relacao"},
    {"id": "risk", "label": "Risco (entidades com risco elevado/médio)", "kind": "entidade"},
    {"id": "insolvent", "label": "Insolvências", "kind": "entidade"},
    {"id": "value", "label": "Valor contratual", "kind": "metrica"},
    {"id": "events", "label": "Eventos por tipo", "kind": "metrica"},
]


def _client(es: Optional[Elasticsearch] = None) -> Optional[Elasticsearch]:
    return es or get_es_client(request_timeout=60)


# ---------------------------------------------------------------------------
# Grafo
# ---------------------------------------------------------------------------
def _degree_table(kind: Optional[str], size: int, es: Optional[Elasticsearch]) -> Dict[str, int]:
    """Grau (nº de arestas) por entidade, somando as duas extremidades."""
    client = _client(es)
    if client is None:
        return {}
    filters = [{"term": {"kind": kind}}] if kind else []
    body = {
        "size": 0,
        "track_total_hits": False,
        "query": {"bool": {"filter": filters}},
        "aggs": {
            "sources": {"terms": {"field": "source_ref", "size": size}},
            "targets": {"terms": {"field": "target_ref", "size": size}},
        },
    }
    try:
        resp = client.search(index=WORLD_RELATIONS_INDEX, body=body)
    except Exception as exc:
        logger.warning("Grau do grafo falhou: %s", exc)
        return {}
    aggs = resp.get("aggregations") or {}
    degree: Dict[str, int] = {}
    for key in ("sources", "targets"):
        for bucket in (aggs.get(key) or {}).get("buckets", []):
            degree[bucket["key"]] = degree.get(bucket["key"], 0) + int(bucket["doc_count"])
    return degree


def centrality(kind: Optional[str] = None, top: int = 20, es: Optional[Elasticsearch] = None) -> Dict[str, Any]:
    """Entidades mais centrais (grau) e o valor agregado das suas arestas."""
    client = _client(es)
    if client is None:
        return {"error": "Elasticsearch indisponível", "results": []}
    degree = _degree_table(kind, size=2000, es=client)
    refs = [ref for ref, _ in sorted(degree.items(), key=lambda item: item[1], reverse=True)[: max(1, top)]]
    if not refs:
        return {"results": [], "note": "Sem relações no mundo — reconstruir o mundo primeiro."}
    entities = _entities_by_ref(refs, es=client)
    results = []
    for ref in refs:
        entity = entities.get(ref) or {}
        results.append(
            {
                "entity_ref": ref,
                "name": entity.get("name") or ref,
                "entity_type": entity.get("entity_type"),
                "degree": degree.get(ref, 0),
                "contracts_value": entity.get("contracts_value"),
                "risk": entity.get("risk"),
                "risk_label": entity.get("risk_label"),
            }
        )
    return {"results": results, "kind": kind}


def _entities_by_ref(refs: List[str], es: Optional[Elasticsearch]) -> Dict[str, Dict[str, Any]]:
    client = es or _client()
    if client is None or not refs:
        return {}
    try:
        resp = client.mget(index=WORLD_STATE_INDEX, body={"ids": refs})
    except Exception:
        return {}
    out: Dict[str, Dict[str, Any]] = {}
    for doc in resp.get("docs") or []:
        if doc.get("found"):
            out[doc["_id"]] = doc.get("_source") or {}
    return out


def build_graph(
    entity_ref: Optional[str] = None,
    depth: int = 1,
    kind: Optional[str] = None,
    node_limit: int = 120,
    edge_limit: int = 400,
    es: Optional[Elasticsearch] = None,
) -> Dict[str, Any]:
    """Subgrafo do mundo em torno de uma entidade (ou o grafo global dos mais centrais).

    A expansão é BFS por `depth` níveis sobre as arestas do índice de relações;
    os nós e as arestas são cortados em `node_limit`/`edge_limit` (grafo grande
    não se desenha nem se lê).
    """
    client = _client(es)
    if client is None:
        return {"error": "Elasticsearch indisponível", "nodes": [], "edges": []}
    node_limit = max(2, min(400, int(node_limit)))
    edge_limit = max(1, min(2000, int(edge_limit)))
    filters = [{"term": {"kind": kind}}] if kind else []

    # Sem entidade de partida: usa as mais centrais e mostra o grafo global.
    if not entity_ref:
        central = centrality(kind=kind, top=min(40, node_limit), es=client).get("results") or []
        seeds = [item["entity_ref"] for item in central]
        if not seeds:
            seeds = [_hit_ref(hit) for hit in _top_related_edges(client, filters, edge_limit)]
        edges = _edges_for_refs(client, seeds, filters, edge_limit)
        return _shape(edges, node_limit, edge_limit, es=client, origin=None)

    origin = str(entity_ref).strip()
    origin_ref = origin if origin.startswith(("entidade:", "pessoa:")) else model._ref_for(origin)
    seen = {origin_ref}
    frontier = [origin_ref]
    edges: List[Dict[str, Any]] = []
    seen_edges: set = set()
    for _ in range(max(1, min(4, int(depth)))):
        if not frontier or len(edges) >= edge_limit:
            break
        batch = _edges_for_refs(client, frontier, filters, edge_limit - len(edges))
        next_frontier: List[str] = []
        for edge in batch:
            if edge["relation_id"] in seen_edges:
                continue
            seen_edges.add(edge["relation_id"])
            edges.append(edge)
            for end in (edge.get("source_ref"), edge.get("target_ref")):
                if end and end not in seen:
                    seen.add(end)
                    next_frontier.append(end)
        frontier = next_frontier
    return _shape(edges, node_limit, edge_limit, es=client, origin=origin_ref)


def _top_related_edges(client: Elasticsearch, filters: List[Dict[str, Any]], limit: int) -> List[Dict[str, Any]]:
    body = {
        "size": max(1, min(500, limit)),
        "track_total_hits": False,
        "query": {"bool": {"filter": filters}},
        "sort": [{"value_sum": {"order": "desc", "missing": "_last"}}],
    }
    try:
        resp = client.search(index=WORLD_RELATIONS_INDEX, body=body)
    except Exception:
        return []
    return [_hit_source(hit) for hit in (resp.get("hits") or {}).get("hits") or []]


def _hit_ref(hit: Dict[str, Any]) -> str:
    source = hit.get("_source") or {}
    return source.get("source_ref") or source.get("target_ref") or ""


def _edges_for_refs(
    client: Elasticsearch,
    refs: List[str],
    filters: List[Dict[str, Any]],
    limit: int,
) -> List[Dict[str, Any]]:
    if not refs or limit <= 0:
        return []
    body = {
        "size": max(1, min(1000, limit)),
        "track_total_hits": False,
        "query": {
            "bool": {
                "filter": filters
                + [
                    {
                        "bool": {
                            "should": [
                                {"terms": {"source_ref": refs}},
                                {"terms": {"target_ref": refs}},
                            ],
                            "minimum_should_match": 1,
                        }
                    }
                ]
            }
        },
        "sort": [{"value_sum": {"order": "desc", "missing": "_last"}}],
    }
    try:
        resp = client.search(index=WORLD_RELATIONS_INDEX, body=body)
    except Exception as exc:
        logger.warning("Leitura de arestas falhou: %s", exc)
        return []
    return [_hit_source(hit) for hit in (resp.get("hits") or {}).get("hits") or []]


def _shape(
    edges: List[Dict[str, Any]],
    node_limit: int,
    edge_limit: int,
    es: Optional[Elasticsearch],
    origin: Optional[str],
) -> Dict[str, Any]:
    """Converte arestas em nós+arestas prontos a desenhar (com cortes)."""
    degree: Dict[str, int] = {}
    value: Dict[str, float] = {}
    for edge in edges:
        for end in (edge.get("source_ref"), edge.get("target_ref")):
            if end:
                degree[end] = degree.get(end, 0) + 1
                value[end] = value.get(end, 0.0) + float(edge.get("value_sum") or 0.0)
    refs = sorted(degree, key=lambda ref: (degree[ref], value[ref]), reverse=True)[:node_limit]
    kept = set(refs)
    entities = _entities_by_ref(refs, es)
    nodes = []
    for ref in refs:
        entity = entities.get(ref) or {}
        nodes.append(
            {
                "id": ref,
                "name": entity.get("name") or ref,
                "entity_type": entity.get("entity_type"),
                "risk": entity.get("risk"),
                "risk_label": entity.get("risk_label"),
                "contracts_value": entity.get("contracts_value"),
                "degree": degree.get(ref, 0),
                "origin": ref == origin,
            }
        )
    drawn_edges = []
    for edge in edges:
        if edge.get("source_ref") in kept and edge.get("target_ref") in kept:
            drawn_edges.append(
                {
                    "id": edge.get("relation_id"),
                    "source": edge.get("source_ref"),
                    "target": edge.get("target_ref"),
                    "kind": edge.get("kind"),
                    "kind_label": edge.get("kind_label"),
                    "weight": edge.get("weight"),
                    "value_sum": edge.get("value_sum"),
                    "contracts_count": edge.get("contracts_count"),
                    "first_ts": edge.get("first_ts"),
                    "last_ts": edge.get("last_ts"),
                }
            )
        if len(drawn_edges) >= edge_limit:
            break
    return {
        "origin": origin,
        "nodes": nodes,
        "edges": drawn_edges,
        "truncated": len(edges) >= edge_limit or len(degree) > node_limit,
        "metrics": {
            "nodes": len(nodes),
            "edges": len(drawn_edges),
            "avg_degree": round(sum(degree.values()) / max(1, len(degree)), 3),
        },
    }


def _hit_source(hit: Dict[str, Any]) -> Dict[str, Any]:
    return hit.get("_source") or {}


def paths(
    source: str,
    target: str,
    max_depth: int = 4,
    kind: Optional[str] = None,
    es: Optional[Elasticsearch] = None,
) -> Dict[str, Any]:
    """Caminhos mais curtos entre duas entidades (BFS sobre as arestas)."""
    client = _client(es)
    if client is None:
        return {"error": "Elasticsearch indisponível", "paths": []}
    start = str(source).strip()
    end = str(target).strip()
    start_ref = start if ":" in start else model._ref_for(start)
    end_ref = end if ":" in end else model._ref_for(end)
    if start_ref == end_ref:
        return {"paths": [[start_ref]], "note": "Origem e destino coincidem."}

    filters = [{"term": {"kind": kind}}] if kind else []
    adjacency: Dict[str, set] = {}
    visited = {start_ref}
    frontier = [start_ref]
    found: List[List[str]] = []
    for _ in range(max(1, min(6, int(max_depth)))):
        if not frontier or found:
            break
        batch = _edges_for_refs(client, frontier, filters, 1000)
        next_frontier: List[str] = []
        for edge in batch:
            a, b = edge.get("source_ref"), edge.get("target_ref")
            if not a or not b:
                continue
            adjacency.setdefault(a, set()).add(b)
            adjacency.setdefault(b, set()).add(a)
            for end_ref_candidate in (a, b):
                if end_ref_candidate not in visited:
                    visited.add(end_ref_candidate)
                    next_frontier.append(end_ref_candidate)
        # Reconstrói caminhos simples até ao destino assim que ele aparece.
        found = _bfs_paths(adjacency, start_ref, end_ref, max_depth=int(max_depth))
        frontier = next_frontier

    found = found or _bfs_paths(adjacency, start_ref, end_ref, max_depth=int(max_depth))
    names = _entities_by_ref([ref for path in found for ref in path], es=client)
    return {
        "source": start_ref,
        "target": end_ref,
        "count": len(found),
        "paths": [
            [
                {"id": ref, "name": (names.get(ref) or {}).get("name") or ref, "entity_type": (names.get(ref) or {}).get("entity_type")}
                for ref in path
            ]
            for path in found[:5]
        ],
    }


def _bfs_paths(adjacency: Dict[str, set], start: str, goal: str, max_depth: int) -> List[List[str]]:
    """BFS que devolve até 3 caminhos simples sem repetir nós."""
    results: List[List[str]] = []
    queue: List[List[str]] = [[start]]
    while queue and len(results) < 3:
        path = queue.pop(0)
        node = path[-1]
        if node == goal:
            results.append(path)
            continue
        if len(path) - 1 >= max_depth:
            continue
        for neighbour in sorted(adjacency.get(node, ())):
            if neighbour not in path:
                queue.append(path + [neighbour])
    return results


# ---------------------------------------------------------------------------
# Tempo
# ---------------------------------------------------------------------------
def temporal_profile(
    entity_ref: Optional[str] = None,
    kind: Optional[str] = None,
    years: int = 8,
    interval: str = "month",
    es: Optional[Elasticsearch] = None,
) -> Dict[str, Any]:
    """Série temporal de eventos (contagem e valor) por mês/ano."""
    client = _client(es)
    if client is None:
        return {"error": "Elasticsearch indisponível", "series": []}
    filters: List[Dict[str, Any]] = []
    if entity_ref:
        value = str(entity_ref).strip()
        filters.append(
            {
                "bool": {
                    "should": [
                        {"term": {"entity_ref": value}},
                        {"term": {"entity_ref": model._ref_for(value)}},
                    ],
                    "minimum_should_match": 1,
                }
            }
        )
    if kind:
        filters.append({"terms": {"kind": [k.strip() for k in str(kind).split(",") if k.strip()]}})
    filters.append({"range": {"ts": {"gte": f"now-{max(1, int(years))}y"}}})
    body = {
        "size": 0,
        "track_total_hits": False,
        "query": {"bool": {"filter": filters}},
        "aggs": {
            "series": {
                "date_histogram": {
                    "field": "ts",
                    "calendar_interval": "month" if interval == "month" else "year",
                    "min_doc_count": 0,
                },
                "aggs": {
                    "value": {"sum": {"field": "value"}},
                    "by_kind": {"terms": {"field": "kind", "size": 8}},
                },
            }
        },
    }
    try:
        resp = client.search(index=WORLD_EVENTS_INDEX, body=body)
    except Exception as exc:
        return {"error": str(exc)[:300], "series": []}
    buckets = ((resp.get("aggregations") or {}).get("series") or {}).get("buckets") or []
    return {
        "interval": interval,
        "series": [
            {
                "period": bucket.get("key_as_string"),
                "events": int(bucket.get("doc_count") or 0),
                "value": round(((bucket.get("value") or {}).get("value") or 0.0), 2),
                "kinds": [
                    {"key": inner["key"], "count": inner["doc_count"]}
                    for inner in (bucket.get("by_kind") or {}).get("buckets", [])
                ],
            }
            for bucket in buckets
        ],
    }


def causality(
    entity_ref: Optional[str] = None,
    window_days: int = 45,
    limit: int = 60,
    lookback_days: int = 3650,
    es: Optional[Elasticsearch] = None,
) -> Dict[str, Any]:
    """Influências temporais **candidatas** entre eventos de entidades ligadas.

    Metodologia (heurística, documentada): para cada par de eventos de entidades
    que partilham uma aresta no grafo e cujo intervalo é inferior a
    `window_days`, calcula-se

        score = min(1, peso/10) × (1 - Δt/janela) × severidade_origem

    Marca-se também o *mecanismo* (o tipo de relação) e se o par é
    `contratacao → adjudicacao` (o caso mais interpretável: um anúncio de
    contratação seguido de adjudicação).
    """
    client = _client(es)
    if client is None:
        return {"error": "Elasticsearch indisponível", "links": []}
    filters: List[Dict[str, Any]] = [{"range": {"ts": {"gte": f"now-{max(30, int(lookback_days))}d"}}}]
    if entity_ref:
        value = str(entity_ref).strip()
        filters.append(
            {
                "bool": {
                    "should": [
                        {"term": {"entity_ref": value}},
                        {"term": {"entity_ref": model._ref_for(value)}},
                    ],
                    "minimum_should_match": 1,
                }
            }
        )
    body = {
        "size": 800,
        "track_total_hits": False,
        "query": {"bool": {"filter": filters}},
        "sort": [{"ts": {"order": "asc"}}],
        "_source": ["kind", "entity_ref", "entity_id", "entity_name", "ts", "value", "severity", "source_id"],
    }
    try:
        resp = client.search(index=WORLD_EVENTS_INDEX, body=body)
    except Exception as exc:
        return {"error": str(exc)[:300], "links": []}
    events = [_hit_source(hit) for hit in (resp.get("hits") or {}).get("hits") or []]

    # Arestas (peso) e adjacência para saber que entidades estão ligadas.
    edge_body = {
        "size": 1000,
        "track_total_hits": False,
        "query": {"bool": {"filter": [{"term": {"kind": "adjudicou"}}]}},
        "sort": [{"value_sum": {"order": "desc", "missing": "_last"}}],
        "_source": ["source_ref", "target_ref", "weight", "value_sum", "kind", "kind_label"],
    }
    try:
        edge_resp = client.search(index=WORLD_RELATIONS_INDEX, body=edge_body)
    except Exception:
        edge_resp = {}
    edges = [_hit_source(hit) for hit in (edge_resp.get("hits") or {}).get("hits") or []]
    neighbours: Dict[str, Dict[str, Dict[str, Any]]] = {}
    for edge in edges:
        a, b = edge.get("source_ref"), edge.get("target_ref")
        if not a or not b:
            continue
        neighbours.setdefault(a, {})[b] = edge
        neighbours.setdefault(b, {})[a] = edge

    window = timedelta(days=max(1, int(window_days)))
    links: List[Dict[str, Any]] = []
    for i, first in enumerate(events):
        first_ref = first.get("entity_ref")
        first_ts = _parse_ts(first.get("ts"))
        if not first_ref or not first_ts:
            continue
        for second in events[i + 1 :]:
            second_ref = second.get("entity_ref")
            if second_ref == first_ref or not second_ref:
                continue
            edge = (neighbours.get(first_ref) or {}).get(second_ref)
            if not edge:
                continue
            second_ts = _parse_ts(second.get("ts"))
            if not second_ts:
                continue
            delta = (second_ts - first_ts).total_seconds() / 86400.0
            if delta < 0:
                delta = -delta
                a_event, b_event = second, first
            else:
                a_event, b_event = first, second
            if delta > window.days:
                continue
            weight = float(edge.get("weight") or 1.0)
            severity = float(a_event.get("severity") or 0.3)
            score = min(1.0, weight / 10.0) * (1.0 - delta / max(1.0, float(window.days))) * severity
            links.append(
                {
                    "cause": {
                        "event": a_event.get("kind"),
                        "entity_ref": a_event.get("entity_ref"),
                        "entity_name": a_event.get("entity_name"),
                        "ts": a_event.get("ts"),
                        "value": a_event.get("value"),
                    },
                    "effect": {
                        "event": b_event.get("kind"),
                        "entity_ref": b_event.get("entity_ref"),
                        "entity_name": b_event.get("entity_name"),
                        "ts": b_event.get("ts"),
                        "value": b_event.get("value"),
                    },
                    "mechanism": edge.get("kind"),
                    "mechanism_label": edge.get("kind_label"),
                    "days": round(delta, 1),
                    "weight": weight,
                    "score": round(score, 4),
                    "interpretation": _interpret(a_event.get("kind"), b_event.get("kind")),
                }
            )
        if len(links) > limit * 6:
            break

    links.sort(key=lambda link: link["score"], reverse=True)
    top = links[: max(1, int(limit))]
    return {
        "count": len(links),
        "window_days": window_days,
        "links": top,
        "note": "Influência temporal candidata (heurística), não causalidade provada.",
    }


def _parse_ts(value: Any) -> Optional[datetime]:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value)[:10])
    except Exception:
        return None
    return parsed.replace(tzinfo=timezone.utc)


def _interpret(cause: Optional[str], effect: Optional[str]) -> str:
    if cause == "contratacao" and effect == "adjudicacao":
        return "Um contrato adjudicado a uma entidade ligada surgiu depois da contratação."
    if cause == "insolvencia" or effect == "insolvencia":
        return "A insolvência de uma entidade ligada pode ter afetado a outra parte."
    if cause == "relacao_criada":
        return "A criação da relação antecede o evento seguinte."
    if effect == "cessacao":
        return "Evento seguido de cessação contratual numa entidade ligada."
    return "Eventos temporalmente próximos em entidades ligadas."
