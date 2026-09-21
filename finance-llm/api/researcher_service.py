"""Agente investigador de contratação pública — PublicContractsResearcher.

Arquitetura: Planner → Plano estruturado → Validator → Executor → Tools →
Evidence → Validator → LLM → Report.

O agente executa uma sequência controlada de pesquisas no Elasticsearch,
utilizando os resultados anteriores para decidir o passo seguinte. Cada
afirmação é ligada a evidências; cálculos são validados por Python.
"""
from __future__ import annotations

import asyncio
import json
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Sequence

from api import search360_service as search360
from api.elasticsearch_client import (
    get_contract_analytics,
    search_companies,
    search_contracts,
)
from api.vector_service import vector_search as _vector_search_entities, ENTITIES_INDEX as _ENTITIES_INDEX

# ---------------------------------------------------------------------------
# Configuração e limites
# ---------------------------------------------------------------------------
MAX_ITERATIONS = 10
MAX_TOOL_CALLS = 30
MAX_DOCUMENTS = 100
MAX_EVIDENCE = 20
DEFAULT_TIMEOUT = 30.0

# ---------------------------------------------------------------------------
# Modelo de dados
# ---------------------------------------------------------------------------
@dataclass
class Evidence:
    source_id: str
    source_type: str
    fact: str
    confidence: float = 1.0
    payload: Dict[str, Any] = field(default_factory=dict)


@dataclass
class Claim:
    text: str
    claim_type: str  # FACT, CALCULATION, INFERENCE, HYPOTHESIS
    evidence: List[Evidence] = field(default_factory=list)
    validated: bool = False


@dataclass
class ResearchStep:
    iteration: int
    tool: str
    arguments: Dict[str, Any]
    result_summary: str
    elapsed_ms: int
    evidence_added: int


@dataclass
class InvestigationState:
    question: str
    plan: List[Dict[str, Any]] = field(default_factory=list)
    facts: List[str] = field(default_factory=list)
    entities: List[Dict[str, Any]] = field(default_factory=list)
    contracts: List[Dict[str, Any]] = field(default_factory=list)
    relationships: List[Dict[str, Any]] = field(default_factory=list)
    evidence: List[Evidence] = field(default_factory=list)
    steps: List[ResearchStep] = field(default_factory=list)
    claims: List[Claim] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    started_at: float = field(default_factory=time.perf_counter)
    tool_calls: int = 0
    finished: bool = False


# ---------------------------------------------------------------------------
# Ferramentas permitidas
# ---------------------------------------------------------------------------
def _tool_resolve_entity_by_vector(q: str, top_k: int = 5) -> Dict[str, Any]:
    """Resolve entidade pelo nome/ticker usando vector search do índice finance_entities."""
    try:
        res = _vector_search_entities(
            index=_ENTITIES_INDEX,
            query=q,
            top_k=top_k,
            filters=None,
            min_score=0.5,
        )
        items = res.get("items", [])
        if not items:
            return {"items": []}
        out = []
        for it in items:
            if not it.get("nif"):
                continue
            out.append({
                "nif": it["nif"],
                "nome": it.get("name", it.get("nome", q)),
                "contracts_total": it.get("contracts_count", it.get("as_adjudicatario_count", 0)),
                "total_value": it.get("total_value", 0.0),
                "adjudicante": None,
                "adjudicatario": {
                    "contracts_count": it.get("as_adjudicatario_count", 0),
                    "total_value": it.get("as_adjudicatario_value", 0.0),
                } if it.get("as_adjudicatario_count") else None,
            })
        return {"items": out}
    except Exception as e:
        return {"error": str(e), "items": []}


def _tool_search_contracts(
    query: str = "",
    year_from: Optional[int] = None,
    year_to: Optional[int] = None,
    district: Optional[str] = None,
    company_nif: Optional[str] = None,
    entity_nif: Optional[str] = None,
    cpv_code: Optional[str] = None,
    size: int = 20,
) -> Dict[str, Any]:
    """Pesquisa contratos públicos por texto, datas, localização, NIFs ou CPV."""
    return search_contracts(
        q=query or None,
        year=year_from if year_from == year_to else None,
        nif=company_nif,
        counterparty_nif=entity_nif,
        region=district,
        cpv_code=cpv_code,
        start_date=f"{year_from}-01-01" if year_from else None,
        end_date=f"{year_to}-12-31" if year_to else None,
        size=min(size, 50),
    )


def _tool_get_company(nif: str) -> Dict[str, Any]:
    """Devolve a ficha de uma empresa pelo NIF."""
    return search_companies(q=nif, size=5)


def _tool_aggregate_contracts(
    query: str = "",
    group_field: str = "adjudicatarios.parsed.nif",
    year_from: Optional[int] = None,
    year_to: Optional[int] = None,
    cpv_code: Optional[str] = None,
) -> Dict[str, Any]:
    """Agrega contratos por campo (por defeito NIF adjudicatário)."""
    return get_contract_analytics(
        q=query or None,
        start_date=f"{year_from}-01-01" if year_from else None,
        end_date=f"{year_to}-12-31" if year_to else None,
        cpv_code=cpv_code,
    )


