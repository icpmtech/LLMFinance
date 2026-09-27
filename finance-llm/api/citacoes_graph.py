"""Grafo do módulo de citações e notificações editais (CITIUS).

Constrói uma rede a partir do índice ``finance_citacoes_edital``: cada nó é um
valor de uma **dimensão** (interveniente, papel, tribunal, comarca, tipo de
édito, processo, modelo do documento, NIF, tempo…) e cada aresta é a
**co-ocorrência** desses valores no mesmo édito — ou a ligação entre duas
dimensões distintas (ex.: parte ativa → parte passiva, agente de execução →
comarca).

As dimensões de **entidade** vêm dos intervenientes (``intervenientes`` é uma
lista ``nested`` com ``papel``/``nome``/``nif``) e são derivadas do papel:

- ``parte_ativa``   → Exequente, Autor, Requerente, Embargante, Habilitante
- ``parte_passiva`` → Executado, Réu, Requerido, Citado, Notificado, Arguido
- ``agente``        → Agente de Execução (Sol.)
- ``credor``        → Credor
- ``interveniente`` → qualquer papel
- ``nif``           → NIF/NIPC do documento analisado (`documento_nifs`)

O motor **percorre os documentos** (``scan_citacoes``, com ``search_after`` e um
teto configurável) em vez de usar agregações: as dimensões de entidade vivem em
listas ``nested`` e só a varredura permite cruzá-las e calcular valor/caracteres
por nó. Como o módulo recolhe janelas curtas (por omissão os últimos 6 meses),
o conjunto é pequeno.
"""
from __future__ import annotations

import logging
import re
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Set, Tuple

from api.elasticsearch_client import scan_citacoes

logger = logging.getLogger(__name__)

# ------------------------------------------------------------------ dimensões
# `type` agrupa a legenda/cores na UI; `field` = campo plano; `nested` = campo de
# `intervenientes`; `papeis` = papéis que compõem a dimensão (None = todos);
# `time` = dimensão temporal derivada de `data_publicacao`.
CITACOES_GRAPH_DIMENSIONS: Dict[str, Dict[str, Any]] = {
    "parte_ativa": {
        "label": "Parte ativa (exequente, autor, requerente)",
        "short": "Parte ativa",
        "type": "entidade",
        "papeis": ["Exequente", "Autor", "Requerente", "Embargante", "Habilitante", "Exequente(s)"],
    },
    "parte_passiva": {
        "label": "Parte passiva (executado, réu, requerido)",
        "short": "Citado",
        "type": "entidade",
        "papeis": ["Executado", "Réu", "Requerido", "Citado", "Notificado", "Arguido", "Embargado", "Habilitado"],
    },
    "agente": {
        "label": "Agente de execução",
        "short": "Agente",
        "type": "entidade",
        "papeis": ["Agente de Execução (Sol.)", "Agente de Execução"],
    },
    "credor": {"label": "Credor", "short": "Credor", "type": "entidade", "papeis": ["Credor"]},
    "interveniente": {
        "label": "Interveniente (qualquer papel)",
        "short": "Interveniente",
        "type": "entidade",
        "papeis": None,
    },
    "nif": {"label": "NIF/NIPC (do documento)", "short": "NIF", "type": "entidade", "field": "documento_nifs"},
    "sede": {
        "label": "Sede do tribunal (terra)",
        "short": "Sede",
        "type": "jurisdicao",
        "field": "tribunal_comarca",
    },
    "comarca": {"label": "Comarca judicial", "short": "Comarca", "type": "jurisdicao", "field": "comarca_judicial"},
    "tribunal": {"label": "Tribunal/serviço", "short": "Tribunal", "type": "jurisdicao", "field": "tribunal.keyword"},
    "juizo": {"label": "Juízo", "short": "Juízo", "type": "jurisdicao", "field": "juizo"},
    "tipo": {"label": "Tipo de édito (citação/notificação/anúncio)", "short": "Tipo", "type": "processo", "field": "tipo"},
    "ato": {"label": "Ato publicado", "short": "Ato", "type": "processo", "field": "ato.keyword"},
    "especie": {"label": "Espécie do processo", "short": "Espécie", "type": "processo", "field": "especie.keyword"},
    "processo": {"label": "Processo", "short": "Processo", "type": "processo", "field": "processo_numero"},
    "papel": {"label": "Papel do interveniente", "short": "Papel", "type": "processo", "nested": "intervenientes.papel"},
    "modelo": {
        "label": "Modelo do documento (PDF)",
        "short": "Modelo",
        "type": "documento",
        "field": "documento_modelo",
    },
    "titulo": {
        "label": "Título do documento",
        "short": "Título",
        "type": "documento",
        "field": "documento_titulo",
    },
    "assunto": {
        "label": "Assunto do documento",
        "short": "Assunto",
        "type": "documento",
        "field": "documento_assunto",
    },
    "ano": {"label": "Ano de publicação", "short": "Ano", "type": "tempo", "time": "year"},
    "mes": {"label": "Mês de publicação", "short": "Mês", "type": "tempo", "time": "month"},
}

