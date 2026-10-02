"""Pesquisa unificada («estilo Google») sobre tudo o que o IQ OS tem.

Uma pergunta, um resultado por área. O `unified_search` dispara em paralelo uma
consulta por **âmbito** (recolha, contratos, contratos de Espanha, entidades de
Espanha, empresas, marcas, firmas, notícias de mercado, imprensa recolhida,
mercado e CRM) e devolve grupos normalizados — cada item com título, subtítulo,
excerto, data, etiquetas e (quando faz sentido) a vista interna que o abre.

Decisões importantes:

- **Um âmbito não derruba os outros.** Cada grupo corre isolado com o seu
  `try/except`; um índice em baixo devolve `error` naquele grupo e o resto da
  página continua a funcionar.
- **Os âmbitos de sessão só aparecem com sessão.** O CRM é privado por
  utilizador (`owner_id`), pelo que só é pesquisado quando há sessão válida —
  e nunca devolve registos de outra pessoa.
- **Parallelismo limitado** (`ThreadPoolExecutor`) para não sobrecarregar o
  Elasticsearch nem a API com uma pesquisa por clique.
- **Espanha é um âmbito próprio** (`contratos_es`, PLACSP): são 4 milhões de
  documentos noutro esquema de campos (castelhano), por isso não se misturam com
  os contratos portugueses. `entities_es` responde ao mesmo problema pelo lado
  oposto: como cada documento é um contrato, os **nomes** dos órgãos adjudicantes
  e das empresas adjudicatárias são obtidos por agregação.
"""
from __future__ import annotations

import asyncio
import json
import logging
import re
import unicodedata
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from typing import Any, Dict, Iterable, List, Optional
from urllib.parse import quote_plus

from elasticsearch import Elasticsearch

from api.elasticsearch_client import (
    CRM_INDEX,
    NON_NEWS_SOURCE_IDS,
    NON_NEWS_SOURCE_PREFIXES,
    contratos_es_autocomplete,
    ensure_indices,
    get_es_client,
    search_contratos_es,
    search_contratos_es_entities,
    search_contracts,
    search_entities,
    search_firmas,
    search_people_faceted,
    search_scraped,
    search_social,
    search_trademarks,
)

logger = logging.getLogger(__name__)

NEWS_INDEX = "finance_news"
PRICES_INDEX = "finance_prices"

# Âmbitos mostrados na página. `all` não é um grupo: significa «todos».
SCOPES: List[Dict[str, Any]] = [
    {"id": "scraped", "label": "Recolha", "hint": "Dados recolhidos de sites (scraping)"},
    {"id": "social", "label": "Redes sociais", "hint": "Publicações de LinkedIn, TikTok, Reddit e Facebook — filtráveis por tipo e plataforma"},
    {"id": "contracts", "label": "Contratos", "hint": "Contratação pública (portal base)"},
    {"id": "contracts_es", "label": "Contratos ES", "hint": "Contratação pública de Espanha (PLACSP)"},
    {"id": "entities_es", "label": "Entidades ES", "hint": "Órgãos adjudicantes e empresas adjudicatárias de Espanha"},
    {"id": "entities", "label": "Empresas", "hint": "Cadastro de entidades"},
    {"id": "pessoas", "label": "Pessoas", "hint": "Pessoas com ficha (CIRE, registo societário e política) — filtráveis por origem e fonte"},
    {"id": "politicos", "label": "Políticos", "hint": "Políticos portugueses (Wikipédia e parlamento) — filtráveis por partido, círculo e cargo"},
    {"id": "wikipedia", "label": "Wikipédia", "hint": "Enciclopédia livre (PT e EN), consultada em direto"},
    {"id": "trademarks", "label": "Marcas", "hint": "Marcas registadas (INPI)"},
    {"id": "firmas", "label": "Firmas", "hint": "Firmas e denominações (RNPC)"},
    {"id": "news", "label": "Notícias Elastic", "hint": "Notícias de mercado no índice `finance_news` (por ativo e por tema)"},
    {"id": "imprensa", "label": "Imprensa", "hint": "Notícias recolhidas dos jornais (SAPO, Lusa, Jornal Económico, Observador, ECO…)"},
    {"id": "market", "label": "Mercado", "hint": "Tickers e cotações indexadas"},
    {"id": "crm", "label": "CRM", "hint": "Contas, contactos e oportunidades", "session": True},
]
SCOPE_IDS = [scope["id"] for scope in SCOPES]

# Filtros (facetas) de cada âmbito: nome legível → campo do índice e etiqueta.
# O âmbito de origem decide o vocabulário: pedir `partido` no âmbito das
# notícias é ignorado, porque lá esse filtro não existe.
SCOPE_FILTERS: Dict[str, Dict[str, Dict[str, str]]] = {
    "social": {
        "tipo": {"field": "kind", "label": "Tipo"},
        "plataforma": {"field": "platform", "label": "Plataforma"},
        "etiqueta": {"field": "tags", "label": "Etiqueta"},
    },
    "pessoas": {
        "origem": {"field": "roles.role_org", "label": "Origem"},
        "fonte": {"field": "source", "label": "Fonte"},
    },
    "politicos": {
        "partido": {"field": "metadata.partido.keyword", "label": "Partido"},
        "circulo": {"field": "metadata.circulo_eleitoral.keyword", "label": "Círculo eleitoral"},
        "cargo": {"field": "metadata.office.keyword", "label": "Cargo"},
        "fonte": {"field": "source", "label": "Fonte"},
    },
    "imprensa": {"fonte": {"field": "source_id", "label": "Jornal"}},
    "scraped": {"fonte": {"field": "source_id", "label": "Fonte"}},
    "wikipedia": {"fonte": {"field": "lang", "label": "Wikipédia"}},
}

#: Políticos: ficha da Wikipédia **ou** ficha do parlamento (as duas famílias que
#: existem em `finance_people`, identificadas pelo `source`).
POLITICOS_QUERY: Dict[str, Any] = {
    "bool": {
        "should": [
            {"prefix": {"nif": "PT-WIKI-PT:"}},
            {"prefix": {"nif": "PT-AR-BID:"}},
            {"exists": {"field": "metadata.partido"}},
        ],
        "minimum_should_match": 1,
    }
}

#: Nome apresentável de cada fonte de pessoas.
PEOPLE_SOURCE_LABELS = {
    "pt.wikipedia.org": "Wikipédia PT",
    "parlamento.pt/deputados": "Parlamento",
    "cire": "CIRE",
    "societario": "Registo societário",
    "publicacoes_mj": "Publicações do MJ",
}


def parse_filters(raw: Optional[str]) -> Dict[str, str]:
    """Filtros pedidos pela interface (`{"partido":"PS"}` ou `partido:PS`)."""
    text = (raw or "").strip()
    if not text:
        return {}
    if text.startswith("{"):
        try:
            parsed = json.loads(text)
        except ValueError:
            return {}
        if isinstance(parsed, dict):
            return {str(k): str(v) for k, v in parsed.items() if v not in (None, "")}
        return {}
    pairs: Dict[str, str] = {}
    for chunk in text.split(","):
        name, _, value = chunk.partition(":")
        if name.strip() and value.strip():
            pairs[name.strip()] = value.strip()
    return pairs


