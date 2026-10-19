"""Fichas e grafo de relações do Governo.

Este módulo liga as quatro fontes recolhidas para o Governo:

* ``finance_governo_ministerios`` — 18 ministérios (17 ministérios + PM);
* ``finance_governo_composicao`` — 59 membros do Governo;
* ``finance_governo_nomeacoes`` — 1 021 nomeações dos gabinetes;
* ``finance_scraped`` — os mesmos registos, para a pesquisa do módulo de recolha.

A partir delas constrói:

* o **grafo geral** ministério → membro → gabinete → nomeações;
* a **ficha de um membro** com detalhe, remunerações do gabinete, relações e
  grafo centrado na pessoa;
* a **ficha de uma pessoa de entidade** (``finance_people``) com cargos,
  empresas e grafo.

As relações seguem o vocabulário da ontologia (``ministerio``, ``membro``,
``gabinete``, ``nomeacao``, ``pessoa``, ``empresa``), para o frontend as poder
desenhar com o mesmo ``GraphCanvas`` dos restantes grafos.
"""
from __future__ import annotations

import hashlib
import math
import re
import unicodedata
from typing import Any, Dict, Iterable, List, Optional

from api.elasticsearch_client import (
    ensure_indices,
    get_es_client,
    get_person_by_nif,
    people_graph_for_person,
    search_people,
)

COMPOSICAO_INDEX = "finance_governo_composicao"
NOMEACOES_INDEX = "finance_governo_nomeacoes"
MINISTERIOS_INDEX = "finance_governo_ministerios"
SCRAPED_INDEX = "finance_scraped"

#: Tipos de nó e cores (as mesmas chaves que o `GraphCanvas` usa).
TYPE_COLORS: Dict[str, str] = {
    "ministerio": "#38bdf8",
    "membro": "#f472b6",
    "gabinete": "#a78bfa",
    "nomeacao": "#fbbf24",
    "pessoa": "#34d399",
    "empresa": "#60a5fa",
}
TYPE_LABELS: Dict[str, str] = {
    "ministerio": "Ministérios",
    "membro": "Membros do Governo",
    "gabinete": "Gabinetes",
    "nomeacao": "Nomeações",
    "pessoa": "Pessoas",
    "empresa": "Empresas",
}

MAX_GRAPH_ROWS = 60
MAX_DETAIL_ROWS = 400
MAX_COMPANY_NODES = 24


# ---------------------------------------------------------------------------
# Utilitários
# ---------------------------------------------------------------------------
def _fold(value: Any) -> str:
    text = unicodedata.normalize("NFKD", str(value or ""))
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    return " ".join(text.casefold().split())


def _slug(value: Any) -> str:
    return re.sub(r"[^a-z0-9]+", "-", _fold(value)).strip("-")


def _money(value: Any) -> Optional[float]:
    try:
        return float(value) if value not in (None, "") else None
    except (TypeError, ValueError):
        return None


_CLIENT: Any = None
_INDICES_READY = False


def _client():
    """Cliente Elasticsearch preparado (uma única `ensure_indices` por processo).

    `ensure_indices` percorre e cria dezenas de índices: correr isto em cada
    `_search`/`_count` fazia a visão geral demorar ~10 s em vez de ~1 s.
    """
    global _CLIENT, _INDICES_READY
    if _CLIENT is None:
        _CLIENT = get_es_client()
        if not _CLIENT:
            return None
    if not _INDICES_READY:
        try:
            ensure_indices(_CLIENT)
        except Exception:
            pass
        _INDICES_READY = True
    return _CLIENT


def _search(index: str, body: Dict[str, Any], *, size: int = 1) -> List[Dict[str, Any]]:
    client = _client()
    if not client:
        return []
    try:
        response = client.search(index=index, body={**body, "size": size}, _source=True)
    except Exception:
        return []
    return [{**hit.get("_source", {}), "id": hit.get("_id")} for hit in response.get("hits", {}).get("hits", [])]


