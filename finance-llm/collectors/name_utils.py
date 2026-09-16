"""Utilitários para derivar termos de pesquisa a partir de nomes de empresas.

Os serviços públicos (INPI para marcas, RNPC/PNS para firmas) usam pesquisas por
semelhança que falham com pontuação e com sufixos societários: por exemplo,
``"CEGID-PRIMAVERA - BUSINESS SOFTWARE SOLUTIONS, SA"`` devolve 0 resultados,
enquanto ``"PRIMAVERA BUSINESS SOFTWARE SOLUTIONS"`` devolve 29.

Este módulo gera uma lista ordenada de candidatos, do mais específico para o mais
genérico, para que o enriquecimento tente alternativas até encontrar resultados.
"""
from __future__ import annotations

import difflib
import re
from typing import Any, Dict, List

# SuFixos societários e formas jurídicas que atrapalham a pesquisa por semelhança.
LEGAL_SUFFIXES = {
    "SA", "S A", "LDA", "LDA", "UNIPESSOAL", "EPE", "E P E", "SGPS", "SGPS SA",
    "LIMITADA", "LTD", "SRL", "SL", "GMBH", "NV", "BV", "AG", "INC", "CORP",
    "SOCIEDADE ANONIMA", "SOCIEDADE POR QUOTAS", "SOCIEDADE UNIPESSOAL",
    "EM NOME INDIVIDUAL", "ENI", "ACE", "CRL", "COOPERATIVA",
}

# Palavras demasiado genéricas para servirem de termo de pesquisa isolado.
STOPWORDS = {"DE", "DA", "DO", "DAS", "DOS", "E", "EM", "A", "O", "OS", "AS", "PARA", "POR"}

_PUNCT_RE = re.compile(r"[^\w\s]", re.UNICODE)
_WS_RE = re.compile(r"\s+")


def clean_name(name: str) -> str:
    """Remove pontuação e normaliza espaços: ``"A-B, S.A."`` -> ``"A B S A"``."""
    if not name:
        return ""
    text = _PUNCT_RE.sub(" ", str(name))
    text = _WS_RE.sub(" ", text)
    return text.strip().upper()


def strip_legal_suffixes(cleaned: str) -> str:
    """Remove sufixos societários do fim do nome (``... LDA``, ``... S A``)."""
    tokens = cleaned.split()
    while tokens and tokens[-1] in LEGAL_SUFFIXES:
        tokens.pop()
    return " ".join(tokens)


def name_search_candidates(name: str, min_words: int = 2) -> List[str]:
    """Devolve termos de pesquisa por ordem de prioridade (sem duplicados).

    Exemplo para ``"CEGID-PRIMAVERA - BUSINESS SOFTWARE SOLUTIONS, SA"``::

        ["CEGID PRIMAVERA BUSINESS SOFTWARE SOLUTIONS",
         "CEGID PRIMAVERA BUSINESS SOFTWARE SOLUTIONS, SA",  (limpo)
         "CEGID PRIMAVERA BUSINESS SOFTWARE",
         "CEGID PRIMAVERA",
         "PRIMAVERA"]

    O último candidato recorre ao token mais distintivo, útil quando a razão
    social completa não devolve resultados.
    """
    if not name or not str(name).strip():
        return []

    raw = str(name).strip()
    cleaned = clean_name(raw)
    stripped = strip_legal_suffixes(cleaned)

    candidates: List[str] = []
    for term in (stripped, cleaned, raw.strip()):
        if term and term not in candidates:
            candidates.append(term)

    # Prefixos progressivamente mais curtos (mantendo min_words palavras).
    words = stripped.split()
    for end in range(len(words) - 1, min_words - 1, -1):
        term = " ".join(words[:end])
        if term and term not in candidates:
            candidates.append(term)

    # Tokens individuais distintivos (do maior para o menor).
    distinctive = sorted(
        (w for w in words if w not in STOPWORDS and len(w) >= 4),
        key=len,
        reverse=True,
    )
    for token in distinctive:
        if token not in candidates:
            candidates.append(token)

    return candidates


def name_similarity(a: str, b: str) -> float:
    """Semelhança entre dois nomes de empresa, entre 0 e 1.

    Combina a sobreposição de palavras (Jaccard) com a razão de sequência, dando
    peso extra a um nome contido no outro. Serve para distinguir, por exemplo,
    ``"PRIMAVERA SOFTWARE BUSINESS SOLUTIONS"`` de ``"CAVES PRIMAVERA"`` quando a
    pesquisa pública teve de recorrer a um termo genérico.
    """
    ca = strip_legal_suffixes(clean_name(a))
    cb = strip_legal_suffixes(clean_name(b))
    if not ca or not cb:
        return 0.0
    if ca == cb:
        return 1.0
    if ca in cb or cb in ca:
        return 0.9

    ta, tb = set(ca.split()), set(cb.split())
    jaccard = len(ta & tb) / max(1, len(ta | tb))
    ratio = difflib.SequenceMatcher(None, ca, cb).ratio()
    # Se só partilham uma palavra, vale mais a razão de sequência do que Jaccard.
    return max(ratio, jaccard)


def rank_items_by_similarity(
    items: List[Dict[str, Any]],
    reference_name: str,
    key: str,
    similarity_field: str = "name_similarity",
    min_keep: int = 3,
    threshold: float = 0.45,
) -> List[Dict[str, Any]]:
    """Anota cada item com a semelhança do seu nome face a ``reference_name``.

    Ordena por semelhança decrescente. Se existirem pelo menos ``min_keep`` itens
    acima de ``threshold``, os restantes são descartados (evita guardar marcas ou
    firmas de empresas diferentes só porque partilham uma palavra).
    """
    scored: List[Dict[str, Any]] = []
    for item in items:
        value = item.get(key) or item.get("nome") or item.get("name") or ""
        enriched = dict(item)
        enriched[similarity_field] = round(name_similarity(reference_name, str(value)), 4)
        scored.append(enriched)

    scored.sort(key=lambda it: it.get(similarity_field, 0.0), reverse=True)

    strong = [it for it in scored if it.get(similarity_field, 0.0) >= threshold]
    if len(strong) >= min_keep:
        return strong
    return scored
