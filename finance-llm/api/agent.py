"""Agente IQ OS — orquestra ferramentas e gera resposta final."""
import asyncio
import json
import re
from concurrent.futures import ThreadPoolExecutor
from typing import Any, AsyncIterator, Dict, List, Optional

from api import cloud_chat, events_service as events, providers_service as providers
from api.models import ChatMessage, Source, ToolCall
from api.tools import (
    TOOLS,
    extract_tickers,
    forecast_prices,
    get_stock_history,
    get_stock_info,
)
from sentiment.feature_engineering import generate_sentiment_blended_forecast
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


def _is_forecast_question(question: str) -> bool:
    """Detecta se o utilizador pede uma previsão/projeção de preços."""
    keywords = [
        "previs",
        "prever",
        "projet",
        "projec",
        "forecast",
        "predict",
        "prognos",
        "expectativa",
        "futuro",
        "próximos",
        "proximos",
        "irá subir",
        "vai subir",
        "vai descer",
        "irá descer",
        "preço amanh",
    ]
    q = question.lower()
    return any(k in q for k in keywords)


def _is_sentiment_question(question: str) -> bool:
    """Detecta se o utilizador pede análise de sentimento/impacto de notícias."""
    keywords = [
        "sentiment",
        "sentimento",
        "notícias",
        "noticias",
        "news",
        "headlines",
        "imprensa",
        "analise de sentimento",
        "análise de sentimento",
        "blending",
        "misturar",
        "macro",
        "earnings",
        "resultados",
    ]
    q = question.lower()
    return any(k in q for k in keywords)


