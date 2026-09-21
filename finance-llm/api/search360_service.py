"""Serviço do meta-modelo de pesquisa 360.

Junta quatro ideias numa só resposta:

1. **Federação** — o tema é pesquisado em paralelo em todas as fontes ligadas
   (plataforma, documentos, Wikipédia, Wikidata, Banco Mundial, dados.gov.pt,
   OpenAlex, Crossref, web) e os resultados são normalizados, deduplicados e
   facetados.
2. **Metamodelo** — cada fonte é descrita (família, capacidades, ícone, custo,
   confiança) e o plano de pesquisa explica *porque* cada fonte foi usada.
3. **Analítica 360** — o dossiê de um tema reúne entidades internas, entidades
   canónicas (Wikidata), artigos, conjuntos de dados, séries de indicadores,
   documentos, ficheiros e uma síntese com citações.
4. **Grafo e biblioteca** — o mesmo material é reorganizado como grafo navegável
   (tema → entidades → fontes → documentos) e como biblioteca de pastas e
   ficheiros (uma pasta por família de fonte), com ícones por tipo.

Nada aqui inventa dados: quando uma fonte falha, o item não aparece e a falha
sai em `warnings` com o tempo gasto, para o utilizador saber o que não foi lido.
"""
from __future__ import annotations

import asyncio
import logging
import re
import threading
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Sequence, Tuple

import httpx

from api import search360_sources as sources

logger = logging.getLogger(__name__)

CACHE_TTL = 600.0
CACHE_MAX = 80
SOURCE_TIMEOUT = 30.0
MAX_NODES = 45
MAX_SYNTHESIS_EVIDENCE = 26

_cache: Dict[str, Tuple[float, Dict[str, Any]]] = {}

# Arranque a frio: a primeira ligação ao Elasticsearch (criar índices, mapear
# campos) pode levar dezenas de segundos. Aquece-se em segundo plano mal a
# aplicação abre o módulo, para que a primeira pesquisa já seja rápida.
_warm_lock = threading.Lock()
_warm_started = False


def warmup() -> None:
    """Prepara as fontes internas em segundo plano (uma vez por processo)."""
    global _warm_started
    with _warm_lock:
        if _warm_started:
            return
        _warm_started = True

    def worker() -> None:
        try:
            sources.index_overview()
            sources.internal_search("energia", limit=2)
            sources.local_files("energia", limit=3)
        except Exception as exc:  # nunca deve perturbar o arranque
            logger.info("Aquecimento do 360 falhou: %s", exc)

    import threading  # noqa: PLC0415

    threading.Thread(target=worker, name="search360-warmup", daemon=True).start()

# --------------------------------------------------------------------------
# Cache
# --------------------------------------------------------------------------
def _cache_key(kind: str, term: str, sources_ids: Sequence[str], extra: str = "") -> str:
    return f"{kind}|{term.strip().lower()}|{','.join(sorted(sources_ids))}|{extra}"


def _cache_get(key: str) -> Optional[Dict[str, Any]]:
    hit = _cache.get(key)
    if not hit:
        return None
    stamp, value = hit
    if time.time() - stamp > CACHE_TTL:
        _cache.pop(key, None)
        return None
    return value


def _cache_set(key: str, value: Dict[str, Any]) -> None:
    if len(_cache) >= CACHE_MAX:
        _cache.clear()
    _cache[key] = (time.time(), value)


def clear_cache() -> None:
    _cache.clear()


# --------------------------------------------------------------------------
# Plano de pesquisa
# --------------------------------------------------------------------------
STOPWORDS = {
    "a", "o", "as", "os", "de", "da", "do", "das", "dos", "e", "em", "no", "na", "nos", "nas", "para", "por",
    "sobre", "com", "sem", "que", "qual", "quais", "como", "onde", "quando", "um", "uma", "uns", "umas", "the",
    "of", "and", "for", "with", "on", "in", "about",
}
TICKER_RE = re.compile(r"\b([A-Z]{2,6})(?:\.(LS|PA|DE|L|MI|AS))?\b")
NIF_RE = re.compile(r"\b([1-9]\d{8})\b")


