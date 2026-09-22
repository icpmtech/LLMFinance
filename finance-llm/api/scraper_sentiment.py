"""Sentimento de cada notícia recolhida — modelo de IA, com reserva local.

O que faz
---------
Para cada item de uma recolha, lê o texto (integral quando a fonte o traz, senão
o resumo ou o título) e classifica-o em **positivo / neutro / negativo**, com uma
polaridade entre -1 e 1. O resultado fica no item (`sentiment`) e em campos
próprios no índice (`sentiment`, `sentiment_score`, `sentiment_engine`), pelo que
a pesquisa o pode filtrar e **resumir o sentimento do conjunto de resultados**.

Motores
-------
- `ai`: pergunta a um fornecedor de IA (OpenAI, DeepSeek, Ollama, …) e exige uma
  resposta JSON curta. Custa uma chamada por item — daí o `max_items`.
- `lexicon`: o léxico português do módulo de sentimento (`sentiment_service`),
  local e gratuito.
- `auto` (omissão): usa a IA quando há fornecedor utilizável e cai no léxico se
  não houver (ou se a chamada falhar). O item regista sempre **que motor** o
  classificou, para não haver dúvidas sobre a origem do número.

A escolha do fornecedor segue a regra do resto da plataforma (`providers_service`
+ `scraper_ai.pick_provider`): chave do utilizador da sessão, depois chave do
ambiente, depois o Ollama local. Sem nada disso, o motor é o léxico.
"""
from __future__ import annotations

import asyncio
import json
import logging
import re
import threading
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from api import sentiment_service

logger = logging.getLogger(__name__)

#: Motores aceites numa definição de fonte.
ENGINES = ("auto", "ai", "lexicon")
ENGINE_LABELS = {
    "auto": "IA quando disponível (reserva: léxico local)",
    "ai": "Modelo de IA (obrigatório)",
    "lexicon": "Léxico português local",
}
#: Campos do item que podem servir de matéria-prima ao sentimento.
FIELDS = ("text", "summary", "title")
FIELD_LABELS = {
    "text": "Texto integral (cai no resumo e no título se faltar)",
    "summary": "Resumo/entrada (cai no título se faltar)",
    "title": "Só o título",
}
#: Etiquetas possíveis (as mesmas do módulo de sentimento).
LABELS = ("positivo", "neutro", "negativo")

#: Texto mínimo para valer a pena classificar (títulos soltos não dão sinal).
MIN_CHARS = 80
#: Quanto do artigo é enviado ao modelo (o lead chega; o texto todo custa mais).
AI_TEXT_CHARS = 1500
AI_MAX_TOKENS = 300
#: Uma chamada que demore mais do que isto não serve para uma recolha.
AI_TIMEOUT_SECONDS = 45
#: Falhas seguidas a partir das quais se deixa de tentar este fornecedor.
AI_FAILURES_BEFORE_COOLDOWN = 2
AI_COOLDOWN_SECONDS = 600

#: Estado em memória dos fornecedores que estão a falhar (evita esperar N vezes).
_ai_failures: Dict[str, int] = {}
_ai_cooldown: Dict[str, float] = {}

DEFAULT_CONFIG: Dict[str, Any] = {
    "enabled": False,
    "engine": "auto",
    "provider": "",
    "model": "",
    "max_items": 10,
    "field": "text",
    "min_chars": MIN_CHARS,
}

PROMPT = (
    "És analista de notícias económicas e escreves para um leitor português. "
    "Classifica o sentimento da notícia do ponto de vista do leitor: "
    "«positivo» se é uma boa notícia (crescimento, acordo, resultados melhores, alívio), "
    "«negativo» se é má notícia (crise, perdas, subidas de preços, risco, despedimentos), "
    "«neutro» se é sobretudo factual ou sem juízo de valor. "
    "Responde APENAS com JSON válido, sem texto à volta, no formato:\n"
    '{"sentimento": "positivo|neutro|negativo", "polaridade": <número entre -1 e 1>, '
    '"justificacao": "<até 20 palavras>"}'
)


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


# ------------------------------------------------------------------- definição
def normalize_config(raw: Any) -> Dict[str, Any]:
    """Valida o bloco `sentiment` de uma definição de fonte."""
    raw = raw if isinstance(raw, dict) else {}
    engine = str(raw.get("engine") or DEFAULT_CONFIG["engine"]).strip().lower()
    if engine not in ENGINES:
        engine = DEFAULT_CONFIG["engine"]
    field = str(raw.get("field") or DEFAULT_CONFIG["field"]).strip().lower()
    if field not in FIELDS:
        field = DEFAULT_CONFIG["field"]
    try:
        max_items = int(raw.get("max_items") if raw.get("max_items") is not None else DEFAULT_CONFIG["max_items"])
    except (TypeError, ValueError):
        max_items = DEFAULT_CONFIG["max_items"]
    try:
        min_chars = int(raw.get("min_chars") or DEFAULT_CONFIG["min_chars"])
    except (TypeError, ValueError):
        min_chars = DEFAULT_CONFIG["min_chars"]
    return {
        "enabled": bool(raw.get("enabled", False)),
        "engine": engine,
        "provider": str(raw.get("provider") or "").strip(),
        "model": str(raw.get("model") or "").strip(),
        "max_items": max(0, min(max_items, 100)),
        "field": field,
        "min_chars": max(0, min(min_chars, 5000)),
    }


