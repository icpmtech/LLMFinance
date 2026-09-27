"""Teste dos diagramas Mermaid do World Model (identificadores e rótulos seguros).

O Mermaid falhava os diagramas por duas razões independentes:

1. **identificadores** com espaços/acentos («Administrador da insolvência»,
   `dynamic-network`) → corrigido com `mermaid_id`/`MermaidIds`;
2. **rótulos de aresta** com parênteses (`alvos (anomalias)`), que o parser lê
   como início da forma de um nó → corrigido com `mermaid_edge_label`, que
   devolve o texto **entre aspas** (com `#`, `|` e `"` passados a entidades).

Este teste não usa Elasticsearch: `index_status` engole os erros do cliente, pelo
que basta um cliente falso que levanta em todas as chamadas. O `meta.json` fica
num diretório temporário para não mexer no mundo do utilizador.
"""
from __future__ import annotations

import re
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from api import world_agent as agent  # noqa: E402
from api import world_model as model  # noqa: E402

# O `pipeline_graph` lê `meta.json`; escrever no do utilizador seria incorreto.
model.META_PATH = Path(tempfile.mkdtemp(prefix="iqos_world_mermaid_")) / "meta.json"

ok = 0


def check(label: str, condition: bool, detail: object = "") -> None:
    global ok
    if condition:
        ok += 1
        print(f"  OK  {label}")
    else:
        print(f" FAIL {label} :: {detail}")
        raise SystemExit(1)


# ---------------------------------------------------------------------------
# Validador genérico: o que o parser Mermaid não aceita
# ---------------------------------------------------------------------------
#: Identificador válido para um nó: sem acentos, espaços, hífen ou parênteses
#: (dígitos no início são aceites pelo Mermaid — há entidades com id `62212`).
ID_RE = re.compile(r"^[A-Za-z0-9_]+$")
#: Tokens que o parser interpreta dentro de `|…|` sem aspas.
UNSAFE_IN_PIPE = "()[]{}"


def _edge(line: str) -> tuple[str, str, str] | None:
    """Parte uma aresta em `(origem, rótulo, destino)`; `None` se não for aresta.

    Aceita as duas formas usadas nos geradores: `a -->|"x"| b` e
    `a["A"] -->|"x"| b["B"]` (nó definido inline).
    """
    if "-->|" not in line:
        return None
    head, rest = line.split("-->|", 1)
    if "|" not in rest:
        return None
    label, tail = rest.split("|", 1)
    source = head.strip().split("[")[0].strip()
    target = tail.strip().split("[")[0].strip()
    if not source or not target:
        return None
    return source, label, target


class _NoClient:
    """Cliente ES falso: contagens fixas, pesquisas a falhar (o `index_status` trata)."""

    def count(self, **kwargs: object) -> object:
        return {"count": 5}

    def search(self, **kwargs: object) -> object:
        raise RuntimeError("sem Elasticsearch no teste")


def validate(label: str, text: str, *, expect_nodes: int = 1, expect_edges: int = 1) -> None:
    """Confirma que um diagrama gerado seria aceite pelo parser do Mermaid."""
    lines = [line for line in str(text or "").splitlines() if line.strip()]
    check(f"{label}: tem cabeçalho", bool(lines) and lines[0].strip().startswith(("flowchart", "graph")), lines[:1])
    ids: list[str] = []
    labels: list[str] = []
    checked = 0
    for line in lines[1:]:
        parsed = _edge(line)
        if parsed is None:
            continue
        source, edge_label, target = parsed
        checked += 1
        ids.extend([source, target])
        labels.append(edge_label)
    check(f"{label}: arestas reconhecidas", checked >= expect_edges, text)
    for node_id in ids:
        check(f"{label}: id válido «{node_id}»", bool(ID_RE.match(node_id)), node_id)
    for edge_label in labels:
        # Entre aspas o texto é opaco (parênteses incluídos); sem aspas, qualquer
        # `(`/`[`/`{` faz o parser procurar a forma de um nó e falhar o diagrama.
        quoted = edge_label.startswith('"') and edge_label.endswith('"')
        check(f"{label}: rótulo protegido «{edge_label}»", quoted or not any(char in edge_label for char in UNSAFE_IN_PIPE), edge_label)
    check(f"{label}: nós suficientes", len(set(ids)) >= expect_nodes, sorted(set(ids)))


print("1. mermaid_id")
check("espaços e acentos", model.mermaid_id("Administrador da insolvência") == "Administrador_da_insolvencia", model.mermaid_id("Administrador da insolvência"))
check("hífen", model.mermaid_id("dynamic-network") == "dynamic_network", model.mermaid_id("dynamic-network"))
check("dois pontos", model.mermaid_id("subject:501234567") == "subject_501234567", model.mermaid_id("subject:501234567"))
check("cardinal #", model.mermaid_id("contratos#123") == "contratos_123", model.mermaid_id("contratos#123"))
check("parênteses", model.mermaid_id("alvos (anomalias)") == "alvos_anomalias", model.mermaid_id("alvos (anomalias)"))
check("dígitos no início aceites", model.mermaid_id("62212") == "62212", model.mermaid_id("62212"))
check("vazio → n", model.mermaid_id("") == "n" and model.mermaid_id(None) == "n", model.mermaid_id(""))
check("só pontuação → n", model.mermaid_id("---") == "n", model.mermaid_id("---"))