def plan(term: str, requested: Optional[Sequence[str]] = None) -> Dict[str, Any]:
    """Decide que fontes usar e o que esperar delas."""
    clean = (term or "").strip()
    words = [word for word in re.split(r"\s+", clean) if word]
    meaningful = [word for word in words if word.lower() not in STOPWORDS]
    chosen = [source_id for source_id in (requested or []) if source_id in sources.CATALOG_BY_ID]
    auto = not chosen
    # Deteção de tickers: a regex é case-sensitive. Mapeia palavras conhecidas
    # (edp, galp, bcp, etc.) antes de correr a regex para capturar variantes
    # em minúsculas.
    ticker_aliases = {
        "edp": "EDP",
        "galp": "GALP",
        "bcp": "BCP",
        "bpi": "BPI",
        "nos": "NOS",
        "sonae": "SONAE",
        "altri": "ALTR",
        "jmt": "JMT",
        "ren": "REN",
        "mota-engil": "MOTA",
    }
    clean_for_tickers = clean
    for alias, symbol in ticker_aliases.items():
        clean_for_tickers = re.sub(rf"\b{re.escape(alias)}\b", symbol, clean_for_tickers, flags=re.IGNORECASE)
    tickers = [match.group(1) for match in TICKER_RE.finditer(clean_for_tickers)]
    nifs = [match.group(1) for match in NIF_RE.finditer(clean)]
    looks_macro = any(word.lower() in {"energia", "inflação", "pib", "clima", "população", "desemprego", "economia", "mercado"} for word in meaningful)
    strategy = "entidade" if (nifs or tickers) else ("tema" if len(meaningful) <= 4 else "investigação")
    if auto:
        if strategy == "entidade":
            # Numa entidade concreta, dados de investigação e indicadores macro só poluem.
            chosen = ["internal", "documents", "wikipedia_pt", "wikidata"]
        else:
            chosen = [entry["id"] for entry in sources.CATALOG if entry.get("default")]
    steps: List[Dict[str, Any]] = []
    for source_id in chosen:
        spec = sources.CATALOG_BY_ID[source_id]
        steps.append(
            {
                "source_id": source_id,
                "label": spec["label"],
                "family": spec["family"],
                "why": _why(source_id, strategy=strategy, macro=looks_macro),
                "capabilities": spec.get("capabilities") or [],
            }
        )
    return {
        "term": clean,
        "strategy": strategy,
        "keywords": meaningful,
        "tickers": tickers,
        "nifs": nifs,
        "sources": chosen,
        "steps": steps,
        "auto": auto,
        "macro_hint": looks_macro,
    }


def _why(source_id: str, *, strategy: str, macro: bool) -> str:
    reasons = {
        "internal": "Ver o que a plataforma já sabe: entidades, contratos, notícias e recolhas.",
        "documents": "Encontrar documentos, conjuntos e ficheiros relacionados.",
        "wikipedia_pt": "Contexto enciclopédico em português e secções para navegar.",
        "wikipedia_en": "Cobertura técnica internacional do mesmo tema.",
        "wikidata": "Entidade canónica (Q-id) com identificadores e relações.",
        "worldbank": "Séries e indicadores macroeconómicos para quantificar.",
        "dadosgov": "Dados abertos nacionais: conjuntos e recursos descarregáveis.",
        "openalex": "Investigação científica com citações e áreas de estudo.",
        "crossref": "Publicações com DOI e respetivos autores.",
        "web": "Tudo o que não esteja em catálogo.",
        "ai": "Sintetizar as evidências numa resposta citada.",
    }
    base = reasons.get(source_id, "Fonte complementar.")
    if source_id == "worldbank" and not macro:
        return base + " (relevante se o tema tiver dimensão socioeconómica)"
    if strategy == "entidade" and source_id in ("wikidata", "internal"):
        return base + " (há identificadores no pedido: NIF ou ticker)"
    return base


# --------------------------------------------------------------------------
# Execução federada
# --------------------------------------------------------------------------
async def _run_external(source_id: str, term: str, limit: int) -> List[Dict[str, Any]]:
    async with sources.client() as client:
        if source_id == "wikipedia_pt":
            return await sources.wikipedia_search(client, term, lang="pt", limit=limit)
        if source_id == "wikipedia_en":
            return await sources.wikipedia_search(client, term, lang="en", limit=limit)
        if source_id == "wikidata":
            return await sources.wikidata_search(client, term, limit=limit)
        if source_id == "worldbank":
            return await sources.worldbank_search(client, term, limit=limit)
        if source_id == "dadosgov":
            return await sources.dadosgov_search(client, term, limit=limit)
        if source_id == "openalex":
            return await sources.openalex_search(client, term, limit=limit)
        if source_id == "crossref":
            return await sources.crossref_search(client, term, limit=limit)
    if source_id == "web":
        return await sources.web_search(term, limit=limit)
    return []