def item_text(item: Dict[str, Any], config: Dict[str, Any]) -> str:
    """Texto a classificar, pela ordem pedida na definição (com quedas sucessivas)."""
    field = config.get("field") or "text"
    order = {
        "text": ("text", "summary", "title"),
        "summary": ("summary", "text", "title"),
        "title": ("title",),
    }[field]
    for key in order:
        value = item.get(key)
        if isinstance(value, (list, tuple)):
            value = " · ".join(str(v) for v in value)
        text = re.sub(r"\s+", " ", str(value or "")).strip()
        if len(text) >= int(config.get("min_chars") or 0):
            return text
    return ""


# ------------------------------------------------------------------ motores
def analyze_lexicon(text: str) -> Dict[str, Any]:
    """Classificação local (léxico português com negação e intensificadores)."""
    result = sentiment_service.analyze_text(text)
    return {
        "label": result.get("label") or "neutro",
        "polarity": float(result.get("polarity") or 0.0),
        "score": float(result.get("score") or 0.0),
        "hits": int(result.get("hits") or 0),
        "engine": "lexicon",
        "provider": "",
        "model": "",
    }


def _parse_json(text: str) -> Optional[Dict[str, Any]]:
    """Extrai o primeiro objeto JSON de uma resposta de modelo."""
    raw = str(text or "").strip()
    match = re.search(r"\{.*\}", raw, re.S)
    if not match:
        return None
    try:
        data = json.loads(match.group(0))
    except Exception:
        return None
    return data if isinstance(data, dict) else None


def _clean_label(value: Any) -> str:
    label = str(value or "").strip().lower()
    mapping = {
        "positive": "positivo", "positivo": "positivo", "boa": "positivo",
        "negative": "negativo", "negativo": "negativo", "ma": "negativo", "má": "negativo",
        "neutral": "neutro", "neutro": "neutro",
    }
    return mapping.get(label, "")


def _clamp(value: Any) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return 0.0
    return max(-1.0, min(1.0, number))


def _run_sync(coro: Any, timeout: float = AI_TIMEOUT_SECONDS) -> Any:
    """Corre uma rotina assíncrona a partir do fio da recolha (que não tem loop)."""
    async def guarded() -> Any:
        return await asyncio.wait_for(coro, timeout=timeout)

    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(guarded())
    # Há um loop a correr neste fio: isola num fio novo para não bloquear.
    box: Dict[str, Any] = {}

    def runner() -> None:
        try:
            box["value"] = asyncio.run(guarded())
        except Exception as exc:  # pragma: no cover - depende do ambiente
            box["error"] = exc

    thread = threading.Thread(target=runner, name="sentiment-ai", daemon=True)
    thread.start()
    thread.join()
    if "error" in box:
        raise box["error"]
    return box.get("value")


def _provider_key(provider: Optional[str], model: Optional[str], user_id: Optional[str]) -> str:
    return f"{user_id or '-'}|{provider or 'predefinido'}|{model or 'predefinido'}"


def _in_cooldown(key: str) -> bool:
    until = _ai_cooldown.get(key, 0.0)
    if until <= 0:
        return False
    if time.time() >= until:
        _ai_cooldown.pop(key, None)
        _ai_failures.pop(key, None)
        return False
    return True


def _register_failure(key: str) -> None:
    falhas = _ai_failures.get(key, 0) + 1
    _ai_failures[key] = falhas
    if falhas >= AI_FAILURES_BEFORE_COOLDOWN:
        _ai_cooldown[key] = time.time() + AI_COOLDOWN_SECONDS
        logger.warning(
            "Sentimento: fornecedor %s falhou %s vezes; a usar o léxico local durante %s minutos.",
            key,
            falhas,
            AI_COOLDOWN_SECONDS // 60,
        )


def _register_success(key: str) -> None:
    _ai_failures.pop(key, None)
    _ai_cooldown.pop(key, None)