#: Métricas: éditos (documentos distintos) ou menções (intervenções).
CITACOES_GRAPH_METRICS = {"editais": "Éditos", "mencoes": "Menções a intervenientes"}

#: Receitas prontas (perguntas frequentes sobre citações editais).
CITACOES_GRAPH_RECIPES: List[Dict[str, Any]] = [
    {
        "id": "quem-cita-quem",
        "label": "Quem cita quem",
        "description": "Liga a parte ativa (exequente/autor) à parte passiva (executado/réu) citada no édito.",
        "dimension_a": "parte_ativa",
        "dimension_b": "parte_passiva",
        "metric": "editais",
        "view": "network",
        "limit": 60,
    },
    {
        "id": "partes-do-mesmo-processo",
        "label": "Partes do mesmo processo",
        "description": "Intervenientes que aparecem no mesmo édito (quem é citado ao lado de quem).",
        "dimension_a": "interveniente",
        "dimension_b": "interveniente",
        "metric": "editais",
        "view": "network",
        "limit": 60,
    },
    {
        "id": "agente-comarca",
        "label": "Agentes por comarca",
        "description": "Sedes/comarcas onde cada agente de execução actua.",
        "dimension_a": "agente",
        "dimension_b": "sede",
        "metric": "editais",
        "view": "network",
        "limit": 50,
    },
    {
        "id": "citados-tribunal",
        "label": "Citados por tribunal",
        "description": "Que partes passivas aparecem em cada tribunal (sedes com mais éditos).",
        "dimension_a": "parte_passiva",
        "dimension_b": "tribunal",
        "metric": "editais",
        "view": "network",
        "limit": 60,
    },
    {
        "id": "tipo-comarca",
        "label": "Tipo de édito por comarca",
        "description": "Citações, notificações e anúncios distribuídos pelas comarcas.",
        "dimension_a": "comarca",
        "dimension_b": "tipo",
        "metric": "editais",
        "view": "sankey",
        "limit": 40,
    },
    {
        "id": "mes-tipo",
        "label": "Evolução por mês e tipo",
        "description": "Volume mensal de éditos, separado por citação/notificação/anúncio.",
        "dimension_a": "mes",
        "dimension_b": "tipo",
        "metric": "editais",
        "view": "sankey",
        "limit": 40,
    },
    {
        "id": "modelo-tribunal",
        "label": "Modelos de documento por tribunal",
        "description": "Que modelos de édito (PDF) cada tribunal usa — só éditos com documento analisado.",
        "dimension_a": "modelo",
        "dimension_b": "tribunal",
        "metric": "editais",
        "view": "network",
        "limit": 60,
    },
]

#: Tetos de segurança do servidor.
CITACOES_GRAPH_MAX_SCAN = 50_000
CITACOES_GRAPH_MAX_NODES = 5_000
CITACOES_GRAPH_MAX_EDGES = 20_000


def citacoes_graph_dimensions() -> Dict[str, Any]:
    """Dimensões, métricas, receitas e limites disponíveis para o grafo."""
    return {
        "dimensions": [
            {
                "key": key,
                "label": spec["label"],
                "short": spec["short"],
                "type": spec["type"],
            }
            for key, spec in CITACOES_GRAPH_DIMENSIONS.items()
        ],
        "metrics": [{"key": key, "label": label} for key, label in CITACOES_GRAPH_METRICS.items()],
        "recipes": CITACOES_GRAPH_RECIPES,
        "limits": {
            "max_scan": CITACOES_GRAPH_MAX_SCAN,
            "max_nodes": CITACOES_GRAPH_MAX_NODES,
            "max_edges": CITACOES_GRAPH_MAX_EDGES,
        },
    }


# ------------------------------------------------------------------- valores
def _fold(value: Any) -> str:
    """Minúsculas sem acentos (comparar papéis)."""
    import unicodedata

    texto = unicodedata.normalize("NFKD", str(value or "").strip().lower())
    return "".join(ch for ch in texto if not unicodedata.combining(ch))