async def _collect(
    source_id: str,
    term: str,
    *,
    limit: int,
    scope: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    started = time.perf_counter()
    try:
        if source_id == "internal":
            payload = await asyncio.wait_for(asyncio.to_thread(sources.internal_search, term, limit=limit, scope=scope), timeout=SOURCE_TIMEOUT)
            items = [*(payload.get("entities") or []), *(payload.get("documents") or [])]
            return {
                "source_id": source_id,
                "items": items,
                "warnings": payload.get("warnings") or [],
                "ms": int((time.perf_counter() - started) * 1000),
                "extra": {"resolved": payload.get("resolved") or {}},
            }
        if source_id == "documents":
            items = await asyncio.wait_for(
                asyncio.to_thread(sources.internal_search, term, limit=limit, scope=scope), timeout=SOURCE_TIMEOUT
            )
            files = await asyncio.to_thread(sources.local_files, term, limit=limit)
            return {
                "source_id": source_id,
                "items": [*(items.get("documents") or []), *files],
                "warnings": items.get("warnings") or [],
                "ms": int((time.perf_counter() - started) * 1000),
                "extra": {},
            }
        items = await asyncio.wait_for(_run_external(source_id, term, limit), timeout=SOURCE_TIMEOUT)
        return {"source_id": source_id, "items": items, "warnings": [], "ms": int((time.perf_counter() - started) * 1000), "extra": {}}
    except asyncio.TimeoutError:
        return {"source_id": source_id, "items": [], "warnings": [f"{source_id}: não respondeu em {int(SOURCE_TIMEOUT)}s."], "ms": int(SOURCE_TIMEOUT * 1000), "extra": {}}
    except Exception as exc:  # fonte indisponível não pode derrubar a pesquisa
        logger.info("Fonte 360 %s falhou: %s", source_id, exc)
        return {"source_id": source_id, "items": [], "warnings": [f"{source_id}: {exc}"], "ms": int((time.perf_counter() - started) * 1000), "extra": {}}


def _dedupe(items: Sequence[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Remove repetições (mesmo título normalizado) mantendo a pontuação mais alta."""
    best: Dict[str, Dict[str, Any]] = {}
    for entry in items:
        key = re.sub(r"[^a-z0-9]+", "", str(entry.get("title") or "").lower())[:70]
        if not key:
            continue
        current = best.get(key)
        if current is None:
            best[key] = entry
            continue
        # Preferir o item mais completo e mais pontuado; guardar as outras fontes.
        others = set(current.get("also_in") or [])
        if entry["source_id"] != current["source_id"]:
            others.add(entry["source_id"])
        if entry.get("score", 0) > current.get("score", 0) or (entry.get("snippet") and not current.get("snippet")):
            entry["also_in"] = sorted(others)
            best[key] = entry
        else:
            current["also_in"] = sorted(others)
    return list(best.values())


def _facets(items: Sequence[Dict[str, Any]]) -> Dict[str, List[Dict[str, Any]]]:
    def count(field: str, *, flatten: bool = False) -> List[Dict[str, Any]]:
        buckets: Dict[str, int] = {}
        for entry in items:
            value = entry.get(field)
            if value is None or value == "":
                continue
            values = value if isinstance(value, list) else [value]
            for single in values:
                if single is None or single == "":
                    continue
                buckets[str(single)] = buckets.get(str(single), 0) + 1
        return [{"value": key, "count": value} for key, value in sorted(buckets.items(), key=lambda pair: -pair[1])[:12]]

    years: Dict[str, int] = {}
    for entry in items:
        match = re.search(r"(19|20)\d{2}", str(entry.get("date") or ""))
        if match:
            years[match.group(0)] = years.get(match.group(0), 0) + 1
    return {
        "source": count("source_id"),
        "family": count("source_family"),
        "kind": count("kind"),
        "badges": count("badges", flatten=True),
        "year": [{"value": key, "count": value} for key, value in sorted(years.items(), reverse=True)[:12]],
    }


async def search(
    term: str,
    *,
    sources_ids: Optional[Sequence[str]] = None,
    limit: int = 6,
    scope: Optional[Dict[str, Any]] = None,
    skip_ai: bool = False,
) -> Dict[str, Any]:
    """Pesquisa federada: devolve itens normalizados, facetas, plano e tempos."""
    clean = (term or "").strip()
    if not clean:
        return {"term": "", "items": [], "facets": {}, "plan": plan(""), "warnings": ["Escreva o que quer investigar."], "stats": {}}
    research = plan(clean, sources_ids)
    selected = [source_id for source_id in research["sources"] if skip_ai or source_id != "ai"]
    key = _cache_key("search", clean, selected, str(limit))
    cached = _cache_get(key)
    if cached:
        return {**cached, "cached": True}
    warmup()

    started = time.perf_counter()
    results = await asyncio.gather(*[_collect(source_id, clean, limit=limit, scope=scope) for source_id in selected])
    items: List[Dict[str, Any]] = []
    per_source: List[Dict[str, Any]] = []
    warnings: List[str] = []
    resolved: Dict[str, Any] = {}
    for result in results:
        source_id = result["source_id"]
        items.extend(result["items"])
        warnings.extend(result["warnings"])
        resolved = resolved or (result.get("extra") or {}).get("resolved") or {}
        per_source.append(
            {
                "source_id": source_id,
                "label": sources.CATALOG_BY_ID[source_id]["label"],
                "family": sources.CATALOG_BY_ID[source_id]["family"],
                "items": len(result["items"]),
                "ms": result["ms"],
                "ok": not result["warnings"],
            }
        )
    unique = _dedupe(items)
    unique.sort(key=lambda entry: -float(entry.get("score") or 0))
    payload = {
        "term": clean,
        "plan": research,
        "items": unique,
        "facets": _facets(unique),
        "per_source": per_source,
        "warnings": warnings,
        "entities": resolved.get("candidates") or [],
        "stats": {
            "items": len(unique),
            "sources_queried": len(selected),
            "sources_with_results": len([row for row in per_source if row["items"]]),
            "ms": int((time.perf_counter() - started) * 1000),
            "by_kind": _facets(unique)["kind"],
        },
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }
    _cache_set(key, payload)
    return payload


# --------------------------------------------------------------------------
# Biblioteca (pastas e ficheiros)
# --------------------------------------------------------------------------
FOLDER_META: Dict[str, Dict[str, str]] = {
    "internal": {"label": "Plataforma IQ OS", "icon": "database", "accent": "45,212,191"},
    "documents": {"label": "Documentos e ficheiros", "icon": "folder", "accent": "96,165,250"},
    "encyclopedia": {"label": "Enciclopédia e entidades", "icon": "book-open", "accent": "148,163,184"},
    "opendata": {"label": "Dados abertos", "icon": "archive", "accent": "251,191,36"},
    "research": {"label": "Investigação", "icon": "graduation-cap", "accent": "244,114,182"},
    "web": {"label": "Web", "icon": "globe-2", "accent": "248,113,113"},
    "ai": {"label": "Síntese de IA", "icon": "sparkles", "accent": "56,189,248"},
}


def library(payload: Dict[str, Any]) -> Dict[str, Any]:
    """Organiza os resultados como pastas (por família) com ficheiros (itens)."""
    folders: Dict[str, Dict[str, Any]] = {}
    for entry in payload.get("items") or []:
        family = entry.get("source_family") or "outra"
        meta = FOLDER_META.get(family, {"label": family.title(), "icon": "folder", "accent": "148,163,184"})
        folder = folders.setdefault(
            family,
            {"id": family, "label": meta["label"], "icon": meta["icon"], "accent": meta["accent"], "files": [], "subfolders": {}},
        )
        subfolder = entry.get("kind") or "outro"
        bucket = folder["subfolders"].setdefault(subfolder, [])
        bucket.append(
            {
                "id": entry["id"],
                "label": entry["title"],
                "kind": entry["kind"],
                "icon": entry.get("icon") or entry["kind"],
                "url": entry.get("url"),
                "date": entry.get("date"),
                "source_id": entry["source_id"],
                "snippet": entry.get("snippet"),
                "badges": entry.get("badges") or [],
            }
        )
    tree: List[Dict[str, Any]] = []
    for family, folder in folders.items():
        subfolders = [
            {"id": f"{family}:{kind}", "label": kind_label(kind), "kind": kind, "files": files}
            for kind, files in sorted(folder["subfolders"].items(), key=lambda pair: -len(pair[1]))
        ]
        tree.append(
            {
                "id": family,
                "label": folder["label"],
                "icon": folder["icon"],
                "accent": folder["accent"],
                "count": sum(len(sub["files"]) for sub in subfolders),
                "subfolders": subfolders,
            }
        )
    tree.sort(key=lambda folder: -int(folder["count"]))
    return {
        "term": payload.get("term"),
        "folders": tree,
        "totals": {"folders": len(tree), "files": sum(int(folder["count"]) for folder in tree)},
    }


KIND_LABELS = {
    "entity": "Entidades",
    "article": "Artigos",
    "document": "Documentos",
    "dataset": "Conjuntos de dados",
    "metric": "Indicadores",
    "news": "Notícias",
    "file": "Ficheiros",
    "topic": "Temas",
    "summary": "Sínteses",
    "outro": "Outros",
}


def kind_label(kind: str) -> str:
    return KIND_LABELS.get(kind, kind.title())


# --------------------------------------------------------------------------
# Grafo de navegação
# --------------------------------------------------------------------------
KIND_COLORS = {
    "topic": "#38bdf8",
    "entity": "#2dd4bf",
    "article": "#94a3b8",
    "document": "#93c5fd",
    "dataset": "#fbbf24",
    "metric": "#34d399",
    "news": "#fb7185",
    "file": "#a78bfa",
    "summary": "#60a5fa",
}


def graph(payload: Dict[str, Any], *, limit: int = MAX_NODES) -> Dict[str, Any]:
    """Grafo do tema: o tema no centro, ligado a entidades, artigos, dados e documentos."""
    term = payload.get("term") or ""
    center_id = f"topic:{_slug(term)}"
    nodes: Dict[str, Dict[str, Any]] = {
        center_id: {
            "id": center_id,
            "label": term,
            "kind": "topic",
            "depth": 0,
            "value": 1,
            "color": KIND_COLORS["topic"],
            "icon": "search",
            "source_id": None,
            "url": None,
        }
    }
    edges: List[Dict[str, Any]] = []
    seen_edges: set = set()

    def add_edge(source_id: str, target_id: str, label: str, weight: float = 1.0) -> None:
        key = (source_id, target_id, label)
        if key in seen_edges:
            return
        seen_edges.add(key)
        edges.append({"source": source_id, "target": target_id, "label": label, "value": round(float(weight), 2)})

    # Entidades internas primeiro (são o que a plataforma sabe de concreto).
    ordered = sorted(
        payload.get("items") or [],
        key=lambda entry: (0 if entry.get("kind") == "entity" else 1, -float(entry.get("score") or 0)),
    )
    counts: Dict[str, int] = {}
    for entry in ordered:
        if len(nodes) >= limit:
            break
        kind = entry.get("kind") or "document"
        node_id = f"{kind}:{entry['id']}"
        if node_id in nodes:
            continue
        nodes[node_id] = {
            "id": node_id,
            "label": entry.get("title"),
            "kind": kind,
            "depth": 1,
            "value": float(entry.get("score") or 0.5),
            "color": KIND_COLORS.get(kind, "#94a3b8"),
            "icon": entry.get("icon") or kind,
            "source_id": entry.get("source_id"),
            "source_label": entry.get("source_label"),
            "url": entry.get("url"),
            "date": entry.get("date"),
            "snippet": entry.get("snippet"),
        }
        add_edge(center_id, node_id, "encontra", float(entry.get("score") or 0.5))
        counts[kind] = counts.get(kind, 0) + 1
    return {
        "term": term,
        "nodes": list(nodes.values()),
        "edges": edges,
        "legend": [{"kind": kind, "label": kind_label(kind), "count": count, "color": KIND_COLORS.get(kind, "#94a3b8")} for kind, count in sorted(counts.items(), key=lambda pair: -pair[1])],
        "totals": {"nodes": len(nodes), "edges": len(edges)},
    }


def _slug(text: str) -> str:
    from api.ontology_registry import slugify  # noqa: PLC0415

    return slugify(text or "tema", fallback="tema")


# --------------------------------------------------------------------------
# Indicadores (analítica)
# --------------------------------------------------------------------------
async def metrics(payload: Dict[str, Any], *, country: str = "PRT") -> List[Dict[str, Any]]:
    """Séries de indicadores para os conjuntos de dados encontrados (Banco Mundial)."""
    indicators = [entry for entry in (payload.get("items") or []) if entry.get("source_id") == "worldbank" and entry.get("data", {}).get("indicator")]
    series: List[Dict[str, Any]] = []
    if not indicators:
        return series
    async with sources.client() as client:
        for entry in indicators[:2]:
            indicator = entry["data"]["indicator"]
            try:
                data = await sources.worldbank_series(client, indicator, country=country)
            except Exception as exc:
                logger.info("Série %s falhou: %s", indicator, exc)
                continue
            if not data:
                continue
            series.append(
                {
                    "indicator": indicator,
                    "label": data.get("name") or entry.get("title"),
                    "country": country,
                    "points": data["points"],
                    "first": data["first"],
                    "last": data["last"],
                    "change": data["change"],
                    "change_pct": data["change_pct"],
                    "url": entry.get("url"),
                }
            )
    return series


# --------------------------------------------------------------------------
# Síntese com citações
# --------------------------------------------------------------------------
SYSTEM = (
    "És o analista do IQ OS. Escreves sínteses em português de Portugal, apenas com as evidências numeradas "
    "que te são dadas, citando sempre no formato [n]. Não inventas números, datas nem nomes; se algo não "
    "estiver nas evidências, escreves explicitamente que não foi encontrado nas fontes consultadas."
)


def _evidence(payload: Dict[str, Any]) -> List[Dict[str, Any]]:
    items = sorted(payload.get("items") or [], key=lambda entry: -float(entry.get("score") or 0))
    return items[:MAX_SYNTHESIS_EVIDENCE]


def _prompt(term: str, evidence: Sequence[Dict[str, Any]], metrics: Sequence[Dict[str, Any]]) -> str:
    lines = [f"Tema: {term}", "", "Evidências:"]
    for position, entry in enumerate(evidence, start=1):
        lines.append(
            f"[{position}] ({entry.get('source_label')} · {kind_label(entry.get('kind') or '')}"
            + (f" · {entry.get('date')}" if entry.get("date") else "")
            + f") {entry.get('title')}"
            + (f" — {entry.get('snippet')}" if entry.get("snippet") else "")
            + (f" <{entry.get('url')}>" if entry.get("url") else "")
        )
    if metrics:
        lines.append("")
        lines.append("Indicadores:")
        for entry in metrics:
            lines.append(
                f"- {entry['label']}: {entry['first']['value']:.2f} em {entry['first']['year']} → "
                f"{entry['last']['value']:.2f} em {entry['last']['year']} ({entry['change']:+.2f})"
            )
    lines.append("")
    lines.append(
        "Escreve: 1) o que é o tema em três frases; 2) o que a plataforma IQ OS já tem sobre ele "
        "(dados concretos, com citações); 3) o que as fontes abertas acrescentam (com citações); "
        "4) indicadores quantitativos, se existirem; 5) lacunas e próximos passos. "
        "Máximo 450 palavras, sem markdown, com as citações [n] no corpo do texto."
    )
    return "\n".join(lines)


def _factual_synthesis(term: str, payload: Dict[str, Any], metrics: Sequence[Dict[str, Any]]) -> str:
    """Síntese sem modelo: tudo o que se encontrou, por fonte, sem interpretação."""
    items = payload.get("items") or []
    per_source = payload.get("per_source") or []
    blocks = [f"Resumo factual de «{term}» a partir de {len(items)} itens em {len(per_source)} fontes consultadas."]
    by_kind: Dict[str, List[Dict[str, Any]]] = {}
    for entry in items:
        by_kind.setdefault(entry.get("kind") or "document", []).append(entry)
    for kind, entries in sorted(by_kind.items(), key=lambda pair: -len(pair[1])):
        titles = "; ".join(str(entry.get("title"))[:70] for entry in entries[:4])
        blocks.append(f"{kind_label(kind)} ({len(entries)}): {titles}.")
    if metrics:
        for entry in metrics:
            blocks.append(
                f"{entry['label']} ({entry['country']}): {entry['first']['value']:.2f} em {entry['first']['year']} → "
                f"{entry['last']['value']:.2f} em {entry['last']['year']}."
            )
    empty = [row["label"] for row in per_source if not row["items"]]
    if empty:
        blocks.append("Fontes sem resultados: " + ", ".join(empty) + ".")
    blocks.append("Texto montado sem modelo de IA: apenas contagens e títulos, tal como devolvidos pelas fontes.")
    return "\n\n".join(blocks)


async def synthesis(
    term: str,
    payload: Dict[str, Any],
    *,
    session: Any = None,
    backend: Optional[str] = None,
    metrics: Optional[Sequence[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    """Síntese do tema com citações (IA quando configurada, factual caso contrário)."""
    from api import ontology_ai as ai  # noqa: PLC0415

    evidence = _evidence(payload)
    metrics = list(metrics or [])
    result: Dict[str, Any] = {
        "term": term,
        "evidence": [
            {"n": index, "title": entry.get("title"), "source": entry.get("source_label"), "url": entry.get("url"), "date": entry.get("date"), "kind": entry.get("kind")}
            for index, entry in enumerate(evidence, start=1)
        ],
        "notes": [],
        "warnings": [],
    }
    chosen = ai.available_backend(session, backend)
    result["backend"] = {"kind": chosen["kind"], "provider": chosen.get("provider"), "model": chosen.get("model")}
    if not evidence:
        result["text"] = f"Não foram encontradas evidências sobre «{term}» nas fontes consultadas."
        result["mode"] = "empty"
        return result
    if chosen["kind"] == "cloud":
        try:
            text = await ai.ask_model(
                chosen,
                system=SYSTEM,
                prompt=_prompt(term, evidence, metrics),
                max_tokens=1600,
                temperature=0.2,
            )
            if text:
                result["text"] = text
                result["mode"] = "ai"
                result["notes"].append(f"Síntese redigida por {chosen.get('provider')}:{chosen.get('model')}.")
                return result
        except Exception as exc:
            logger.info("Síntese 360 falhou: %s", exc)
            result["warnings"].append(f"IA indisponível ({exc}); síntese factual.")
    elif chosen["kind"] == "unavailable":
        result["notes"].append(chosen.get("note") or "Sem chave de API: síntese factual.")
    else:
        result["notes"].append("Sem modelo configurado: síntese factual a partir das fontes.")
    result["text"] = _factual_synthesis(term, payload, metrics)
    result["mode"] = "factual"
    return result


# --------------------------------------------------------------------------
# Dossiê 360
# --------------------------------------------------------------------------
async def topic(
    term: str,
    *,
    sources_ids: Optional[Sequence[str]] = None,
    limit: int = 6,
    scope: Optional[Dict[str, Any]] = None,
    session: Any = None,
    backend: Optional[str] = None,
    country: str = "PRT",
    with_synthesis: bool = True,
) -> Dict[str, Any]:
    """Dossiê completo de um tema: pesquisa + biblioteca + grafo + indicadores + síntese."""
    clean = (term or "").strip()
    key = _cache_key("topic", clean, [source_id for source_id in (sources_ids or ["auto"])], f"{limit}|{country}|{with_synthesis}")
    cached = _cache_get(key)
    if cached:
        return {**cached, "cached": True}
    payload = await search(clean, sources_ids=sources_ids, limit=limit, scope=scope, skip_ai=True)
    series = await metrics(payload, country=country)
    dossier: Dict[str, Any] = {
        "term": clean,
        "plan": payload.get("plan"),
        "items": payload.get("items"),
        "facets": payload.get("facets"),
        "per_source": payload.get("per_source"),
        "warnings": payload.get("warnings"),
        "stats": payload.get("stats"),
        "library": library(payload),
        "graph": graph(payload),
        "metrics": series,
        "generated_at": payload.get("generated_at"),
    }
    if with_synthesis:
        dossier["synthesis"] = await synthesis(clean, payload, session=session, backend=backend, metrics=series)
    if payload.get("stats", {}).get("items"):
        _cache_set(key, dossier)
    return dossier


def status() -> Dict[str, Any]:
    """Estado do metamodelo: fontes, índices internos e cache."""
    warmup()
    return {
        "sources": sources.catalog(),
        "indexes": sources.index_overview(),
        "cache": {"entries": len(_cache), "ttl_seconds": int(CACHE_TTL)},
        "families": sorted({entry["family"] for entry in sources.CATALOG}),
    }
