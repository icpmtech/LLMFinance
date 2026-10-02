"""Tradução FR → PT dos textos dos contratos de França, com IA.

Os contratos do DECP (Données Essentielles de la Commande Publique) estão em
francês: o objeto, a natureza, o procedimento, a forma de preço e o tipo de local.
Esta página permite lê-los em português, **a pedido** (a tradução custa tempo e
dinheiro), usando o fornecedor de IA configurado na plataforma
(Definições → Fornecedores de IA).

Decisões que interessam:

- **Cache persistente** (`data/contratos-franca/traducao-pt.json`): o mesmo texto
  francês só é traduzido uma vez, mesmo entre reinícios do servidor. A chave é o
  texto original normalizado; a cache é gravada de forma atómica.
- **Lotes**: um pedido ao modelo leva até `MAX_ITENS` textos (ou `MAX_CHARS`),
  sempre com a instrução de devolver **só** um array JSON na mesma ordem. Falhas
  de análise ficam registadas e os textos respetivos voltam no original.
- **Nunca inventar**: se não houver fornecedor de IA configurado, a função
  devolve um erro explícito (a página mostra-o) em vez de devolver texto francês
  como se fosse traduzido.
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
CACHE_PATH = ROOT / "data" / "contratos-franca" / "traducao-pt.json"

#: Quantos textos vão num pedido ao modelo (o objeto de um contrato pode ser
#: longo; o limite de caracteres protege o contexto).
MAX_ITENS = 15
MAX_CHARS = 6000
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
        logger.warning("Cache de tradução ilegível (%s); a recomeçar.", exc)
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
        logger.warning("Não foi possível gravar a cache de tradução: %s", exc)


def _normalizar(texto: str) -> str:
    return re.sub(r"\s+", " ", (texto or "")).strip()


def cache_status() -> Dict[str, Any]:
    with _lock:
        cache = _carregar_cache()
        return {"cached": len(cache), "path": str(CACHE_PATH)}


PROMPT = (
    "És um tradutor técnico de contratação pública. Traduz do francês para português europeu "
    "cada um dos textos do array JSON que recebes.\n"
    "Regras:\n"
    "- mantém siglas, códigos (CPV, SIRET, códigos postais), números, datas e nomes próprios;\n"
    "- usa a terminologia de contratação pública portuguesa (marché public = contrato público, "
    "acheteur = entidade adjudicante, titulaire = adjudicatário, lot = lote, montant = valor);\n"
    "- não acrescentes explicações;\n"
    "- devolve APENAS um array JSON de strings, com exatamente o mesmo número de elementos e a "
    "mesma ordem da entrada.\n"
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
) -> List[str]:
    """Traduz um lote; devolve sempre o mesmo número de textos (original em caso de falha)."""
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
            max_tokens=min(4000, 400 + 6 * sum(len(t) for t in lote)),
        )

    try:
        try:
            resposta = asyncio.run(correr())
        except RuntimeError:
            # Já existe um ciclo de eventos (rota async): corre num ciclo próprio.
            import concurrent.futures

            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
                resposta = pool.submit(lambda: asyncio.run(correr())).result(timeout=180)
    except Exception as exc:
        logger.warning("Tradução falhou (%s): %s", provider_id, exc)
        return list(lote)

    traduzidos = _extrair_array(resposta)
    if not traduzidos or len(traduzidos) != len(lote):
        logger.warning(
            "Resposta de tradução inutilizável (esperados %d, obtidos %s)",
            len(lote),
            len(traduzidos) if traduzidos else "0",
        )
        return list(lote)
    return traduzidos


def translate_texts(
    texts: List[str],
    *,
    user_id: Optional[str] = None,
    provider: Optional[str] = None,
    model: Optional[str] = None,
) -> Dict[str, Any]:
    """Traduz os textos FR→PT (cache primeiro) e devolve o mapa original→tradução."""
    pedidos = [_normalizar(texto) for texto in texts or []]
    pedidos = [texto for texto in pedidos if texto]
    unicos: List[str] = []
    vistos = set()
    for texto in pedidos:
        if texto not in vistos:
            vistos.add(texto)
            unicos.append(texto)

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
                    "Definições → Fornecedores de IA para traduzir os contratos."
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
            for original, traduzido in zip(lote, traduzidos):
                limpo = _normalizar(traduzido)
                if limpo and limpo != original:
                    resultado[original] = limpo
        with _lock:
            cache.update(resultado)
            if len(cache) > MAX_CACHE:
                for chave in list(cache)[: len(cache) - MAX_CACHE]:
                    cache.pop(chave, None)
            _gravar_cache()

    novos = [texto for texto in por_traduzir if texto in resultado]
    return {
        "translations": resultado,
        "requested": len(unicos),
        "cached": em_cache,
        "translated": len(novos),
        "failed": len(por_traduzir) - len(novos),
        "ai": info_ia,
        "status": cache_status(),
    }