def _scope_filter_map(scope_id: str, filters: Optional[Dict[str, str]]) -> Dict[str, str]:
    """Filtros de um âmbito traduzidos para os campos do índice (nome → valor)."""
    spec = SCOPE_FILTERS.get(scope_id) or {}
    resolved: Dict[str, str] = {}
    for name, value in (filters or {}).items():
        entry = spec.get(name)
        if entry and str(value).strip():
            resolved[entry["field"]] = str(value)
    return resolved


def _filter_panel(scope_id: str, facets: Dict[str, List[Dict[str, Any]]]) -> List[Dict[str, Any]]:
    """Painel de filtros do âmbito: nome, etiqueta e valores contados.

    Cada valor leva `key` (o que se envia no filtro) e `label` (o que se lê no
    ecrã), o que permite mostrar o nome do jornal e filtrar pelo `source_id`.
    """
    spec = SCOPE_FILTERS.get(scope_id) or {}
    panel: List[Dict[str, Any]] = []
    for name, values in (facets or {}).items():
        entry = spec.get(name)
        if not entry or not values:
            continue
        panel.append({"name": name, "label": entry["label"], "values": values[:12]})
    return panel

# Vista interna de cada âmbito, quando o resultado abre uma ficha dentro do IQ OS.
CONTRATOS_ES_VIEW = "contratos-es"

_ACCENTS = str.maketrans("áàâãäéèêëíìîïóòôõöúùûüçÁÀÂÃÄÉÈÊËÍÌÎÏÓÒÔÕÖÚÙÛÜÇ", "aaaaaeeeeiiiiooooouuuucAAAAAEEEEIIIIOOOOOUUUUC")


# ------------------------------------------------------------------ utilidades
def _fold(value: str) -> str:
    """Minúsculas sem acentos, para localizar o termo no texto."""
    return unicodedata.normalize("NFKD", (value or "").translate(_ACCENTS)).lower()


def _clip(value: Any, limit: int = 300) -> str:
    text = re.sub(r"\s+", " ", str(value or "")).strip()
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


