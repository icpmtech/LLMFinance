"""Tradução PT das manchetes do mercado, **com IA**.

As manchetes que o Yahoo devolve para os tickers seguidos estão quase sempre em
inglês. O tom lê-se sobre o original (léxico PT e, quando ele não reconhece nada,
o léxico bilingue PT/EN) — mas **ler o que a manchete diz** exige tradução, e o
modelo local (Helsinki) que o `translate=1` do panorama em direto usa custa
segundos por título em CPU. Aqui a tradução é feita **a pedido** pelo fornecedor
de IA configurado na plataforma (Definições → Fornecedores de IA), em lote.

Decisões que interessam:

- **Cache persistente** (`data/sentiment_market/manchetes-pt.json`): a mesma
  manchete só é traduzida uma vez, mesmo entre reinícios do servidor — reabrir o
  painel não volta a pagar a tradução.
- **Lotes**: um pedido ao modelo leva até `MAX_ITENS` manchetes (ou `MAX_CHARS`),
  sempre com a instrução de devolver **só** um array JSON na mesma ordem.
- **Manchetes já em português**: o modelo devolve-as tal como estão; ficam
  contadas em `unchanged` e guardadas na cache, para não voltar a ser enviadas.
- **Nunca inventar**: sem fornecedor de IA configurado a função devolve um erro
  explícito (o painel mostra-o) em vez de devolver inglês como se fosse tradução.
"""
from __future__ import annotations

import json
import logging
import re
import threading
import uuid
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

logger = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parents[1]
CACHE_PATH = ROOT / "data" / "sentiment_market" / "manchetes-pt.json"

#: Quantas manchetes vão num pedido ao modelo (são curtas; o limite de caracteres
#: existe para uma manchete anormalmente longa não sozinha encher o contexto).
MAX_ITENS = 20
MAX_CHARS = 4000
MAX_CACHE = 20000

_lock = threading.Lock()
_cache: Optional[Dict[str, str]] = None


def _carregar_cache() -> Dict[str, str]:
    global _cache
    if _cache is not None:
        return _cache
    try:
        if CACHE_PATH.is_file():
            dados = json.loads(CACHE_PATH.read_text(encoding="utf-8"))
            _cache = {str(k): str(v) for k, v in dados.items()} if isinstance(dados, dict) else {}
        else:
            _cache = {}
    except Exception as exc:  # cache corrompida não pode impedir a tradução
        logger.warning("Cache de tradução de manchetes ilegível (%s); a recomeçar.", exc)
        _cache = {}
    return _cache


def _gravar_cache() -> None:
    if _cache is None:
        return
    try:
        CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
        temporario = CACHE_PATH.with_suffix(f".{uuid.uuid4().hex}.tmp")
        temporario.write_text(json.dumps(_cache, ensure_ascii=False, indent=0), encoding="utf-8")
        temporario.replace(CACHE_PATH)
    except Exception as exc:  # pragma: no cover - disco cheio/permissões
        logger.warning("Não foi possível gravar a cache de tradução de manchetes: %s", exc)


def _normalizar(texto: str) -> str:
    return re.sub(r"\s+", " ", (texto or "")).strip()


def cache_status() -> Dict[str, Any]:
    with _lock:
        cache = _carregar_cache()
        return {"cached": len(cache), "path": str(CACHE_PATH)}


PROMPT = (
    "És um tradutor de notícias financeiras. Traduz para português europeu cada uma das "
    "manchetes do array JSON que recebes (a maioria está em inglês).\n"
    "Regras:\n"
    "- mantém tickers e símbolos (AAPL, EDP.LS, ^GSPC), nomes de empresas, de pessoas e de "
    "instituições, números, percentagens, datas e unidades;\n"
    "- usa a terminologia de mercado em português (earnings = resultados, shares = ações, "
    "revenue = receita, guidance = estimativas da empresa, buyback = recompra de ações);\n"
    "- se uma manchete já estiver em português europeu, devolve-a exatamente como está;\n"
    "- não acrescentes explicações nem aspas;\n"
    "- devolve APENAS um array JSON de strings, com exatamente o mesmo número de elementos e "
    "a mesma ordem da entrada.\n"
)


def _extrair_array(resposta: str) -> Optional[List[str]]:
    """Lê o array JSON da resposta do modelo (tolera cercas de código e texto à volta)."""
    texto = (resposta or "").strip()
    if not texto:
        return None
    texto = re.sub(r"^```(?:json)?|```$", "", texto, flags=re.MULTILINE).strip()
    candidatos: List[str] = [texto]
    inicio = texto.find("[")
    fim = texto.rfind("]")
    if inicio >= 0 and fim > inicio:
        candidatos.append(texto[inicio : fim + 1])
    for candidato in candidatos:
        try:
            dados = json.loads(candidato)
        except json.JSONDecodeError:
            continue
        if isinstance(dados, list):
            return [str(item) for item in dados]
    return None


