"""Fontes do metamodelo de pesquisa 360.

O IQ OS tem dados internos (Elasticsearch: contratos, notícias, entidades, CRM,
recolhas, documentos) e o mundo tem os seus. Um **meta-modelo** de analítica 360
trata tudo isso como "fontes" com a mesma forma de resposta, para que a pesquisa,
o dossiê, a biblioteca e o grafo funcionem sobre qualquer combinação.

Famílias de fontes:

- `internal` — o que já está indexado na plataforma (Elasticsearch + ontologia);
- `documents` — documentos e ficheiros (RAG, recolhas, conjuntos em `data/`);
- `encyclopedia` — Wikipédia (pt/en) e Wikidata (entidades, relações, imagens);
- `opendata` — Banco Mundial, dados.gov.pt (catálogo de dados abertos);
- `research` — OpenAlex e Crossref (literatura científica);
- `web` — pesquisa na web (DuckDuckGo/Brave/SerpAPI, quando configurados).

Todas as respostas são normalizadas numa lista de **itens**:

```python
{"id", "source_id", "source_label", "source_kind", "kind", "title", "subtitle",
 "snippet", "url", "date", "icon", "badges", "score", "data"}
```

`kind` diz o que o item é (`entity`, `article`, `document`, `dataset`, `metric`,
`news`, `file`, `topic`), o que dá ao frontend o ícone, a pasta da biblioteca e a
cor do nó no grafo.
"""
from __future__ import annotations

import asyncio
import hashlib
import html
import json
import logging
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence

import httpx

logger = logging.getLogger(__name__)

USER_AGENT = "IQOS-Search360/1.0 (analytics 360; +https://github.com/iqos)"
TIMEOUT = httpx.Timeout(connect=8.0, read=14.0, write=10.0, pool=6.0)
MAX_ITEMS_PER_SOURCE = 8

# --------------------------------------------------------------------------
# Catálogo
# --------------------------------------------------------------------------
CATALOG: List[Dict[str, Any]] = [
    {
        "id": "internal",
        "label": "Plataforma IQ OS",
        "family": "internal",
        "description": "Contratos públicos, empresas, notícias, cotações, recolhas e CRM indexados no Elasticsearch.",
        "icon": "database",
        "accent": "45,212,191",
        "kinds": ["entity", "document", "news", "metric"],
        "capabilities": ["search", "entities", "metrics", "graph"],
        "requires_key": False,
        "default": True,
    },
    {
        "id": "documents",
        "label": "Documentos e ficheiros",
        "family": "documents",
        "description": "Documentos carregados (RAG), conjuntos de dados em data/ e ficheiros das recolhas.",
        "icon": "folder",
        "accent": "96,165,250",
        "kinds": ["document", "file", "dataset"],
        "capabilities": ["search", "library"],
        "requires_key": False,
        "default": True,
    },
    {
        "id": "wikipedia_pt",
        "label": "Wikipédia (PT)",
        "family": "encyclopedia",
        "description": "Artigos, resumos, secções e ligações da enciclopédia em português.",
        "icon": "book-open",
        "accent": "148,163,184",
        "kinds": ["article", "topic"],
        "capabilities": ["search", "documents", "graph"],
        "requires_key": False,
        "default": True,
        "lang": "pt",
    },
    {
        "id": "wikipedia_en",
        "label": "Wikipedia (EN)",
        "family": "encyclopedia",
        "description": "Versão inglesa: mais cobertura técnica e científica sobre o mesmo tema.",
        "icon": "book-open",
        "accent": "148,163,184",
        "kinds": ["article", "topic"],
        "capabilities": ["search", "documents", "graph"],
        "requires_key": False,
        "default": False,
        "lang": "en",
    },
    {
        "id": "wikidata",
        "label": "Wikidata",
        "family": "encyclopedia",
        "description": "Entidades canónicas (Q-id), classificações, relações e identificadores externos.",
        "icon": "network",
        "accent": "129,140,248",
        "kinds": ["entity"],
        "capabilities": ["entities", "graph"],
        "requires_key": False,
        "default": True,
    },
    {
        "id": "worldbank",
        "label": "Banco Mundial",
        "family": "opendata",
        "description": "Indicadores macroeconómicos e séries por país (energia, PIB, população, clima).",
        "icon": "globe",
        "accent": "52,211,153",
        "kinds": ["metric", "dataset"],
        "capabilities": ["metrics", "search"],
        "requires_key": False,
        "default": True,
    },
    {
        "id": "dadosgov",
        "label": "dados.gov.pt",
        "family": "opendata",
        "description": "Catálogo nacional de dados abertos: conjuntos, organizações e recursos.",
        "icon": "archive",
        "accent": "251,191,36",
        "kinds": ["dataset"],
        "capabilities": ["search", "library"],
        "requires_key": False,
        "default": True,
    },
    {
        "id": "openalex",
        "label": "OpenAlex",
        "family": "research",
        "description": "Literatura científica: artigos, autores, instituições e citações.",
        "icon": "graduation-cap",
        "accent": "244,114,182",
        "kinds": ["article"],
        "capabilities": ["search", "graph"],
        "requires_key": False,
        "default": True,
    },
    {
        "id": "crossref",
        "label": "Crossref",
        "family": "research",
        "description": "Metadados de publicações com DOI (revistas, autores, datas).",
        "icon": "file-text",
        "accent": "232,121,249",
        "kinds": ["article"],
        "capabilities": ["search"],
        "requires_key": False,
        "default": False,
    },
    {
        "id": "web",
        "label": "Web aberta",
        "family": "web",
        "description": "Pesquisa na web (DuckDuckGo, Brave ou SerpAPI) para o que não está em catálogo.",
        "icon": "globe-2",
        "accent": "248,113,113",
        "kinds": ["document"],
        "capabilities": ["search"],
        "requires_key": False,
        "default": False,
        "note": "O Brave/SerpAPI só são usados se a chave estiver no ambiente.",
    },
    {
        "id": "ai",
        "label": "Modelos de IA",
        "family": "ai",
        "description": "Sínteses com citação das fontes por OpenAI, Anthropic, Google, DeepSeek, Mistral, etc.",
        "icon": "sparkles",
        "accent": "56,189,248",
        "kinds": ["summary"],
        "capabilities": ["synthesis"],
        "requires_key": True,
        "default": True,
    },
]