def _count(index: str, body: Optional[Dict[str, Any]] = None) -> int:
    client = _client()
    if not client:
        return 0
    try:
        response = client.count(index=index, body=body or {"query": {"match_all": {}}})
        return int(response.get("count") or 0)
    except Exception:
        return 0


def _node(
    node_id: str,
    label: str,
    node_type: str,
    *,
    value: float = 1,
    subtitle: str = "",
    extra: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    color = TYPE_COLORS.get(node_type, "#94a3b8")
    label_short = (label or node_id)[:120]
    radius = 10 + min(22, math.sqrt(max(1.0, float(value))) * 4)
    return {
        "id": node_id,
        "key": node_id,
        "label": label_short,
        "dimension": node_type,
        "type": node_type,
        "role": TYPE_LABELS.get(node_type, node_type),
        "subtitle": subtitle,
        "count": int(max(1, value)),
        "total_value": float(value),
        "value": float(value),
        "radius": round(radius, 1),
        "color": color,
        "legendKey": node_type,
        "legendLabel": TYPE_LABELS.get(node_type, node_type),
        **(extra or {}),
    }


def _edge(source: str, target: str, label: str, *, value: float = 1, count: int = 1) -> Dict[str, Any]:
    weight = max(0.2, min(1.0, math.log10(max(2.0, float(value))) / 3.0))
    return {
        "source": source,
        "target": target,
        "label": label,
        "role": label,
        "count": int(max(1, count)),
        "value": float(value),
        "weight": round(weight, 3),
    }


def _graph(
    nodes: Iterable[Dict[str, Any]],
    edges: Iterable[Dict[str, Any]],
    *,
    notes: List[str],
    dimension_a: str,
    dimension_b: str,
    metric: str = "nomeacoes",
    filters: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    node_list = list(nodes)
    edge_list = list(edges)
    node_ids = {node["id"] for node in node_list}
    edge_list = [edge for edge in edge_list if edge["source"] in node_ids and edge["target"] in node_ids]
    return {
        "nodes": node_list,
        "edges": edge_list,
        "meta": {
            "dimension_a": dimension_a,
            "dimension_b": dimension_b,
            "metric": metric,
            "mode": "auto",
            "sample_order": "relevance",
            "sample_limit": None,
            "documents_scanned": len(node_list),
            "documents_matching": len(node_list),
            "scanned_value": sum(float(node.get("value") or 0) for node in node_list),
            "nodes_total": len(node_list),
            "edges_total": len(edge_list),
            "kept_nodes": len(node_list),
            "kept_edges": len(edge_list),
            "omitted_edges": 0,
            "directed": False,
            "notes": notes,
            "filters": filters or {},
        },
    }


def _row_id(row: Dict[str, Any]) -> str:
    raw = "::".join(
        str(row.get(key) or "")
        for key in ("area_slug", "membro", "funcao", "nome", "data_nomeacao", "dre_url")
    )
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:20]


# ---------------------------------------------------------------------------
# Leituras
# ---------------------------------------------------------------------------
def list_members(q: str = "", area: str = "", size: int = 40, offset: int = 0) -> Dict[str, Any]:
    """Lista/pesquisa os membros do Governo na composição."""
    must: List[Dict[str, Any]] = []
    if q:
        must.append(
            {
                "multi_match": {
                    "query": q,
                    "fields": ["nome^4", "nome_oficial^3", "cargo^2", "area_nome", "biografia"],
                    "type": "best_fields",
                }
            }
        )
    if area:
        must.append({"term": {"area_slug": area}})
    body = {
        "query": {"bool": {"must": must}} if must else {"match_all": {}},
        "sort": [{"area_slug": {"order": "asc"}}, {"nome.keyword": {"order": "asc"}}],
    }
    items = _search(COMPOSICAO_INDEX, body, size=max(1, min(size, 200)))
    if offset:
        items = items[offset:]
    total = _count(COMPOSICAO_INDEX, {"query": body["query"]})
    return {
        "total": total,
        "items": [
            {
                "id": item.get("item_id") or item.get("id"),
                "nome": item.get("nome"),
                "nome_oficial": item.get("nome_oficial"),
                "cargo": item.get("cargo"),
                "grupo": item.get("grupo"),
                "area_slug": item.get("area_slug"),
                "area_nome": item.get("area_nome"),
                "foto": item.get("foto_biografia") or item.get("foto"),
                "periodo_inicio": item.get("periodo_inicio"),
                "periodo_fim": item.get("periodo_fim"),
            }
            for item in items
        ],
    }


def _get_member(member_id: str) -> Optional[Dict[str, Any]]:
    member_id = str(member_id or "").strip()
    if not member_id:
        return None
    found = _search(COMPOSICAO_INDEX, {"query": {"term": {"item_id": member_id}}}, size=1)
    if found:
        return found[0]
    found = _search(
        COMPOSICAO_INDEX,
        {
            "query": {
                "bool": {
                    "should": [
                        {"term": {"_id": member_id}},
                        {"term": {"nome.keyword": member_id}},
                    ],
                    "minimum_should_match": 1,
                }
            }
        },
        size=1,
    )
    if found:
        return found[0]
    found = _search(COMPOSICAO_INDEX, {"query": {"match_phrase": {"nome": member_id}}}, size=1)
    return found[0] if found else None


def _get_ministerio(area_slug: str) -> Optional[Dict[str, Any]]:
    found = _search(MINISTERIOS_INDEX, {"query": {"term": {"area_slug": area_slug}}}, size=1)
    return found[0] if found else None


def _cabinet_rows(member: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Nomeações do gabinete do membro (não do ministério inteiro)."""
    area_slug = str(member.get("area_slug") or "")
    if member.get("grupo") == "Primeiro-Ministro":
        area_slug = "primeiro-ministro"
    if not area_slug:
        return []
    rows = _search(
        NOMEACOES_INDEX,
        {
            "query": {"term": {"area_slug": area_slug}},
            "sort": [{"data_nomeacao": {"order": "desc"}}],
        },
        size=1000,
    )
    cargo = _fold(member.get("cargo") or "")
    if not cargo:
        return rows
    matched = []
    for row in rows:
        membro = _fold(row.get("membro") or "")
        if cargo and (cargo in membro or membro in cargo):
            matched.append(row)
    return matched or rows


def _person_match(name: str) -> Optional[Dict[str, Any]]:
    result = search_people(q=name, size=8)
    target = _fold(name)
    for person in result.get("items", []):
        if _fold(person.get("name")) == target:
            return person
    return None


# ---------------------------------------------------------------------------
# Grafo geral
# ---------------------------------------------------------------------------
def graph_overview() -> Dict[str, Any]:
    """Grafo ministério → membro → gabinete, com os totais das nomeações."""
    ministries = _search(
        MINISTERIOS_INDEX,
        {"query": {"match_all": {}}, "sort": [{"area_slug": {"order": "asc"}}]},
        size=100,
    )
    members = _search(
        COMPOSICAO_INDEX,
        {
            "query": {"match_all": {}},
            "sort": [{"area_slug": {"order": "asc"}}, {"nome.keyword": {"order": "asc"}}],
        },
        size=200,
    )

    nodes: Dict[str, Dict[str, Any]] = {}
    edges: List[Dict[str, Any]] = []
    for ministry in ministries:
        slug = str(ministry.get("area_slug") or "")
        total = int(ministry.get("nomeacoes_count") or 0)
        ministry_id = f"ministerio:{slug}"
        cabinet_id = f"gabinete:{slug}"
        nodes[ministry_id] = _node(
            ministry_id,
            ministry.get("area") or slug,
            "ministerio",
            value=max(1, total),
            subtitle=f"{total} nomeações",
            extra={"area_slug": slug, "titular": ministry.get("titular"), "url": ministry.get("url")},
        )
        nodes[cabinet_id] = _node(
            cabinet_id,
            f"Gabinete — {ministry.get('area') or slug}",
            "gabinete",
            value=max(1, total),
            subtitle=f"{ministry.get('secretarios_count') or 0} secretários",
            extra={"area_slug": slug},
        )
        edges.append(_edge(ministry_id, cabinet_id, "nomeações", value=max(1, total), count=total))

    for member in members:
        slug = str(member.get("area_slug") or "")
        if member.get("grupo") == "Primeiro-Ministro":
            slug = "primeiro-ministro"
        member_id = f"membro:{member.get('item_id') or member.get('id')}"
        ministry_id = f"ministerio:{slug}"
        cabinet_id = f"gabinete:{slug}"
        nodes[member_id] = _node(
            member_id,
            member.get("nome") or "",
            "membro",
            value=1,
            subtitle=member.get("cargo") or "",
            extra={
                "member_id": member.get("item_id") or member.get("id"),
                "area_slug": slug,
                "foto": member.get("foto_biografia") or member.get("foto"),
                "grupo": member.get("grupo"),
            },
        )
        papel = "titular" if member.get("grupo") in ("Ministros", "Primeiro-Ministro") else "secretário"
        edges.append(_edge(ministry_id, member_id, papel, value=1))
        edges.append(_edge(member_id, cabinet_id, "gabinete", value=1))

    stats = {
        "ministerios": _count(MINISTERIOS_INDEX),
        "membros": _count(COMPOSICAO_INDEX),
        "nomeacoes": _count(NOMEACOES_INDEX),
        "composicao": _count(COMPOSICAO_INDEX),
        "scraped": _count(
            SCRAPED_INDEX,
            {
                "query": {
                    "terms": {
                        "source_id": ["governo-nomeacoes", "governo-composicao", "governo-ministerios"]
                    }
                }
            },
        ),
    }
    return {
        "stats": stats,
        "areas": [
            {
                "area_slug": ministry.get("area_slug"),
                "area": ministry.get("area"),
                "tipo": ministry.get("tipo"),
                "titular": ministry.get("titular"),
                "cargo": ministry.get("cargo"),
                "secretarios_count": ministry.get("secretarios_count"),
                "nomeacoes_count": ministry.get("nomeacoes_count"),
                "url": ministry.get("url"),
            }
            for ministry in ministries
        ],
        "membros": list_members(size=200).get("items", []),
        "graph": _graph(
            nodes.values(),
            edges,
            notes=["Ministérios, membros do Governo, gabinetes e o volume de nomeações."],
            dimension_a="ministerio",
            dimension_b="membro",
            metric="nomeacoes",
        ),
    }


# ---------------------------------------------------------------------------
# Ficha de um membro
# ---------------------------------------------------------------------------
def member_detail(member_id: str) -> Dict[str, Any]:
    member = _get_member(member_id)
    if not member:
        return {"error": f"Membro do Governo não encontrado: {member_id}", "id": member_id}
    area_slug = str(member.get("area_slug") or "")
    if member.get("grupo") == "Primeiro-Ministro":
        area_slug = "primeiro-ministro"
    ministry = _get_ministerio(area_slug) or {}
    rows = _cabinet_rows(member)

    salaries = [row for row in rows if _money(row.get("rendimento_bruto_eur")) is not None]
    bruto = [float(row["rendimento_bruto_eur"]) for row in salaries]
    liquido = [float(row["rendimento_liquido_eur"]) for row in salaries if _money(row.get("rendimento_liquido_eur")) is not None]
    por_funcao: Dict[str, Dict[str, Any]] = {}
    for row in salaries:
        key = str(row.get("funcao") or "—")
        entry = por_funcao.setdefault(key, {"funcao": key, "total": 0, "bruto": 0.0, "liquido": 0.0})
        entry["total"] += 1
        entry["bruto"] += _money(row.get("rendimento_bruto_eur")) or 0.0
        entry["liquido"] += _money(row.get("rendimento_liquido_eur")) or 0.0

    remuneracoes = {
        "total": len(rows),
        "total_bruto_eur": round(sum(bruto), 2),
        "total_liquido_eur": round(sum(liquido), 2),
        "media_bruta_eur": round(sum(bruto) / len(bruto), 2) if bruto else None,
        "media_liquida_eur": round(sum(liquido) / len(liquido), 2) if liquido else None,
        "min_bruta_eur": min(bruto) if bruto else None,
        "max_bruta_eur": max(bruto) if bruto else None,
        "por_funcao": sorted(por_funcao.values(), key=lambda item: (-item["total"], item["funcao"])),
        "linhas": [
            {
                "id": _row_id(row),
                "funcao": row.get("funcao"),
                "nome": row.get("nome"),
                "rendimento_bruto_eur": row.get("rendimento_bruto_eur"),
                "rendimento_liquido_eur": row.get("rendimento_liquido_eur"),
                "data_nomeacao": row.get("data_nomeacao"),
                "dre_url": row.get("dre_url"),
                "dre_titulo": row.get("dre_titulo"),
                "dre_sumario": row.get("dre_sumario"),
            }
            for row in rows[:MAX_DETAIL_ROWS]
        ],
    }

    relations: List[Dict[str, Any]] = []
    if ministry:
        relations.append(
            {
                "tipo": "ministerio",
                "label": ministry.get("area") or area_slug,
                "cargo": member.get("cargo"),
                "papel": "titular" if member.get("grupo") in ("Ministros", "Primeiro-Ministro") else "secretário",
                "url": ministry.get("url"),
                "area_slug": area_slug,
            }
        )
    relations.append(
        {
            "tipo": "gabinete",
            "label": member.get("cargo") or "Gabinete",
            "total": len(rows),
            "total_bruto_eur": remuneracoes["total_bruto_eur"],
            "area_slug": area_slug,
        }
    )

    person = _person_match(str(member.get("nome") or ""))
    company_nodes: List[Dict[str, Any]] = []
    if person:
        relations.append(
            {
                "tipo": "pessoa",
                "label": person.get("name"),
                "nif": person.get("nif"),
                "url": f"/governo/pessoa/{person.get('nif')}",
                "cargos": len(person.get("roles") or []),
                "empresas": len(person.get("companies") or []),
            }
        )
        company_nodes = _person_company_nodes(person)

    for row in rows[:10]:
        if row.get("dre_url"):
            relations.append(
                {
                    "tipo": "dre",
                    "label": row.get("dre_titulo") or "Despacho",
                    "url": row.get("dre_url"),
                    "data": row.get("data_nomeacao"),
                    "sumario": (row.get("dre_sumario") or "")[:240],
                }
            )

    graph = _member_graph(member, ministry, rows, person, company_nodes)
    return {
        "kind": "membro",
        "id": member.get("item_id") or member.get("id"),
        "membro": {
            "id": member.get("item_id") or member.get("id"),
            "nome": member.get("nome"),
            "nome_oficial": member.get("nome_oficial"),
            "cargo": member.get("cargo"),
            "grupo": member.get("grupo"),
            "area_slug": area_slug,
            "area_nome": member.get("area_nome"),
            "periodo_inicio": member.get("periodo_inicio"),
            "periodo_fim": member.get("periodo_fim"),
            "foto": member.get("foto_biografia") or member.get("foto"),
            "biografia": member.get("biografia"),
            "url": member.get("url"),
        },
        "ministerio": {
            "area": ministry.get("area"),
            "area_slug": area_slug,
            "titular": ministry.get("titular"),
            "cargo": ministry.get("cargo"),
            "secretarios_count": ministry.get("secretarios_count"),
            "nomeacoes_count": ministry.get("nomeacoes_count"),
            "url": ministry.get("url"),
        }
        if ministry
        else None,
        "remuneracoes": remuneracoes,
        "relacoes": relations,
        "pessoa": person,
        "grafo": graph,
    }


def _person_company_nodes(person: Dict[str, Any]) -> List[Dict[str, Any]]:
    nodes: List[Dict[str, Any]] = []
    seen: set[str] = set()
    for role in (person.get("roles") or [])[:MAX_COMPANY_NODES]:
        cnif = str(role.get("company_nif") or "")
        if not cnif or cnif in seen:
            continue
        seen.add(cnif)
        nodes.append(
            _node(
                f"empresa:{cnif}",
                role.get("company_name") or cnif,
                "empresa",
                value=1,
                subtitle=role.get("role") or "",
                extra={"nif": cnif},
            )
        )
    return nodes


def _member_graph(
    member: Dict[str, Any],
    ministry: Dict[str, Any],
    rows: List[Dict[str, Any]],
    person: Optional[Dict[str, Any]],
    company_nodes: List[Dict[str, Any]],
) -> Dict[str, Any]:
    member_id = f"membro:{member.get('item_id') or member.get('id')}"
    area_slug = str(member.get("area_slug") or "")
    if member.get("grupo") == "Primeiro-Ministro":
        area_slug = "primeiro-ministro"
    ministry_id = f"ministerio:{area_slug}"
    cabinet_id = f"gabinete:{area_slug}"
    nodes: Dict[str, Dict[str, Any]] = {
        member_id: _node(
            member_id,
            member.get("nome") or "",
            "membro",
            value=max(1, len(rows)),
            subtitle=member.get("cargo") or "",
            extra={"member_id": member.get("item_id") or member.get("id"), "area_slug": area_slug},
        ),
        ministry_id: _node(
            ministry_id,
            (ministry or {}).get("area") or area_slug,
            "ministerio",
            value=max(1, int((ministry or {}).get("nomeacoes_count") or len(rows))),
            subtitle=f"{(ministry or {}).get('secretarios_count') or 0} secretários",
            extra={"area_slug": area_slug},
        ),
        cabinet_id: _node(
            cabinet_id,
            f"Gabinete — {member.get('cargo') or area_slug}",
            "gabinete",
            value=max(1, len(rows)),
            subtitle=f"{len(rows)} nomeações",
            extra={"area_slug": area_slug},
        ),
    }
    edges: List[Dict[str, Any]] = [
        _edge(
            ministry_id,
            member_id,
            "titular" if member.get("grupo") in ("Ministros", "Primeiro-Ministro") else "secretário",
            value=1,
        ),
        _edge(member_id, cabinet_id, "gabinete", value=max(1, len(rows)), count=len(rows)),
    ]
    for row in rows[:MAX_GRAPH_ROWS]:
        row_id = f"nomeacao:{_row_id(row)}"
        value = _money(row.get("rendimento_bruto_eur")) or 1
        nodes[row_id] = _node(
            row_id,
            row.get("nome") or "",
            "nomeacao",
            value=value,
            subtitle=row.get("funcao") or "",
            extra={
                "funcao": row.get("funcao"),
                "data_nomeacao": row.get("data_nomeacao"),
                "bruto_eur": row.get("rendimento_bruto_eur"),
                "liquido_eur": row.get("rendimento_liquido_eur"),
                "dre_url": row.get("dre_url"),
            },
        )
        edges.append(_edge(cabinet_id, row_id, row.get("funcao") or "nomeação", value=value, count=1))

    if person:
        person_id = f"pessoa:{person.get('nif')}"
        nodes[person_id] = _node(
            person_id,
            person.get("name") or "",
            "pessoa",
            value=max(1, len(company_nodes)),
            subtitle="Pessoa em entidades",
            extra={"nif": person.get("nif")},
        )
        edges.append(_edge(member_id, person_id, "mesma pessoa", value=1))
        for company in company_nodes:
            nodes[company["id"]] = company
            edges.append(_edge(person_id, company["id"], company.get("subtitle") or "cargo", value=1))

    omitted = max(0, len(rows) - MAX_GRAPH_ROWS)
    return _graph(
        nodes.values(),
        edges,
        notes=[
            "Ficha do membro: ministério, gabinete, nomeações e pessoas/empresas ligadas.",
            f"{omitted} nomeações não desenhadas (limite {MAX_GRAPH_ROWS})."
            if omitted
            else "Todas as nomeações do gabinete estão no grafo.",
        ],
        dimension_a="membro",
        dimension_b="nomeacao",
        metric="valor",
        filters={"membro": member.get("nome"), "area_slug": area_slug},
    )


# ---------------------------------------------------------------------------
# Ficha de uma pessoa de entidade
# ---------------------------------------------------------------------------
def person_detail(nif: str) -> Dict[str, Any]:
    nif = str(nif or "").strip()
    if not nif:
        return {"error": "NIF em falta.", "nif": nif}
    person = get_person_by_nif(nif)
    if person.get("error") or not person.get("name"):
        return {"error": person.get("error") or f"Pessoa {nif} não encontrada.", "nif": nif}

    graph_data = people_graph_for_person(nif)
    nodes: Dict[str, Dict[str, Any]] = {}
    edges: List[Dict[str, Any]] = []
    nodes[f"pessoa:{nif}"] = _node(
        f"pessoa:{nif}",
        person.get("name") or nif,
        "pessoa",
        value=max(1, len(person.get("roles") or [])),
        subtitle=f"{len(person.get('companies') or [])} empresas",
        extra={"nif": nif},
    )
    for node in graph_data.get("nodes", []):
        node_type = "empresa" if node.get("type") == "company" else "pessoa"
        node_id = f"{node_type}:{node.get('nif') or node.get('id')}"
        if node_id in nodes:
            continue
        nodes[node_id] = _node(
            node_id,
            node.get("label") or node.get("nif") or node_id,
            node_type,
            value=1,
            extra={"nif": node.get("nif")},
        )
    for edge in graph_data.get("edges", []):
        target_raw = str(edge.get("target", ""))
        target_type = "empresa" if target_raw.startswith("company:") else "pessoa"
        target = f"{target_type}:{target_raw.split(':', 1)[-1]}"
        edges.append(
            _edge(
                f"pessoa:{nif}",
                target,
                edge.get("label") or "cargo",
                value=max(1, edge.get("count") or 1),
                count=int(edge.get("count") or 1),
            )
        )

    government = None
    found = _search(COMPOSICAO_INDEX, {"query": {"match_phrase": {"nome": person.get("name")}}}, size=1)
    if found:
        member = found[0]
        government = {
            "id": member.get("item_id") or member.get("id"),
            "nome": member.get("nome"),
            "cargo": member.get("cargo"),
            "area_slug": member.get("area_slug"),
            "url": f"/governo/ficha/{member.get('item_id') or member.get('id')}",
        }
        member_id = f"membro:{government['id']}"
        nodes[member_id] = _node(
            member_id,
            member.get("nome") or "",
            "membro",
            value=1,
            subtitle=member.get("cargo") or "",
            extra={"member_id": government["id"], "area_slug": member.get("area_slug")},
        )
        edges.append(_edge(f"pessoa:{nif}", member_id, "membro do Governo", value=1))

    return {
        "kind": "pessoa",
        "id": nif,
        "pessoa": {
            "nif": nif,
            "nome": person.get("name"),
            "is_company": bool(person.get("is_company")),
            "roles_count": person.get("roles_count") or len(person.get("roles") or []),
            "companies_count": person.get("companies_count") or len(person.get("companies") or []),
            "companies": (person.get("companies") or [])[:40],
            "latest_roles": (person.get("latest_roles") or person.get("roles") or [])[:40],
            "first_seen": person.get("first_seen"),
            "last_seen": person.get("last_seen"),
        },
        "governo": government,
        "grafo": _graph(
            nodes.values(),
            edges,
            notes=["Pessoa, cargos em empresas e, quando aplicável, a ligação ao Governo."],
            dimension_a="pessoa",
            dimension_b="empresa",
            metric="cargos",
            filters={"nif": nif},
        ),
    }