print("2. mermaid_label")
check("aspas passam a '", model.mermaid_label('Cargo "especial"') == "Cargo 'especial'", model.mermaid_label('Cargo "especial"'))
check("quebras de linha colapsam", model.mermaid_label("uma\nduas\rtrês") == "uma duas três", model.mermaid_label("uma\nduas"))
check("br preservado", model.mermaid_label("A<br/>B") == "A<br/>B", model.mermaid_label("A<br/>B"))
check("& solto escapado", model.mermaid_label("A & B") == "A &amp; B", model.mermaid_label("A & B"))
check("entidade preservada", model.mermaid_label("A &amp; B") == "A &amp; B", model.mermaid_label("A &amp; B"))
check("limite", len(model.mermaid_label("x" * 400, limit=20)) == 20, model.mermaid_label("x" * 400, limit=20))
check("vazio → travessão", model.mermaid_label("   ") == "—", model.mermaid_label("   "))

print("3. mermaid_edge_label")
check("sempre entre aspas", model.mermaid_edge_label("alvos (anomalias)") == '"alvos (anomalias)"', model.mermaid_edge_label("alvos (anomalias)"))
check("parênteses ficam dentro das aspas", "(" in model.mermaid_edge_label("a (b)"), model.mermaid_edge_label("a (b)"))
check("cardinal escapado", model.mermaid_edge_label("contratos#123") == '"contratos#35;123"', model.mermaid_edge_label("contratos#123"))
check("pipe escapado", model.mermaid_edge_label("a | b") == '"a #124; b"', model.mermaid_edge_label("a | b"))
check("limite respeitado", model.mermaid_edge_label("y" * 100, limit=12).startswith('"yyy'), model.mermaid_edge_label("y" * 100, limit=12))

print("4. MermaidIds")
ids = model.MermaidIds()
check("id estável para a mesma origem", ids("a b") == ids("a b"), ids("a b"))
check("colisões resolvidas", len({ids("a b"), ids("a-b"), ids("a.b")}) == 3, [ids("a b"), ids("a-b"), ids("a.b")])
check("contagem", len(ids) == 3, len(ids))
check("id novo continua válido", bool(ID_RE.match(ids("Outro Nome (x)"))), ids("Outro Nome (x)"))

print("5. Catálogo de agentes")
catalog = agent._catalog_mermaid()
validate("catálogo", catalog, expect_nodes=len(agent.AGENTS))
check("catálogo cobre todos os agentes", all(model.mermaid_label(item["label"]) in catalog for item in agent.AGENTS), catalog[:200])

print("6. Grafo de execução (passos com texto sujo)")
trace = agent._ExecutionTrace()
first = trace.add("network", "previsão, memória e anomalias", outputs={"entidades": 3, "nota": 'valor "x" & y'}, flow_label="estado do sujeito")
second = trace.add("scout", "recolher (evidência) de #1", outputs={"contratos#1": 2}, parent=first, flow_label="alvos (anomalias)")
trace.add("narrator", "escrever o relatório", parent=second, flow_label="afirmações + fontes")
execution = trace.mermaid()
validate("execução", execution, expect_nodes=3)
check("fluxo com parênteses protegido", '|"alvos (anomalias)"|' in execution, execution)
check("nós do percurso presentes", execution.count(":::passo") == 3, execution)

print("7. Grafo de evidências")
evidence_graph = agent.build_evidence_graph(
    claims=[
        {"claim": "O valor subiu (12 %)", "kind": "variação", "confidence": "média", "sources": ["ev1"]},
        {"claim": 'Contrato "especial" & atípico', "kind": "risco", "confidence": "baixa", "sources": ["contratos#42"]},
    ],
    evidence=[
        {"id": "ev1", "description": "Amostra (n=30) com #2 outliers", "source_index": "contratos", "source_id": "42", "value": 1234.5},
    ],
    subject={"entity_id": "501234567", "name": "Empresa (Teste), S.A.", "contracts_count": 12, "contracts_value": 999.0},
)
validate("evidências", evidence_graph["mermaid"], expect_nodes=4)
check("sujeito sem parênteses no id", "subject_501234567" in evidence_graph["mermaid"], evidence_graph["mermaid"])

print("8. Ego-rede de relações (o caso que falhou em produção)")
relations = agent.relations_mermaid(
    {
        "nodes": [
            {"id": "62212", "name": "Administrador da insolvência"},
            {"id": "entidade:501234567", "name": 'Empresa "Alfa" & Filhos, Lda.'},
        ],
        "edges": [
            {"source": "62212", "target": "entidade:501234567", "contracts_count": 3, "value_sum": 1250000.0},
        ],
    },
    limit=5,
)
validate("relações", relations, expect_nodes=2)
check("nome com acentos no rótulo", "Administrador da insolvência" in relations, relations)
check("nome de nó entre aspas", '"Administrador da insolvência"' in relations, relations)
check("contagem e valor no rótulo", "3 ctr" in relations and "€" in relations, relations)
empty = agent.relations_mermaid({"nodes": [], "edges": []})
validate("relações vazias", empty, expect_nodes=0, expect_edges=0)
check("caso vazio tem aviso", 'vazio["Sem relações na amostra atual"]' in empty, empty)

print("9. Pipeline em execução")
pipeline = model.pipeline_graph(es=_NoClient())
validate("pipeline", pipeline["mermaid"], expect_nodes=len(model.PIPELINE_STAGES))
check(
    "aresta «alvos (anomalias)» protegida",
    'dynamic_network -->|"alvos (anomalias)"| investigation_agent' in pipeline["mermaid"],
    pipeline["mermaid"],
)
check("contagens nos nós", "docs" in pipeline["mermaid"], pipeline["mermaid"])
check("métricas mantidas", pipeline["metrics"]["layers"] == len(model.PIPELINE_STAGES), pipeline["metrics"])

print(f"\n{ok} verificações OK")