CATALOG_BY_ID = {item["id"]: item for item in CATALOG}


def catalog() -> List[Dict[str, Any]]:
    """Catálogo com a disponibilidade real de cada fonte."""
    import os  # noqa: PLC0415

    web_engines = [name for env, name in (("BRAVE_API_KEY", "Brave"), ("SERPAPI_KEY", "SerpAPI")) if os.getenv(env)]
    items: List[Dict[str, Any]] = []
    for entry in CATALOG:
        item = dict(entry)
        if entry["id"] == "web":
            item["available"] = True
            item["engines"] = ["DuckDuckGo (lite)", *web_engines]
        elif entry["id"] == "internal":
            item["available"] = bool(index_overview())
        elif entry["id"] == "documents":
            item["available"] = True
        else:
            item["available"] = True
        item["seeded"] = bool(entry.get("default"))
        items.append(item)
    return items


# --------------------------------------------------------------------------
# Utilidades
# --------------------------------------------------------------------------
def _hash(*parts: str) -> str:
    return hashlib.sha1("|".join(str(part) for part in parts).encode("utf-8")).hexdigest()[:12]


def _clean(text: Any, limit: int = 400) -> str:
    """Remove HTML e normaliza espaços (os snippets das APIs vêm com `<span>`)."""
    if text is None:
        return ""
    raw = re.sub(r"<[^>]+>", " ", str(text))
    raw = html.unescape(raw)
    raw = re.sub(r"\s+", " ", raw).strip()
    return raw[:limit]