def _lotes(textos: List[str]) -> Iterable[List[str]]:
    lote: List[str] = []
    tamanho = 0
    for texto in textos:
        if lote and (len(lote) >= MAX_ITENS or tamanho + len(texto) > MAX_CHARS):
            yield lote
            lote, tamanho = [], 0
        lote.append(texto)
        tamanho += len(texto)
    if lote:
        yield lote


def _traduzir_lote(
    lote: List[str],
    *,
    provider_id: str,
    spec: Dict[str, Any],
    model_id: Optional[str],
    api_key: Optional[str],
) -> Optional[List[str]]:
    """Traduz um lote; devolve `None` quando o modelo não devolveu o array esperado."""
    import asyncio

    from api import cloud_chat

    mensagens = [
        {"role": "system", "content": PROMPT},
        {"role": "user", "content": json.dumps(lote, ensure_ascii=False)},
    ]

    async def correr() -> str:
        return await cloud_chat.complete_answer(
            provider=provider_id,
            spec=spec,
            model=model_id or spec.get("default_model") or "",
            messages=mensagens,
            api_key=api_key,
            temperature=0.0,
            max_tokens=min(4000, 300 + 6 * sum(len(t) for t in lote)),
        )

    try:
        try:
            resposta = asyncio.run(correr())
        except RuntimeError:
            # Já existe um ciclo de eventos (chamada a partir de código async):
            # corre num ciclo próprio.
            import concurrent.futures

            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
                resposta = pool.submit(lambda: asyncio.run(correr())).result(timeout=180)
    except Exception as exc:
        logger.warning("Tradução das manchetes falhou (%s): %s", provider_id, exc)
        return None

    traduzidos = _extrair_array(resposta)
    if not traduzidos or len(traduzidos) != len(lote):
        logger.warning(
            "Resposta de tradução inutilizável (esperadas %d manchetes, obtidas %s)",
            len(lote),
            len(traduzidos) if traduzidos else "0",
        )
        return None
    return traduzidos


def _unicos(textos: List[str]) -> List[str]:
    unicos: List[str] = []
    vistos = set()
    for texto in textos or []:
        limpo = _normalizar(str(texto))
        if limpo and limpo not in vistos:
            vistos.add(limpo)
            unicos.append(limpo)
    return unicos


def traduzir_manchetes(
    texts: List[str],
    *,
    user_id: Optional[str] = None,
    provider: Optional[str] = None,
    model: Optional[str] = None,
) -> Dict[str, Any]:
    """Traduz manchetes para PT (cache primeiro) e devolve o mapa original→tradução.

    Cada original aparece no mapa mesmo quando o modelo o devolveu inalterado (já
    estava em português); o painel só mostra uma segunda linha quando a tradução
    é diferente do original.
    """
    unicos = _unicos(texts)

    with _lock:
        cache = _carregar_cache()

    por_traduzir = [texto for texto in unicos if texto not in cache]
    em_cache = len(unicos) - len(por_traduzir)
    resultado: Dict[str, str] = {texto: cache[texto] for texto in unicos if texto in cache}

    info_ia: Dict[str, Any] = {}
    if por_traduzir:
        from api.scraper_ai import pick_provider

        provider_id, spec, model_id, api_key = pick_provider(user_id, provider, model)
        if not provider_id or not spec:
            return {
                "error": (
                    "Nenhum fornecedor de IA configurado. Defina uma chave em "
                    "Definições → Fornecedores de IA para traduzir as manchetes."
                ),
                "translations": resultado,
                "requested": len(unicos),
                "cached": em_cache,
            }
        info_ia = {
            "provider": provider_id,
            "provider_label": spec.get("label") or provider_id,
            "model": model_id or spec.get("default_model"),
        }
        for lote in _lotes(por_traduzir):
            traduzidos = _traduzir_lote(
                lote, provider_id=provider_id, spec=spec, model_id=model_id, api_key=api_key
            )
            if traduzidos is None:
                continue  # lote por traduzir: fica fora da cache e repete-se depois
            for original, traduzido in zip(lote, traduzidos):
                limpo = _normalizar(traduzido)
                if limpo:
                    resultado[original] = limpo
        with _lock:
            adicionados = 0
            for texto in por_traduzir:
                if texto in resultado and cache.get(texto) != resultado[texto]:
                    cache[texto] = resultado[texto]
                    adicionados += 1
            if adicionados:  # sem nada de novo não se toca no ficheiro
                if len(cache) > MAX_CACHE:  # as mais antigas saem primeiro
                    for chave in list(cache)[: len(cache) - MAX_CACHE]:
                        cache.pop(chave, None)
                _gravar_cache()

    novos = [texto for texto in por_traduzir if texto in resultado]
    inalterados = len([texto for texto in novos if resultado[texto] == texto])
    return {
        "translations": resultado,
        "requested": len(unicos),
        "cached": em_cache,
        "translated": len(novos) - inalterados,
        "unchanged": inalterados,
        "failed": len(por_traduzir) - len(novos),
        "ai": info_ia,
        "status": cache_status(),
    }
