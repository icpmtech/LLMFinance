"""Agente FinanceLLM — orquestra ferramentas e gera resposta final."""
import asyncio
import json
import re
from concurrent.futures import ThreadPoolExecutor
from typing import AsyncIterator, Dict, List, Optional

from api.models import ChatMessage, Source, ToolCall
from api.tools import TOOLS, extract_tickers, get_stock_history, get_stock_info
from inference.generate import InferenceModel as Gpt2InferenceModel
from inference.generate_mistral import InferenceModel as MistralInferenceModel

# Carrega os modelos gerativos uma única vez, por backend.
_inference_models: dict[str, object] = {}


def get_inference_model(backend: str = "gpt2") -> object:
    """Devolve o modelo de inferência pedido (gpt2 ou mistral)."""
    global _inference_models
    if backend not in _inference_models:
        if backend == "mistral":
            _inference_models[backend] = MistralInferenceModel()
        else:
            _inference_models[backend] = Gpt2InferenceModel()
    return _inference_models[backend]

_executor = ThreadPoolExecutor(max_workers=4, thread_name_prefix="agent_")


def _format_currency(value, currency: str = "€"):
    if value is None or value == "N/A":
        return "N/A"
    try:
        return f"{currency}{float(value):,.2f}"
    except (ValueError, TypeError):
        return str(value)


def _format_pct(value):
    if value is None or value == "N/A":
        return "N/A"
    try:
        v = float(value)
        # yfinance devolve dividendYield já como proporção (0.048) ou percentagem (4.8)
        if v > 1:
            return f"{v:.1f}%"
        return f"{v * 100:.1f}%"
    except (ValueError, TypeError):
        return str(value)


def _trend_bars(history) -> str:
    if history is None or history.empty or len(history) < 2:
        return "Indisponível"
    close_col = "Close" if "Close" in history.columns else "Adj Close"
    if close_col not in history.columns:
        return "Indisponível"
    first = float(history[close_col].iloc[0])
    last = float(history[close_col].iloc[-1])
    change = (last - first) / first
    bar_len = 20
    filled = max(0, min(bar_len, int((change + 0.5) * bar_len)))
    bar = "█" * filled + "░" * (bar_len - filled)
    signal = "Positiva" if change > 0.02 else "Negativa" if change < -0.02 else "Neutra"
    return f"{bar}  {signal} ({change:+.1%})"


def build_context(question: str) -> Dict:
    """Executa ferramentas relevantes e constroi o contexto da resposta."""
    tickers = extract_tickers(question)
    context = {
        "question": question,
        "tickers": tickers,
        "tools": [],
        "sources": [],
        "stock": None,
        "history": None,
    }
    for t in tickers[:1]:  # analisar o primeiro ticker identificado
        info = get_stock_info(t)
        history = get_stock_history(t, period="1y")
        context["stock"] = info
        context["history"] = history
        context["tools"].append(ToolCall(tool="get_stock_info", input={"symbol": t}, output=json.dumps(info, default=str)))
        context["tools"].append(ToolCall(tool="get_stock_history", input={"symbol": t, "period": "1y"}, output=f"{len(history)} dias"))
        if "website" in info and info["website"]:
            context["sources"].append(Source(name=f"Yahoo Finance — {info.get('name', t)}", url=f"https://finance.yahoo.com/quote/{t}", value=str(info.get("price"))))
    return context


def generate_answer(context: Dict, backend: str = "gpt2") -> str:
    """Gera resposta final com o modelo treinado, enriquecido com dados de mercado."""
    q = context["question"]
    stock = context.get("stock")

    if not stock:
        return (
            "Não identifiquei uma empresa ou ticker na tua pergunta. "
            "Pergunta-me sobre empresas como EDP, GALP, Microsoft ou Apple."
        )
    if "error" in stock:
        return f"Não consegui obter dados para **{stock['ticker']}**. Erro: {stock['error']}"

    # Constrói um prompt factual para o modelo gerativo.
    name = stock.get("name", stock["ticker"])
    price = stock.get("price", "N/A")
    dy = stock.get("dividend_yield", "N/A")
    pe = stock.get("pe", "N/A")
    sector = stock.get("sector", "N/A")
    currency = stock.get("currency", "EUR")
    symbol = stock["ticker"]
    trend = _trend_bars(context.get("history"))

    prompt = (
        f"Question: {q}\n"
        f"Company: {name} ({symbol})\n"
        f"Price: {price} {currency}\n"
        f"Sector: {sector}\n"
        f"Dividend Yield: {dy}\n"
        f"P/E: {pe}\n"
        f"Trend (1y): {trend}\n"
        f"Answer:"
    )

    try:
        model = get_inference_model(backend)
        answer = model.generate(prompt, max_new_tokens=80, temperature=0.8)
    except Exception as exc:
        return f"Erro ao gerar resposta com o modelo {backend}: {exc}"

    return answer.strip()


def run_chat(messages: List[ChatMessage], backend: str = "gpt2") -> Dict:
    """Executa o agente síncrono e devolve resposta completa."""
    question = messages[-1].content if messages else ""
    context = build_context(question)
    answer = generate_answer(context, backend=backend)
    return {
        "message": ChatMessage(role="assistant", content=answer),
        "sources": context["sources"],
        "tools": context["tools"],
    }


async def stream_chat(messages: List[ChatMessage], backend: str = "gpt2") -> AsyncIterator[str]:
    """Gera a resposta token a token (simulação de streaming).

    Envia imediatamente um evento de progresso para manter a ligação SSE viva,
    depois executa a recolha de dados num thread separado. Assim o browser não
    aborta o pedido enquanto o yfinance trabalha.
    """
    # 1) Ligar a stream imediatamente.
    yield ":keep-alive\n\n"
    yield "event: status\ndata: " + json.dumps({"status": "busy", "detail": "A recolher dados financeiros..."}) + "\n\n"

    loop = asyncio.get_running_loop()
    result = await loop.run_in_executor(_executor, run_chat, messages, backend)
    text = result["message"].content

    yield "event: meta\ndata: " + json.dumps({"model": f"finance-llm-{backend}", "tickers": text}) + "\n\n"

    for token in re.split(r"(\s+)", text):
        if token:
            yield f"data: {json.dumps({'token': token})}\n\n"
        await asyncio.sleep(0.005)

    yield "event: done\ndata: " + json.dumps({"sources": [s.model_dump() for s in result["sources"]], "tools": [t.model_dump() for t in result["tools"]]}) + "\n\n"