def build_context(question: str) -> Dict:
    """Executa ferramentas relevantes e constroi o contexto da resposta."""
    tickers = extract_tickers(question)
    wants_forecast = _is_forecast_question(question)
    wants_sentiment = _is_sentiment_question(question)
    context = {
        "question": question,
        "tickers": tickers,
        "tools": [],
        "sources": [],
        "stock": None,
        "history": None,
        "forecast": None,
        "sentiment": None,
        "ontology": None,
    }
    # Camada ontológica: identifica objetos da plataforma (empresas, contratos,
    # CPV, marcas, tickers, notícias, CRM) antes de qualquer geração. É este
    # contexto que impede o modelo de inventar entidades e valores.
    try:
        from api import ontology_service as ontology

        ground = ontology.ai_context(question, limit=4, links_per_object=2, link_size=2, link_budget=4)
        context["ontology"] = ground
        context["tools"].append(
            ToolCall(
                tool="ontology_grounding",
                input={"question": question},
                output=f"{len(ground['objects'])} objetos, {len(ground['relations'])} relações",
            )
        )
        for entry in ground["objects"][:4]:
            context["sources"].append(
                Source(
                    name=f"Ontologia · {entry['type_label']}: {entry['label']}",
                    url=None,
                    value=str(entry["id"]),
                )
            )
    except Exception as exc:  # a ontologia nunca deve quebrar o chat
        context["ontology"] = {
            "objects": [],
            "relations": [],
            "grounding": "",
            "notes": [f"Ontologia indisponível: {exc}"],
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

        if wants_forecast:
            try:
                fc = forecast_prices(t, future_days=5, period="5y")
                context["forecast"] = fc
                context["tools"].append(ToolCall(tool="forecast_prices", input={"symbol": t, "future_days": 5}, output=json.dumps(fc, default=str, ensure_ascii=False)))
                if fc.get("plot_path"):
                    context["sources"].append(Source(name=f"Previsão ARIMA — {info.get('name', t)}", url=f"file://{fc['plot_path']}", value=fc["forecast"][-1]["price"] if fc.get("forecast") else None))
            except Exception as exc:
                context["tools"].append(ToolCall(tool="forecast_prices", input={"symbol": t}, output=f"Erro: {exc}"))

        if wants_sentiment:
            try:
                sent = generate_sentiment_blended_forecast(t, future_days=5, period="1y", backend="kronos", include_features=False)
                context["sentiment"] = sent
                context["tools"].append(ToolCall(tool="generate_sentiment_blended_forecast", input={"symbol": t, "future_days": 5}, output=json.dumps(sent, default=str, ensure_ascii=False)))
            except Exception as exc:
                context["tools"].append(ToolCall(tool="generate_sentiment_blended_forecast", input={"symbol": t}, output=f"Erro: {exc}"))
    return context


def generate_answer(context: Dict, backend: str = "gpt2") -> str:
    """Gera resposta final com o modelo treinado, enriquecido com dados de mercado.

    Se o modelo gerativo ainda não estiver suficientemente treinado e devolver
    texto incoerente, cai numa resposta factual baseada nos dados das ferramentas.
    """
    q = context["question"]
    stock = context.get("stock")

    if not stock:
        ontology_context = context.get("ontology") or {}
        if ontology_context.get("objects"):
            # Pergunta sobre dados da plataforma (contratos, empresas, marcas, CRM):
            # responde com os objetos e relações verificados na ontologia.
            from api import ontology_service as ontology

            return ontology.answer_from_context(ontology_context)
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
    forecast = context.get("forecast")
    sentiment = context.get("sentiment")

    forecast_block = ""
    if forecast and "error" not in forecast:
        fc_text = "\n".join(
            f"  {f['date']}: {f['price']:.2f} {currency}"
            for f in forecast.get("forecast", [])
        )
        forecast_block = (
            f"\nARIMA{forecast['order']} Forecast (next {len(forecast.get('forecast', []))} business days):\n"
            f"{fc_text}\n"
            f"  RMSE (test set): {forecast['rmse']:.2f}\n"
            f"  MAPE (test set): {forecast['mape']:.2f}%\n"
            f"  Ljung-Box p-value: {forecast['ljung_box_pvalue']:.4f}\n"
        )

    sentiment_block = ""
    if sentiment and "error" not in sentiment:
        adj = sentiment.get("adjusted_forecast", [])
        if adj:
            last_adj = adj[-1]
            sentiment_block = (
                f"\nSentiment/Macro/Earnings Blended Forecast ({sentiment.get('base_model', 'kronos')}):\n"
                f"  Sinal: {sentiment.get('sentiment_signal', 0):+.2f}, "
                f"Macro: {sentiment.get('macro_signal', 0):+.2f}, "
                f"Earnings: {sentiment.get('earnings_signal', 0):+.2f}\n"
                f"  Previsão ajustada (último dia): {last_adj.get('date')} → {last_adj.get('price')} {currency}\n"
            )
        else:
            sentiment_block = (
                f"\nSentiment analysis: sinal={sentiment.get('blended_signal', 0):+.2f} "
                f"(sentimento {sentiment.get('sentiment_signal', 0):+.2f}, macro {sentiment.get('macro_signal', 0):+.2f}, earnings {sentiment.get('earnings_signal', 0):+.2f}).\n"
            )

    prompt = (
        f"Question: {q}\n"
        f"Company: {name} ({symbol})\n"
        f"Price: {price} {currency}\n"
        f"Sector: {sector}\n"
        f"Dividend Yield: {dy}\n"
        f"P/E: {pe}\n"
        f"Trend (1y): {trend}\n"
        f"{forecast_block}"
        f"{sentiment_block}"
        f"Answer:"
    )

    try:
        model = get_inference_model(backend)
        raw_answer = model.generate(prompt, max_new_tokens=120, temperature=0.7)
    except Exception as exc:
        return f"Erro ao gerar resposta com o modelo {backend}: {exc}"

    answer = raw_answer.strip()
    # Tenta isolar a resposta depois de "Answer:" se o modelo repete o contexto.
    if "Answer:" in answer:
        answer = answer.split("Answer:", 1)[-1].strip()
    # Se ainda for lixo, usa fallback factual.
    if _is_gibberish(answer):
        answer = _fallback_answer(
            name, symbol, price, currency, sector, dy, pe, trend, backend, forecast, sentiment
        )
    return answer


def _is_gibberish(text: str) -> bool:
    """Heurística para detectar texto gerado incoerente / alucinado."""
    if not text or len(text.strip()) < 3:
        return True
    cleaned = text.strip()
    words = [w for w in re.split(r"[^a-zA-ZáàâãéêíóôõúçÇ]+", cleaned) if w and len(w) > 1]
    tokens = [t for t in re.split(r"\s+", cleaned) if t]

    # Poucas palavras reais -> incoerente.
    if len(words) < 4:
        return True

    # Muitas palavras repetidas (ex: "and and and...").
    if len(words) > 5:
        from collections import Counter

        most_common = Counter(words).most_common(1)
        if most_common and most_common[0][1] >= 3 and most_common[0][1] / len(words) > 0.25:
            return True

    # Palavras muito curtas (< 3 letras) ou palavras de ligação dominam o texto.
    short_words = [w for w in words if len(w) < 3]
    stopwords = {"the", "and", "of", "in", "to", "a", "is", "for", "on", "at", "as", "or", "it", "its", "an", "do", "that", "this", "with", "from", "by", "are", "was", "were", "be", "been", "have", "has", "had", "will", "would", "could", "should", "can", "may", "might", "so", "if", "but", "not", "no", "yes", "um", "uma", "o", "os", "a", "as", "de", "da", "do", "das", "dos", "em", "no", "na", "nos", "nas", "para", "por", "com", "sem", "que", "e", "ou", "se", "mas", "são", "foi", "ser", "estar"}
    meaningful = [w for w in words if w.lower() not in stopwords]
    if len(words) > 5 and len(meaningful) / len(words) < 0.35:
        return True
    if len(words) > 5 and len(short_words) / len(words) > 0.5:
        return True

    # Presença de muitas repetições de duplicatas (ex: "and and", "the the").
    dupes = sum(1 for i in range(len(words) - 1) if words[i].lower() == words[i + 1].lower())
    if len(words) > 5 and dupes / len(words) > 0.08:
        return True

    # Tokens com lixo alfanumérico ou pontuação estranha.
    weird_tokens = [t for t in tokens if re.search(r"[^a-zA-ZáàâãéêíóôõúçÇ0-9.,;:!?€$%-]", t)]
    if len(tokens) > 5 and len(weird_tokens) / len(tokens) > 0.2:
        return True

    return False


def _fallback_answer(
    name, symbol, price, currency, sector, dy, pe, trend, backend: str, forecast=None, sentiment=None
) -> str:
    """Resposta factual de fallback quando o modelo gerativo falha."""
    dy_str = _format_pct(dy)
    pe_str = "N/A" if pe in (None, "N/A") else f"{float(pe):.2f}"
    price_str = _format_currency(price, currency)

    forecast_text = ""
    if forecast and "error" not in forecast:
        fc_lines = "\n".join(
            f"- {f['date']}: **{f['price']:.2f} {currency}**" for f in forecast.get("forecast", [])
        )
        forecast_text = (
            f"\n\nPrevisão ARIMA{forecast['order']} para os próximos {len(forecast.get('forecast', []))} dias úteis:\n"
            f"{fc_lines}\n\n"
            f"Métricas no conjunto de teste: RMSE={forecast['rmse']:.2f}, MAPE={forecast['mape']:.2f}%. "
            f"Ljung-Box p-value={forecast['ljung_box_pvalue']:.4f} "
            f"({'resíduos sem padrão' if forecast['ljung_box_pvalue'] > 0.05 else 'resíduos mostram autocorrelação'})."
        )

    sentiment_text = ""
    if sentiment and "error" not in sentiment:
        adj = sentiment.get("adjusted_forecast", [])
        if adj:
            sentiment_text = (
                f"\n\nPrevisão ajustada com sentimento/macro/resultados ({sentiment.get('base_model', 'kronos')}):\n"
                f"- Sinal sentimento: {sentiment.get('sentiment_signal', 0):+.2f}\n"
                f"- Sinal macro: {sentiment.get('macro_signal', 0):+.2f}\n"
                f"- Sinal earnings: {sentiment.get('earnings_signal', 0):+.2f}\n"
                f"- Preço ajustado previsto: {adj[-1].get('price')} {currency} em {adj[-1].get('date')}\n"
                f"- Ajuste de blending: {sentiment.get('blended_signal', 0):+.2f}"
            )
        else:
            sentiment_text = (
                f"\n\nAnálise de sentimento: sinal combinado {sentiment.get('blended_signal', 0):+.2f} "
                f"(sentimento {sentiment.get('sentiment_signal', 0):+.2f}, macro {sentiment.get('macro_signal', 0):+.2f}, "
                f"earnings {sentiment.get('earnings_signal', 0):+.2f})."
            )

    return (
        f"{name} ({symbol}) cotava a {price_str}. "
        f"O sector é {sector}, com dividend yield de {dy_str} e P/E de {pe_str}. "
        f"Tendência de 1 ano: {trend}."
        f"{forecast_text}"
        f"{sentiment_text}\n\n"
        f"Esta resposta é baseada nos dados do Yahoo Finance enquanto o modelo IQ OS ({backend}) continua a ser treinado."
    )


def _context_prompt(context: Dict, question: str) -> str:
    """Instruções + dados recolhidos, para fornecedores externos responderem com contexto."""
    blocks: List[str] = [
        "És o assistente financeiro do IQ OS (plataforma portuguesa de mercados, contratos públicos "
        "e inteligência financeira). Responde em português de Portugal, de forma objectiva e "
        "fundamentada, usando os dados fornecidos abaixo quando forem relevantes. Se não houver "
        "dados suficientes, di-lo com clareza em vez de inventar números.",
    ]
    if context.get("sources"):
        lines = []
        for source in context["sources"]:
            label = getattr(source, "title", None) or getattr(source, "name", None) or str(source)
            lines.append(f"- {label}")
        blocks.append("Fontes consultadas:\n" + "\n".join(lines))
    if context.get("tools"):
        lines = []
        for tool in context["tools"]:
            name = getattr(tool, "name", "ferramenta")
            output = getattr(tool, "output", "") or ""
            lines.append(f"- {name}: {str(output)[:1200]}")
        blocks.append("Dados recolhidos pelas ferramentas:\n" + "\n".join(lines))
    blocks.append(f"Pergunta do utilizador: {question}")
    return "\n\n".join(blocks)


def _cloud_request(
    messages: List[ChatMessage],
    backend: str,
    *,
    user_id: Optional[str] = None,
    user_email: Optional[str] = None,
) -> Dict[str, Any]:
    """Prepara o pedido a um fornecedor externo (contexto + chave resolvida)."""
    parsed = providers.parse_backend(backend)
    provider = parsed.get("provider")
    model = parsed.get("model") or ""
    spec = parsed.get("spec") or {}
    if not provider or not spec:
        raise cloud_chat.CloudError(parsed.get("error") or "Fornecedor desconhecido.")

    api_key, key_source = providers.resolve_key(user_id, provider)
    if not api_key and not spec.get("key_optional"):
        raise cloud_chat.CloudError(
            f"O fornecedor {spec.get('label') or provider} ainda não tem chave de API. "
            "Configure-a em Definições → Fornecedores de IA."
        )

    question = messages[-1].content if messages else ""
    context = build_context(question)

    # O contexto financeiro vai no `system`; a conversa mantém-se como veio do chat.
    system = _context_prompt(context, question)
    conversation: List[Dict[str, str]] = []
    for message in messages:
        role = "assistant" if getattr(message, "role", "user") == "assistant" else "user"
        conversation.append({"role": role, "content": str(message.content)})

    return {
        "provider": provider,
        "spec": spec,
        "model": model,
        "api_key": api_key or "",
        "key_source": key_source,
        "system": system,
        "conversation": conversation,
        "context": context,
        "user_email": user_email,
    }


def run_chat(messages: List[ChatMessage], backend: str = "gpt2", *, user_id: Optional[str] = None, user_email: Optional[str] = None) -> Dict:
    """Executa o agente síncrono e devolve resposta completa."""
    parsed = providers.parse_backend(backend)
    if parsed["kind"] == "cloud":
        try:
            request = _cloud_request(messages, backend, user_id=user_id, user_email=user_email)
        except cloud_chat.CloudError as error:
            events.log_event(
                "warning",
                "providers",
                f"Pedido recusado ({backend}): {error.message}",
                user_id=user_id,
                user_email=user_email,
                data={"backend": backend},
            )
            return {
                "message": ChatMessage(role="assistant", content=f"⚠️ {error.message}"),
                "sources": [],
                "tools": [],
                "model": backend,
            }
        try:
            answer = asyncio.run(
                cloud_chat.complete_answer(
                    provider=request["provider"],
                    spec=request["spec"],
                    model=request["model"],
                    messages=[{"role": "system", "content": request["system"]}, *request["conversation"]],
                    api_key=request["api_key"],
                    max_tokens=1024,
                )
            )
        except cloud_chat.CloudError as error:
            events.log_event(
                "error",
                "providers",
                f"Falha no chat com {request['provider']}/{request['model']}: {error.message}",
                user_id=user_id,
                user_email=user_email,
                data={"provider": request["provider"], "model": request["model"], "status": error.status},
            )
            answer = f"⚠️ {error.message}"
        events.log_event(
            "info",
            "providers",
            f"Chat via {request['provider']}/{request['model']} ({len(answer)} caracteres)",
            user_id=user_id,
            user_email=user_email,
            data={"provider": request["provider"], "model": request["model"], "key_source": request["key_source"]},
        )
        return {
            "message": ChatMessage(role="assistant", content=answer),
            "sources": request["context"]["sources"],
            "tools": request["context"]["tools"],
            "model": f"{request['provider']}:{request['model']}",
        }

    question = messages[-1].content if messages else ""
    context = build_context(question)
    answer = generate_answer(context, backend=backend)
    return {
        "message": ChatMessage(role="assistant", content=answer),
        "sources": context["sources"],
        "tools": context["tools"],
        "model": f"finance-llm-{backend}",
    }


async def stream_chat(
    messages: List[ChatMessage],
    backend: str = "gpt2",
    *,
    user_id: Optional[str] = None,
    user_email: Optional[str] = None,
) -> AsyncIterator[str]:
    """Gera a resposta token a token.

    Modelos locais: envia um evento de progresso, recolhe os dados num thread
    separado e simula o streaming. Fornecedores externos: transmite os pedaços
    reais devolvidos pela API do fornecedor.
    """
    parsed = providers.parse_backend(backend)

    # 1) Ligar a stream imediatamente.
    yield ":keep-alive\n\n"

    if parsed["kind"] == "cloud":
        yield "event: status\ndata: " + json.dumps({"status": "busy", "detail": "A contactar o fornecedor…"}) + "\n\n"
        try:
            request = _cloud_request(messages, backend, user_id=user_id, user_email=user_email)
        except cloud_chat.CloudError as error:
            yield "event: error\ndata: " + json.dumps({"message": error.message}) + "\n\n"
            text = f"⚠️ {error.message}"
            for token in re.split(r"(\s+)", text):
                if token:
                    yield f"data: {json.dumps({'token': token})}\n\n"
            yield "event: done\ndata: " + json.dumps({"sources": [], "tools": []}) + "\n\n"
            return

        yield "event: meta\ndata: " + json.dumps(
            {"model": f"{request['provider']}:{request['model']}", "provider": request["provider"]}
        ) + "\n\n"
        yield "event: status\ndata: " + json.dumps({"status": "busy", "detail": "A gerar a resposta…"}) + "\n\n"

        collected: List[str] = []
        try:
            async for chunk in cloud_chat.stream_answer(
                provider=request["provider"],
                spec=request["spec"],
                model=request["model"],
                messages=[{"role": "system", "content": request["system"]}, *request["conversation"]],
                api_key=request["api_key"],
                max_tokens=1024,
            ):
                collected.append(chunk)
                yield f"data: {json.dumps({'token': chunk})}\n\n"
        except cloud_chat.CloudError as error:
            events.log_event(
                "error",
                "providers",
                f"Falha no streaming com {request['provider']}/{request['model']}: {error.message}",
                user_id=user_id,
                user_email=user_email,
                data={"provider": request["provider"], "model": request["model"], "status": error.status},
            )
            fallback = f"⚠️ {error.message}"
            collected.append(fallback)
            yield f"data: {json.dumps({'token': fallback})}\n\n"

        events.log_event(
            "info",
            "providers",
            f"Resposta de {request['provider']}/{request['model']} ({sum(len(part) for part in collected)} caracteres)",
            user_id=user_id,
            user_email=user_email,
            data={"provider": request["provider"], "model": request["model"], "key_source": request["key_source"]},
        )
        yield "event: done\ndata: " + json.dumps(
            {
                "sources": [source.model_dump() for source in request["context"]["sources"]],
                "tools": [tool.model_dump() for tool in request["context"]["tools"]],
            }
        ) + "\n\n"
        return

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