def _month(value: Optional[str]) -> Optional[str]:
    """``2026-09-26`` → ``2026-09`` (mês de publicação)."""
    if not value:
        return None
    return str(value)[:7]


def _year(value: Optional[str]) -> Optional[str]:
    """``2026-09-26`` → ``2026``."""
    if not value:
        return None
    return str(value)[:4]


def _matches_papel(papeis_alvo: Optional[List[str]], papel: str) -> bool:
    """Indica se um papel do édito pertence à dimensão (comparação sem acentos)."""
    if papeis_alvo is None:
        return True
    alvo = _fold(papel)
    for candidato in papeis_alvo:
        base = _fold(candidato)
        if alvo == base or alvo.startswith(base) or base in alvo:
            return True
    return False


_SUFIXOS_RE = re.compile(r"\b(s\.?a\.?s?\.?|lda\.?|unipessoal|e\s+filhos|e\s+companhia)\b", re.I)


def _chave_entidade(nome: str) -> str:
    """Chave de agrupamento de um interveniente.

    A lista do portal e o PDF escrevem a mesma empresa de formas diferentes
    («Caixa Económica Montepio Geral» e «Caixa Económica Montepio Geral, Caixa
    Económica Bancária, S.A.»). A chave corta na primeira vírgula e remove
    sufixos societários, para a rede juntar as variantes sem juntar empresas
    distintas (ex.: «Montepio Crédito - Instituição Financeira de Crédito» é
    outra entidade).
    """
    texto = _fold(nome).split(",", 1)[0]
    texto = _SUFIXOS_RE.sub(" ", texto)
    return re.sub(r"\s+", " ", texto).strip(" .-")


def _values(doc: Dict[str, Any], dimension: str) -> List[Dict[str, Any]]:
    """Valores de uma dimensão num édito: ``[{id, label, description?}]``."""
    spec = CITACOES_GRAPH_DIMENSIONS.get(dimension)

    if dimension == "nif":
        out = []
        for nif in (doc.get("documento_nifs") or []) + [
            item.get("nif") for item in (doc.get("intervenientes") or []) if item.get("nif")
        ]:
            if nif and not any(entry["id"] == str(nif) for entry in out):
                out.append({"id": str(nif), "label": str(nif)})
        return out

    if dimension == "papel":
        out = []
        for papel in doc.get("papeis") or []:
            if papel and not any(entry["id"] == papel for entry in out):
                out.append({"id": str(papel), "label": str(papel)})
        return out

    if spec and spec.get("papeis") is not None:
        out = []
        for item in doc.get("intervenientes") or []:
            papel = str(item.get("papel") or "").strip()
            nome = str(item.get("nome") or "").strip()
            if not nome or not _matches_papel(spec["papeis"], papel):
                continue
            chave = _chave_entidade(nome)
            if chave and not any(entry["id"] == chave for entry in out):
                out.append({"id": chave, "label": nome, "papel": papel, "nif": item.get("nif")})
        return out

    if dimension == "interveniente":
        out = []
        for item in doc.get("intervenientes") or []:
            nome = str(item.get("nome") or "").strip()
            chave = _chave_entidade(nome)
            if chave and not any(entry["id"] == chave for entry in out):
                out.append({"id": chave, "label": nome, "papel": item.get("papel"), "nif": item.get("nif")})
        return out

    if dimension == "mes":
        valor = _month(doc.get("data_publicacao"))
        return [{"id": valor, "label": valor}] if valor else []

    if dimension == "ano":
        valor = _year(doc.get("data_publicacao"))
        return [{"id": valor, "label": valor}] if valor else []

    if spec and spec.get("field"):
        valores = doc.get(spec["field"].split(".")[0])
        if isinstance(valores, list):
            return [{"id": str(v), "label": str(v)} for v in valores if v]
        if valores in (None, ""):
            return []
        return [{"id": str(valores), "label": str(valores)}]

    return []