async def _ask_model(text: str, *, title: str, provider: Optional[str], model: Optional[str], user_id: Optional[str]) -> Dict[str, Any]:
    """Pergunta ao fornecedor de IA escolhido; devolve a classificação validada."""
    from api import cloud_chat
    from api.scraper_ai import pick_provider

    provider_id, spec, model_id, key = pick_provider(user_id, provider, model)
    if not provider_id or not spec:
        raise RuntimeError("Nenhum fornecedor de IA configurado.")

    prompt = f"{PROMPT}\n\nTítulo: {title[:300]}\n\nTexto: {text[:AI_TEXT_CHARS]}"
    answer = await cloud_chat.complete_answer(
        provider=provider_id,
        spec=spec,
        model=model_id or spec.get("default_model") or "",
        messages=[{"role": "user", "content": prompt}],
        api_key=key,
        temperature=0.0,
        max_tokens=AI_MAX_TOKENS,
    )
    data = _parse_json(answer)
    if not data:
        # Modelos pequenos respondem muitas vezes com uma frase em vez de JSON:
        # se a palavra estiver lá, aceita-se a leitura e perde-se a polaridade.
        label = _clean_label(answer)
        if not label:
            raise RuntimeError("A IA não devolveu JSON válido.")
        return {
            "label": label,
            "polarity": 0.0,
            "score": 0.0,
            "hits": 0,
            "engine": "ai",
            "provider": provider_id,
            "model": model_id or str(spec.get("default_model") or ""),
            "justification": re.sub(r"\s+", " ", str(answer))[:200],
            "parsed": "texto",
        }
    label = _clean_label(data.get("sentimento") or data.get("label") or data.get("sentiment"))
    if not label:
        polarity = _clamp(data.get("polaridade") or data.get("polarity") or 0.0)
        label = sentiment_service.label_for(polarity)
    polarity = _clamp(data.get("polaridade") if data.get("polaridade") is not None else data.get("polarity"))
    return {
        "label": label,
        "polarity": round(polarity, 3),
        "score": round(polarity * 10, 2),
        "hits": 0,
        "engine": "ai",
        "provider": provider_id,
        "model": model_id or str(spec.get("default_model") or ""),
        "justification": re.sub(r"\s+", " ", str(data.get("justificacao") or data.get("justification") or ""))[:200],
    }


def analyze_item(item: Dict[str, Any], config: Dict[str, Any], *, user_id: Optional[str] = None) -> Optional[Dict[str, Any]]:
    """Classifica um item. Devolve `None` quando não há texto suficiente."""
    text = item_text(item, config)
    if not text:
        return None
    engine = config.get("engine") or "auto"
    if engine in ("ai", "auto"):
        chave = _provider_key(config.get("provider") or None, config.get("model") or None, user_id)
        if engine == "auto" and _in_cooldown(chave):
            logger.debug("Sentimento: %s em descanso; a usar o léxico local.", chave)
        else:
            try:
                result = _run_sync(
                    _ask_model(
                        text,
                        title=str(item.get("title") or ""),
                        provider=config.get("provider") or None,
                        model=config.get("model") or None,
                        user_id=user_id,
                    )
                )
                _register_success(chave)
                result["chars"] = len(text)
                result["analyzed_at"] = _now()
                if engine == "auto":
                    result["fallback"] = False
                return result
            except Exception as exc:
                _register_failure(chave)
                logger.info("Sentimento por IA indisponível (%s); a usar o léxico local.", exc)
                if engine == "ai":
                    # O modelo era obrigatório: não se inventa um resultado com outro motor.
                    return {
                        "label": "",
                        "polarity": 0.0,
                        "engine": "ai",
                        "provider": config.get("provider") or "",
                        "model": config.get("model") or "",
                        "error": f"{type(exc).__name__}: {exc}"[:300],
                        "chars": len(text),
                        "analyzed_at": _now(),
                    }
    result = analyze_lexicon(text)
    result["chars"] = len(text)
    result["analyzed_at"] = _now()
    if engine == "auto":
        result["fallback"] = True
    return result


def analyze_items(
    items: List[Dict[str, Any]],
    config: Dict[str, Any],
    *,
    user_id: Optional[str] = None,
    limit: Optional[int] = None,
) -> Dict[str, int]:
    """Classifica uma lista de itens (até `limit`) e escreve `item['sentiment']`."""
    if not config.get("enabled"):
        return {"sentiment_count": 0, "sentiment_errors": 0, "sentiment_skipped": 0}
    cap = int(config.get("max_items") or 0) if limit is None else int(limit)
    counters = {"sentiment_count": 0, "sentiment_errors": 0, "sentiment_skipped": 0}
    for item in items:
        if cap and counters["sentiment_count"] + counters["sentiment_errors"] >= cap:
            break
        result = analyze_item(item, config, user_id=user_id)
        if result is None:
            counters["sentiment_skipped"] += 1
            continue
        if not result.get("label"):
            counters["sentiment_errors"] += 1
            item["sentiment"] = result
            continue
        item["sentiment"] = result
        counters["sentiment_count"] += 1
    return counters


# ------------------------------------------------------------------- resumo
def summarize(rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Resumo do sentimento de vários itens (usado no painel da pesquisa).

    A polaridade média conta apenas os itens classificados — e reporta a
    cobertura, para um conjunto em que quase nada foi analisado não aparecer
    como «neutro» por diluição dos zeros.
    """
    counts = {label: 0 for label in LABELS}
    polarities: List[float] = []
    for row in rows or []:
        label = str(row.get("sentiment") or "").strip().lower()
        score = row.get("sentiment_score")
        if isinstance(score, (int, float)):
            polarities.append(float(score))
        if label in counts:
            counts[label] += 1
    analyzed = sum(counts.values())
    media = round(sum(polarities) / len(polarities), 3) if polarities else 0.0
    total = len(rows or [])
    return {
        **counts,
        "analyzed": analyzed,
        "total": total,
        "polarity": media,
        "label": sentiment_service.label_for(media) if analyzed else "sem dados",
        "coverage": round(analyzed / total, 3) if total else 0.0,
    }
