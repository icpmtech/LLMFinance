"""Ontologia de uma pesquisa: que entidades aparecem e como se ligam.

Uma pesquisa na Pesquisa total devolve listas; a **ontologia da pesquisa** mostra
o mesmo conjunto como grafo — o termo no centro, as empresas, pessoas, notícias e
contratos que casam com ele à volta, e as ligações que existem entre eles
(`pessoa → empresa` pelos cargos do registo, `termo → resultado` pelo que a
pesquisa encontrou).

Não se inventam relações: cada aresta sai de um dado real — o `roles.company_nif`
das fichas de pessoas, os NIFs das fichas de empresas, o âmbito de onde o
resultado veio. O grafo é devolvido em JSON (nós/arestas, para desenhar em
qualquer lado) e em **Mermaid** (texto pronto a colar num relatório).

Reutiliza a Pesquisa total como fonte: o mesmo `q`/`scope`/`filters` devolve os
mesmos itens, pelo que grafo e lista nunca divergem.
"""
from __future__ import annotations

import logging
import re
from typing import Any, Dict, List, Optional

from api.elasticsearch_client import search_people_faceted
from api.search_service import unified_search

logger = logging.getLogger(__name__)

#: Âmbitos que entram na ontologia e o que cada um significa no grafo.
ONTOLOGY_SCOPES: Dict[str, str] = {
    "entities": "empresa",
    "entities_es": "empresa_es",
    "pessoas": "pessoa",
    "politicos": "politico",
    "contracts": "contrato",
    "contracts_es": "contrato_es",
    "news": "noticia",
    "imprensa": "noticia",
    "wikipedia": "referencia",
    "trademarks": "marca",
    "firmas": "firma",
}

TYPE_LABELS: Dict[str, str] = {
    "termo": "Termo",
    "empresa": "Empresa",
    "empresa_es": "Empresa (ES)",
    "pessoa": "Pessoa",
    "politico": "Político",
    "contrato": "Contrato",
    "contrato_es": "Contrato (ES)",
    "noticia": "Notícia",
    "referencia": "Referência",
    "marca": "Marca",
    "firma": "Firma",
}

#: Cor de cada tipo no Mermaid (as arestas levam a relação).
TYPE_STYLES: Dict[str, str] = {
    "termo": "fill:#1d4ed8,stroke:#93c5fd,color:#ffffff",
    "empresa": "fill:#0f766e,stroke:#5eead4,color:#ffffff",
    "empresa_es": "fill:#115e59,stroke:#5eead4,color:#ffffff",
    "pessoa": "fill:#7c2d12,stroke:#fdba74,color:#ffffff",
    "politico": "fill:#78350f,stroke:#fcd34d,color:#ffffff",
    "contrato": "fill:#334155,stroke:#cbd5e1,color:#ffffff",
    "contrato_es": "fill:#1e293b,stroke:#cbd5e1,color:#ffffff",
    "noticia": "fill:#4c1d95,stroke:#d8b4fe,color:#ffffff",
    "referencia": "fill:#164e63,stroke:#a5f3fc,color:#ffffff",
    "marca": "fill:#831843,stroke:#f9a8d4,color:#ffffff",
    "firma": "fill:#27272a,stroke:#d4d4d8,color:#ffffff",
}

MAX_PER_TYPE = 10
MAX_PEOPLE_LINKS = 8
#: Quantos itens de cada âmbito entram no grafo. Os contratos são muitos e
#: grandes: deixá-los dominar escondia as empresas e as pessoas, que são o que
#: interessa ver numa ontologia.
MAX_BY_SCOPE: Dict[str, int] = {
    "contracts": 4,
    "contracts_es": 4,
    "news": 4,
    "imprensa": 4,
    "wikipedia": 3,
    "entities": 8,
    "entities_es": 4,
    "pessoas": 8,
    "politicos": 8,
    "trademarks": 4,
    "firmas": 2,
}