# ------------------------------------------------------------------- motor
def _add_node(
    nodes: Dict[str, Dict[str, Any]],
    dimension: str,
    item: Dict[str, Any],
    valor: float,
) -> str:
    """Acumula um nó (documentos, menções e valor) e devolve o seu id."""
    node_id = f"{dimension}|{item['id']}"
    node = nodes.get(node_id)
    if node is None:
        node = nodes[node_id] = {
            "id": node_id,
            "key": str(item["id"]),
            "label": item.get("label") or str(item["id"]),
            "dimension": dimension,
            "type": CITACOES_GRAPH_DIMENSIONS[dimension]["type"],
            "role": CITACOES_GRAPH_DIMENSIONS[dimension]["label"],
            "count": 0,
            "mentions": 0,
            "valor": 0.0,
            "keys": [],
        }
    if item.get("papel"):
        node.setdefault("keys", [])
        node["keys"] = list(dict.fromkeys([*node["keys"], item["papel"]]))[:6]
    if item.get("nif"):
        node["nif"] = item["nif"]
    # A mesma entidade aparece escrita de formas diferentes na lista e no PDF:
    # fica o rótulo mais curto (habitualmente o nome limpo).
    novo_label = str(item.get("label") or item["id"])
    if len(novo_label) < len(str(node["label"])):
        node["label"] = novo_label
    node["mentions"] += 1
    node["valor"] = round(float(node["valor"]) + valor, 2)
    return node_id


def _add_edge(
    edges: Dict[str, Dict[str, Any]],
    source: str,
    target: str,
    valor: float,
    directed: bool,
) -> str:
    """Acumula uma menção numa aresta e devolve a sua chave.

    A contagem de **éditos** da aresta é feita uma vez por documento (fora daqui),
    senão um édito com várias partes inflacionava o total.
    """
    if not directed and target < source:
        source, target = target, source
    key = f"{source}->{target}"
    edge = edges.get(key)
    if edge is None:
        edge = edges[key] = {"source": source, "target": target, "count": 0, "mentions": 0, "valor": 0.0}
    edge["mentions"] = int(edge.get("mentions") or 0) + 1
    edge["valor"] = round(float(edge["valor"]) + valor, 2)
    return key


