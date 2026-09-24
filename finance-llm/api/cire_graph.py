"""Grafo do módulo CIRE (insolvências e revitalizações).

Constrói uma rede a partir do índice ``finance_cire``: cada nó é um valor de uma
**dimensão** (entidade, tribunal, comarca, tipo de processo, ato, tempo…) e cada
aresta é a **co-ocorrência** desses valores na mesma publicação — ou a ligação
entre duas dimensões distintas (ex.: administrador da insolvência → insolvente).

Como o índice guarda os intervenientes numa lista ``nested`` (``papel``/``nome``/
``nif``), as dimensões de entidade são derivadas do papel:

- ``insolvente``   → papéis «Insolvente» e «Devedor»
- ``administrador``→ papel «Administrador Insolvência»
- ``credor``       → papel «Credor»
- ``requerente``   → papel «Requerente»
- ``interveniente``→ qualquer papel com NIF ou nome

O motor percorre os documentos com ``search_after`` (amostragem configurável,
``sample=0`` = todos até ao teto do servidor) e, quando só há uma dimensão
«plana» (tribunal, tipo, ano…), usa **agregações** do Elasticsearch para devolver
contagens exatas e completas sem varrer o índice.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from elasticsearch import Elasticsearch

from api.elasticsearch_client import CIRE_INDEX, get_es_client

logger = logging.getLogger(__name__)

# ------------------------------------------------------------------ dimensões
# `type` agrupa a legenda/cores na UI; `field` = campo plano agregável;
# `papeis` = papéis dos intervenientes que compõem a dimensão (None = todos);
# `time` = dimensão temporal derivada de `data_publicacao`.
CIRE_GRAPH_DIMENSIONS: Dict[str, Dict[str, Any]] = {
    "insolvente": {
        "label": "Insolvente / devedor",
        "short": "Insolvente",
        "type": "entidade",
        "papeis": ["Insolvente", "Devedor"],
        "field": "insolvente.keyword",
    },
    "administrador": {
        "label": "Administrador da insolvência",
        "short": "Administrador",
        "type": "entidade",
        "papeis": ["Administrador Insolvência"],
    },
    "credor": {
        "label": "Credor",
        "short": "Credor",
        "type": "entidade",
        "papeis": ["Credor"],
    },
    "requerente": {
        "label": "Requerente",
        "short": "Requerente",
        "type": "entidade",
        "papeis": ["Requerente"],
    },
    "interveniente": {
        "label": "Interveniente (qualquer papel)",
        "short": "Interveniente",
        "type": "entidade",
        "papeis": None,
    },
    "tribunal": {"label": "Tribunal", "short": "Tribunal", "type": "jurisdicao", "field": "tribunal.keyword"},
    "comarca": {"label": "Comarca", "short": "Comarca", "type": "jurisdicao", "field": "tribunal_comarca"},
    "sede": {"label": "Localidade (sede do tribunal)", "short": "Localidade", "type": "jurisdicao", "field": "tribunal_sede"},
    "juizo": {"label": "Juízo", "short": "Juízo", "type": "jurisdicao", "field": "juizo"},
    "especie": {"label": "Espécie de processo", "short": "Espécie", "type": "processo", "field": "especie.keyword"},
    "tipo": {"label": "Tipo (Insolvência / PER / PEAP / PEVE)", "short": "Tipo", "type": "processo", "field": "tipo"},
    "ato": {"label": "Ato publicado", "short": "Ato", "type": "processo", "field": "ato.keyword"},
    "papel": {"label": "Papel do interveniente", "short": "Papel", "type": "processo", "nested_field": "intervenientes.papel"},
    "ano": {"label": "Ano de publicação", "short": "Ano", "type": "tempo", "time": "year"},
    "mes": {"label": "Mês de publicação", "short": "Mês", "type": "tempo", "time": "month"},
}

# Métricas: publicações (documentos distintos) ou menções (intervenções).
CIRE_GRAPH_METRICS = {"publicacoes": "Publicações", "mencoes": "Menções a intervenientes"}

# Receitas prontas (perguntas frequentes sobre insolvências).
CIRE_GRAPH_RECIPES: List[Dict[str, Any]] = [
    {
        "id": "admin-insolvente",
        "label": "Quem administra quem",
        "description": "Administradores da insolvência ligados aos insolventes que acompanham.",
        "dimension_a": "administrador",
        "dimension_b": "insolvente",
        "metric": "publicacoes",
        "view": "network",
        "limit": 60,
    },
    {
        "id": "insolvente-credor",
        "label": "Insolvente × credores",
        "description": "Quem é credor de quem: insolventes ligados aos seus credores.",
        "dimension_a": "insolvente",
        "dimension_b": "credor",
        "metric": "publicacoes",
        "view": "network",
        "limit": 60,
    },
    {
        "id": "co-credores",
        "label": "Co-credores",
        "description": "Credores que aparecem nos mesmos processos (quem partilha o prejuízo).",
        "dimension_a": "credor",
        "dimension_b": "credor",
        "metric": "publicacoes",
        "view": "network",
        "limit": 50,
    },
    {
        "id": "admin-comarca",
        "label": "Administradores por comarca",
        "description": "Que comarcas concentram cada administrador da insolvência.",
        "dimension_a": "comarca",
        "dimension_b": "administrador",
        "metric": "publicacoes",
        "view": "hierarchical",
        "limit": 60,
    },
    {
        "id": "territorio",
        "label": "Território",
        "description": "Comarcas com mais publicações (treemap: a área é o nº de publicações).",
        "dimension_a": "comarca",
        "dimension_b": None,
        "metric": "publicacoes",
        "view": "treemap",
        "limit": 30,
    },
    {
        "id": "tipos",
        "label": "Tipos de processo",
        "description": "Insolvência, PER, PEAP e PEVE por espécie e por comarca.",
        "dimension_a": "tipo",
        "dimension_b": "especie",
        "metric": "publicacoes",
        "view": "sankey",
        "limit": 40,
    },
    {
        "id": "evolucao",
        "label": "Evolução mensal",
        "description": "Publicações por mês, repartidas por tipo de processo.",
        "dimension_a": "mes",
        "dimension_b": "tipo",
        "metric": "publicacoes",
        "view": "hierarchical",
        "limit": 80,
    },
    {
        "id": "actos",
        "label": "Atos mais publicados",
        "description": "Que atos dominam a publicidade do CIRE (ranking por publicações).",
        "dimension_a": "ato",
        "dimension_b": None,
        "metric": "publicacoes",
        "view": "list",
        "limit": 40,
    },
    {
        "id": "custom",
        "label": "Personalizado",
        "description": "Escolha as dimensões, a métrica e a visualização.",
        "dimension_a": "administrador",
        "dimension_b": "comarca",
        "metric": "publicacoes",
        "view": "network",
        "limit": 60,
    },
]

# Tetos de segurança (devolvidos em `meta.limits`).
CIRE_GRAPH_MAX_SCAN = 300_000
CIRE_GRAPH_MAX_NODES = 10_000
CIRE_GRAPH_MAX_EDGES = 30_000
# Máximo de valores de cada lado considerados por documento (evita explosão combinatória).
CIRE_GRAPH_MAX_VALUES_PER_DOC = 15

_SOURCE_FIELDS = [
    "pub_id",
    "data_publicacao",
    "tipo",
    "especie",
    "ato",
    "tribunal",
    "tribunal_comarca",
    "tribunal_sede",
    "juizo",
    "insolvente",
    "intervenientes",
]

# Dimensões agregáveis por termos (contagens exatas, sem varrer documentos).
# As dimensões de entidade e as arestas exigem varredura.
_AGGABLE_DIMENSIONS = {
    "tribunal",
    "comarca",
    "sede",
    "juizo",
    "especie",
    "tipo",
    "ato",
    "papel",
    "insolvente",
    "ano",
    "mes",
}


# ------------------------------------------------------------------ consulta
def _cire_query(
    q: Optional[str] = None,
    tipo: Optional[str] = None,
    especie: Optional[str] = None,
    ato: Optional[str] = None,
    comarca: Optional[str] = None,
    tribunal: Optional[str] = None,
    papel: Optional[str] = None,
    nif: Optional[str] = None,
    data_from: Optional[str] = None,
    data_to: Optional[str] = None,
    has_documento: Optional[bool] = None,
) -> Dict[str, Any]:
    """Constrói a consulta do Elasticsearch (os mesmos filtros da pesquisa)."""
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
    if tipo:
        filters.append({"term": {"tipo": tipo}})
    if especie:
        filters.append({"match_phrase": {"especie": especie}})
    if ato:
        filters.append({"match_phrase": {"ato": ato}})
    if comarca:
        filters.append({"term": {"tribunal_comarca": comarca}})
    if tribunal:
        filters.append({"match_phrase": {"tribunal": tribunal}})
    if nif:
        filters.append({"term": {"nifs": str(nif)}})
    if papel:
        filters.append({"nested": {"path": "intervenientes", "query": {"term": {"intervenientes.papel": papel}}}})
    if has_documento is not None:
        filters.append({"term": {"has_documento": bool(has_documento)}})
    if data_from or data_to:
        interval: Dict[str, str] = {}
        if data_from:
            interval["gte"] = data_from
        if data_to:
            interval["lte"] = data_to
        filters.append({"range": {"data_publicacao": interval}})

    if not must and not filters:
        return {"match_all": {}}
    query: Dict[str, Any] = {"bool": {}}
    if must:
        query["bool"]["must"] = must
    if filters:
        query["bool"]["filter"] = filters
    return query


# ------------------------------------------------------------------ valores
def _time_key(value: Any, granularity: str) -> Optional[str]:
    """Deriva «AAAA» ou «AAAA-MM» de uma data ISO."""
    if not value:
        return None
    text = str(value)
    if len(text) < 7:
        return None
    return text[:4] if granularity == "year" else text[:7]


def _interveniente_key(iv: Dict[str, Any]) -> Optional[str]:
    nif = iv.get("nif")
    nome = (iv.get("nome") or "").strip()
    if nif:
        return str(nif)
    if nome:
        return f"nome:{nome.lower()}"
    return None


def _dimension_values(source: Dict[str, Any], dimension: str) -> List[Dict[str, Any]]:
    """Extrai os valores de uma dimensão num documento.

    Devolve uma lista de dicts com ``key`` (identificador estável), ``label``
    (texto a mostrar), ``role`` (papel, nas entidades) e ``nif`` quando existir.
    """
    spec = CIRE_GRAPH_DIMENSIONS[dimension]

    if spec.get("time"):
        key = _time_key(source.get("data_publicacao"), spec["time"])
        return [{"key": key, "label": key, "role": spec["short"]}] if key else []

    if spec.get("nested_field"):
        field = spec["nested_field"].split(".")[-1]
        seen: List[Dict[str, Any]] = []
        for iv in source.get("intervenientes") or []:
            if not isinstance(iv, dict):
                continue
            value = iv.get(field)
            if value:
                seen.append({"key": str(value), "label": str(value), "role": spec["short"]})
        return seen

    if "papeis" in spec or dimension == "insolvente":
        papeis = spec.get("papeis")
        out: List[Dict[str, Any]] = []
        for iv in source.get("intervenientes") or []:
            if not isinstance(iv, dict):
                continue
            papel = iv.get("papel")
            if papeis is not None and papel not in papeis:
                continue
            key = _interveniente_key(iv)
            if not key:
                continue
            nome = (iv.get("nome") or "").strip() or key
            out.append({"key": key, "label": nome, "role": papel or spec["short"], "nif": iv.get("nif")})
        return out

    field = spec.get("field")
    if not field:
        return []
    raw = source.get(field.split(".")[0]) if "." in field else source.get(field)
    if raw is None:
        return []
    values = raw if isinstance(raw, list) else [raw]
    return [
        {"key": str(value), "label": str(value), "role": spec["short"]}
        for value in values
        if value not in (None, "")
    ]


def _add_node(
    nodes: Dict[str, Dict[str, Any]],
    dimension: str,
    item: Dict[str, Any],
) -> str:
    """Cria/atualiza um nó e devolve o seu id."""
    node_id = f"{dimension}:{item['key']}"
    node = nodes.get(node_id)
    if node is None:
        node = {
            "id": node_id,
            "key": str(item["key"]),
            "label": str(item.get("label") or item["key"]),
            "dimension": dimension,
            "type": CIRE_GRAPH_DIMENSIONS[dimension]["type"],
            "role": item.get("role") or CIRE_GRAPH_DIMENSIONS[dimension]["short"],
            "count": 0,
            "mentions": 0,
            "total_value": 0.0,
            "nif": item.get("nif") or None,
        }
        nodes[node_id] = node
    node["count"] += 1
    node["mentions"] += 1
    return node_id


def _add_edge(edges: Dict[str, Dict[str, Any]], source: str, target: str, directed: bool) -> None:
    """Cria/atualiza uma aresta (não dirigida quando as dimensões coincidem)."""
    if source == target:
        return
    left, right = (source, target) if directed or source <= target else (target, source)
    key = f"{left}->{right}"
    edge = edges.get(key)
    if edge is None:
        edge = {"source": left, "target": right, "count": 0, "value": 0.0, "mentions": 0}
        edges[key] = edge
    edge["count"] += 1
    edge["mentions"] += 1


def _pick_balanced_nodes(
    nodes: Dict[str, Dict[str, Any]],
    edges: Dict[str, Dict[str, Any]],
    metric_key: str,
    dimension_a: str,
    dimension_b: str,
    limit: int,
) -> List[Dict[str, Any]]:
    """Escolhe os nós de um grafo de duas dimensões repartindo o orçamento.

    Ordenar todos os nós pela contagem global deixaria de fora um dos lados (as
    contagens de cada lado são de ordens de grandeza diferentes). Regras:

    1. **Reserva** — cada lado garante ~1/4 do orçamento, escolhido pelas
       arestas mais fortes (garante que ambos os lados aparecem e que os nós
       escolhidos estão ligados uns aos outros).
    2. **Preenchimento** — o resto do orçamento continua a seguir as arestas
       mais fortes, sem limites por lado.
    3. **Sobra** — completa com os nós mais ligados e, por fim, com os de maior
       contagem.
    """
    degree: Dict[str, int] = {}
    for edge in edges.values():
        weight = edge.get(metric_key) or 0
        degree[edge["source"]] = degree.get(edge["source"], 0) + weight
        degree[edge["target"]] = degree.get(edge["target"], 0) + weight

    def dimension_of(node_id: str) -> Optional[str]:
        node = nodes.get(node_id)
        return node["dimension"] if node else None

    ranked_edges = sorted(edges.values(), key=lambda item: item.get(metric_key) or 0, reverse=True)
    kept: Dict[str, Dict[str, Any]] = {}

    def add_side(dimension: str, quota: int) -> None:
        """Acrescenta nós deste lado (até ao limite) pelas arestas mais fortes."""
        if quota <= 0 or len(kept) >= limit:
            return
        added = 0
        for edge in ranked_edges:
            if len(kept) >= limit or added >= quota:
                break
            for node_id in (edge["source"], edge["target"]):
                if node_id in kept or dimension_of(node_id) != dimension:
                    continue
                kept[node_id] = nodes[node_id]
                added += 1
                break

    reserve = max(1, limit // 4)
    add_side(dimension_a, reserve)
    add_side(dimension_b, reserve)

    # Preenchimento pelas arestas mais fortes (sem quotas por lado).
    for edge in ranked_edges:
        if len(kept) >= limit:
            break
        for node_id in (edge["source"], edge["target"]):
            if node_id not in kept:
                kept[node_id] = nodes[node_id]

    # Sobra: nós mais ligados e, por fim, os de maior contagem.
    if len(kept) < limit:
        rest = [node for node in nodes.values() if node["id"] not in kept]
        rest.sort(key=lambda node: (degree.get(node["id"], 0), node.get(metric_key) or 0), reverse=True)
        for node in rest[: limit - len(kept)]:
            kept[node["id"]] = node

    result = list(kept.values())
    result.sort(key=lambda node: node.get(metric_key) or 0, reverse=True)
    return result


# ------------------------------------------------------------------ agregados
def _aggregate_nodes(
    client: Elasticsearch,
    query: Dict[str, Any],
    dimension: str,
    limit: int,
) -> Optional[Dict[str, Any]]:
    """Contagens exatas dos nós de uma dimensão plana/temporal (agregações)."""
    spec = CIRE_GRAPH_DIMENSIONS[dimension]
    size = 0 if not limit else max(2, limit)

    if spec.get("time"):
        agg: Dict[str, Any] = {
            "nodes": {
                "date_histogram": {
                    "field": "data_publicacao",
                    "calendar_interval": spec["time"],
                    "format": "yyyy" if spec["time"] == "year" else "yyyy-MM",
                    "order": {"_key": "desc"},
                }
            }
        }
        resp = client.search(index=CIRE_INDEX, body={"size": 0, "query": query, "track_total_hits": True, "aggs": agg})
        buckets = resp.get("aggregations", {}).get("nodes", {}).get("buckets", [])
        nodes = []
        for bucket in buckets[: size or None]:
            key = bucket.get("key_as_string")
            if not key:
                continue
            nodes.append(
                {
                    "id": f"{dimension}:{key}",
                    "key": key,
                    "label": key,
                    "dimension": dimension,
                    "type": spec["type"],
                    "role": spec["short"],
                    "count": bucket["doc_count"],
                    "mentions": bucket["doc_count"],
                    "total_value": 0.0,
                    "nif": None,
                }
            )
    else:
        field = spec.get("field")
        if not field:
            return None
        agg = {"nodes": {"terms": {"field": field, "size": size or 100}}}
        resp = client.search(index=CIRE_INDEX, body={"size": 0, "query": query, "track_total_hits": True, "aggs": agg})
        buckets = resp.get("aggregations", {}).get("nodes", {}).get("buckets", [])
        nodes = [
            {
                "id": f"{dimension}:{bucket['key']}",
                "key": bucket["key"],
                "label": bucket["key"],
                "dimension": dimension,
                "type": spec["type"],
                "role": spec["short"],
                "count": bucket["doc_count"],
                "mentions": bucket["doc_count"],
                "total_value": 0.0,
                "nif": bucket["key"] if str(bucket["key"]).isdigit() else None,
            }
            for bucket in buckets
        ]

    total = int(resp.get("hits", {}).get("total", {}).get("value", 0) or 0)
    return {"nodes": nodes, "documents_matching": total}


# ------------------------------------------------------------------ construtor
def build_cire_graph(
    dimension_a: str,
    dimension_b: Optional[str] = None,
    metric: str = "publicacoes",
    mode: str = "auto",
    q: Optional[str] = None,
    tipo: Optional[str] = None,
    especie: Optional[str] = None,
    ato: Optional[str] = None,
    comarca: Optional[str] = None,
    tribunal: Optional[str] = None,
    papel: Optional[str] = None,
    nif: Optional[str] = None,
    data_from: Optional[str] = None,
    data_to: Optional[str] = None,
    has_documento: Optional[bool] = None,
    min_count: int = 1,
    limit: int = 60,
    edge_limit: int = 400,
    sample: int = 20_000,
    es: Optional[Elasticsearch] = None,
) -> Dict[str, Any]:
    """Constrói o grafo das insolvências/revitalizações a partir do CIRE.

    - ``dimension_b`` igual a ``dimension_a`` → rede de co-ocorrência (ex.:
      credores que partilham processos); nulo → apenas nós (rankings/treemaps).
    - ``metric``: ``publicacoes`` (documentos distintos) ou ``mencoes``
      (intervenções), usado para ordenar e para espessura das arestas.
    - ``mode``: ``exato`` usa agregações (dimensões planas, sem amostragem);
      ``amostra`` percorre até ``sample`` documentos; ``auto`` escolhe o melhor.
    - ``limit``, ``edge_limit`` e ``sample`` aceitam 0 = todos (sujeitos aos
      tetos ``CIRE_GRAPH_MAX_*``, devolvidos em ``meta.limits``).
    """
    client = es or get_es_client()
    if not client:
        return {"error": "Elasticsearch indisponível", "nodes": [], "edges": [], "meta": {}}
    if dimension_a not in CIRE_GRAPH_DIMENSIONS:
        return {"error": f"Dimensão desconhecida: {dimension_a}", "nodes": [], "edges": [], "meta": {}}
    if dimension_b and dimension_b not in CIRE_GRAPH_DIMENSIONS:
        return {"error": f"Dimensão desconhecida: {dimension_b}", "nodes": [], "edges": [], "meta": {}}

    dimension_b = dimension_b or None
    metric = metric if metric in CIRE_GRAPH_METRICS else "publicacoes"
    mode = mode if mode in ("auto", "exato", "amostra") else "auto"
    same_dimension = dimension_b == dimension_a
    min_count = max(1, min(int(min_count or 1), 1000))

    query = _cire_query(
        q=q,
        tipo=tipo,
        especie=especie,
        ato=ato,
        comarca=comarca,
        tribunal=tribunal,
        papel=papel,
        nif=nif,
        data_from=data_from,
        data_to=data_to,
        has_documento=has_documento,
    )
    filters_meta = {
        "q": q,
        "tipo": tipo,
        "especie": especie,
        "ato": ato,
        "comarca": comarca,
        "tribunal": tribunal,
        "papel": papel,
        "nif": nif,
        "data_from": data_from,
        "data_to": data_to,
        "has_documento": has_documento,
        "min_count": min_count,
    }

    nodes_limit = 0 if int(limit) <= 0 else max(2, min(int(limit), CIRE_GRAPH_MAX_NODES))
    edges_limit = 0 if int(edge_limit) <= 0 else max(0, min(int(edge_limit), CIRE_GRAPH_MAX_EDGES))

    # ---- caminho exato (agregações) para nós de dimensões planas ----
    if not dimension_b and mode in ("auto", "exato") and dimension_a in _AGGABLE_DIMENSIONS:
        try:
            exact = _aggregate_nodes(client, query, dimension_a, nodes_limit)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Agregação exata do grafo CIRE falhou (%s); a usar varredura.", exc)
            exact = None
        if exact is not None:
            nodes = [node for node in exact["nodes"] if node["count"] >= min_count]
            notes = [
                f"Contagens exatas por agregação do Elasticsearch sobre {exact['documents_matching']} publicações.",
            ]
            if len(exact["nodes"]) > len(nodes):
                notes.append(f"{len(exact['nodes']) - len(nodes)} nós com menos de {min_count} publicação(ões) foram omitidos.")
            return {
                "nodes": nodes,
                "edges": [],
                "meta": {
                    "dimension_a": dimension_a,
                    "dimension_b": None,
                    "metric": metric,
                    "mode": "exato",
                    "complete": True,
                    "directed": False,
                    "documents_scanned": 0,
                    "documents_matching": exact["documents_matching"],
                    "nodes_total": len(exact["nodes"]),
                    "edges_total": 0,
                    "kept_nodes": len(nodes),
                    "kept_edges": 0,
                    "omitted_edges": 0,
                    "truncated_documents": 0,
                    "limits": {
                        "max_scan": CIRE_GRAPH_MAX_SCAN,
                        "max_nodes": CIRE_GRAPH_MAX_NODES,
                        "max_edges": CIRE_GRAPH_MAX_EDGES,
                    },
                    "notes": notes,
                    "filters": filters_meta,
                },
            }

    # ---- varredura de documentos (todas as dimensões, com arestas) ----
    all_documents = int(sample) <= 0
    scan_ceiling = CIRE_GRAPH_MAX_SCAN
    sample = scan_ceiling if all_documents else max(100, min(int(sample), scan_ceiling))
    page_size = 5000
    sort: List[Any] = [
        {"data_publicacao": {"order": "desc", "missing": "_last"}},
        {"pub_id": {"order": "asc"}},
    ]

    nodes: Dict[str, Dict[str, Any]] = {}
    edges: Dict[str, Dict[str, Any]] = {}
    scanned = 0
    total_hits = 0
    truncated_documents = 0
    scan_capped = False

    try:
        search_after: Optional[List[Any]] = None
        while all_documents or scanned < sample:
            remaining = scan_ceiling - scanned
            if remaining <= 0:
                scan_capped = True
                break
            page = min(page_size, remaining, sample - scanned if not all_documents else page_size)
            if page <= 0:
                break
            body: Dict[str, Any] = {
                "size": page,
                "query": query,
                "sort": sort,
                "_source": _SOURCE_FIELDS,
            }
            # Contar todos os documentos é caro: só é pedido na primeira página.
            if search_after is None:
                body["track_total_hits"] = True
            else:
                body["search_after"] = search_after
            resp = client.search(index=CIRE_INDEX, body=body)
            hits = resp.get("hits", {}).get("hits", [])
            if search_after is None:
                total_block = resp.get("hits", {}).get("total") or {}
                if isinstance(total_block, dict):
                    total_hits = total_block.get("value") or 0
            if not hits:
                break

            for hit in hits:
                source = hit.get("_source") or {}
                scanned += 1

                values_a = _dimension_values(source, dimension_a)
                truncated = len(values_a) > CIRE_GRAPH_MAX_VALUES_PER_DOC
                ids_a = list(
                    dict.fromkeys(
                        _add_node(nodes, dimension_a, item)
                        for item in values_a[:CIRE_GRAPH_MAX_VALUES_PER_DOC]
                    )
                )
                if truncated:
                    truncated_documents += 1
                if not dimension_b or not ids_a:
                    continue

                if same_dimension:
                    for index, left in enumerate(ids_a):
                        for right in ids_a[index + 1:]:
                            _add_edge(edges, left, right, directed=False)
                    continue

                values_b = _dimension_values(source, dimension_b)
                if len(values_b) > CIRE_GRAPH_MAX_VALUES_PER_DOC:
                    truncated_documents += 1
                ids_b = list(
                    dict.fromkeys(
                        _add_node(nodes, dimension_b, item)
                        for item in values_b[:CIRE_GRAPH_MAX_VALUES_PER_DOC]
                    )
                )
                for left in ids_a:
                    for right in ids_b:
                        _add_edge(edges, left, right, directed=True)

            if len(hits) < page:
                break
            last_sort = hits[-1].get("sort")
            if not last_sort:
                break
            search_after = last_sort
    except Exception as exc:  # noqa: BLE001
        logger.exception("Grafo do CIRE falhou na varredura")
        return {"error": str(exc), "nodes": [], "edges": [], "meta": {}}

    nodes_total = len(nodes)
    edges_total = len(edges)
    if min_count > 1:
        nodes = {key: node for key, node in nodes.items() if node["count"] >= min_count}

    metric_key = "mentions" if metric == "mencoes" else "count"
    split_sides = bool(dimension_b) and not same_dimension and bool(nodes_limit)
    if split_sides:
        # Num grafo de duas dimensões (ex.: administrador × insolvente) ordenar
        # todos os nós pela contagem global deixaria de fora um dos lados — as
        # entidades de um lado têm sempre contagens muito diferentes do outro.
        # O orçamento é repartido e cada lado escolhe os nós mais ligados.
        kept_nodes = _pick_balanced_nodes(nodes, edges, metric_key, dimension_a, dimension_b or "", nodes_limit)
    else:
        scored = sorted(nodes.values(), key=lambda node: (node.get(metric_key) or 0), reverse=True)
        kept_nodes = scored[:nodes_limit] if nodes_limit else scored
    kept_ids = {node["id"] for node in kept_nodes}
    kept_edges = [edge for edge in edges.values() if edge["source"] in kept_ids and edge["target"] in kept_ids]
    kept_edges.sort(key=lambda edge: (edge.get(metric_key) or 0), reverse=True)
    dropped_edges = max(0, len(kept_edges) - edges_limit) if edges_limit else 0
    if edges_limit:
        kept_edges = kept_edges[:edges_limit]

    sampled = scanned < total_hits or scan_capped
    complete = not sampled and len(kept_nodes) == len(nodes) and not dropped_edges

    notes = []
    if scan_capped:
        notes.append(
            f"Varredura limitada a {scanned} de {total_hits} publicações (teto do servidor: "
            f"{CIRE_GRAPH_MAX_SCAN}). Aplique filtros (tipo, comarca, datas) para reduzir o conjunto."
        )
    elif sampled:
        notes.append(
            f"Amostra das {scanned} publicações mais recentes de {total_hits} que correspondem aos filtros. "
            "Use «Todas as publicações» para contagens completas."
        )
    else:
        notes.append(f"As {total_hits} publicações do filtro foram analisadas (sem amostragem).")
    if len(nodes) != nodes_total:
        notes.append(f"{nodes_total - len(nodes)} nós omitidos por terem menos de {min_count} publicação(ões).")
    if len(kept_nodes) < len(nodes):
        notes.append(f"Mostrados {len(kept_nodes)} de {len(nodes)} nós.")
    if split_sides:
        notes.append(
            "Nós repartidos pelas duas dimensões: os mais ligados de cada lado "
            "(para não mostrar apenas um lado do grafo)."
        )
    if dropped_edges:
        notes.append(f"{dropped_edges} arestas omitidas por limite.")
    if truncated_documents:
        notes.append(
            f"Em {truncated_documents} publicações com muitos intervenientes só foram considerados os "
            f"primeiros {CIRE_GRAPH_MAX_VALUES_PER_DOC} valores."
        )
    if same_dimension:
        notes.append("Arestas = co-ocorrência na mesma publicação (mesmo processo).")

    return {
        "nodes": kept_nodes,
        "edges": kept_edges,
        "meta": {
            "dimension_a": dimension_a,
            "dimension_b": dimension_b,
            "metric": metric,
            "mode": "varredura-total" if all_documents else "amostra",
            "complete": complete,
            "directed": bool(dimension_b) and not same_dimension,
            "scan_capped": scan_capped,
            "sample_limit": None if all_documents else sample,
            "documents_scanned": scanned,
            "documents_matching": total_hits,
            "nodes_total": nodes_total,
            "edges_total": edges_total,
            "kept_nodes": len(kept_nodes),
            "kept_edges": len(kept_edges),
            "omitted_edges": dropped_edges,
            "truncated_documents": truncated_documents,
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "limits": {
                "max_scan": CIRE_GRAPH_MAX_SCAN,
                "max_nodes": CIRE_GRAPH_MAX_NODES,
                "max_edges": CIRE_GRAPH_MAX_EDGES,
            },
            "notes": notes,
            "filters": filters_meta,
        },
    }


def cire_graph_dimensions() -> Dict[str, Any]:
    """Dimensões, métricas e receitas disponíveis para o grafo do CIRE."""
    return {
        "dimensions": [
            {
                "key": key,
                "label": spec["label"],
                "short": spec["short"],
                "type": spec["type"],
                "aggable": key in _AGGABLE_DIMENSIONS,
            }
            for key, spec in CIRE_GRAPH_DIMENSIONS.items()
        ],
        "metrics": [{"key": key, "label": label} for key, label in CIRE_GRAPH_METRICS.items()],
        "recipes": CIRE_GRAPH_RECIPES,
        "limits": {
            "max_scan": CIRE_GRAPH_MAX_SCAN,
            "max_nodes": CIRE_GRAPH_MAX_NODES,
            "max_edges": CIRE_GRAPH_MAX_EDGES,
        },
    }