def excerpt(text: Any, query: str, limit: int = 260) -> str:
    """Excerto à volta da primeira ocorrência do termo (ou o início do texto)."""
    full = re.sub(r"\s+", " ", str(text or "")).strip()
    if not full:
        return ""
    if not query:
        return _clip(full, limit)
    haystack = _fold(full)
    needle = _fold(query.split()[0]) if query.split() else ""
    index = haystack.find(needle) if needle else -1
    if index < 0:
        return _clip(full, limit)
    start = max(0, index - limit // 3)
    end = min(len(full), start + limit)
    prefix = "…" if start > 0 else ""
    suffix = "…" if end < len(full) else ""
    return f"{prefix}{full[start:end].strip()}{suffix}"


def _iso(value: Any) -> Optional[str]:
    if not value:
        return None
    if isinstance(value, datetime):
        return value.isoformat()
    return str(value)


def _item(
    scope: str,
    item_id: str,
    title: str,
    *,
    subtitle: str = "",
    snippet: str = "",
    url: str = "",
    date: Any = None,
    badges: Optional[Iterable[Any]] = None,
    extra: Optional[Dict[str, Any]] = None,
    image: str = "",
    sentiment: Optional[Dict[str, Any]] = None,
    open_view: Optional[Dict[str, str]] = None,
    score: Optional[float] = None,
) -> Dict[str, Any]:
    return {
        "scope": scope,
        "id": str(item_id or ""),
        "title": _clip(title, 220),
        "subtitle": _clip(subtitle, 200),
        "snippet": _clip(snippet, 320),
        "url": str(url or ""),
        "image": str(image or ""),
        "date": _iso(date),
        "badges": [str(b) for b in (badges or []) if b not in (None, "")][:6],
        "extra": extra or {},
        "sentiment": sentiment or {},
        "open": open_view,
        "score": score,
    }


def _group(scope: str, label: str, items: List[Dict[str, Any]], total: int, took_ms: int) -> Dict[str, Any]:
    return {"scope": scope, "label": label, "total": int(total or 0), "items": items, "took_ms": took_ms, "error": None}


def _error_group(scope: str, label: str, error: str) -> Dict[str, Any]:
    return {"scope": scope, "label": label, "total": 0, "items": [], "took_ms": 0, "error": error}


def _party_names(entries: Any) -> List[str]:
    """Nomes das partes de um contrato.

    O índice guarda `{"raw": [...], "parsed": [{"nif", "nome"}]}` (um dicionário),
    mas versões antigas de documentos podem ter uma lista de entradas — as duas
    formas são aceites para a pesquisa nunca rebentar com dados reais.
    """
    names: List[str] = []

    def add_parsed(parsed: Any) -> None:
        if isinstance(parsed, dict):
            parsed = [parsed]
        for part in parsed or []:
            if isinstance(part, dict) and part.get("nome"):
                names.append(str(part["nome"]))

    def add_raw(raw: Any) -> None:
        values = [raw] if isinstance(raw, str) else (raw or [])
        for value in values:
            if isinstance(value, str) and value.strip():
                names.append(value.strip())

    if isinstance(entries, dict):
        add_parsed(entries.get("parsed"))
        if not names:
            add_raw(entries.get("raw"))
        return names

    for entry in entries or []:
        if isinstance(entry, str):
            if entry.strip():
                names.append(entry.strip())
        elif isinstance(entry, dict):
            before = len(names)
            add_parsed(entry.get("parsed"))
            if len(names) == before:
                add_raw(entry.get("raw"))
    return names


def _flat(value: Any) -> Optional[str]:
    """Valor simples para um badge (lista → texto unido)."""
    if value in (None, "", []):
        return None
    if isinstance(value, list):
        parts = [str(v).strip() for v in value if str(v).strip()]
        return ", ".join(parts) or None
    if isinstance(value, dict):
        return None
    return str(value)


def _cpv_code(value: Any) -> Optional[str]:
    if isinstance(value, str):
        return value or None
    if isinstance(value, list) and value:
        first = value[0]
        if isinstance(first, dict):
            return first.get("code")
        if isinstance(first, str):
            return first
    return None


def _label_for(scope_id: str) -> str:
    return next((s["label"] for s in SCOPES if s["id"] == scope_id), scope_id)


# ------------------------------------------------------------------- âmbitos
#: Campos de um item recolhido que guardam a sua imagem (por ordem de preferência).
_SCRAPED_IMAGE_KEYS = ("imagem", "image", "img", "thumbnail", "foto", "cover", "imagem_url", "image_url")
#: Tamanho máximo de um valor extraído mostrado na interface (o texto integral não conta).
_SCRAPED_VALUE_LIMIT = 300
_SCRAPED_VALUES_MAX = 12


def _scraped_image(data: Dict[str, Any]) -> str:
    """Imagem do item recolhido (o `src` real, já sem marcadores de 1×1 pixel)."""
    for key in _SCRAPED_IMAGE_KEYS:
        for name, value in data.items():
            if name.lower() == key and isinstance(value, str) and value.startswith("http"):
                return value
    for name, value in data.items():
        if re.search(r"(img|image|imagem|foto|thumb|cover|logo)", name, re.I) and isinstance(value, str) and value.startswith("http"):
            return value
    return ""


def _scraped_values(data: Dict[str, Any]) -> Dict[str, Any]:
    """Valores extraídos que a interface mostra ao lado de cada item.

    O texto integral do artigo é muito grande para uma lista de valores, pelo que
    os valores longos ficam de fora (continuam pesquisáveis no índice).
    """
    valores: Dict[str, Any] = {}
    for name, value in data.items():
        if name.lower() in {"url", "texto", "text", "conteudo", "body"}:
            continue
        if isinstance(value, str):
            if len(value) > _SCRAPED_VALUE_LIMIT:
                continue
            if value.startswith("http") and name.lower() in _SCRAPED_IMAGE_KEYS:
                continue
        valores[name] = value
        if len(valores) >= _SCRAPED_VALUES_MAX:
            break
    return valores


def _search_scraped_group(q: str, size: int, offset: int, filters: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    source = (filters or {}).get("fonte")
    result = search_scraped(
        q=q or None, size=size, from_=offset, sort="relevance" if q else "recent", source_id=source
    )
    if result.get("error"):
        return _error_group("scraped", _label_for("scraped"), str(result["error"]))
    items = []
    for hit in result.get("items", []):
        data = hit.get("data") or {}
        items.append(
            _item(
                "scraped",
                hit.get("item_id") or hit.get("url") or "",
                hit.get("title") or hit.get("item_id") or "",
                subtitle=hit.get("source_name") or hit.get("source_id") or "",
                snippet=hit.get("summary") or hit.get("text") or "",
                url=hit.get("url") or "",
                date=hit.get("scraped_at"),
                badges=[*(hit.get("tags") or [])[:5]],
                image=_scraped_image(data),
                sentiment={
                    "label": hit.get("sentiment") or "",
                    "polarity": hit.get("sentiment_score"),
                    "engine": hit.get("sentiment_engine") or "",
                }
                if hit.get("sentiment")
                else None,
                extra={"valores": _scraped_values(data)},
            )
        )
    total = int(result.get("total") or 0)
    facets = result.get("facets") or {}
    grupo = {**_group("scraped", _label_for("scraped"), items, total, 0), "facets": facets}
    # Fonte escolhida no painel: mostra-se pelo nome legível, filtra-se pelo id.
    grupo["filters"] = _filter_panel(
        "scraped",
        {
            "fonte": [
                {"key": entry.get("id") or entry["key"], "label": entry["key"], "count": entry["count"]}
                for entry in (facets.get("publishers") or [])
            ]
        },
    )
    # Sentimento do conjunto de resultados (não só da página): é o que permite
    # dizer o tom da pesquisa, e não apenas o de cada notícia.
    if result.get("sentiment"):
        grupo["sentiment"] = result["sentiment"]
    return grupo


#: Nome apresentável de cada plataforma social (etiquetas dos resultados).
_SOCIAL_PLATFORM_LABELS = {
    "linkedin": "LinkedIn",
    "tiktok": "TikTok",
    "reddit": "Reddit",
    "facebook": "Facebook",
}

#: Nome apresentável de cada **tipo** de publicação social.
_SOCIAL_KIND_LABELS = {
    "post": "Publicação",
    "video": "Vídeo",
    "comment": "Comentário",
    "profile": "Perfil",
    "page": "Página",
    "article": "Artigo",
    "short": "Short",
}


def _social_badges(hit: Dict[str, Any]) -> List[str]:
    """Etiquetas de uma publicação social (plataforma, comunidade e interação)."""
    badges: List[str] = []
    platform = str(hit.get("platform") or "")
    if platform:
        badges.append(_SOCIAL_PLATFORM_LABELS.get(platform, platform))
    community = str(hit.get("community") or "")
    if community:
        badges.append(community)
    for name, label in (("likes", "reações"), ("comments", "comentários"), ("shares", "partilhas"), ("views", "vistas")):
        try:
            value = int(hit.get(name) or 0)
        except (TypeError, ValueError):
            value = 0
        if value:
            badges.append(f"{value:,} {label}".replace(",", " "))
    return badges


def _search_social_group(q: str, size: int, offset: int, filters: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    """Publicações recolhidas das redes sociais (âmbito «Redes sociais»).

    Aceita os filtros do âmbito — **tipo** de publicação (`post`, `video`…),
    plataforma e etiqueta — e devolve o painel com as contagens de cada um.
    """
    ativos = filters or {}
    result = search_social(
        q=q or None,
        platform=ativos.get("plataforma"),
        kinds=[ativos["tipo"]] if ativos.get("tipo") else None,
        tags=[ativos["etiqueta"]] if ativos.get("etiqueta") else None,
        size=size,
        from_=offset,
        sort="relevance" if q else "recent",
    )
    if result.get("error"):
        return _error_group("social", _label_for("social"), str(result["error"]))
    items = []
    for hit in result.get("items", []):
        items.append(
            _item(
                "social",
                hit.get("item_id") or hit.get("url") or "",
                hit.get("title") or hit.get("text") or hit.get("item_id") or "",
                subtitle=" · ".join(
                    part for part in (hit.get("channel_name"), hit.get("author")) if part
                ),
                snippet=hit.get("text") or hit.get("title") or "",
                url=hit.get("url") or "",
                date=hit.get("published_at") or hit.get("collected_at"),
                badges=_social_badges(hit),
                image=hit.get("image") or "",
                sentiment={
                    "label": hit.get("sentiment") or "",
                    "polarity": hit.get("sentiment_score"),
                    "engine": hit.get("sentiment_engine") or "",
                }
                if hit.get("sentiment")
                else None,
                extra={
                    "valores": {k: v for k, v in (hit.get("data") or {}).items() if v not in (None, "")},
                    "plataforma": _SOCIAL_PLATFORM_LABELS.get(str(hit.get("platform") or ""), hit.get("platform") or ""),
                    "canal": hit.get("channel_name") or "",
                    "interacao": {
                        "likes": hit.get("likes"),
                        "comentarios": hit.get("comments"),
                        "partilhas": hit.get("shares"),
                        "vistas": hit.get("views"),
                    },
                },
            )
        )
    total = int(result.get("total") or 0)
    facets = result.get("facets") or {}
    grupo = {**_group("social", _label_for("social"), items, total, 0), "facets": facets}
    grupo["filters"] = _filter_panel(
        "social",
        {
            "tipo": [
                {"key": b["key"], "label": _SOCIAL_KIND_LABELS.get(str(b["key"]), b["key"]), "count": b["count"]}
                for b in (facets.get("kinds") or [])
            ],
            "plataforma": [
                {
                    "key": b["key"],
                    "label": _SOCIAL_PLATFORM_LABELS.get(str(b["key"]), b["key"]),
                    "count": b["count"],
                }
                for b in (facets.get("platforms") or [])
            ],
            "etiqueta": [{"key": b["key"], "count": b["count"]} for b in (facets.get("tags") or [])],
        },
    )
    if result.get("sentiment"):
        grupo["sentiment"] = result["sentiment"]
    return grupo


def _search_contracts_group(q: str, size: int, offset: int) -> Dict[str, Any]:
    result = search_contracts(q=q or None, size=size, from_=offset)
    if result.get("error"):
        return _error_group("contracts", _label_for("contracts"), str(result["error"]))
    items = []
    for row in result.get("items", []):
        adjudicantes = _party_names(row.get("adjudicantes"))
        adjudicatarios = _party_names(row.get("adjudicatarios"))
        preco = row.get("precoContratual")
        parsed_adj = row.get("adjudicatarios") if isinstance(row.get("adjudicatarios"), dict) else {}
        primeira_parte = (parsed_adj.get("parsed") or [{}])[0] if parsed_adj else {}
        items.append(
            _item(
                "contracts",
                row.get("idcontrato") or row.get("doc_id") or "",
                row.get("objectoContrato") or row.get("descContrato") or "Contrato",
                subtitle=" → ".join(filter(None, [", ".join(adjudicantes[:2]), ", ".join(adjudicatarios[:2])])),
                snippet=row.get("descContrato") or row.get("objectoContrato") or "",
                date=row.get("dataPublicacao") or row.get("dataCelebracaoContrato"),
                badges=[row.get("Ano"), _flat(row.get("tipoContrato")), _flat(row.get("NUTs"))],
                # Nome e NIF da parte adjudicatária em campos próprios: é o que
                # liga o contrato à empresa na ontologia da pesquisa (e permite
                # abrir a ficha a partir do cartão).
                extra={
                    "preco": preco,
                    "cpv": _cpv_code(row.get("cpv")),
                    "adjudicatario": primeira_parte.get("nome") or (adjudicatarios[0] if adjudicatarios else None),
                    "adjudicatario_nif": primeira_parte.get("nif"),
                },
                open_view={"view": "contract-detail", "arg": str(row.get("idcontrato") or "")},
                score=row.get("score"),
            )
        )
    return _group("contracts", _label_for("contracts"), items, result.get("total", 0), 0)


def _search_contratos_es_group(q: str, size: int, offset: int) -> Dict[str, Any]:
    """Contratos públicos de Espanha (PLACSP).

    O índice `contratos_es` tem outro esquema (campos em castelhano) e é muito
    maior do que o português, pelo que é pesquisado com relevância quando há
    texto e ordenado por data de publicação quando não há.
    """
    result = search_contratos_es(
        q=q or None,
        size=size,
        from_=offset,
        sort_by="relevancia" if q else None,
        with_facets=False,
    )
    if result.get("error"):
        return _error_group("contracts_es", _label_for("contracts_es"), str(result["error"]))
    items = []
    for row in result.get("items", []):
        valor = row.get("valor_adjudicado")
        valor_tipo = "adjudicado"
        if not isinstance(valor, (int, float)):
            valor = row.get("valor_base")
            valor_tipo = "base"
        badges: List[Any] = [
            row.get("ano"),
            row.get("tipo_contrato_label"),
            row.get("estado_label"),
            row.get("localidad") or row.get("nuts"),
            "Contrato menor" if row.get("es_menor") else None,
        ]
        items.append(
            _item(
                "contracts_es",
                row.get("doc_id") or "",
                row.get("objeto") or row.get("descripcion") or "Contrato (Espanha)",
                subtitle=" → ".join(
                    filter(None, [str(row.get("organo_nombre") or ""), str(row.get("adjudicatario_nombre") or "")])
                ),
                snippet=row.get("descripcion") or row.get("objeto") or "",
                url=row.get("enlace") or "",
                date=row.get("fecha_publicacion") or row.get("fecha_adjudicacion"),
                badges=badges,
                extra={
                    "valor": valor if isinstance(valor, (int, float)) else None,
                    "valor_tipo": valor_tipo,
                    "organo": row.get("organo_nombre"),
                    "adjudicatario": row.get("adjudicatario_nombre"),
                    "adjudicatario_nif": row.get("adjudicatario_nif"),
                    "cpv": _cpv_code(row.get("cpv")),
                    "ano": row.get("ano"),
                    "fonte": row.get("fonte"),
                    "pais": "ES",
                    # A parte adjudicatária, para a ontologia ligar contrato → empresa.
                    "adjudicatario": row.get("adjudicatario_nombre"),
                    "adjudicatario_nif": row.get("adjudicatario_nif"),
                },
                open_view={"view": CONTRATOS_ES_VIEW, "arg": str(row.get("doc_id") or "")},
                score=row.get("score"),
            )
        )
    return _group("contracts_es", _label_for("contracts_es"), items, result.get("total", 0), 0)


def _search_entities_es_group(q: str, size: int, offset: int) -> Dict[str, Any]:
    """Quem contrata e quem ganha em Espanha (PLACSP).

    No índice espanhol cada documento é **um contrato**, por isso as entidades
    são nomes agregados: o grupo devolve os órgãos adjudicantes e as empresas
    adjudicatárias que casam com o termo, com o número de contratos e o valor
    adjudicado somado. Entrelaça os dois tipos para a página mostrar sempre
    entidades contratantes **e** empresas adjudicatárias.
    """
    result = search_contratos_es_entities(q=q or None, size=size, from_=offset)
    if result.get("error"):
        return _error_group("entities_es", _label_for("entities_es"), str(result["error"]))
    items = []
    for row in result.get("items", []):
        value = row.get("total_value")
        count = int(row.get("count") or 0)
        money = f"{value:,.0f} €".replace(",", " ") if isinstance(value, (int, float)) else "—"
        nif = row.get("nif")
        dir3 = row.get("organo_id")
        items.append(
            _item(
                "entities_es",
                f"{row.get('kind')}:{row.get('name')}",
                row.get("name") or "(sem nome)",
                subtitle=" · ".join(filter(None, [row.get("kind_label"), row.get("city"), row.get("nuts")])),
                snippet=f"{count:,} contratos · {money} adjudicado".replace(",", " "),
                badges=[
                    row.get("kind_label"),
                    f"NIF {nif}" if nif else (f"DIR3 {dir3}" if dir3 else None),
                    row.get("last_year"),
                ],
                extra={
                    "contratos": count,
                    "valor": value if isinstance(value, (int, float)) else None,
                    "kind": row.get("kind"),
                    "pais": "ES",
                },
                open_view={"view": CONTRATOS_ES_VIEW, "arg": str(row.get("name") or ""), "mode": str(row.get("kind") or "")},
            )
        )
    return _group("entities_es", _label_for("entities_es"), items, result.get("total", 0), 0)


def _search_entities_group(q: str, size: int, offset: int) -> Dict[str, Any]:
    result = search_entities(q=q or None, size=size, from_=offset)
    if result.get("error"):
        return _error_group("entities", _label_for("entities"), str(result["error"]))
    items = []
    for row in result.get("items", []):
        items.append(
            _item(
                "entities",
                row.get("nif") or row.get("name") or "",
                row.get("name") or "(sem nome)",
                subtitle=row.get("country") or "",
                snippet=f"{row.get('contracts_count') or 0} contratos · {row.get('total_value') or 0:,.0f} €".replace(",", " "),
                badges=[row.get("source"), "NIF " + str(row.get("nif")) if row.get("nif") else None],
                extra={
                    "contratos": row.get("contracts_count"),
                    "valor": row.get("total_value"),
                    "adjudicante": row.get("as_adjudicante_count"),
                    "adjudicatario": row.get("as_adjudicatario_count"),
                },
                open_view={"view": "company-detail", "arg": str(row.get("nif") or "")} if row.get("nif") else None,
            )
        )
    return _group("entities", _label_for("entities"), items, result.get("total", 0), 0)


def _search_trademarks_group(q: str, size: int, offset: int) -> Dict[str, Any]:
    result = search_trademarks(q=q or None, size=size, from_=offset)
    if result.get("error"):
        return _error_group("trademarks", _label_for("trademarks"), str(result["error"]))
    items = []
    for row in result.get("items", []):
        nif = row.get("company_nif") or row.get("holder_nif")
        items.append(
            _item(
                "trademarks",
                row.get("process_number") or row.get("mark_name") or "",
                row.get("mark_name") or "(marca)",
                subtitle=row.get("holder_name") or "",
                snippet=f"{row.get('mark_type') or ''} {row.get('current_phase') or ''}".strip(),
                date=row.get("application_date"),
                badges=[row.get("process_number"), row.get("modality")],
                open_view={"view": "company-detail", "arg": str(nif)} if nif else None,
            )
        )
    return _group("trademarks", _label_for("trademarks"), items, result.get("total", 0), 0)


def _search_firmas_group(q: str, size: int, offset: int) -> Dict[str, Any]:
    result = search_firmas(q=q or None, size=size, from_=offset)
    if result.get("error"):
        return _error_group("firmas", _label_for("firmas"), str(result["error"]))
    items = []
    for row in result.get("items", []):
        items.append(
            _item(
                "firmas",
                row.get("numero_certificado") or row.get("nipc") or row.get("nome") or "",
                row.get("nome") or "(firma)",
                subtitle=" · ".join(filter(None, [row.get("concelho"), row.get("cae_principal")])),
                snippet=row.get("situacao_detalhe") or row.get("situacao") or "",
                badges=[row.get("situacao"), "NIPC " + str(row.get("nipc")) if row.get("nipc") else None],
                open_view={"view": "company-detail", "arg": str(row.get("company_nif"))}
                if row.get("company_nif")
                else None,
            )
        )
    return _group("firmas", _label_for("firmas"), items, result.get("total", 0), 0)


def _search_news_group(client: Elasticsearch, q: str, size: int, offset: int) -> Dict[str, Any]:
    if not q:
        body: Dict[str, Any] = {
            "query": {"match_all": {}},
            "sort": [{"published": {"order": "desc", "missing": "_last"}}],
            "from": offset,
            "size": size,
        }
    else:
        body = {
            "query": {
                "bool": {
                    "should": [
                        {"multi_match": {"query": q, "fields": ["title^4", "translated_title^3", "summary^2", "summary_pt^2", "topics^2", "entities.name^2", "publisher", "topic^3"], "operator": "and", "lenient": True}},
                        {"term": {"ticker": q.upper()}},
                        # O tema com que a notícia foi recolhida (`topic`, em minúsculas na
                        # escrita): sem isto, uma notícia recolhida por tema só aparecia
                        # quando o termo calhava estar no título.
                        {"term": {"topic": q.strip().lower()}},
                    ],
                    "minimum_should_match": 1,
                }
            },
            "sort": ["_score", {"published": {"order": "desc", "missing": "_last"}}],
            "from": offset,
            "size": size,
            "track_total_hits": True,
        }
    resp = client.search(index=NEWS_INDEX, body=body)
    hits = resp.get("hits", {})
    total = hits.get("total", 0)
    total = total.get("value", 0) if isinstance(total, dict) else total
    items = []
    for hit in hits.get("hits", []):
        row = hit.get("_source") or {}
        ticker = str(row.get("ticker") or "").strip()
        topic = str(row.get("topic") or "").strip()
        # De onde vem a notícia: o ativo ou (sem ativo) o tema com que foi recolhida.
        origin = ticker or (f"tema: {topic}" if topic else "")
        badges = [
            badge
            for badge in [row.get("sentiment"), topic if not ticker else None, *(row.get("topics") or [])[:3]]
            if badge
        ]
        items.append(
            _item(
                "news",
                hit.get("_id") or row.get("url") or "",
                row.get("translated_title") or row.get("title") or "(notícia)",
                subtitle=" · ".join(filter(None, [row.get("publisher"), origin])),
                snippet=row.get("summary_pt") or row.get("translated_summary") or row.get("summary") or "",
                url=row.get("url") or "",
                date=row.get("published"),
                badges=badges,
                open_view={"view": "ticker-detail", "arg": ticker} if ticker else None,
                score=hit.get("_score"),
            )
        )
    market_total = total

    # Só o índice `finance_news`: notícias de mercado por ativo e por tema. A
    # imprensa recolhida dos jornais vive na **recolha** e tem âmbito próprio
    # (`imprensa`), para não se misturarem duas coisas com origens diferentes.
    return _group("news", _label_for("news"), items, market_total, 0)


def _search_imprensa_group(q: str, size: int, offset: int, filters: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    """Imprensa recolhida dos jornais (índice da recolha, sem cadastro).

    É a outra metade das notícias do IQ OS: o índice `finance_scraped` tem
    artigos da SAPO, Lusa, Jornal Económico, Observador, ECO, Dinheiro Vivo…
    misturados com cadastro de empresas (`empresas-*`, `iberinform-*`) e dados de
    ensaio (`tmp-*`), que ficam de fora — ver `NON_NEWS_SOURCE_*`. Os nomes dos
    jornais estão em `source_name`; o subtítulo de cada item leva-o. O filtro
    `fonte` limita a um jornal (é o que faz o clique numa faceta de fonte).
    """
    source = (filters or {}).get("fonte")
    result = search_scraped(
        q=q or None,
        size=size,
        from_=offset,
        sort="relevance" if q else "recent",
        source_id=source,
        exclude_prefixes=NON_NEWS_SOURCE_PREFIXES,
        exclude_ids=NON_NEWS_SOURCE_IDS,
    )
    if result.get("error"):
        return _error_group("imprensa", _label_for("imprensa"), str(result["error"]))
    items = []
    for hit in result.get("items", []):
        items.append(
            _item(
                "imprensa",
                hit.get("item_id") or hit.get("url") or "",
                hit.get("title") or "(notícia)",
                subtitle=" · ".join(
                    filter(None, [hit.get("source_name") or hit.get("source_id"), "recolha"])
                ),
                snippet=hit.get("summary") or hit.get("text") or "",
                url=hit.get("url") or "",
                date=hit.get("scraped_at"),
                badges=[*(hit.get("tags") or [])[:3]],
                sentiment={
                    "label": hit.get("sentiment") or "",
                    "polarity": hit.get("sentiment_score"),
                    "engine": hit.get("sentiment_engine") or "",
                }
                if hit.get("sentiment")
                else None,
            )
        )
    # As facetas alimentam o painel lateral de fontes/jornais: o âmbito da
    # imprensa traz as suas (sem cadastro) para que o painel continue a fazer
    # sentido quando a pesquisa está limitada a esse âmbito.
    facets = result.get("facets") or {}
    grupo = {
        **_group("imprensa", _label_for("imprensa"), items, int(result.get("total") or 0), 0),
        "facets": facets,
    }
    grupo["filters"] = _filter_panel(
        "imprensa",
        {
            "fonte": [
                {"key": entry.get("id") or entry["key"], "label": entry["key"], "count": entry["count"]}
                for entry in (facets.get("publishers") or [])
            ]
        },
    )
    return grupo


def _people_subtitle(row: Dict[str, Any], scope_id: str) -> str:
    """Subtítulo de uma ficha de pessoa: partido, círculo, cargos e fonte."""
    meta = row.get("metadata") or {}
    fonte = PEOPLE_SOURCE_LABELS.get(str(row.get("source") or ""), str(row.get("source") or ""))
    if scope_id == "politicos":
        return " · ".join(
            part for part in (row.get("name") and fonte, meta.get("partido"), meta.get("circulo_eleitoral")) if part
        )
    papeis = [str(entry.get("role") or "") for entry in (row.get("roles") or []) if entry.get("role")]
    cargo = papeis[0] if papeis else ""
    return " · ".join(
        part for part in (cargo, f"{int(row.get('roles_count') or 0)} cargos" if row.get("roles_count") else "", fonte) if part
    )


def _people_item(scope_id: str, row: Dict[str, Any]) -> Dict[str, Any]:
    """Item da pesquisa para uma ficha de `finance_people`."""
    meta = row.get("metadata") or {}
    fonte = PEOPLE_SOURCE_LABELS.get(str(row.get("source") or ""), str(row.get("source") or ""))
    url = meta.get("wiki_url") or meta.get("url_biografia") or ""
    if scope_id == "politicos":
        badges = [meta.get("partido"), meta.get("circulo_eleitoral"), fonte]
        extra = {"partido": meta.get("partido") or "", "cargo": meta.get("office") or "", "fonte": fonte}
    else:
        etiquetas = [str(t) for t in (row.get("tags") or []) if t not in (None, "")]
        badges = [*etiquetas[:2], fonte]
        extra = {
            "cargos": [
                " ".join(part for part in (entry.get("role"), entry.get("company_name")) if part)
                for entry in (row.get("roles") or [])[:6]
            ]
        }
    return _item(
        scope_id,
        row.get("nif") or "",
        row.get("name") or "(sem nome)",
        subtitle=_people_subtitle(row, scope_id),
        snippet=row.get("biography") or "",
        url=url,
        badges=badges,
        image=meta.get("photo_url") or row.get("photo_url") or "",
        extra=extra,
        open_view={"view": "person-detail", "arg": str(row.get("nif") or "")},
    )


#: Campos que a pesquisa de políticos também varre além do nome: sem isto,
#: procurar «deputado» ou «PS» não encontrava nenhum político.
POLITICOS_MATCH_FIELDS = ["metadata.office", "metadata.partido", "metadata.circulo_eleitoral"]


def _search_people_scope(
    scope_id: str,
    q: str,
    size: int,
    offset: int,
    filters: Optional[Dict[str, str]] = None,
    base_query: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Âmbitos «Pessoas» e «Políticos» (mesmo índice, universos diferentes)."""
    spec = SCOPE_FILTERS[scope_id]
    result = search_people_faceted(
        q=q or None,
        base_query=base_query,
        match_fields=POLITICOS_MATCH_FIELDS if scope_id == "politicos" else None,
        filters=_scope_filter_map(scope_id, filters),
        facet_fields={name: entry["field"] for name, entry in spec.items()},
        size=size,
        from_=offset,
        sort="relevance" if q else "name",
    )
    if result.get("error"):
        return _error_group(scope_id, _label_for(scope_id), str(result["error"]))
    items = [_people_item(scope_id, row) for row in (result.get("items") or [])]
    grupo = _group(scope_id, _label_for(scope_id), items, int(result.get("total") or 0), 0)
    facets = result.get("facets") or {}
    # A fonte mostra-se pelo nome (o valor guardado é um domínio).
    facets["fonte"] = [
        {
            "key": entry["key"],
            "label": PEOPLE_SOURCE_LABELS.get(str(entry["key"]), str(entry["key"])),
            "count": entry["count"],
        }
        for entry in (facets.get("fonte") or [])
    ]
    grupo["filters"] = _filter_panel(scope_id, facets)
    return grupo


def _search_pessoas_group(q: str, size: int, offset: int, filters: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    """Pessoas com ficha (só pessoas: as empresas têm o âmbito «Empresas»)."""
    return _search_people_scope(
        "pessoas", q, size, offset, filters, base_query={"term": {"is_company": False}}
    )


def _search_politicos_group(q: str, size: int, offset: int, filters: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    """Políticos portugueses: ficha da Wikipédia ou do parlamento, com filtros."""
    return _search_people_scope("politicos", q, size, offset, filters, base_query=POLITICOS_QUERY)


def _wikipedia_articles(term: str, langs: List[str], limit: int, offset: int) -> Dict[str, Any]:
    """Artigos da Wikipédia (uma consulta por idioma, em paralelo).

    Reutiliza as fontes da Pesquisa 360 (`search360_sources`), que já falam a
    API do MediaWiki — o âmbito da Pesquisa total é só a cola. `asyncio.run`
    aqui corre num *worker thread* da pesquisa, onde não há ciclo de eventos.
    Devolve os artigos da página e o **total real** de cada idioma (`totalhits`)
    e quantos já foram saltados, para a interface poder paginar e dizer o total.
    """
    from api.search360_sources import client as http_client
    from api.search360_sources import wikipedia_search_with_total

    async def run() -> List[Any]:
        async with http_client() as http:
            return await asyncio.gather(
                *[
                    wikipedia_search_with_total(http, term, lang=lang, limit=limit, offset=offset)
                    for lang in langs
                ],
                return_exceptions=True,
            )

    respostas = asyncio.run(run())
    artigos: List[Dict[str, Any]] = []
    total = 0
    for lang, resposta in zip(langs, respostas):
        if isinstance(resposta, BaseException):
            logger.info("Wikipédia (%s) indisponível: %s", lang, resposta)
            continue
        linhas, por_idioma = resposta
        total += int(por_idioma or 0)
        artigos.extend({"lang": lang, **row} for row in linhas)
    return {"items": artigos, "total": total, "offset": offset}


def _search_wikipedia_group(q: str, size: int, offset: int, filters: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    """Enciclopédia: artigos da Wikipédia PT (e EN), consultados em direto.

    Sem termo não se chama a API (não faz sentido listar a enciclopédia), e uma
    falha de rede devolve o erro **do âmbito**, sem derrubar os outros grupos.
    O `offset` vai ao `sroffset` do MediaWiki, pelo que o *scroll* infinito
    continua a trazer artigos novos (e o total é o da enciclopédia, não o da
    página).
    """
    if not q:
        return _group("wikipedia", _label_for("wikipedia"), [], 0, 0)
    fonte = (filters or {}).get("fonte")
    langs = ["en"] if fonte == "en" else (["pt"] if fonte == "pt" else ["pt", "en"])
    por_pagina = max(1, min(int(size), 50))
    try:
        resultado = _wikipedia_articles(q, langs, por_pagina, offset)
    except Exception as exc:
        return _error_group("wikipedia", _label_for("wikipedia"), f"Wikipédia: {exc}")
    artigos = resultado["items"]
    items = []
    for artigo in artigos:
        lang = str(artigo.get("lang") or "pt")
        items.append(
            _item(
                "wikipedia",
                artigo.get("id") or artigo.get("url") or "",
                artigo.get("title") or "(artigo)",
                subtitle=" · ".join(
                    part
                    for part in (
                        "Wikipédia PT" if lang == "pt" else "Wikipedia EN",
                        artigo.get("subtitle"),
                    )
                    if part
                ),
                snippet=artigo.get("snippet") or "",
                url=artigo.get("url") or "",
                date=artigo.get("date"),
                badges=["Wikipédia", lang.upper()],
                extra={"pageid": (artigo.get("data") or {}).get("pageid"), "idioma": lang},
                score=artigo.get("score"),
            )
        )
    # Contagens por idioma para o painel: o total de cada wiki e o que já veio.
    contagens = [
        {
            "key": lang,
            "label": "Wikipédia PT" if lang == "pt" else "Wikipedia EN",
            "count": sum(1 for artigo in artigos if artigo.get("lang") == lang),
        }
        for lang in langs
    ]
    grupo = _group("wikipedia", _label_for("wikipedia"), items, int(resultado["total"]), 0)
    grupo["filters"] = _filter_panel("wikipedia", {"fonte": contagens})
    return grupo


def _search_market_group(client: Elasticsearch, q: str, size: int, offset: int) -> Dict[str, Any]:
    query: Dict[str, Any]
    term = (q or "").strip().upper()
    if term:
        query = {
            "bool": {
                "should": [
                    {"term": {"ticker": term}},
                    {"prefix": {"ticker": term}},
                    {"wildcard": {"ticker": {"value": f"*{term}*", "case_insensitive": True}}},
                ],
                "minimum_should_match": 1,
            }
        }
    else:
        query = {"match_all": {}}
    resp = client.search(
        index=PRICES_INDEX,
        body={
            "size": 0,
            "query": query,
            "aggs": {
                "tickers": {
                    "terms": {"field": "ticker", "size": max(1, min(size, 50))},
                    "aggs": {
                        "last": {"top_hits": {"size": 1, "sort": [{"date": {"order": "desc"}}], "_source": ["date", "close", "period"]}},
                    },
                }
            },
        },
    )
    buckets = (resp.get("aggregations", {}).get("tickers", {}) or {}).get("buckets", [])
    items = []
    for bucket in buckets[offset:]:
        top = (bucket.get("last", {}).get("hits", {}).get("hits") or [{}])[0].get("_source", {})
        close = top.get("close")
        items.append(
            _item(
                "market",
                bucket["key"],
                bucket["key"],
                subtitle=f"último fecho {close:,.2f}".replace(",", " ") if isinstance(close, (int, float)) else "",
                snippet=f"{bucket['doc_count']} cotações indexadas · {top.get('date') or ''}",
                date=top.get("date"),
                badges=[top.get("period")],
                extra={"close": close, "pontos": bucket["doc_count"]},
                open_view={"view": "ticker-detail", "arg": str(bucket["key"])},
            )
        )
    return _group("market", _label_for("market"), items, len(buckets), 0)


def _search_crm_group(client: Elasticsearch, scope: Dict[str, Any], q: str, size: int, offset: int) -> Dict[str, Any]:
    query: Dict[str, Any] = {
        "bool": {
            "must": [
                {
                    "multi_match": {
                        "query": q,
                        "fields": ["name^4", "title^4", "subject^3", "role^2", "notes", "email", "city", "nif", "sector"],
                        "lenient": True,
                    }
                }
            ]
        }
    }
    if not scope.get("see_all"):
        query["bool"]["filter"] = [{"term": {"owner_id": scope["user_id"]}}]
    resp = client.search(
        index=CRM_INDEX,
        body={"query": query, "from": offset, "size": size, "track_total_hits": True, "sort": ["_score"]},
    )
    hits = resp.get("hits", {})
    total = hits.get("total", 0)
    total = total.get("value", 0) if isinstance(total, dict) else total
    kind_label = {"account": "Conta", "contact": "Contacto", "deal": "Oportunidade", "activity": "Atividade"}
    items = []
    for hit in hits.get("hits", []):
        row = hit.get("_source") or {}
        kind = row.get("kind") or "account"
        record_id = row.get("id") or ""
        title = row.get("name") or row.get("title") or row.get("subject") or "(registro)"
        view = f"crm-account:{record_id}" if kind == "account" else f"crm-edit:{kind}s:{record_id}"
        items.append(
            _item(
                "crm",
                f"{kind}:{record_id}",
                title,
                subtitle=" · ".join(filter(None, [kind_label.get(kind, kind), row.get("sector") or row.get("role")])),
                snippet=row.get("notes") or row.get("email") or row.get("subject") or "",
                date=row.get("updated_at") or row.get("created_at"),
                badges=[kind_label.get(kind, kind), row.get("stage"), row.get("status")],
                open_view={"view": view, "arg": record_id},
                score=hit.get("_score"),
            )
        )
    return _group("crm", _label_for("crm"), items, total, 0)


# ------------------------------------------------------------------ pesquisa
def unified_search(
    q: str,
    *,
    scope: str = "all",
    size: int = 8,
    offset: int = 0,
    filters: Optional[str] = None,
    session_scope: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Pesquisa por texto em todos os âmbitos (ou num só) e devolve grupos.

    `filters` são as facetas escolhidas na interface (`{"partido": "PS"}` ou
    `partido:PS`): cada âmbito aplica só as que conhece (`SCOPE_FILTERS`), pelo
    que um filtro de outra área é simplesmente ignorado.
    """
    query = (q or "").strip()
    filtros = parse_filters(filters)
    size = max(1, min(int(size), 50))
    offset = max(0, int(offset))
    requested = [scope] if scope in SCOPE_IDS else list(SCOPE_IDS)
    if "crm" in requested and not session_scope:
        requested = [s for s in requested if s != "crm"]

    client = get_es_client()
    if not client:
        return {"query": query, "total": 0, "groups": [], "error": "Elasticsearch indisponível", "scopes": SCOPES}
    ensure_indices(client)

    workers: Dict[str, Any] = {
        "scraped": lambda: _search_scraped_group(query, size, offset, filtros),
        "social": lambda: _search_social_group(query, size, offset, filtros),
        "contracts": lambda: _search_contracts_group(query, size, offset),
        "contracts_es": lambda: _search_contratos_es_group(query, size, offset),
        "entities_es": lambda: _search_entities_es_group(query, size, offset),
        "entities": lambda: _search_entities_group(query, size, offset),
        "pessoas": lambda: _search_pessoas_group(query, size, offset, filtros),
        "politicos": lambda: _search_politicos_group(query, size, offset, filtros),
        "wikipedia": lambda: _search_wikipedia_group(query, size, offset, filtros),
        "trademarks": lambda: _search_trademarks_group(query, size, offset),
        "firmas": lambda: _search_firmas_group(query, size, offset),
        "news": lambda: _search_news_group(client, query, size, offset),
        "imprensa": lambda: _search_imprensa_group(query, size, offset, filtros),
        "market": lambda: _search_market_group(client, query, size, offset),
        "crm": lambda: _search_crm_group(client, session_scope or {}, query, size, offset),
    }

    started = datetime.now()
    groups: List[Dict[str, Any]] = []
    with ThreadPoolExecutor(max_workers=min(4, max(1, len(requested)))) as pool:
        futures = {}
        for scope_id in requested:
            label = _label_for(scope_id)
            task = workers.get(scope_id)
            if not task:
                continue
            future = pool.submit(task)
            futures[future] = (scope_id, label)
        for future, (scope_id, label) in futures.items():
            try:
                group = future.result(timeout=25)
            except Exception as exc:
                logger.warning("Pesquisa unificada: âmbito %s falhou: %s", scope_id, exc)
                group = _error_group(scope_id, label, f"{type(exc).__name__}: {exc}")
            groups.append(group)

    order = {scope_id: index for index, scope_id in enumerate(SCOPE_IDS)}
    groups.sort(key=lambda g: order.get(g["scope"], 99))
    took_ms = int((datetime.now() - started).total_seconds() * 1000)
    return {
        "query": query,
        "scope": scope,
        "size": size,
        "offset": offset,
        "filters": filtros,
        "took_ms": took_ms,
        "total": sum(g["total"] for g in groups),
        "groups": groups,
        "scopes": SCOPES,
        "facets": next(
            (
                g.get("facets")
                for g in groups
                if g["scope"] in {"scraped", "imprensa"} and g.get("facets")
            ),
            {},
        ),
    }


def suggest(q: str, *, limit: int = 8, session_scope: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Sugestões para a caixa de pesquisa (entidades, recolha, tickers, Espanha)."""
    query = (q or "").strip()
    if len(query) < 2:
        return {"query": query, "items": []}

    items: List[Dict[str, Any]] = []
    client = get_es_client()
    if not client:
        return {"query": query, "items": []}
    ensure_indices(client)

    def entities() -> List[Dict[str, Any]]:
        result = search_entities(q=query, size=limit)
        return [
            {"text": row.get("name") or "", "scope": "entities", "hint": f"Empresa · NIF {row.get('nif') or '—'}", "arg": str(row.get("nif") or "")}
            for row in (result.get("items") or [])
            if row.get("name")
        ]

    def scraped() -> List[Dict[str, Any]]:
        result = search_scraped(q=query, size=limit, sort="relevance")
        return [
            {"text": hit.get("title") or "", "scope": "scraped", "hint": hit.get("source_name") or "Recolha", "arg": hit.get("item_id") or ""}
            for hit in (result.get("items") or [])
            if hit.get("title")
        ]

    def contratos_es() -> List[Dict[str, Any]]:
        """Órgãos, adjudicatários e CPV do PLACSP (abre no âmbito de entidades)."""
        label = {"organo": "Órgão (ES)", "adjudicatario": "Adjudicatária (ES)", "cpv": "CPV (ES)"}
        result = contratos_es_autocomplete(q=query, size=limit)
        return [
            {
                "text": entry.get("text") or "",
                "scope": "entities_es",
                "hint": f"{label.get(entry.get('type') or '', 'Espanha')} · {entry.get('count') or 0}",
                "arg": entry.get("text") or "",
            }
            for entry in (result.get("suggestions") or [])
            if entry.get("text")
        ]

    def tickers() -> List[Dict[str, Any]]:
        resp = client.search(
            index=PRICES_INDEX,
            body={
                "size": 0,
                "query": {"prefix": {"ticker": query.upper()}},
                "aggs": {"tickers": {"terms": {"field": "ticker", "size": limit}}},
            },
        )
        buckets = (resp.get("aggregations", {}).get("tickers", {}) or {}).get("buckets", [])
        return [{"text": b["key"], "scope": "market", "hint": f"Mercado · {b['doc_count']} cotações", "arg": b["key"]} for b in buckets]

    by_kind: Dict[str, List[Dict[str, Any]]] = {}
    with ThreadPoolExecutor(max_workers=4) as pool:
        jobs = {
            "entities": pool.submit(entities),
            "scraped": pool.submit(scraped),
            "market": pool.submit(tickers),
            "contracts_es": pool.submit(contratos_es),
        }
        for name, job in jobs.items():
            try:
                entries = list(job.result(timeout=10))
            except Exception as exc:
                logger.debug("Sugestões (%s) falharam: %s", name, exc)
                continue
            for entry in entries:
                entry["kind"] = name
            by_kind[name] = entries

    # Intercala as fontes (a 1.ª sugestão de cada uma aparece sempre), para
    # nenhuma ficar sem espaço — sem isto o Espanha nunca chegava à lista.
    depth = max((len(entries) for entries in by_kind.values()), default=0)
    for index in range(depth):
        for entries in by_kind.values():
            if index < len(entries):
                items.append(entries[index])

    seen = set()
    unique: List[Dict[str, Any]] = []
    for entry in items:
        key = (entry["scope"], entry["text"].lower())
        if key in seen or not entry["text"]:
            continue
        seen.add(key)
        unique.append(entry)
    return {"query": query, "items": unique[: max(1, min(limit * 2, 20))]}


def scopes_catalog() -> List[Dict[str, Any]]:
    """Catálogo de âmbitos para a UI."""
    return [
        {"id": "all", "label": "Tudo", "hint": "Todos os âmbitos com resultados"},
        *SCOPES,
    ]


def external_search_url(q: str) -> str:
    """Ligação de recurso para pesquisar fora do IQ OS."""
    return f"https://duckduckgo.com/?q={quote_plus(q)}"