def _tool_find_relationships(company_nif: str) -> Dict[str, Any]:
    """Descobre entidades adjudicantes relacionadas a uma empresa."""
    contracts = search_contracts(nif=company_nif, size=100)
    relations: Dict[str, Dict[str, Any]] = {}
    for doc in contracts.get("items", []):
        for party in doc.get("adjudicantes", {}).get("parsed", []) or []:
            nif = party.get("nif")
            if not nif:
                continue
            entry = relations.setdefault(nif, {"entity": party.get("nome"), "nif": nif, "contracts": 0, "value": 0.0})
            entry["contracts"] += 1
            entry["value"] += float(doc.get("precoContratual") or 0)
    return {"company_nif": company_nif, "entities": list(relations.values())}


def _tool_search_companies(q: str = "", size: int = 10) -> Dict[str, Any]:
    """Pesquisa entidades/empresas por nome/ticker e devolve NIFs."""
    return search_companies(q=q, size=size)


TOOLS: Dict[str, Callable[..., Any]] = {
    "search_contracts": _tool_search_contracts,
    "get_company": _tool_get_company,
    "search_companies": _tool_search_companies,
    "resolve_entity_by_vector": _tool_resolve_entity_by_vector,
    "aggregate_contracts": _tool_aggregate_contracts,
    "find_relationships": _tool_find_relationships,
}

TOOL_SCHEMA: Dict[str, Dict[str, Any]] = {
    "search_contracts": {
        "required": [],
        "properties": {
            "query": {"type": "string"},
            "year_from": {"type": "integer"},
            "year_to": {"type": "integer"},
            "district": {"type": "string"},
            "company_nif": {"type": "string"},
            "entity_nif": {"type": "string"},
            "cpv_code": {"type": "string"},
            "size": {"type": "integer"},
        },
    },
    "get_company": {"required": ["nif"], "properties": {"nif": {"type": "string"}}},
    "search_companies": {"required": ["q"], "properties": {"q": {"type": "string"}, "size": {"type": "integer"}}},
    "resolve_entity_by_vector": {"required": ["q"], "properties": {"q": {"type": "string"}, "top_k": {"type": "integer"}}},
    "aggregate_contracts": {
        "required": ["group_field"],
        "properties": {
            "query": {"type": "string"},
            "group_field": {"type": "string"},
            "year_from": {"type": "integer"},
            "year_to": {"type": "integer"},
            "cpv_code": {"type": "string"},
        },
    },
    "find_relationships": {"required": ["company_nif"], "properties": {"company_nif": {"type": "string"}}},
}


# ---------------------------------------------------------------------------
# Validator / executor
# ---------------------------------------------------------------------------
def _validate_tool_call(call: Dict[str, Any]) -> Dict[str, Any]:
    """Valida nome da ferramenta e argumentos. Rejeita tudo o resto."""
    tool = call.get("tool")
    if tool not in TOOLS:
        return {"error": f"Ferramenta não permitida: {tool}"}
    schema = TOOL_SCHEMA[tool]
    args = call.get("arguments", {})
    for req in schema.get("required", []):
        if req not in args:
            return {"error": f"Argumento obrigatório em falta: {req}"}
    return {"tool": tool, "arguments": args}


async def _execute_tool(call: Dict[str, Any]) -> Dict[str, Any]:
    """Executa uma ferramenta validada."""
    validated = _validate_tool_call(call)
    if "error" in validated:
        return validated
    tool_name = validated["tool"]
    args = validated["arguments"]
    fn = TOOLS[tool_name]
    try:
        if asyncio.iscoroutinefunction(fn):
            return await asyncio.wait_for(fn(**args), timeout=DEFAULT_TIMEOUT)
        return await asyncio.to_thread(fn, **args)
    except asyncio.TimeoutError:
        return {"error": f"Timeout ao executar {tool_name}"}
    except Exception as e:
        return {"error": f"{tool_name}: {e}"}


# ---------------------------------------------------------------------------
# Planeamento
# ---------------------------------------------------------------------------
RESEARCHER_SYSTEM = (
    "És um agente investigador especializado em contratação pública portuguesa. "
    "Tens acesso a ferramentas que consultam dados indexados do Portal BASE no Elasticsearch.\n\n"
    "Regras:\n"
    "1. Nunca inventes contratos, empresas, valores ou NIFs.\n"
    "2. Utiliza as ferramentas para obter factos.\n"
    "3. Não trates uma hipótese como facto.\n"
    "4. Mantém as fontes de cada afirmação.\n"
    "5. Se os dados forem insuficientes, indica-o.\n"
    "6. Não faças inferências não suportadas.\n\n"
    "Ferramentas disponíveis:\n"
    "- search_contracts(query, year_from, year_to, district, company_nif, entity_nif, cpv_code, size)\n"
    "- get_company(nif)\n"
    "- aggregate_contracts(query, group_field, year_from, year_to, cpv_code)\n"
    "- find_relationships(company_nif)\n\n"
    "Devolve APENAS um plano JSON com a chave 'steps', onde cada passo tem 'tool' e 'arguments'. "
    "Quando tiveres informação suficiente para responder, devolve 'tool': 'finish'."
)