def item(
    source_id: str,
    *,
    kind: str,
    title: str,
    subtitle: Optional[str] = None,
    snippet: Optional[str] = None,
    url: Optional[str] = None,
    date: Optional[str] = None,
    icon: Optional[str] = None,
    badges: Optional[Iterable[str]] = None,
    score: float = 0.5,
    data: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Constrói um item normalizado do metamodelo."""
    spec = CATALOG_BY_ID.get(source_id, {})
    return {
        "id": f"{source_id}:{_hash(title, url or '', kind)}",
        "source_id": source_id,
        "source_label": spec.get("label") or source_id,
        "source_family": spec.get("family") or "outra",
        "source_kind": spec.get("family") or "outra",
        "kind": kind,
        "title": _clean(title, 220) or "(sem título)",
        "subtitle": _clean(subtitle, 180) or None,
        "snippet": _clean(snippet, 600) or None,
        "url": url,
        "date": date,
        "icon": icon or kind,
        "badges": [str(badge) for badge in (badges or []) if badge],
        "score": round(float(score), 3),
        "data": data or {},
    }


def _year(value: Any) -> Optional[str]:
    match = re.search(r"(19|20)\d{2}", str(value or ""))
    return match.group(0) if match else None


def client() -> httpx.AsyncClient:
    """Cliente HTTP das fontes externas (timeouts curtos, `user-agent` próprio)."""
    return httpx.AsyncClient(timeout=TIMEOUT, follow_redirects=True, headers={"user-agent": USER_AGENT, "accept": "application/json"})


# --------------------------------------------------------------------------
# Enciclopédia: Wikipédia e Wikidata
# --------------------------------------------------------------------------
async def wikipedia_search(client: httpx.AsyncClient, term: str, *, lang: str = "pt", limit: int = 5) -> List[Dict[str, Any]]:
    source_id = f"wikipedia_{lang}"
    response = await client.get(
        f"https://{lang}.wikipedia.org/w/api.php",
        params={"action": "query", "list": "search", "srsearch": term, "format": "json", "srlimit": limit, "srprop": "snippet|wordcount|timestamp"},
    )
    response.raise_for_status()
    payload = response.json()
    hits = ((payload.get("query") or {}).get("search")) or []
    total = ((payload.get("query") or {}).get("searchinfo") or {}).get("totalhits")
    results: List[Dict[str, Any]] = []
    for hit in hits:
        title = str(hit.get("title") or "")
        results.append(
            item(
                source_id,
                kind="article",
                title=title,
                subtitle=f"{hit.get('wordcount', 0)} palavras" + (f" · {total} resultados" if total else ""),
                snippet=hit.get("snippet"),
                url=f"https://{lang}.wikipedia.org/wiki/{title.replace(' ', '_')}",
                date=_year(hit.get("timestamp")) or hit.get("timestamp"),
                icon="book-open",
                badges=["enciclopédia", lang.upper()],
                score=0.78,
                data={"pageid": hit.get("pageid"), "wordcount": hit.get("wordcount"), "lang": lang},
            )
        )
    return results


async def wikipedia_page(client: httpx.AsyncClient, title: str, *, lang: str = "pt") -> Dict[str, Any]:
    """Resumo + secções + ligações de um artigo (base da biblioteca e do grafo)."""
    summary: Dict[str, Any] = {}
    sections: List[Dict[str, Any]] = []
    try:
        response = await client.get(f"https://{lang}.wikipedia.org/api/rest_v1/page/summary/{title.replace(' ', '_')}")
        if response.status_code == 200:
            payload = response.json()
            summary = {
                "title": payload.get("title"),
                "extract": _clean(payload.get("extract"), 1500),
                "url": ((payload.get("content_urls") or {}).get("desktop") or {}).get("page"),
                "thumbnail": ((payload.get("thumbnail") or {}).get("source")),
                "coordinates": payload.get("coordinates"),
                "wikidata": payload.get("wikibase_item"),
                "description": payload.get("description"),
                "updated": payload.get("timestamp"),
            }
    except httpx.HTTPError as exc:
        logger.info("Wikipédia: resumo de %s falhou (%s)", title, exc)
    try:
        response = await client.get(
            f"https://{lang}.wikipedia.org/w/api.php",
            params={"action": "parse", "page": title, "prop": "sections", "format": "json", "redirects": 1},
        )
        if response.status_code == 200:
            payload = response.json()
            for section in ((payload.get("parse") or {}).get("sections") or []):
                if str(section.get("toclevel")) != "1":
                    continue
                sections.append(
                    {
                        "id": f"s{section.get('index')}",
                        "label": _clean(section.get("line"), 120),
                        "anchor": section.get("anchor"),
                        "number": section.get("number"),
                    }
                )
    except httpx.HTTPError as exc:
        logger.info("Wikipédia: secções de %s falharam (%s)", title, exc)
    return {"summary": summary, "sections": sections, "lang": lang, "title": title}


async def wikidata_search(client: httpx.AsyncClient, term: str, *, lang: str = "pt", limit: int = 4) -> List[Dict[str, Any]]:
    response = await client.get(
        "https://www.wikidata.org/w/api.php",
        params={"action": "wbsearchentities", "search": term, "language": lang, "uselang": lang, "format": "json", "limit": limit, "type": "item"},
    )
    response.raise_for_status()
    payload = response.json()
    results: List[Dict[str, Any]] = []
    for hit in payload.get("search") or []:
        qid = str(hit.get("id") or "")
        results.append(
            item(
                "wikidata",
                kind="entity",
                title=str(hit.get("label") or qid),
                subtitle=f"{qid} · {hit.get('description') or 'sem descrição'}",
                snippet=hit.get("description"),
                url=f"https://www.wikidata.org/wiki/{qid}",
                icon="network",
                badges=["entidade", qid],
                score=0.7,
                data={"qid": qid, "description": hit.get("description"), "aliases": hit.get("aliases") or []},
            )
        )
    return results


async def wikidata_entity(client: httpx.AsyncClient, qid: str, *, lang: str = "pt") -> Dict[str, Any]:
    """Entidade Wikidata com rótulos, propriedades principais e imagens."""
    response = await client.get(f"https://www.wikidata.org/wiki/Special:EntityData/{qid}.json")
    if response.status_code != 200:
        return {}
    payload = response.json()
    entity = (payload.get("entities") or {}).get(qid) or {}
    labels = {key: value.get("value") for key, value in (entity.get("labels") or {}).items()}
    descriptions = {key: value.get("value") for key, value in (entity.get("descriptions") or {}).items()}
    claims = entity.get("claims") or {}
    sitelinks = entity.get("sitelinks") or {}
    images: List[str] = []
    for claim in (claims.get("P18") or [])[:3]:
        try:
            filename = claim["mainsnak"]["datavalue"]["value"]
            images.append(f"https://commons.wikimedia.org/wiki/Special:FilePath/{str(filename).replace(' ', '_')}")
        except (KeyError, TypeError):
            continue
    identifiers: Dict[str, str] = {}
    for prop, name in (("P17", "país"), ("P31", "instância de"), ("P571", "início"), ("P856", "site")):
        if prop in claims:
            identifiers[name] = f"{len(claims[prop])} valor(es)"
    return {
        "qid": qid,
        "label": labels.get(lang) or labels.get("en") or qid,
        "description": descriptions.get(lang) or descriptions.get("en"),
        "labels": labels,
        "images": images,
        "claims": len(claims),
        "sitelinks": {key: value.get("title") for key, value in list(sitelinks.items())[:12]},
        "identifiers": identifiers,
    }


# --------------------------------------------------------------------------
# Dados abertos: Banco Mundial e dados.gov.pt
# --------------------------------------------------------------------------
PT_EN_TERMS = {
    "energia": "energy",
    "renovável": "renewable",
    "renovavel": "renewable",
    "renováveis": "renewable",
    "eletricidade": "electricity",
    "electricidade": "electricity",
    "pib": "gdp",
    "inflação": "inflation",
    "inflacao": "inflation",
    "desemprego": "unemployment",
    "população": "population",
    "populacao": "population",
    "pobreza": "poverty",
    "saúde": "health",
    "saude": "health",
    "educação": "education",
    "educacao": "education",
    "clima": "climate",
    "emissões": "emissions",
    "emissoes": "emissions",
    "agricultura": "agriculture",
    "turismo": "tourism",
    "exportações": "exports",
    "exportacoes": "exports",
    "dívida": "debt",
    "divida": "debt",
    "investimento": "investment",
    "água": "water",
    "agua": "water",
    "floresta": "forest",
    "transportes": "transport",
}


def _worldbank_query(term: str) -> str:
    """Traduz as palavras mais comuns para inglês (a API só entende inglês)."""
    words = [word.strip(".,;:") for word in str(term).split() if word.strip(".,;:")]
    translated = [PT_EN_TERMS.get(word.lower(), word) for word in words]
    return " ".join(translated)


# Indicadores do Banco Mundial que respondem às perguntas mais frequentes.
# Evita a pesquisa difusa (`q=`) que devolvia indicadores de pobreza rural sem série.
KNOWN_INDICATORS: List[Dict[str, Any]] = [
    {"code": "EG.ELC.RNEW.ZS", "label": "Eletricidade de fontes renováveis (% do total)", "terms": ["energia", "renovável", "renovavel", "renováveis", "renewable", "energy", "eletricidade", "electricidade", "electricity"]},
    {"code": "EG.FEC.RNEW.ZS", "label": "Energia renovável (% do consumo final)", "terms": ["renovável", "renovavel", "renewable", "energia", "energy"]},
    {"code": "EG.USE.PCAP.KG.OE", "label": "Consumo de energia per capita", "terms": ["energia", "energy", "consumo", "consumption"]},
    {"code": "EN.GHG.CO2.MT.CE.AR5", "label": "Emissões de CO₂ (Mt)", "terms": ["clima", "emissões", "emissoes", "co2", "carbono", "climate", "emissions"]},
    {"code": "NY.GDP.MKTP.CD", "label": "PIB (USD correntes)", "terms": ["pib", "gdp", "economia", "economy", "crescimento", "growth"]},
    {"code": "NY.GDP.PCAP.CD", "label": "PIB per capita (USD)", "terms": ["pib", "gdp", "rendimento", "income"]},
    {"code": "FP.CPI.TOTL.ZG", "label": "Inflação (preços ao consumidor, %)", "terms": ["inflação", "inflacao", "inflation", "preços", "precos", "cpi"]},
    {"code": "SL.UEM.TOTL.ZS", "label": "Desemprego (% da população ativa)", "terms": ["desemprego", "unemployment", "emprego", "employment", "trabalho", "labor"]},
    {"code": "SP.POP.TOTL", "label": "População total", "terms": ["população", "populacao", "population", "demografia"]},
    {"code": "SP.DYN.LE00.IN", "label": "Esperança média de vida", "terms": ["saúde", "saude", "health", "vida", "life"]},
    {"code": "SE.XPD.TOTL.GD.ZS", "label": "Despesa pública em educação (% do PIB)", "terms": ["educação", "educacao", "education", "escola", "escolar"]},
    {"code": "BX.KLT.DINV.CD.WD", "label": "Investimento direto estrangeiro (entradas)", "terms": ["investimento", "investment", "ide", "fdi"]},
    {"code": "AG.LND.FRST.ZS", "label": "Área florestal (% do território)", "terms": ["floresta", "forest", "incêndios", "incendios", "território"]},
    {"code": "SH.H2O.BASW.ZS", "label": "Acesso a água potável (%)", "terms": ["água", "agua", "water"]},
    {"code": "ST.INT.ARVL", "label": "Chegadas de turistas", "terms": ["turismo", "tourism", "turistas"]},
]


def _known_indicators(term: str, *, limit: int, country: str = "PRT") -> List[Dict[str, Any]]:
    words = {word.lower() for word in re.split(r"[^\wÀ-ÿ]+", str(term)) if word}
    results: List[Dict[str, Any]] = []
    for entry in KNOWN_INDICATORS:
        if not words & set(entry["terms"]):
            continue
        results.append(
            item(
                "worldbank",
                kind="metric",
                title=entry["label"],
                subtitle=f"Indicador {entry['code']} · {country}",
                snippet=None,
                url=f"https://data.worldbank.org/indicator/{entry['code']}?locations={country}",
                date=None,
                icon="globe",
                badges=["dados abertos", "série", entry["code"]],
                score=0.8,
                data={"indicator": entry["code"], "known": True, "terms": entry["terms"]},
            )
        )
        if len(results) >= limit:
            break
    return results


async def worldbank_search(client: httpx.AsyncClient, term: str, *, limit: int = 4, country: str = "PRT") -> List[Dict[str, Any]]:
    """Indicadores do Banco Mundial relevantes: conhecidos primeiro, depois o catálogo."""
    results = _known_indicators(term, limit=limit, country=country)
    if len(results) >= limit:
        return results
    query = _worldbank_query(term)
    needles = [word.lower() for word in query.split() if len(word) >= 3] or [str(term).lower()]
    response = await client.get("https://api.worldbank.org/v2/indicator", params={"format": "json", "q": query, "per_page": max(limit * 4, 12)})
    if response.status_code == 200:
        payload = response.json()
        rows = payload[1] if isinstance(payload, list) and len(payload) > 1 else []
        total = (payload[0] or {}).get("total") if isinstance(payload, list) and payload else None
        known_codes = {entry["data"]["indicator"] for entry in results}
        for row in rows or []:
            if len(results) >= limit or not isinstance(row, dict):
                continue
            indicator = str(row.get("id") or "")
            name = str(row.get("name") or indicator)
            if indicator in known_codes or indicator.startswith(("1.", "2.")):
                continue
            if not any(needle in f"{name} {indicator}".lower() for needle in needles):
                continue
            results.append(
                item(
                    "worldbank",
                    kind="metric",
                    title=name,
                    subtitle=f"Indicador {indicator}" + (f" · {total} no catálogo" if total else ""),
                    snippet=_clean(row.get("sourceNote"), 400) or None,
                    url=f"https://data.worldbank.org/indicator/{indicator}",
                    date=None,
                    icon="globe",
                    badges=["dados abertos", "série", indicator],
                    score=0.6,
                    data={"indicator": indicator, "source": row.get("sourceOrganization"), "topics": row.get("topics")},
                )
            )
    return results


async def worldbank_series(client: httpx.AsyncClient, indicator: str, *, country: str = "PRT", years: str = "2005:2024") -> Dict[str, Any]:
    """Série de um indicador para um país (para os cartões de analítica do dossiê)."""
    response = await client.get(
        f"https://api.worldbank.org/v2/country/{country}/indicator/{indicator}",
        params={"format": "json", "per_page": 60, "date": years},
    )
    if response.status_code != 200:
        return {}
    payload = response.json()
    rows = payload[1] if isinstance(payload, list) and len(payload) > 1 else []
    points = [
        {"year": int(row["date"]), "value": row["value"]}
        for row in (rows or [])
        if isinstance(row, dict) and row.get("value") is not None and str(row.get("date", "")).isdigit()
    ]
    points.reverse()
    if not points:
        return {}
    first, last = points[0], points[-1]
    change = last["value"] - first["value"]
    return {
        "indicator": indicator,
        "country": country,
        "name": (rows[0].get("indicator") or {}).get("value") if rows else indicator,
        "points": points,
        "first": first,
        "last": last,
        "change": change,
        "change_pct": (change / first["value"] * 100) if first["value"] else None,
    }


def _text(value: Any, fallback: str = "") -> str:
    """Valor textual defensivo (as APIs devolvem strings, dicts ou listas no mesmo campo)."""
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        for key in ("name", "title", "value", "label"):
            if isinstance(value.get(key), str):
                return str(value[key])
        return fallback
    if isinstance(value, list) and value:
        return _text(value[0], fallback)
    return fallback


async def dadosgov_search(client: httpx.AsyncClient, term: str, *, limit: int = 5) -> List[Dict[str, Any]]:
    """Conjuntos de dados do catálogo nacional (tenta o tema e, se falhar, a primeira palavra)."""
    queries = [term]
    first = str(term).split()[0] if str(term).strip() else ""
    if first and first.lower() != str(term).lower():
        queries.append(first)
    rows: List[Dict[str, Any]] = []
    for query in queries:
        response = await client.get("https://dados.gov.pt/api/1/datasets/", params={"q": query, "page_size": limit})
        if response.status_code != 200:
            continue
        payload = response.json()
        rows = [row for row in (payload.get("data") or []) if isinstance(row, dict)][:limit]
        if rows:
            break
    results: List[Dict[str, Any]] = []
    for row in rows:
        organization = _text(row.get("organization"), "dados.gov.pt")
        resources = [res for res in (row.get("resources") or []) if isinstance(res, dict)]
        tags = [_text(tag) for tag in (row.get("tags") or []) if _text(tag)]
        results.append(
            item(
                "dadosgov",
                kind="dataset",
                title=_text(row.get("title")) or _text(row.get("slug")),
                subtitle=f"{organization} · {len(resources)} recurso(s)",
                snippet=_clean(row.get("description"), 500) or None,
                url=f"https://dados.gov.pt/pt/datasets/{_text(row.get('slug'))}",
                date=_year(row.get("created_at")) or None,
                icon="archive",
                badges=["dados abertos", "conjunto", *tags[:2]],
                score=0.6,
                data={
                    "organization": organization,
                    "resources": [
                        {"title": _text(res.get("title")), "format": _text(res.get("format")), "url": _text(res.get("url"))}
                        for res in resources[:4]
                    ],
                    "tags": tags[:6],
                },
            )
        )
    return results


# --------------------------------------------------------------------------
# Investigação: OpenAlex e Crossref
# --------------------------------------------------------------------------
async def openalex_search(client: httpx.AsyncClient, term: str, *, limit: int = 5) -> List[Dict[str, Any]]:
    response = await client.get(
        "https://api.openalex.org/works",
        params={"search": term, "per-page": limit, "mailto": "iqos@example.org"},
    )
    if response.status_code != 200:
        return []
    payload = response.json()
    total = (payload.get("meta") or {}).get("count")
    results: List[Dict[str, Any]] = []
    for row in (payload.get("results") or [])[:limit]:
        authors = [str((author.get("author") or {}).get("display_name") or "") for author in (row.get("authorships") or [])[:3]]
        results.append(
            item(
                "openalex",
                kind="article",
                title=str(row.get("title") or row.get("display_name") or ""),
                subtitle=", ".join(name for name in authors if name) + (f" · {total} trabalhos" if total else ""),
                snippet=str(row.get("abstract") or "")[:500] or None,
                url=row.get("doi") or row.get("id"),
                date=_year(row.get("publication_date")) or row.get("publication_date"),
                icon="graduation-cap",
                badges=["investigação", f"{row.get('cited_by_count', 0)} citações"],
                score=0.55,
                data={
                    "doi": row.get("doi"),
                    "cited_by_count": row.get("cited_by_count"),
                    "open_access": (row.get("open_access") or {}).get("is_oa"),
                    "concepts": [concept.get("display_name") for concept in (row.get("concepts") or [])[:5]],
                    "venue": ((row.get("primary_location") or {}).get("source") or {}).get("display_name"),
                },
            )
        )
    return results


async def crossref_search(client: httpx.AsyncClient, term: str, *, limit: int = 4) -> List[Dict[str, Any]]:
    response = await client.get(
        "https://api.crossref.org/works",
        params={"query": term, "rows": limit, "select": "DOI,title,author,issued,container-title,abstract"},
    )
    if response.status_code != 200:
        return []
    payload = response.json()
    results: List[Dict[str, Any]] = []
    for row in ((payload.get("message") or {}).get("items") or [])[:limit]:
        issued = ((row.get("issued") or {}).get("date-parts") or [[None]])[0]
        results.append(
            item(
                "crossref",
                kind="article",
                title=(row.get("title") or [""])[0],
                subtitle=", ".join(
                    f"{author.get('given', '')} {author.get('family', '')}".strip() for author in (row.get("author") or [])[:3]
                ),
                snippet=row.get("abstract"),
                url=f"https://doi.org/{row.get('DOI')}" if row.get("DOI") else None,
                date=str(issued[0]) if issued and issued[0] else None,
                icon="file-text",
                badges=["DOI", str((row.get("container-title") or [''])[0])[:40]],
                score=0.5,
                data={"doi": row.get("DOI"), "venue": (row.get("container-title") or [None])[0]},
            )
        )
    return results


# --------------------------------------------------------------------------
# Web
# --------------------------------------------------------------------------
async def web_search(term: str, *, limit: int = 5) -> List[Dict[str, Any]]:
    """Pesquisa na web com os motores já configurados em `api.tools`."""
    from api import tools  # noqa: PLC0415

    try:
        rows = await asyncio.to_thread(tools.web_search, term, limit, "auto")
    except Exception as exc:  # motor indisponível
        logger.info("Pesquisa web falhou: %s", exc)
        return []
    results: List[Dict[str, Any]] = []
    for row in (rows or [])[:limit]:
        if not isinstance(row, dict):
            continue
        results.append(
            item(
                "web",
                kind="document",
                title=str(row.get("title") or row.get("url") or ""),
                subtitle=str(row.get("source") or row.get("engine") or "web"),
                snippet=row.get("snippet") or row.get("description"),
                url=row.get("url"),
                icon="globe-2",
                badges=["web", str(row.get("engine") or "")],
                score=0.45,
                data={"engine": row.get("engine"), "source": row.get("source")},
            )
        )
    return results


# --------------------------------------------------------------------------
# Internas: ontologia, Elasticsearch, documentos e ficheiros
# --------------------------------------------------------------------------
def internal_search(term: str, *, limit: int = 6, scope: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Entidades e documentos do IQ OS relacionados com o tema (ontologia + Elasticsearch)."""
    from api import ontology_service as ontology  # noqa: PLC0415

    entities: List[Dict[str, Any]] = []
    warnings: List[str] = []
    try:
        resolved = ontology.resolve_entities(term, limit=limit, scope=scope)
    except Exception as exc:
        resolved = {}
        warnings.append(f"Resolução de entidades falhou: {exc}")
    for candidate in (resolved.get("candidates") or [])[:limit]:
        label = candidate.get("label") or candidate.get("id")
        kind = str(candidate.get("type_id") or "object")
        entities.append(
            item(
                "internal",
                kind="entity",
                title=str(label),
                subtitle=f"{candidate.get('type_label') or kind}" + (f" · {candidate.get('matched_on')}" if candidate.get("matched_on") else ""),
                snippet=candidate.get("reason") or candidate.get("query_hint"),
                url=f"/tickers/{candidate.get('id')}" if kind == "ticker" else None,
                icon="building" if kind in ("empresa", "entidade_publica") else "boxes",
                badges=["plataforma", kind],
                score=0.9,
                data={
                    "type_id": candidate.get("type_id"),
                    "object_id": candidate.get("id"),
                    "match": candidate.get("matched_on"),
                    "score": candidate.get("score"),
                },
            )
        )
    documents: List[Dict[str, Any]] = []
    try:
        documents.extend(_internal_text_hits(term, limit=limit))
    except Exception as exc:
        warnings.append(f"Pesquisa em índices falhou: {exc}")
    return {"entities": entities, "documents": documents, "warnings": warnings, "resolved": resolved}


def _internal_text_hits(term: str, *, limit: int = 6) -> List[Dict[str, Any]]:
    """Procura o tema nos índices de texto da plataforma (notícias, recolhas, contratos)."""
    from api import elasticsearch_client as es_client  # noqa: PLC0415

    results: List[Dict[str, Any]] = []
    client = es_client.get_es_client()
    if not client:
        return results
    # Notícias de mercado
    try:
        news = es_client.search_all_tickers(term, 0, limit)
        for row in (news or {}).get("items") or []:
            if not isinstance(row, dict):
                continue
            results.append(
                item(
                    "internal",
                    kind="news",
                    title=str(row.get("title") or row.get("headline") or ""),
                    subtitle=f"{row.get('publisher') or row.get('ticker') or 'notícia'}",
                    snippet=row.get("summary") or row.get("description") or "",
                    url=row.get("url"),
                    date=str(row.get("published") or row.get("date") or "")[:10] or None,
                    icon="newspaper",
                    badges=["notícia"],
                    score=0.66,
                    data={"ticker": row.get("ticker"), "source": "finance_news"},
                )
            )
    except Exception as exc:
        logger.debug("Notícias: %s", exc)
    # Recolhas (scraper)
    try:
        scraped = es_client.search_scraped(term, size=limit)
        for row in (scraped or {}).get("items") or []:
            results.append(
                item(
                    "internal",
                    kind="document",
                    title=str(row.get("title") or row.get("url") or ""),
                    subtitle=str(row.get("source_id") or "recolha"),
                    snippet=row.get("text") or row.get("summary") or "",
                    url=row.get("url"),
                    date=str(row.get("published_at") or row.get("collected_at") or "")[:10] or None,
                    icon="radar",
                    badges=["recolha"],
                    score=0.58,
                    data={"source_id": row.get("source_id"), "tags": row.get("tags")},
                )
            )
    except Exception as exc:
        logger.debug("Recolhas: %s", exc)
    # Contratos públicos
    try:
        contracts = es_client.search_contracts(term, size=limit)
        for row in (contracts or {}).get("items") or []:
            results.append(
                item(
                    "internal",
                    kind="document",
                    title=str(row.get("objectoContrato") or row.get("objecto") or row.get("idcontrato") or "contrato"),
                    subtitle=f"{row.get('adjudicantes') or ''} → {row.get('adjudicatarios') or ''}",
                    snippet=str(row.get("descContrato") or "")[:400] or None,
                    url=f"/contratos/{row.get('idcontrato')}" if row.get("idcontrato") else None,
                    date=str(row.get("dataCelebracaoContrato") or "")[:10] or None,
                    icon="file-text",
                    badges=["contrato", str(row.get("Ano") or "")],
                    score=0.6,
                    data={"idcontrato": row.get("idcontrato"), "preco": row.get("precoContratual")},
                )
            )
    except Exception as exc:
        logger.debug("Contratos: %s", exc)
    # Ficheiros/documentos indexados no RAG
    try:
        from api.rag_service import get_document_store  # noqa: PLC0415

        store = get_document_store()
        needle = term.lower()[:40]
        for row in store.list() or []:
            name = str(getattr(row, "title", None) or getattr(row, "filename", None) or getattr(row, "doc_id", ""))
            extra = getattr(row, "extra", None) or {}
            summary = str(extra.get("summary") or "") if isinstance(extra, dict) else ""
            if needle and needle not in name.lower() and needle not in summary.lower():
                continue
            created = getattr(row, "created_at", None) or 0
            results.append(
                item(
                    "documents",
                    kind="document",
                    title=name,
                    subtitle=f"{getattr(row, 'pages', 0) or '?'} páginas · {getattr(row, 'size_bytes', 0) / 1024:.0f} KB",
                    snippet=summary or None,
                    url=f"/rag/documents/{getattr(row, 'doc_id', '')}",
                    date=datetime.fromtimestamp(created, tz=timezone.utc).strftime("%Y-%m-%d") if created else None,
                    icon="file-text",
                    badges=["documento", "indexado" if getattr(row, "indexed", False) else "por indexar"],
                    score=0.52,
                    data={"doc_id": getattr(row, "doc_id", None), "filename": getattr(row, "filename", None)},
                )
            )
    except Exception as exc:
        logger.debug("Documentos: %s", exc)
    return results[: max(limit * 2, 6)]


def local_files(term: str, *, limit: int = 12) -> List[Dict[str, Any]]:
    """Ficheiros de `data/` (conjuntos, documentos, dumps) que correspondem ao tema."""
    root = Path(__file__).resolve().parents[1] / "data"
    if not root.exists():
        return []
    needle = re.sub(r"[^a-z0-9]+", "", term.lower())
    results: List[Dict[str, Any]] = []
    for path in sorted(root.rglob("*")):
        if not path.is_file() or len(results) >= limit:
            continue
        name = path.name
        if needle and needle not in re.sub(r"[^a-z0-9]+", "", name.lower()) and needle not in re.sub(r"[^a-z0-9]+", "", str(path.parent.name).lower()):
            continue
        try:
            size = path.stat().st_size
        except OSError:
            continue
        results.append(
            item(
                "documents",
                kind="file",
                title=name,
                subtitle=f"{path.parent.relative_to(root)} · {size / 1024:.1f} KB",
                url=None,
                date=datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc).strftime("%Y-%m-%d"),
                icon="file",
                badges=[path.suffix.lstrip(".") or "ficheiro"],
                score=0.4,
                data={"path": str(path.relative_to(root)), "size": size},
            )
        )
    return results


