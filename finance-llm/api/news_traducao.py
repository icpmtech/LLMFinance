"""Tradução PT das **notícias**, com o fornecedor de IA configurado na plataforma.

As notícias do índice `finance_news` chegam quase sempre em inglês (o Yahoo
devolve o original) e é o NLP da recolha que as traduz — mas só quando a recolha
passou por um ticker, e sempre a pagar segundos do modelo local em CPU. Quando o
editor está a olhar para uma notícia e quer **publicá-la no blog**, o caminho
curto é traduzi-la a pedido, pelo fornecedor de IA que a solução já tem
configurado (Definições → Fornecedores de IA).

O que se reutiliza e o que é próprio deste módulo:

- **A maquinaria dos lotes** (JSON tolerante, ciclo de eventos) é a mesma das
  manchetes do mercado — `api.manchetes_traducao._traduzir_lote` —, para não
  haver duas implementações do mesmo truque;
- **O prompt é próprio**: aqui traduzem-se títulos **e** resumos de notícias, com
  a regra de manter nomes, números, percentagens e tickers intactos;
- **A cache é própria** (`data/news/traducoes-pt.json`): a mesma notícia não volta
  a ser traduzida entre reinícios, e as manchetes do mercado não se misturam com
  o texto das notícias;
- **Sem fornecedor configurado devolve erro explícito** (nunca inglês a passar por
  tradução) — quem chama mostra-o em vez de guardar texto enganador.
"""
from __future__ import annotations

import json
import logging
import threading
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional

from api.manchetes_traducao import _extrair_array, _lotes, _normalizar, _traduzir_lote

logger = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parents[1]
CACHE_PATH = ROOT / "data" / "news" / "traducoes-pt.json"

#: Quantos textos vão num pedido ao modelo. Cada notícia são dois (título e
#: resumo), por isso um lote de 8 é meia dúzia de notícias.
MAX_ITENS = 8
MAX_CHARS = 6000
#: Tamanho máximo da cache (as entradas mais antigas saem primeiro).
MAX_CACHE = 20000

_lock = threading.Lock()
_cache: Optional[Dict[str, str]] = None

PROMPT = (
    "És um tradutor de notícias de economia e finanças. Traduz para português europeu cada "
    "um dos textos do array JSON que recebes (a maioria está em inglês). Alguns são títulos, "
    "outros são resumos — traduz todos da mesma maneira.\n"
    "Regras:\n"
    "- mantém tickers e símbolos (AAPL, EDP.LS, ^GSPC), nomes de empresas, de pessoas e de "
    "instituições, números, percentagens, valores, datas e unidades;\n"
    "- usa a terminologia económica em português (earnings = resultados, shares = ações, "
    "revenue = receita, guidance = estimativas da empresa, buyback = recompra de ações, "
    "contract award = adjudicação);\n"
    "- não acrescentes explicações, aspas nem o texto original;\n"
    "- se um texto já estiver em português europeu, devolve-o exatamente como está;\n"
    "- devolve APENAS um array JSON de strings, com exatamente o mesmo número de elementos e "
    "a mesma ordem da entrada.\n"
)


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
    except Exception as exc:  # cache ilegível não pode impedir a tradução
        logger.warning("Cache de tradução de notícias ilegível (%s); a recomeçar.", exc)
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
        logger.warning("Não foi possível gravar a cache de tradução de notícias: %s", exc)


def cache_status() -> Dict[str, Any]:
    with _lock:
        cache = _carregar_cache()
        return {"cached": len(cache), "path": str(CACHE_PATH)}


def _unicos(textos: List[str]) -> List[str]:
    """Textos úteis, sem repetições (o título pode repetir-se no resumo)."""
    unicos: List[str] = []
    vistos = set()
    for texto in textos or []:
        limpo = _normalizar(str(texto))
        if limpo and limpo not in vistos:
            vistos.add(limpo)
            unicos.append(limpo)
    return unicos