async def _planner(state: InvestigationState, *, backend: Optional[str] = None, session: Any = None) -> Dict[str, Any]:
    """Gera o próximo passo/plano a partir do estado atual."""
    from api import ontology_ai as ai  # noqa: PLC0415

    chosen = ai.available_backend(session, backend)
    if chosen.get("kind") != "cloud":
        # Planner determinístico simples quando não há modelo cloud.
        return _deterministic_planner(state)

    history = "\n".join(
        f"Passo {s.iteration}: {s.tool} -> {s.result_summary}" for s in state.steps[-6:]
    )
    prompt = (
        f"Pergunta original: {state.question}\n\n"
        f"Histórico recente:\n{history}\n\n"
        "Decide o próximo passo. Se já tiveres informação suficiente, usa 'tool': 'finish'. "
        "Caso contrário, escolhe uma ferramenta e argumentos concretos."
    )
    try:
        text = await ai.ask_model(
            chosen,
            system=RESEARCHER_SYSTEM,
            prompt=prompt,
            max_tokens=400,
            temperature=0.2,
        )
        plan = ai.extract_json(text or "")
        if isinstance(plan, dict) and plan.get("steps"):
            return {"steps": plan["steps"]}
    except Exception:
        pass
    return _deterministic_planner(state)


def _extract_question_intents(question: str) -> Dict[str, Any]:
    """Extrai intenções de uma pergunta em português: anos, distrito, entidades, CPV."""
    import re

    text = question
    intents: Dict[str, Any] = {"year_from": None, "year_to": None, "district": None, "entities": [], "cpv": None}

    # Anos: "entre 2022 e 2024", "em 2023", "desde 2021", "de 2020 a 2025"
    year_patterns = [
        r"entre\s+(\d{4})\s+e\s+(\d{4})",
        r"de\s+(\d{4})\s+a(?:te)?\s+(\d{4})",
        r"desde\s+(\d{4})",
        r"em\s+(\d{4})",
        r"ano\s+(\d{4})",
    ]
    years_found: List[int] = []
    for pat in year_patterns:
        for m in re.finditer(pat, text, flags=re.IGNORECASE):
            for g in m.groups():
                if g:
                    years_found.append(int(g))
    if years_found:
        intents["year_from"] = min(years_found)
        intents["year_to"] = max(years_found)

    # Distritos / regiões
    district_keywords = {
        "Aveiro": ["aveiro"],
        "Beja": ["beja"],
        "Braga": ["braga"],
        "Bragança": ["bragança", "braganca"],
        "Castelo Branco": ["castelo branco"],
        "Coimbra": ["coimbra"],
        "Évora": ["évora", "evora"],
        "Faro": ["faro", "algarve"],
        "Guarda": ["guarda"],
        "Leiria": ["leiria"],
        "Lisboa": ["lisboa", "lisbon"],
        "Portalegre": ["portalegre"],
        "Porto": ["porto"],
        "Santarém": ["santarém", "santarem"],
        "Setúbal": ["setúbal", "setubal"],
        "Viana do Castelo": ["viana do castelo"],
        "Vila Real": ["vila real"],
        "Viseu": ["viseu"],
        "Açores": ["açores", "acores"],
        "Madeira": ["madeira"],
    }
    lower = text.lower()
    for district, keywords in district_keywords.items():
        if any(kw in lower for kw in keywords):
            intents["district"] = district
            break

    # Entidades: tickers/nomes em maiúsculas (EDP, GALP, NOS, etc.) ou nomes próprios conhecidos.
    # Ignorar palavras funcionais comuns.
    stopwords = {
        "Investiga", "Contratos", "Empresa", "Empresas", "Entre", "Desde", "Ano", "Anos",
        "Portugal", "Público", "Pública", "Estado", "Portal", "Base", "NIF", "SA", "LDA",
        "SGPS", "Contratação", "Contrato", "Adjudicante", "Adjudicatária", "Adjudicatário",
        "Software", "Computadores", "Consultoria", "Construção", "Saúde", "Papel", "CPV",
    }
    # Ticker-like (2-6 letras maiúsculas), ou expressões com nome próprio.
    ticker_candidates = re.findall(r"\b[A-Z]{2,6}\b", text)
    proper_candidates = re.findall(r"\b[A-Z][a-záàâãéêíóôõúç]+(?:\s+(?:de|do|da|dos|das|e|&)?\s*[A-Z][a-záàâãéêíóôõúç]+)*\b", text)
    seen: set = set()
    for c in ticker_candidates + proper_candidates:
        c = c.strip()
        if not c or c in seen or c in stopwords or len(c) < 2:
            continue
        # Ignorar candidatos que coincidem com distrito (já tratado) e palavras comuns.
        if c.lower() in district_keywords:
            continue
        seen.add(c)
        intents["entities"].append(c)

    # CPV: código ou palavras-chave (simplificado: captura "CPV" + 8 dígitos ou "software", "consultoria", etc.)
    cpv_match = re.search(r"CPV\s*:?\s*(\d{8}-?\d?)", text, flags=re.IGNORECASE)
    if cpv_match:
        intents["cpv"] = cpv_match.group(1).replace("-", "")
    else:
        cpv_keywords = {
            "software": "722",
            "computadores": "302",
            "consultoria": "713",
            "construção": "450",
            "saúde": "336",
            "papel": "301",
        }
        for kw, prefix in cpv_keywords.items():
            if kw in lower:
                intents["cpv"] = prefix
                break

    return intents