def _nif_from_item(item: Dict[str, Any]) -> str:
    """NIF do item, quando a vista interna que o abre é uma ficha."""
    target = item.get("open") or {}
    arg = str(target.get("arg") or "")
    if target.get("view") in {"company-detail", "person-detail"} and arg:
        return arg
    raw = str(item.get("id") or "")
    return raw if raw.isdigit() else ""


def _node_id(kind: str, key: str) -> str:
    return f"{kind}:{key}"


def _mermaid_id(index: int) -> str:
    return f"n{index}"


def _mermaid_text(text: Any, limit: int = 48) -> str:
    """Texto seguro para um rótulo Mermaid (aspas e quebras fora)."""
    clean = re.sub(r"\s+", " ", str(text or "")).strip().replace('"', "'")
    return clean if len(clean) <= limit else clean[: limit - 1] + "…"


def _person_companies(person_nif: str, known: Dict[str, Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Empresas de uma pessoa, pelas fichas (`roles.company_nif`), entre as do grafo."""
    result = search_people_faceted(filters={"nif": str(person_nif)}, size=1, sort="name")
    rows = result.get("items") or []
    if not rows:
        return []
    edges: List[Dict[str, Any]] = []
    seen: set = set()
    for role in rows[0].get("roles") or []:
        nif = str(role.get("company_nif") or "")
        if not nif or nif in seen or nif not in known:
            continue
        seen.add(nif)
        edges.append(
            {
                "source": _node_id("person", str(person_nif)),
                "target": _node_id("company", nif),
                "label": role.get("role") or role.get("acto") or "cargo",
                "kind": "cargo",
                "weight": 1,
            }
        )
    return edges


def search_ontology(
    query: str,
    *,
    scope: str = "all",
    filters: Optional[Dict[str, str]] = None,
    size: int = 12,
    session_scope: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Grafo (nós/arestas + Mermaid) do que a pesquisa encontrou."""
    term = (query or "").strip()
    if not term:
        return {"term": "", "nodes": [], "edges": [], "legend": [], "totals": {"nodes": 0, "edges": 0}, "mermaid": ""}

    payload = unified_search(term, scope=scope, size=size, filters=filters, session_scope=session_scope)
    term_id = _node_id("term", term.lower())
    nodes: List[Dict[str, Any]] = [
        {
            "id": term_id,
            "label": term,
            "type": "termo",
            "type_label": TYPE_LABELS["termo"],
            "scope": scope,
            "depth": 0,
        }
    ]
    seen: Dict[str, Dict[str, Any]] = {term_id: nodes[0]}
    edges: List[Dict[str, Any]] = []
    seen_edges: set = set()

    def _add_edge(source: str, target: str, label: str, kind: str, weight: int = 1) -> None:
        """Aresta única: o mesmo par (origem, destino, tipo) não se repete."""
        key = (source, target, kind)
        if key in seen_edges:
            return
        seen_edges.add(key)
        edges.append({"id": f"{source}->{target}", "source": source, "target": target, "label": label, "kind": kind, "weight": weight})

    counts: Dict[str, int] = {}
    companies: Dict[str, Dict[str, Any]] = {}

    for group in payload.get("groups") or []:
        kind = ONTOLOGY_SCOPES.get(str(group.get("scope") or ""))
        if not kind or not group.get("items"):
            continue
        counts[group["scope"]] = int(group.get("total") or 0)
        limite = MAX_BY_SCOPE.get(str(group.get("scope") or ""), MAX_PER_TYPE)
        for index, item in enumerate(group.get("items") or []):
            if index >= limite:
                break
            nif = _nif_from_item(item)
            key = nif or str(item.get("id") or item.get("title") or len(seen))
            node_id = _node_id(kind, key)
            if node_id in seen:
                continue
            node = {
                "id": node_id,
                "label": item.get("title") or key,
                "type": kind,
                "type_label": TYPE_LABELS.get(kind, kind),
                "scope": group.get("scope"),
                "subtitle": item.get("subtitle") or "",
                "url": item.get("url") or "",
                "open": item.get("open"),
                "date": item.get("date"),
                "value": (item.get("extra") or {}).get("preco"),
                "depth": 1,
            }
            nodes.append(node)
            seen[node_id] = node
            _add_edge(term_id, node_id, TYPE_LABELS.get(kind, kind).lower(), "resultado")
            if kind == "empresa" and nif:
                companies[nif] = node
            # Contrato → empresa: a parte adjudicatária vem no próprio item, pelo
            # que o grafo mostra quem ganhou, e não só o objeto do contrato.
            if kind in {"contrato", "contrato_es"}:
                extra = item.get("extra") or {}
                party_nif = str(extra.get("adjudicatario_nif") or "").strip()
                party_name = str(extra.get("adjudicatario") or "").strip()
                if party_nif or party_name:
                    company_id = _node_id("company", party_nif or party_name)
                    if company_id not in seen:
                        company = {
                            "id": company_id,
                            "label": party_name or party_nif,
                            "type": "empresa",
                            "type_label": TYPE_LABELS["empresa"],
                            "scope": group.get("scope"),
                            "nif": party_nif,
                            "depth": 2,
                        }
                        nodes.append(company)
                        seen[company_id] = company
                        if party_nif:
                            companies[party_nif] = company
                    _add_edge(node_id, company_id, "adjudicatário", "adjudicatario")

    # Pessoa → empresa, pelos cargos do registo (só quando a empresa também está no grafo).
    people = [node for node in nodes if node["type"] in {"pessoa", "politico"}]
    for person in people[:MAX_PEOPLE_LINKS]:
        person_nif = person["id"].split(":", 1)[1]
        for edge in _person_companies(person_nif, companies):
            _add_edge(edge["source"], edge["target"], edge["label"], edge["kind"])

    # Mermaid: ids curtos e rótulos entre aspas (é o que o parser aceita).
    lines = ["flowchart LR"]
    ids = {node["id"]: _mermaid_id(index) for index, node in enumerate(nodes)}
    for node in nodes:
        label = _mermaid_text(node.get("label"))
        extra = node.get("value")
        if isinstance(extra, (int, float)) and extra:
            label += f" · {extra:,.0f} €".replace(",", " ")
        lines.append(f'  {ids[node["id"]]}["{label}"]')
    edge_lines = []
    for edge in edges:
        source = ids.get(edge["source"])
        target = ids.get(edge["target"])
        if not source or not target:
            continue
        edge_lines.append(f'  {source} -->|"{_mermaid_text(edge["label"], 28)}"| {target}')
    lines.extend(edge_lines)
    for kind, style in TYPE_STYLES.items():
        members = [ids[node["id"]] for node in nodes if node["type"] == kind]
        if members:
            lines.append(f"  classDef {kind} {style};")
            lines.append(f"  class {','.join(members)} {kind};")

    return {
        "term": term,
        "scope": scope,
        "filters": filters or {},
        "nodes": nodes,
        "edges": edges,
        "legend": [
            {"type": kind, "label": TYPE_LABELS.get(kind, kind), "style": TYPE_STYLES.get(kind, "")}
            for kind in sorted({node["type"] for node in nodes})
        ],
        "totals": {
            "nodes": len(nodes),
            "edges": len(edges),
            "by_type": {kind: sum(1 for node in nodes if node["type"] == kind) for kind in TYPE_LABELS},
            "scopes": counts,
            "results": payload.get("total") or 0,
        },
        "mermaid": "\n".join(lines),
        "caveats": [
            "As ligações saem dos dados reais: `termo → resultado` pelo que a pesquisa encontrou e "
            "`pessoa → empresa` pelos cargos do registo (CIRE/societário/parlamento).",
        ],
    }