def index_overview() -> List[Dict[str, Any]]:
    """Panorama dos índices do Elasticsearch (contagens e o que representam)."""
    from api import elasticsearch_client as es_client  # noqa: PLC0415

    client = es_client.get_es_client()
    if not client:
        return []
    labels = {
        es_client.CONTRACTS_INDEX: ("Contratos públicos", "contratos"),
        es_client.TRADEMARKS_INDEX: ("Marcas (INPI)", "documentos"),
        es_client.FIRMAS_INDEX: ("Firmas (RNPC)", "documentos"),
        es_client.ENTITIES_INDEX: ("Entidades", "entidades"),
        es_client.CRM_INDEX: ("CRM", "privado"),
        es_client.SCRAPED_INDEX: ("Recolhas", "documentos"),
        "finance_news": ("Notícias", "documentos"),
        "finance_prices": ("Cotações", "mercados"),
        "finance_sentiment_daily": ("Sentimento", "mercados"),
    }
    overview: List[Dict[str, Any]] = []
    for index, (label, kind) in labels.items():
        try:
            count = int(client.count(index=index).get("count", 0))
        except Exception:
            continue
        overview.append({"index": index, "label": label, "kind": kind, "documents": count})
    overview.sort(key=lambda row: -int(row["documents"]))
    return overview