def _normalize_district_label(district: Optional[str]) -> str:
    """Normaliza nome de distrito/região para comparação textual."""
    if not district:
        return ""
    mapping = {
        "área metropolitana do porto": "porto",
        "área metropolitana de lisboa": "lisboa",
        "região autónoma da madeira": "madeira",
        "região autónoma dos açores": "açores",
    }
    lower = district.lower().strip()
    return mapping.get(lower, lower)


def _district_nifs_from_state(state: InvestigationState, district: Optional[str]) -> set:
    """Devolve NIFs de entidades identificadas como pertencendo ao distrito mencionado."""
    if not district:
        return set()
    nifs: set = set()
    normalized = _normalize_district_label(district)
    for e in state.entities:
        nome = (e.get("nome") or "").lower()
        if normalized in nome or district.lower() in nome:
            nif = e.get("nif")
            if nif:
                nifs.add(nif)
    return nifs


def _deterministic_planner(state: InvestigationState) -> Dict[str, Any]:
    """Planner determinístico focado: resolve entidade → contratos → relacionamentos.

    Estratégia:
    1. Resolver a entidade principal (nome/ticker → NIF) via search_companies.
    2. Buscar contratos dessa entidade no período (sem CPV/district que over-constrangem).
    3. Descobrir entidades adjudicantes relacionadas (find_relationships).
    4. Buscar contratos da entidade filtrados por CPV, se houver CPV e houver
       contratos suficientes na busca aberta (fallback semântico).
    5. Buscar entidades do distrito mencionado para cruzar com relacionamentos.
    6. Agregar total de contratos no período para contexto de mercado.
    """
    plan = {"steps": []}
    intents = _extract_question_intents(state.question)
    year_from = intents.get("year_from")
    year_to = intents.get("year_to")
    district = intents.get("district")
    entities = intents.get("entities") or []
    cpv_code = intents.get("cpv")

    resolved_nifs: Dict[str, str] = {e.get("nif"): e.get("nome") for e in state.entities if e.get("nif")}
    unresolved_entities = [
        e for e in entities
        if e and not any(
            e.lower() in (name or "").lower() or e.lower() == (nif or "").lower()
            for nif, name in resolved_nifs.items()
        )
    ]

    # 1. Resolver entidade principal: vector search primeiro; depois fallback search_companies.
    vector_done = any(s.tool == "resolve_entity_by_vector" for s in state.steps)
    if unresolved_entities and not vector_done:
        plan["steps"].append({"tool": "resolve_entity_by_vector", "arguments": {"q": unresolved_entities[0], "top_k": 10}})
        # Também faz fallback textual se o vector ainda não tiver sido testado.
        plan["steps"].append({"tool": "search_companies", "arguments": {"q": unresolved_entities[0], "size": 10}})
    elif unresolved_entities and not any(s.tool == "search_companies" for s in state.steps):
        plan["steps"].append({"tool": "search_companies", "arguments": {"q": unresolved_entities[0], "size": 10}})

    # Se o vector resolver devolveu entidades confiáveis, usá-las como principal.
    vector_hits = [
        item for s in state.steps
        if s.tool == "resolve_entity_by_vector"
        for item in (s.result.get("items", []) if hasattr(s, "result") else [])
        if item.get("nif")
    ]
    best_vector = vector_hits[0] if vector_hits else None
    if best_vector and not resolved_nifs:
        state.entities.append({
            "nif": best_vector["nif"],
            "nome": best_vector["nome"],
            "role": "adjudicatario" if best_vector.get("adjudicatario") else "unknown",
            "contracts": best_vector.get("contracts_total"),
            "total_value": best_vector.get("total_value"),
        })
        resolved_nifs: Dict[str, str] = {best_vector["nif"]: best_vector["nome"]}

    nif_to_search = next(iter(resolved_nifs), None)

    # 2. Contratos da entidade no período (busca ampla para garantir volume).
    if nif_to_search and not any(
        s.tool == "search_contracts" and s.arguments.get("company_nif") == nif_to_search and not s.arguments.get("cpv_code")
        for s in state.steps
    ):
        args: Dict[str, Any] = {"company_nif": nif_to_search, "size": 100}
        if year_from:
            args["year_from"] = year_from
        if year_to:
            args["year_to"] = year_to
        plan["steps"].append({"tool": "search_contracts", "arguments": args})

    # 3. Relacionamentos da entidade principal.
    if nif_to_search and not any(
        s.tool == "find_relationships" and s.arguments.get("company_nif") == nif_to_search for s in state.steps
    ):
        plan["steps"].append({"tool": "find_relationships", "arguments": {"company_nif": nif_to_search}})

    # 4. Busca textual focada por CPV quando há CPV e entidade resolvida.
    if nif_to_search and cpv_code and not any(
        s.tool == "search_contracts" and s.arguments.get("company_nif") == nif_to_search and s.arguments.get("cpv_code") == cpv_code
        for s in state.steps
    ):
        args = {"company_nif": nif_to_search, "cpv_code": cpv_code, "size": 50}
        if year_from:
            args["year_from"] = year_from
        if year_to:
            args["year_to"] = year_to
        plan["steps"].append({"tool": "search_contracts", "arguments": args})

    # 5. Entidades do distrito para cruzar com relacionamentos.
    if district and not any(s.tool == "search_companies" and s.arguments.get("q") == district for s in state.steps):
        plan["steps"].append({"tool": "search_companies", "arguments": {"q": district, "size": 50}})

    # 6. Agregação geral apenas para contexto de mercado (sem CPV para evitar 0 resultados).
    if not any(s.tool == "aggregate_contracts" for s in state.steps):
        args: Dict[str, Any] = {"group_field": "adjudicatarios.parsed.nif"}
        if year_from:
            args["year_from"] = year_from
        if year_to:
            args["year_to"] = year_to
        plan["steps"].append({"tool": "aggregate_contracts", "arguments": args})

    if not plan["steps"]:
        plan["steps"].append({"tool": "finish"})
    return plan


