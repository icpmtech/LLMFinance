"""Motor de agentes dinâmicos LangGraph para o IQ OS.

Este módulo permite executar grafos de agentes configuráveis (tools, prompts,
RAG e supervisor) usando LangGraph. As configurações são carregadas do índice
`iq_os_agent_configs` do Elasticsearch e o LLM é resolvido através do catálogo
de fornecedores existente (`api.providers_service`).

Padrões implementados:
- ReAct simples quando `graph` está vazio.
- Nós `prompt`/`tool`/`rag` com transições sequenciais.
- Supervisor opcional para delegar em subagentes.
- Integração com o motor RAG existente para retrieval.
"""
from __future__ import annotations

import json
import logging
import time
import uuid
from typing import Any, Callable, Dict, List, Optional, Sequence

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage, ToolMessage
from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder
from langchain_core.runnables import RunnableConfig
from langchain_core.tools import StructuredTool, Tool
from langgraph.graph import END, StateGraph

from api import ontology_ai
from api.cloud_chat import complete_answer
from api.elasticsearch_client import AGENT_CONFIGS_INDEX, ensure_indices, get_es_client
from api.models import AgentConfig, AgentRunRequest, AgentRunResponse, AgentRunStep, RagSource
from api.rag_service import get_rag_engine
from api.tools import (
    get_actions,
    get_calendar,
    get_financials,
    get_holders,
    get_news,
    get_options,
    get_recommendations,
    get_stock_history,
    get_stock_info,
    get_sustainability,
    get_technical_indicators,
    yahoo_search,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Catálogo interno de ferramentas disponíveis para agentes dinâmicos.
# Cada tool devolve um dict/string JSON-safe. O motor converte automaticamente.
# ---------------------------------------------------------------------------

def _json_safe(value: Any) -> Any:
    """Converte pandas/numpy em JSON serializável de forma superficial."""
    try:
        import pandas as pd
    except ImportError:
        pd = None  # type: ignore
    if pd is not None and isinstance(value, pd.DataFrame):
        return json.loads(value.to_json(orient="records", date_format="iso"))
    if pd is not None and isinstance(value, pd.Series):
        return value.tolist()
    if isinstance(value, dict):
        return {k: _json_safe(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_json_safe(v) for v in value]
    return value


def _tool(name: str, fn: Callable[..., Any], description: str) -> Tool:
    return Tool(name=name, func=lambda **kwargs: json.dumps(_json_safe(fn(**kwargs)), ensure_ascii=False, default=str), description=description)


AVAILABLE_TOOLS: Dict[str, Tool] = {
    "stock_info": _tool(
        "stock_info",
        get_stock_info,
        "Devolve informações de uma ação (nome, preço, P/E, sector, etc.). Argumento: symbol (str).",
    ),
    "stock_history": _tool(
        "stock_history",
        lambda symbol, period="1y", interval="1d": json.loads(get_stock_history(symbol, period, interval).to_json(orient="records", date_format="iso")),
        "Devolve histórico de preços de uma ação. Argumentos: symbol (str), period (str, default 1y), interval (str, default 1d).",
    ),
    "financials": _tool("financials", get_financials, "Devolve demonstrações financeiras. Argumento: symbol (str)."),
    "news": _tool("news", get_news, "Devolve notícias recentes de uma ação. Argumento: symbol (str)."),
    "calendar": _tool("calendar", get_calendar, "Devolve calendário de earnings. Argumento: symbol (str)."),
    "holders": _tool("holders", get_holders, "Devolve detentores institucionais. Argumento: symbol (str)."),
    "options": _tool("options", get_options, "Devolve cadeias de opções. Argumento: symbol (str)."),
    "recommendations": _tool("recommendations", get_recommendations, "Devolve recomendações de analistas. Argumento: symbol (str)."),
    "actions": _tool("actions", get_actions, "Devolve dividendos e splits. Argumento: symbol (str)."),
    "sustainability": _tool("sustainability", get_sustainability, "Devolve classificação ESG. Argumento: symbol (str)."),
    "technical_indicators": _tool(
        "technical_indicators",
        get_technical_indicators,
        "Devolve indicadores técnicos (SMA, RSI, MACD, etc.). Argumentos: symbol (str), period (str, default 1y).",
    ),
    "yahoo_search": _tool(
        "yahoo_search",
        yahoo_search,
        "Pesquisa empresas/tickers no Yahoo Finance. Argumentos: query (str), max_results (int, default 8).",
    ),
}


def _rag_tool(question: str, index: Optional[str] = None, mode: Optional[str] = None, top_k: int = 5) -> str:
    """Ferramenta de RAG integrada com o motor existente."""
    engine = get_rag_engine()
    from api.rag_routes import _parse_mode

    flags = _parse_mode(mode or "hybrid")
    try:
        result = engine.answer(
            question,
            top_k=top_k,
            max_new_tokens=512,
            temperature=0.1,
            return_sources=True,
            use_hybrid=flags["use_hybrid"],
            use_rerank=flags["use_rerank"],
            use_crag=flags["use_crag"],
        )
        return json.dumps({"answer": result.get("answer"), "sources_count": len(result.get("sources") or [])}, ensure_ascii=False)
    except Exception as exc:
        return json.dumps({"error": f"RAG falhou: {exc}"}, ensure_ascii=False)


AVAILABLE_TOOLS["rag"] = Tool(
    name="rag",
    func=lambda **kwargs: _rag_tool(**kwargs),
    description="Responde com base em documentos carregados no RAG. Argumentos: question (str), index (str, opcional), mode (str, opcional), top_k (int, default 5).",
)


# ---------------------------------------------------------------------------
# Estado do grafo
# ---------------------------------------------------------------------------

class AgentState(Dict[str, Any]):
    """Estado simples do grafo: mensagens + variáveis de contexto."""

    messages: List[BaseMessage]
    context: Dict[str, Any]
    steps: List[AgentRunStep]
    sources: List[RagSource]
    error: Optional[str]


def _make_state(messages: List[BaseMessage], context: Dict[str, Any]) -> AgentState:
    return AgentState(
        messages=messages,
        context=context or {},
        steps=[],
        sources=[],
        error=None,
    )


# ---------------------------------------------------------------------------
# LLM binding
# ---------------------------------------------------------------------------

async def _resolve_cloud_backend(user_id: Optional[str], backend: Optional[str]) -> Optional[Dict[str, Any]]:
    """Usa o catálogo de fornecedores do IQ OS."""
    if not backend:
        return None
    chosen = ontology_ai.available_backend(None, backend)
    if chosen.get("kind") == "cloud":
        return chosen
    return None


def _langchain_llm_from_backend(backend: Dict[str, Any]) -> BaseChatModel:
    """Adaptador cloud -> LangChain ChatOpenAI / ChatAnthropic / ChatGoogle / ChatOllama."""
    provider = backend["provider"]
    spec = backend.get("spec") or {}
    base_url = (spec.get("base_url") or spec.get("api_base") or "").rstrip("/")
    model = backend.get("model") or ""
    api_key = backend.get("api_key") or ""

    if provider == "anthropic":
        from langchain_anthropic import ChatAnthropic

        return ChatAnthropic(model=model, anthropic_api_key=api_key, temperature=0.3, max_tokens=2048)
    if provider == "google":
        from langchain_google_genai import ChatGoogleGenerativeAI

        return ChatGoogleGenerativeAI(model=model, google_api_key=api_key, temperature=0.3, max_output_tokens=2048)

    # OpenAI-compatible (OpenAI, DeepSeek, xAI, Groq, Mistral, OpenRouter, Ollama cloud).
    from langchain_openai import ChatOpenAI

    kwargs: Dict[str, Any] = {"model": model, "api_key": api_key, "temperature": 0.3, "max_tokens": 2048}
    if base_url:
        kwargs["base_url"] = base_url
    if provider == "ollama-cloud":
        kwargs["default_headers"] = {"content-type": "application/json"}
    return ChatOpenAI(**kwargs)


def _simple_llm_call(messages: List[Dict[str, str]], backend: Optional[Dict[str, Any]], temperature: float = 0.3, max_tokens: int = 2048) -> str:
    """Caminho síncrono para chamadas cloud sem LangGraph (fallback)."""
    if not backend:
        return "[sem backend cloud configurado]"
    system = "\n\n".join(m["content"] for m in messages if m.get("role") == "system")
    conversation = [{"role": m["role"], "content": m["content"]} for m in messages if m.get("role") != "system"]
    try:
        return complete_answer(
            provider=backend["provider"],
            spec=backend.get("spec") or {},
            model=backend.get("model") or "",
            messages=[{"role": "system", "content": system}] + conversation if system else conversation,
            api_key=backend.get("api_key"),
            temperature=temperature,
            max_tokens=max_tokens,
        )
    except Exception as exc:
        logger.warning("Falha LLM call simples: %s", exc)
        return f"[erro LLM: {exc}]"


# ---------------------------------------------------------------------------
# Compilação dinâmica do grafo
# ---------------------------------------------------------------------------

def _build_react_agent(config: AgentConfig, backend: Optional[Dict[str, Any]]):
    """Agente ReAct simples quando não existe grafo definido."""
    tools = [AVAILABLE_TOOLS[t.tool_id] for t in (config.tools or []) if t.enabled and t.tool_id in AVAILABLE_TOOLS]
    system = config.system_prompt or "És um agente útil do IQ OS. Usa as ferramentas disponíveis para responder."
    prompt = ChatPromptTemplate.from_messages([("system", system), MessagesPlaceholder(variable_name="messages")])

    if backend and tools:
        llm = _langchain_llm_from_backend(backend)
        agent = prompt | llm.bind_tools(tools)

        async def call_model(state: AgentState) -> Dict[str, Any]:
            response = await agent.ainvoke({"messages": state["messages"]})
            return {"messages": state["messages"] + [response]}

        async def call_tool(state: AgentState) -> Dict[str, Any]:
            last_message = state["messages"][-1]
            if not isinstance(last_message, AIMessage) or not last_message.tool_calls:
                return {}
            tool_messages = []
            for call in last_message.tool_calls:
                tool = next((t for t in tools if t.name == call.get("name")), None)
                if tool is None:
                    tool_messages.append(ToolMessage(content=f"Ferramenta {call.get('name')} não encontrada.", tool_call_id=call.get("id") or "tc"))
                    continue
                try:
                    output = tool.invoke(call.get("args") or {})
                except Exception as exc:
                    output = f"Erro: {exc}"
                tool_messages.append(ToolMessage(content=str(output), tool_call_id=call.get("id") or "tc"))
            return {"messages": state["messages"] + tool_messages}

        def should_continue(state: AgentState) -> str:
            last = state["messages"][-1]
            if isinstance(last, AIMessage) and last.tool_calls:
                return "tools"
            return END

        workflow = StateGraph(AgentState)
        workflow.add_node("agent", call_model)
        workflow.add_node("tools", call_tool)
        workflow.set_entry_point("agent")
        workflow.add_conditional_edges("agent", should_continue, {"tools": "tools", END: END})
        workflow.add_edge("tools", "agent")
        return workflow.compile()

    # Sem tools: LLM puro.
    if backend:
        llm = _langchain_llm_from_backend(backend)
        agent = prompt | llm

        async def call_model(state: AgentState) -> Dict[str, Any]:
            response = await agent.ainvoke({"messages": state["messages"]})
            return {"messages": state["messages"] + [response]}

        workflow = StateGraph(AgentState)
        workflow.add_node("agent", call_model)
        workflow.set_entry_point("agent")
        return workflow.compile()

    # Sem backend: resposta direta sem LLM.
    async def echo(state: AgentState) -> Dict[str, Any]:
        return {"messages": state["messages"] + [AIMessage(content="Configura um backend de IA para executar este agente.")]}

    workflow = StateGraph(AgentState)
    workflow.add_node("agent", echo)
    workflow.set_entry_point("agent")
    return workflow.compile()


def _build_custom_graph(config: AgentConfig, backend: Optional[Dict[str, Any]]):
    """Compila um grafo definido pelo utilizador."""
    graph_def = config.graph or AgentConfig().graph
    nodes = graph_def.nodes or []
    edges = graph_def.edges or []
    if not nodes:
        return _build_react_agent(config, backend)

    tool_map = {t.tool_id: AVAILABLE_TOOLS[t.tool_id] for t in (config.tools or []) if t.enabled and t.tool_id in AVAILABLE_TOOLS}

    def make_node_handler(node):
        kind = node.kind
        prompt_text = node.prompt or ""
        output_key = node.output_key or node.id

        async def handler(state: AgentState) -> Dict[str, Any]:
            updates: Dict[str, Any] = {"steps": state["steps"] + [AgentRunStep(kind="node", name=node.id, content=node.label or node.id)]}
            if kind == "prompt":
                messages = state["messages"] + [HumanMessage(content=prompt_text)] if prompt_text else state["messages"]
                if backend:
                    llm = _langchain_llm_from_backend(backend)
                    response = await llm.ainvoke(messages)
                    updates["messages"] = messages + [response]
                    if output_key:
                        updates.setdefault("context", {})[output_key] = response.content
                else:
                    fallback = _simple_llm_call([{"role": "user", "content": prompt_text}], backend)
                    updates["messages"] = messages + [AIMessage(content=fallback)]
            elif kind == "rag":
                result = _rag_tool(prompt_text or state["context"].get("question", ""), config.rag_index, config.rag_mode)
                updates["messages"] = state["messages"] + [AIMessage(content=str(result))]
                if output_key:
                    updates.setdefault("context", {})[output_key] = result
            elif kind == "tool" and node.tools:
                tool_results = []
                for tool_id in node.tools:
                    tool = tool_map.get(tool_id)
                    if not tool:
                        continue
                    try:
                        result = tool.invoke(state["context"])
                    except Exception as exc:
                        result = f"Erro: {exc}"
                    tool_results.append(f"{tool_id}: {result}")
                    updates["steps"].append(AgentRunStep(kind="tool", name=tool_id, content=str(result)[:500]))
                combined = "\n\n".join(tool_results)
                updates["messages"] = state["messages"] + [HumanMessage(content=combined)]
                if output_key:
                    updates.setdefault("context", {})[output_key] = combined
            elif kind == "output":
                updates.setdefault("context", {})[output_key or "output"] = prompt_text or state["messages"][-1].content
            else:
                updates["messages"] = state["messages"]
            return updates

        return handler

    workflow = StateGraph(AgentState)
    node_handlers = {}
    for node in nodes:
        handler = make_node_handler(node)
        workflow.add_node(node.id, handler)
        node_handlers[node.id] = node

    entry = nodes[0].id
    workflow.set_entry_point(entry)

    # Ligações explícitas.
    for edge in edges:
        workflow.add_edge(edge.source, edge.target)

    # Transições sequenciais implícitas quando não há edges.
    if not edges:
        for i in range(len(nodes) - 1):
            workflow.add_edge(nodes[i].id, nodes[i + 1].id)
        workflow.add_edge(nodes[-1].id, END)

    return workflow.compile()


def build_agent_graph(config: AgentConfig, backend: Optional[Dict[str, Any]] = None):
    """Compila o grafo LangGraph para uma configuração de agente."""
    if config.graph and (config.graph.nodes or config.graph.edges):
        return _build_custom_graph(config, backend)
    return _build_react_agent(config, backend)


# ---------------------------------------------------------------------------
# CRUD de configurações no Elasticsearch
# ---------------------------------------------------------------------------

def _es() -> Optional[Any]:
    client = get_es_client()
    if client:
        ensure_indices(client)
    return client


def _now() -> str:
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _new_agent_id() -> str:
    return f"agent_{uuid.uuid4().hex[:16]}"


def _filter_doc_for_owner(doc: Dict[str, Any], user_id: Optional[str], is_admin: bool = False) -> bool:
    owner = doc.get("owner_id")
    if is_admin:
        return True
    if not user_id:
        return doc.get("is_public") is True
    return owner == user_id or doc.get("is_public") is True


def _to_agent_config(source: Dict[str, Any]) -> AgentConfig:
    return AgentConfig(**source)


async def list_agent_configs(user_id: Optional[str], *, is_admin: bool = False, size: int = 100) -> List[AgentConfig]:
    """Lista configurações acessíveis ao utilizador."""
    client = _es()
    if not client:
        return []
    query: Dict[str, Any] = {"bool": {"must": [{"term": {"enabled": True}}]}}
    if not is_admin and user_id:
        query["bool"]["should"] = [{"term": {"owner_id": user_id}}, {"term": {"is_public": True}}]
        query["bool"]["minimum_should_match"] = 1
    try:
        response = client.search(index=AGENT_CONFIGS_INDEX, body={"query": query, "size": size, "sort": [{"updated_at": {"order": "desc"}}]})
        results = []
        for hit in response.get("hits", {}).get("hits", []):
            source = dict(hit.get("_source") or {})
            source["agent_id"] = hit.get("_id")
            if _filter_doc_for_owner(source, user_id, is_admin):
                results.append(_to_agent_config(source))
        return results
    except Exception as exc:
        logger.warning("Erro ao listar agentes: %s", exc)
        return []


async def get_agent_config(agent_id: str, user_id: Optional[str], *, is_admin: bool = False) -> Optional[AgentConfig]:
    """Carrega uma configuração de agente."""
    client = _es()
    if not client:
        return None
    try:
        response = client.get(index=AGENT_CONFIGS_INDEX, id=agent_id)
        source = dict(response.get("_source") or {})
        source["agent_id"] = agent_id
        if not _filter_doc_for_owner(source, user_id, is_admin):
            return None
        return _to_agent_config(source)
    except Exception as exc:
        logger.warning("Erro ao obter agente %s: %s", agent_id, exc)
        return None


async def save_agent_config(config: AgentConfig, user_id: Optional[str]) -> AgentConfig:
    """Cria ou atualiza uma configuração de agente."""
    client = _es()
    if not client:
        raise RuntimeError("Elasticsearch indisponível.")
    agent_id = config.agent_id or _new_agent_id()
    now = _now()
    payload = config.model_dump(exclude={"agent_id", "created_at", "updated_at"}, exclude_unset=True)
    payload["updated_at"] = now
    if not config.agent_id:
        payload["created_at"] = now
    if user_id:
        payload["owner_id"] = user_id
    try:
        client.index(index=AGENT_CONFIGS_INDEX, id=agent_id, document=payload, refresh=True)
        return _to_agent_config({**payload, "agent_id": agent_id})
    except Exception as exc:
        logger.warning("Erro ao guardar agente %s: %s", agent_id, exc)
        raise


async def delete_agent_config(agent_id: str, user_id: Optional[str], *, is_admin: bool = False) -> bool:
    """Remove uma configuração de agente."""
    existing = await get_agent_config(agent_id, user_id, is_admin=is_admin)
    if not existing:
        return False
    if not is_admin and existing.owner_id != user_id:
        return False
    client = _es()
    if not client:
        return False
    try:
        client.delete(index=AGENT_CONFIGS_INDEX, id=agent_id, refresh=True)
        return True
    except Exception as exc:
        logger.warning("Erro ao apagar agente %s: %s", agent_id, exc)
        return False


# ---------------------------------------------------------------------------
# Execução de agente
# ---------------------------------------------------------------------------

async def run_agent(req: AgentRunRequest, user_id: Optional[str], *, is_admin: bool = False) -> AgentRunResponse:
    """Executa um agente dinâmico e devolve a resposta final."""
    t0 = time.perf_counter()
    config = await get_agent_config(req.agent_id, user_id, is_admin=is_admin)
    if not config:
        return AgentRunResponse(agent_id=req.agent_id, thread_id=req.thread_id or str(uuid.uuid4()), message={"role": "assistant", "content": "Agente não encontrado."}, error="Agente não encontrado.")

    backend = await _resolve_cloud_backend(user_id, config.backend)
    thread_id = req.thread_id or str(uuid.uuid4())
    system = config.system_prompt or "És um agente útil do IQ OS."
    messages: List[BaseMessage] = [SystemMessage(content=system), HumanMessage(content=req.message)]
    state = _make_state(messages, req.context)

    if not backend and not (config.graph and config.graph.nodes):
        return AgentRunResponse(
            agent_id=req.agent_id,
            thread_id=thread_id,
            message={"role": "assistant", "content": "Configura um backend de IA para executar este agente."},
            steps=state["steps"],
            elapsed_seconds=round(time.perf_counter() - t0, 2),
        )

    try:
        graph = build_agent_graph(config, backend)
        final_state = await graph.ainvoke(state, config=RunnableConfig(recursion_limit=25))
        final_messages = final_state.get("messages", state["messages"])
        last = final_messages[-1] if final_messages else AIMessage(content="")
        content = last.content if hasattr(last, "content") else str(last)
        return AgentRunResponse(
            agent_id=req.agent_id,
            thread_id=thread_id,
            message={"role": "assistant", "content": content},
            steps=final_state.get("steps", state["steps"]),
            sources=final_state.get("sources", []),
            elapsed_seconds=round(time.perf_counter() - t0, 2),
        )
    except Exception as exc:
        logger.warning("Erro a executar agente %s: %s", req.agent_id, exc)
        fallback = _simple_llm_call(
            [{"role": "system", "content": system}, {"role": "user", "content": req.message}],
            backend,
            temperature=config.temperature,
            max_tokens=config.max_tokens,
        )
        return AgentRunResponse(
            agent_id=req.agent_id,
            thread_id=thread_id,
            message={"role": "assistant", "content": fallback},
            steps=state["steps"] + [AgentRunStep(kind="error", content=str(exc))],
            elapsed_seconds=round(time.perf_counter() - t0, 2),
            error=str(exc),
        )


async def stream_agent(req: AgentRunRequest, user_id: Optional[str], *, is_admin: bool = False):
    """Gera eventos SSE para execução de um agente dinâmico."""
    t0 = time.perf_counter()
    config = await get_agent_config(req.agent_id, user_id, is_admin=is_admin)
    if not config:
        yield f"event: error\ndata: {json.dumps({'error': 'Agente não encontrado.'}, ensure_ascii=False)}\n\n"
        return

    backend = await _resolve_cloud_backend(user_id, config.backend)
    thread_id = req.thread_id or str(uuid.uuid4())
    system = config.system_prompt or "És um agente útil do IQ OS."
    messages: List[BaseMessage] = [SystemMessage(content=system), HumanMessage(content=req.message)]
    state = _make_state(messages, req.context)

    if not backend and not (config.graph and config.graph.nodes):
        yield f"data: {json.dumps({'token': 'Configura um backend de IA para executar este agente.'}, ensure_ascii=False)}\n\n"
        yield "event: done\ndata: {}\n\n"
        return

    graph = build_agent_graph(config, backend)
    final_state = await graph.ainvoke(state, config=RunnableConfig(recursion_limit=25))
    final_messages = final_state.get("messages", state["messages"])
    last = final_messages[-1] if final_messages else AIMessage(content="")
    content = last.content if hasattr(last, "content") else str(last)

    for step in final_state.get("steps", []):
        yield f"event: step\ndata: {json.dumps(step.model_dump(), ensure_ascii=False)}\n\n"
    for source in final_state.get("sources", []):
        yield f"event: source\ndata: {json.dumps(source.model_dump(), ensure_ascii=False)}\n\n"

    # Stream a resposta final palavra a palavra (simulação; fornecedor já vem em chunks).
    for word in content.split():
        yield f"data: {json.dumps({'token': word + ' '}, ensure_ascii=False)}\n\n"
    yield f"event: done\ndata: {json.dumps({'elapsed_seconds': round(time.perf_counter() - t0, 2)}, ensure_ascii=False)}\n\n"