def traduzir_textos(
    textos: List[str],
    *,
    user_id: Optional[str] = None,
    provider: Optional[str] = None,
    model: Optional[str] = None,
) -> Dict[str, Any]:
    """Traduz textos para PT (cache primeiro) e devolve o mapa original→tradução.

    Devolve `{"error": …}` quando não há fornecedor de IA configurado: é melhor
    dizer que não deu do que devolver o original a passar por tradução.
    """
    unicos = _unicos(textos)
    if not unicos:
        return {"translations": {}, "requested": 0, "cached": 0, "status": cache_status()}

    with _lock:
        cache = _carregar_cache()

    por_traduzir = [texto for texto in unicos if texto not in cache]
    resultado: Dict[str, str] = {texto: cache[texto] for texto in unicos if texto in cache}
    em_cache = len(unicos) - len(por_traduzir)

    if not por_traduzir:
        return {
            "translations": resultado,
            "requested": len(unicos),
            "cached": em_cache,
            "translated": 0,
            "unchanged": 0,
            "failed": 0,
            "ai": {},
            "status": cache_status(),
        }

    from api.scraper_ai import pick_provider

    provider_id, spec, model_id, api_key = pick_provider(user_id, provider, model)
    if not provider_id or not spec:
        return {
            "error": (
                "Nenhum fornecedor de IA configurado. Defina uma chave em Definições → "
                "Fornecedores de IA para traduzir as notícias."
            ),
            "translations": resultado,
            "requested": len(unicos),
            "cached": em_cache,
            "status": cache_status(),
        }

    info_ia: Dict[str, Any] = {
        "provider": provider_id,
        "provider_label": spec.get("label") or provider_id,
        "model": model_id or spec.get("default_model"),
    }
    for lote in _lotes(por_traduzir, MAX_ITENS, MAX_CHARS):
        traduzidos = _traduzir_lote(
            lote, provider_id=provider_id, spec=spec, model_id=model_id, api_key=api_key, prompt=PROMPT
        )
        if traduzidos is None:
            continue  # lote falhado: fica fora da cache e repete-se no pedido seguinte
        for original, traduzido in zip(lote, traduzidos):
            limpo = _normalizar(traduzido)
            if limpo:
                # Mesmo quando o texto já estava em português fica na cache: é o
                # que evita voltar a pagar uma tradução para o mesmo texto.
                resultado[original] = limpo

    with _lock:
        adicionados = 0
        for texto in por_traduzir:
            if texto in resultado and cache.get(texto) != resultado[texto]:
                cache[texto] = resultado[texto]
                adicionados += 1
        if adicionados:  # sem nada de novo não se toca no ficheiro
            if len(cache) > MAX_CACHE:
                for chave in list(cache)[: len(cache) - MAX_CACHE]:
                    cache.pop(chave, None)
            _gravar_cache()

    novos = [texto for texto in por_traduzir if texto in resultado]
    inalterados = len([texto for texto in novos if resultado.get(texto) == texto])
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


def traduzir_noticia(
    noticia: Dict[str, Any],
    *,
    user_id: Optional[str] = None,
    provider: Optional[str] = None,
    model: Optional[str] = None,
) -> Dict[str, Any]:
    """Traduz o título e o resumo de uma notícia (PT) com o fornecedor configurado.

    O que já estiver traduzido não volta ao modelo: se a notícia traz
    `translated_title`/`summary_pt` (do NLP da recolha), é isso que se devolve e só
    o que falta é traduzido. Devolve `{"error": …}` quando não há fornecedor
    configurado, mantendo o texto original — quem chama decide o que mostrar.
    """
    original_titulo = str(noticia.get("title") or "").strip()
    original_resumo = str(noticia.get("summary") or "").strip()
    titulo_pt = str(noticia.get("translated_title") or "").strip()
    resumo_pt = str(noticia.get("summary_pt") or noticia.get("translated_summary") or "").strip()

    resultado: Dict[str, Any] = {
        "titulo": titulo_pt or original_titulo,
        "resumo": resumo_pt or original_resumo,
        "original_titulo": original_titulo,
        "original_resumo": original_resumo,
        "traduzido": bool(titulo_pt or resumo_pt),
        "status": cache_status(),
    }

    faltas: List[str] = []
    if not titulo_pt and original_titulo:
        faltas.append(original_titulo)
    if not resumo_pt and original_resumo:
        faltas.append(original_resumo)
    if not faltas:
        return resultado

    traducao = traduzir_textos(faltas, user_id=user_id, provider=provider, model=model)
    if traducao.get("error"):
        return {**resultado, "error": traducao["error"]}
    mapa = traducao.get("translations") or {}
    resultado["titulo"] = mapa.get(original_titulo) or resultado["titulo"]
    resultado["resumo"] = mapa.get(original_resumo) or resultado["resumo"]
    resultado["ia"] = traducao.get("ai") or {}
    resultado["traduzido"] = bool(titulo_pt or resumo_pt) or any(
        mapa.get(texto) not in (None, texto) for texto in faltas
    )
    resultado["status"] = traducao.get("status") or resultado["status"]
    return resultado