def build_citacoes_graph(
    *,
    dimension_a: str,
    dimension_b: Optional[str] = None,
    metric: str = "editais",
    q: Optional[str] = None,
    referencia: Optional[str] = None,
    processo: Optional[str] = None,
    tribunal: Optional[str] = None,
    tribunal_comarca: Optional[str] = None,
    comarca_judicial: Optional[str] = None,
    tipo: Optional[str] = None,
    ato: Optional[str] = None,
    especie: Optional[str] = None,
    citado: Optional[str] = None,
    nome: Optional[str] = None,
    papel: Optional[str] = None,
    nif: Optional[str] = None,
    modelo: Optional[str] = None,
    data_from: Optional[str] = None,
    data_to: Optional[str] = None,
    has_documento: Optional[bool] = None,
    has_texto: Optional[bool] = None,
    min_count: int = 1,
    limit: int = 60,
    edge_limit: int = 400,
    max_docs: int = 20_000,
) -> Dict[str, Any]:
    """Constrói o grafo dos éditos de citação/notificação.

    Cada nó é uma entidade, tribunal, comarca, tipo, modelo ou período; cada
    aresta liga dois valores que co-ocorrem no mesmo édito (ou liga duas
    dimensões distintas, ex.: parte ativa → parte passiva).
    """
    if dimension_a not in CITACOES_GRAPH_DIMENSIONS:
        return {"error": f"Dimensão desconhecida: {dimension_a}", "nodes": [], "edges": []}
    if dimension_b and dimension_b not in CITACOES_GRAPH_DIMENSIONS:
        return {"error": f"Dimensão desconhecida: {dimension_b}", "nodes": [], "edges": []}
    metric = metric if metric in CITACOES_GRAPH_METRICS else "editais"
    dimension_b = dimension_b or None
    mesmo_lado = dimension_b == dimension_a
    max_docs = max(1, min(int(max_docs) or CITACOES_GRAPH_MAX_SCAN, CITACOES_GRAPH_MAX_SCAN))

    varredura = scan_citacoes(
        q=q,
        referencia=referencia,
        processo=processo,
        tribunal=tribunal,
        tribunal_comarca=tribunal_comarca,
        comarca_judicial=comarca_judicial,
        tipo=tipo,
        ato=ato,
        especie=especie,
        citado=citado,
        nome=nome,
        papel=papel,
        nif=nif,
        modelo=modelo,
        data_from=data_from,
        data_to=data_to,
        has_documento=has_documento,
        has_texto=has_texto,
        max_docs=max_docs,
    )
    if varredura.get("error"):
        return {"error": varredura["error"], "nodes": [], "edges": []}

    nodes: Dict[str, Dict[str, Any]] = {}
    edges: Dict[str, Dict[str, Any]] = {}
    valor_total = 0.0
    com_texto = 0

    for doc in varredura["items"]:
        valor = 0.0
        try:
            valor = float(doc.get("documento_valor") or 0.0)
        except (TypeError, ValueError):
            valor = 0.0
        valor_total += valor
        if doc.get("has_texto"):
            com_texto += 1

        valores_a = _values(doc, dimension_a)
        if not valores_a:
            continue
        ids_a = list(
            dict.fromkeys(_add_node(nodes, dimension_a, item, valor) for item in valores_a)
        )
        # Contagem por documento (a métrica «éditos» conta documentos distintos).
        for node_id in ids_a:
            nodes[node_id]["count"] += 1

        if not dimension_b:
            continue
        pares: Set[str] = set()
        if mesmo_lado:
            for index, left in enumerate(ids_a):
                for right in ids_a[index + 1:]:
                    pares.add(_add_edge(edges, left, right, valor, directed=False))
        else:
            valores_b = _values(doc, dimension_b)
            ids_b = list(
                dict.fromkeys(_add_node(nodes, dimension_b, item, valor) for item in valores_b)
            )
            for node_id in ids_b:
                nodes[node_id]["count"] += 1
            for left in ids_a:
                for right in ids_b:
                    pares.add(_add_edge(edges, left, right, valor, directed=True))
        # Um édito conta uma vez por aresta (mesmo com várias partes do mesmo lado).
        for key in pares:
            edges[key]["count"] = int(edges[key].get("count") or 0) + 1

    metric_key = "count" if metric == "editais" else "mentions"
    ordenados = sorted(
        [node for node in nodes.values() if node["count"] >= max(1, int(min_count))],
        key=lambda node: (node.get(metric_key) or 0, node.get("valor") or 0.0),
        reverse=True,
    )
    mantidos = ordenados[: max(1, min(int(limit) or CITACOES_GRAPH_MAX_NODES, CITACOES_GRAPH_MAX_NODES))]
    if not limit:
        mantidos = ordenados
    ids_mantidos = {node["id"] for node in mantidos}

    edge_metric = "count" if metric == "editais" else "mentions"
    arestas = [
        edge
        for edge in edges.values()
        if edge["source"] in ids_mantidos and edge["target"] in ids_mantidos
    ]
    arestas.sort(key=lambda edge: (edge.get(edge_metric) or 0, edge.get("valor") or 0.0), reverse=True)
    omitidas = 0
    if edge_limit:
        omitidas = max(0, len(arestas) - int(edge_limit))
        arestas = arestas[: int(edge_limit)]

    digitalizados = len(varredura["items"])
    notas = [f"Analisados {digitalizados} éditos dos {varredura['total']} que correspondem aos filtros."]
    if varredura.get("truncated"):
        notas.append(
            f"Varredura limitada a {digitalizados} éditos (teto do servidor: {max_docs}). "
            "Restrinja os filtros (datas, tribunal, tipo) para ver o conjunto completo."
        )
    if len(ordenados) > len(mantidos):
        notas.append(f"Mostrados {len(mantidos)} de {len(ordenados)} nós.")
    if omitidas:
        notas.append(f"{omitidas} arestas omitidas por limite.")
    if mesmo_lado:
        notas.append("Arestas = co-ocorrência no mesmo édito; o valor soma os éditos em que aparecem juntos.")

    return {
        "nodes": mantidos,
        "edges": arestas,
        "meta": {
            "dimension_a": dimension_a,
            "dimension_b": dimension_b,
            "metric": metric,
            "mode": "varredura",
            "complete": not varredura.get("truncated"),
            "documents_scanned": digitalizados,
            "documents_matching": int(varredura.get("total") or digitalizados),
            "documents_value": round(valor_total, 2),
            "documents_with_text": com_texto,
            "nodes_total": len(ordenados),
            "edges_total": len(arestas) + omitidas,
            "kept_nodes": len(mantidos),
            "kept_edges": len(arestas),
            "omitted_edges": omitidas,
            "directed": bool(dimension_b) and not mesmo_lado,
            "limits": {
                "max_scan": CITACOES_GRAPH_MAX_SCAN,
                "max_nodes": CITACOES_GRAPH_MAX_NODES,
                "max_edges": CITACOES_GRAPH_MAX_EDGES,
            },
            "notes": notas,
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "filters": {
                "q": q,
                "tipo": tipo,
                "comarca": comarca_judicial,
                "tribunal": tribunal,
                "papel": papel,
                "nif": nif,
                "data_from": data_from,
                "data_to": data_to,
                "has_texto": has_texto,
            },
        },
    }