# ---------------------------------------------------------------------------
# Atualização do estado
# ---------------------------------------------------------------------------
def _update_state(state: InvestigationState, step: ResearchStep, result: Dict[str, Any]) -> None:
    """Extrai entidades, contratos, relações e evidências do resultado."""
    if "error" in result:
        state.warnings.append(f"{step.tool}: {result['error']}")
        return

    if step.tool == "search_contracts":
        items = result.get("items", [])
        for doc in items[:MAX_DOCUMENTS]:
            contract_id = doc.get("idcontrato") or doc.get("doc_id") or "?"
            state.contracts.append(doc)
            state.evidence.append(
                Evidence(
                    source_id=str(contract_id),
                    source_type="contract",
                    fact=f"Contrato {contract_id}: {doc.get('objectoContrato','')} — {doc.get('precoContratual')} €",
                    payload=doc,
                )
            )
            # Adiciona entidades encontradas.
            for party_kind, role in (("adjudicatarios", "adjudicatario"), ("adjudicantes", "adjudicante")):
                for p in doc.get(party_kind, {}).get("parsed", []) or []:
                    entity = {
                        "nif": p.get("nif"),
                        "nome": p.get("nome"),
                        "role": role,
                        "source_contract": contract_id,
                    }
                    if entity["nif"] and not any(e.get("nif") == entity["nif"] and e.get("role") == role for e in state.entities):
                        state.entities.append(entity)

    elif step.tool in ("get_company", "search_companies", "resolve_entity_by_vector"):
        for item in result.get("items", []):
            nif = item.get("nif")
            nome = item.get("nome") or item.get("name")
            if nif and not any(e.get("nif") == nif for e in state.entities):
                # Determinar papel preferencial se houver resumo por papel.
                role = "unknown"
                if item.get("adjudicatario") and not item.get("adjudicante"):
                    role = "adjudicatario"
                elif item.get("adjudicante") and not item.get("adjudicatario"):
                    role = "adjudicante"
                state.entities.append({
                    "nif": nif,
                    "nome": nome,
                    "role": role,
                    "contracts": item.get("contracts") or item.get("contracts_total"),
                    "total_value": item.get("total_value"),
                })
                state.evidence.append(
                    Evidence(
                        source_id=nif,
                        source_type="entity",
                        fact=f"Entidade {nome} (NIF {nif}) — {item.get('contracts_total') or item.get('contracts') or 0} contratos",
                        payload=item,
                    )
                )

    elif step.tool == "find_relationships":
        intents = _extract_question_intents(state.question)
        district = intents.get("district")
        district_nifs = _district_nifs_from_state(state, district)
        for rel in result.get("entities", []):
            # Se a pergunta referir um distrito, destacar relações com entidades desse distrito.
            rel_nif = rel.get("nif")
            rel_entity = rel.get("entity") or ""
            is_district_match = bool(district) and (
                (rel_nif and rel_nif in district_nifs) or
                district.lower() in rel_entity.lower() or
                _normalize_district_label(district).lower() in rel_entity.lower()
            )
            rel["district_match"] = is_district_match
            state.relationships.append(rel)
            fact = f"{rel.get('entity')} adjudicou {rel.get('contracts')} contratos ({rel.get('value')} €)"
            if is_district_match:
                fact = f"[{district}] {fact}"
            state.evidence.append(
                Evidence(
                    source_id=f"rel-{rel_nif}",
                    source_type="relationship",
                    fact=fact,
                    payload=rel,
                )
            )

    elif step.tool == "aggregate_contracts":
        analytics = result
        total_contracts = analytics.get("total_contracts") if analytics.get("total_contracts") is not None else analytics.get("total")
        total_value = analytics.get("total_value")
        state.facts.append(f"Total de mercado no período: {total_contracts} contratos; valor {total_value} €")
        for row in (analytics.get("top_entities") or [])[:10]:
            state.evidence.append(
                Evidence(
                    source_id=row.get("key"),
                    source_type="aggregate_entity",
                    fact=f"{row.get('description') or row.get('key')}: {row.get('count')} contratos, {row.get('total_value')} €",
                    payload=row,
                )
            )


# ---------------------------------------------------------------------------
# Relatório
# ---------------------------------------------------------------------------
async def _generate_report(state: InvestigationState, *, backend: Optional[str] = None, session: Any = None) -> str:
    """Gera relatório estruturado a partir do estado."""
    from api import ontology_ai as ai  # noqa: PLC0415

    evidence_text = "\n".join(f"- {e.fact}" for e in state.evidence[:MAX_EVIDENCE])
    entities_text = "\n".join(f"- {e.get('nome')} (NIF {e.get('nif')}, {e.get('role')})" for e in state.entities[:20])
    relationships_text = "\n".join(
        f"- {r.get('entity')} ({r.get('nif')}): {r.get('contracts')} contratos, {r.get('value')} €"
        for r in state.relationships[:20]
    )

    system = (
        "És um analista de contratação pública. Escreve um relatório em português de Portugal "
        "baseado apenas nas evidências fornecidas. Marca claramente factos, cálculos, inferências e hipóteses. "
        "Indica limitações quando os dados forem insuficientes."
    )
    prompt = (
        f"Pergunta: {state.question}\n\n"
        f"Entidades identificadas:\n{entities_text}\n\n"
        f"Evidências:\n{evidence_text}\n\n"
        f"Relações contratuais:\n{relationships_text}\n\n"
        "Escreve um relatório com: Objetivo, Identificação, Atividade contratual, Entidades adjudicantes, "
        "Categorias, Evolução temporal, Relações identificadas, Evidências e Limitações."
    )

    chosen = ai.available_backend(session, backend)
    if chosen.get("kind") != "cloud":
        return _deterministic_report(state)

    try:
        return await ai.ask_model(chosen, system=system, prompt=prompt, max_tokens=1200, temperature=0.3)
    except Exception:
        return _deterministic_report(state)


def _infer_role(name: Optional[str], fallback: str = "unknown") -> str:
    """Infere o papel provável de uma entidade pelo nome."""
    if not name:
        return fallback
    lower = name.lower()
    # Entidades públicas/compradoras típicas.
    buyer_hints = [
        "município", "câmara municipal", "freguesia", "universidade", "hospital",
        "centro hospitalar", "ipo ", "metro do", "metro de", "infraestruturas de portugal",
        "nav portugal", "água", "águas", "resíduos", "saúde", "escola", "instituto",
        "polícia", "bombeiros", "forças armadas", "governo civil", "junto europeia",
        "comunidade intermunicipal", "área metropolitana", "associação de municípios",
    ]
    if any(h in lower for h in buyer_hints):
        return "adjudicante"
    # Terminações de empresas privadas adjudicatárias.
    seller_hints = [" lda", " sa", " sgps", "unipessoal", "consultoria", "software", "construção"]
    if any(h in lower for h in seller_hints):
        return "adjudicatario"
    return fallback


def _entity_name_for_nif(state: InvestigationState, nif: Optional[str]) -> str:
    for e in state.entities:
        if e.get("nif") == nif:
            return e.get("nome") or nif
    return nif or "Entidade"


def _deterministic_report(state: InvestigationState) -> str:
    """Relatório determinístico de fallback focado na entidade principal e nas suas evidências."""
    intents = _extract_question_intents(state.question)
    district = intents.get("district")
    cpv = intents.get("cpv")
    cpv_label = {"722": "software", "302": "computadores", "713": "consultoria", "450": "construção", "336": "saúde", "301": "papel"}.get(str(cpv) or "", cpv)
    year_from = intents.get("year_from")
    year_to = intents.get("year_to")

    # Corrigir papéis inferidos nas entidades antes de reportar.
    for e in state.entities:
        if e.get("role") in (None, "unknown"):
            e["role"] = _infer_role(e.get("nome"), e.get("role") or "unknown")

    # Identificar a entidade principal (primeira resolvida ou primeira adjudicatária).
    main_nif = None
    main_name = None
    for e in state.entities:
        if e.get("role") == "adjudicatario":
            main_nif = e.get("nif")
            main_name = e.get("nome")
            break
    if not main_nif:
        for e in state.entities:
            if e.get("nif"):
                main_nif = e.get("nif")
                main_name = e.get("nome")
                break

    # Separar contratos da entidade principal.
    main_contracts = []
    for doc in state.contracts:
        nifs = [p.get("nif") for p in doc.get("adjudicatarios", {}).get("parsed", []) or []]
        if main_nif in nifs:
            main_contracts.append(doc)
    total_main_contracts = len(main_contracts)
    total_main_value = sum(float(c.get("precoContratual") or 0) for c in main_contracts)

    # Contratos com CPV pedido.
    def _cpv_starts(doc, prefix):
        raw = doc.get("cpv")
        codes = []
        if isinstance(raw, str):
            codes.append(raw)
        elif isinstance(raw, list):
            codes.extend(str(x) for x in raw)
        elif isinstance(raw, dict):
            codes.append(str(raw.get("code", "")))
        return any(c.startswith(str(prefix)) for c in codes)

    cpv_contracts = [c for c in main_contracts if cpv and _cpv_starts(c, cpv)]
    cpv_value = sum(float(c.get("precoContratual") or 0) for c in cpv_contracts)

    # Top contratos relevantes: preferir CPV, senão gerais da entidade.
    if cpv_contracts:
        top_contracts = sorted(cpv_contracts, key=lambda x: float(x.get("precoContratual") or 0), reverse=True)[:10]
    else:
        top_contracts = sorted(main_contracts, key=lambda x: float(x.get("precoContratual") or 0), reverse=True)[:10]

    # Entidades relacionadas, separadas por ligação ao distrito e por volume.
    district_rels = [r for r in state.relationships if r.get("district_match")][:20]
    other_rels = sorted(
        [r for r in state.relationships if not r.get("district_match")],
        key=lambda x: float(x.get("value") or 0),
        reverse=True,
    )[:20]

    # Título com foco da pergunta.
    title = state.question.strip().rstrip("?").replace("Investiga ", "").replace("Investiga a relação entre ", "")
    if len(title) > 120:
        title = title[:117] + "..."

    lines = [
        f"# {title}",
        "",
        "## 1. Objetivo",
        state.question,
        "",
        "## 2. Entidades identificadas",
    ]

    main_entities = [e for e in state.entities if e.get("nif") == main_nif][:1]
    district_entities = [e for e in state.entities if district and district.lower() in (e.get("nome") or "").lower() and e.get("nif") != main_nif][:10]
    other_entities = [e for e in state.entities if e.get("nif") not in {main_nif} | {x.get("nif") for x in district_entities}][:15]

    if main_entities:
        lines.append("**Entidade principal:**")
        for e in main_entities:
            lines.append(f"- {e.get('nome')} (NIF {e.get('nif')}, {e.get('role')})")
    if district_entities:
        lines.append("")
        lines.append(f"**Entidades ligadas a {district}:**")
        for e in district_entities:
            lines.append(f"- {e.get('nome')} (NIF {e.get('nif')}, {e.get('role')})")
    if other_entities:
        lines.append("")
        lines.append("**Outras entidades mencionadas nos contratos:**")
        for e in other_entities:
            lines.append(f"- {e.get('nome')} (NIF {e.get('nif')}, {e.get('role')})")
    if not state.entities:
        lines.append("- Não foram identificadas entidades nos dados recolhidos.")

    lines.extend(["", "## 3. Atividade contratual"])
    lines.append(f"- Entidade principal: {main_name or 'N/A'} (NIF {main_nif or 'N/A'})")
    period_str = f" entre {year_from} e {year_to}" if year_from and year_to else (f" em {year_from}" if year_from else "")
    lines.append(f"- Contratos da entidade principal{period_str}: {total_main_contracts}")
    lines.append(f"- Valor total{period_str}: {total_main_value:,.2f} €")
    if cpv:
        if cpv_contracts:
            lines.append(f"- Contratos com CPV {cpv} ({cpv_label}){period_str}: {len(cpv_contracts)} ({cpv_value:,.2f} €)")
        else:
            lines.append(f"- **Não foram encontrados contratos com CPV {cpv} ({cpv_label}) atribuídos a {main_name or 'a entidade principal'}{period_str}.**")
    for f in state.facts:
        lines.append(f"- {f}")

    lines.extend(["", "## 4. Contratos mais relevantes"])
    if cpv and not cpv_contracts:
        lines.append(f"Não existem contratos da {main_name or 'entidade principal'} classificados com CPV {cpv} ({cpv_label}) no período. Abaixo apresentam-se os contratos gerais da entidade para contexto:")
        lines.append("")
    if top_contracts:
        for c in top_contracts:
            c_id = c.get("idcontrato") or c.get("doc_id") or "?"
            obj = (c.get("objectoContrato") or "")[:120]
            entity_names = ", ".join(p.get("nome") or p.get("nif") or "" for p in c.get("adjudicantes", {}).get("parsed", []) or [] if p.get("nome") or p.get("nif")) or "N/A"
            lines.append(f"- **{c_id}** — {obj} — {float(c.get('precoContratual') or 0):,.2f} € (adjudicante: {entity_names})")
    else:
        lines.append("- Não foram recolhidos contratos específicos para a entidade principal.")

    lines.extend(["", "## 5. Relações contratuais com entidades adjudicantes"])
    if district:
        lines.append(f"**Adjudicantes ligadas a {district}:**")
        if district_rels:
            for r in district_rels:
                lines.append(f"- {r.get('entity')} (NIF {r.get('nif')}): {r.get('contracts')} contrato(s), {float(r.get('value') or 0):,.2f} €")
        else:
            lines.append(f"- Não foram encontradas relações diretas com entidades de {district}.")
        lines.append("")
    if other_rels:
        lines.append("**Principais adjudicantes a nível nacional (por volume contratado):**")
        for r in other_rels:
            lines.append(f"- {r.get('entity')} (NIF {r.get('nif')}): {r.get('contracts')} contrato(s), {float(r.get('value') or 0):,.2f} €")
    elif not district_rels:
        lines.append("- Não foram identificadas relações contratuais.")

    if state.evidence:
        lines.extend(["", "## 6. Evidências resumidas"])
        lines.append(f"Foram recolhidas {len(state.evidence)} evidências ({len(state.contracts)} contratos, {len(state.entities)} entidades, {len(state.relationships)} relações).")
        # Mostrar apenas factos-chave para evitar repetição.
        key_facts = []
        if main_nif and total_main_contracts:
            key_facts.append(f"Total contratos {main_name or main_nif}: {total_main_contracts}")
        if cpv:
            key_facts.append(f"CPV {cpv}: {len(cpv_contracts)} contrato(s)")
        if district_rels:
            key_facts.append(f"Relações em {district}: {len(district_rels)}")
        for f in key_facts:
            lines.append(f"- {f}")

    lines.extend(["", "## 7. Limitações"])
    lines.append("- A análise baseia-se apenas nos dados indexados no Elasticsearch.")
    if cpv and not cpv_contracts:
        lines.append(f"- A pergunta menciona {cpv_label} (CPV {cpv}), mas não foram encontrados contratos da {main_name or 'entidade principal'} com essa classificação no período/distrito indicados.")
    if cpv:
        lines.append(f"- CPV {cpv} é uma busca por prefixo; contratos com classificação semântica semelhante mas código diferente não são incluídos.")
    if district:
        lines.append(f"- O distrito {district} foi inferido a partir dos nomes das entidades e não da localização de execução (NUTs/localExecucao) dos contratos.")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Investigação principal
# ---------------------------------------------------------------------------
async def investigate(
    question: str,
    *,
    backend: Optional[str] = None,
    session: Any = None,
    max_iterations: int = MAX_ITERATIONS,
) -> Dict[str, Any]:
    """Executa a investigação e devolve o relatório com auditoria completa."""
    state = InvestigationState(question=question)

    # Planeamento inicial.
    initial_plan = await _planner(state, backend=backend, session=session)
    state.plan = initial_plan.get("steps", [])

    for iteration in range(1, max_iterations + 1):
        if state.finished or state.tool_calls >= MAX_TOOL_CALLS:
            break

        # Escolhe o próximo passo do plano ou replaneia.
        if not state.plan:
            plan = await _planner(state, backend=backend, session=session)
            state.plan = plan.get("steps", [])

        if not state.plan:
            break

        next_call = state.plan.pop(0)
        if next_call.get("tool") == "finish":
            state.finished = True
            break

        state.tool_calls += 1
        started = time.perf_counter()
        result = await _execute_tool(next_call)
        elapsed_ms = int((time.perf_counter() - started) * 1000)

        summary = result.get("total") if isinstance(result.get("total"), int) else len(result.get("items", [])) if "items" in result else len(result.get("entities", [])) if "entities" in result else 0
        if "error" in result:
            summary = f"erro: {result['error']}"

        step = ResearchStep(
            iteration=iteration,
            tool=next_call["tool"],
            arguments=next_call.get("arguments", {}),
            result_summary=str(summary),
            elapsed_ms=elapsed_ms,
            evidence_added=0,
        )
        _update_state(state, step, result)
        step.evidence_added = len(state.evidence)
        state.steps.append(step)

    report = await _generate_report(state, backend=backend, session=session)

    return {
        "status": "completed",
        "iterations": len(state.steps),
        "tool_calls": state.tool_calls,
        "elapsed_seconds": round(time.perf_counter() - state.started_at, 2),
        "report": report,
        "entities": state.entities[:50],
        "relationships": state.relationships[:50],
        "contracts": state.contracts[:50],
        "evidence": [
            {"source_id": e.source_id, "source_type": e.source_type, "fact": e.fact, "confidence": e.confidence}
            for e in state.evidence[:MAX_EVIDENCE]
        ],
        "steps": [
            {
                "iteration": s.iteration,
                "tool": s.tool,
                "arguments": s.arguments,
                "result_summary": s.result_summary,
                "elapsed_ms": s.elapsed_ms,
                "evidence_added": s.evidence_added,
            }
            for s in state.steps
        ],
        "warnings": state.warnings,
        "plan": initial_plan.get("steps", []),
    }
