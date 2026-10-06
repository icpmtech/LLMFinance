"""Serviço OSINT baseado no user-scanner (kaifcodec/user-scanner).

Integra a engine de username/email do user-scanner com o Elasticsearch do IQ OS,
guardando cada pesquisa no índice ``finance_osint`` e devolvendo um grafo simples
para visualização das plataformas encontradas.

Além de usernames e emails, aceita **NIF** como alvo: nesse caso não há scan
externo — o valor é validado (dígito de controlo) e cruzado com o que o próprio
IQ OS já tem indexado (contribuintes, contratos, societário, CIRE, cadastro e
ontologia), devolvendo-se tudo na mesma forma (`hits`/`pivots`/`graph`).
"""
from __future__ import annotations

import asyncio
import hashlib
import logging
import re
import time
import unicodedata
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List, Optional, Tuple

try:
    from user_scanner.core import confidence as us_confidence
    from user_scanner.core import engine as us_engine
    from user_scanner.core import pivots as us_pivots
    _USER_SCANNER_AVAILABLE = True
except Exception:  # pragma: no cover - dependência opcional não instalada
    us_confidence = None  # type: ignore
    us_engine = None  # type: ignore
    us_pivots = None  # type: ignore
    _USER_SCANNER_AVAILABLE = False

from api.elasticsearch_client import ensure_indices, get_es_client

logger = logging.getLogger(__name__)

OSINT_INDEX = "finance_osint"

# Categorias comuns rápidas por tipo de alvo. O scan completo pode levar
# vários minutos (2510+ módulos), por isso o modo normal restringe a uma
# categoria representativa e o utilizador pode pedir full_scan.
# Atenção: a categoria tem de existir em `load_categories(is_email=...)` — uma
# categoria inexistente (era o caso de "global" para email) fazia o scan cair
# silenciosamente na primeira da lista (`adult`).
DEFAULT_CATEGORY: Dict[str, str] = {
    "username": "finance",
    "email": "crm",
}

# Tipos de alvo aceites. `nif` não usa o user-scanner: cruza os dados internos.
OSINT_KINDS = ("username", "email", "nif")
# Tipos em que o conceito de "categoria de plataformas" não se aplica.
KINDS_WITHOUT_CATEGORY = ("nif",)

# Presets de categorias para o UI: poupam escolher uma a uma e dão uma noção
# do custo (cada categoria são dezenas/centenas de pedidos a sites externos).
CATEGORY_PRESETS: List[Dict[str, Any]] = [
    {
        "id": "identidade",
        "label": "Identidade",
        "hint": "Perfis pessoais e redes sociais",
        "username": ["social", "community", "creator", "dating"],
        "email": ["social", "community", "creator"],
    },
    {
        "id": "profissional",
        "label": "Profissional / técnico",
        "hint": "Repositórios, portefólios e redes de trabalho",
        "username": ["dev", "learning", "finance"],
        "email": ["dev", "jobs", "learning"],
    },
    {
        "id": "comercio",
        "label": "Compras e serviços",
        "hint": "Lojas, viagens e serviços com conta de cliente",
        "username": ["shopping", "music", "entertainment"],
        "email": ["shopping", "travel", "music", "news"],
    },
    {
        "id": "completo",
        "label": "Todas as categorias",
        "hint": "Varredura completa — demora vários minutos",
        "username": [],
        "email": [],
    },
]

# Quantas categorias correr ao mesmo tempo. Medido em `dev`+`learning` (726
# plataformas, container Docker): paralelo 54,9 s / 252 erros vs sequencial
# 58,0 s / 216 erros. O paralelismo poupa ~5% do tempo mas aumenta 17% os erros
# (os sites bloqueiam pedidos simultâneos do mesmo IP), e como «Found» só sai do
# que respondeu bem, o sequencial dá mais resultados úteis. Fica em 1.
_MAX_PARALLEL_CATEGORIES = 1


def category_platform_counts(is_email: bool = False, es: Any = None) -> Dict[str, int]:
    """Número de plataformas verificadas por cada categoria.

    Serve para o UI mostrar o custo antes de lançar o scan: escolher uma
    categoria de 400 plataformas não é o mesmo que escolher uma de 30.
    """
    if not _USER_SCANNER_AVAILABLE or us_engine is None:
        return {}
    counts: Dict[str, int] = {}
    for name, path in us_engine.load_categories(is_email=is_email).items():
        try:
            counts[name] = len(us_engine.load_modules(path))
        except Exception:  # pragma: no cover - depende da biblioteca
            counts[name] = 0
    return counts

# Status numéricos do user-scanner -> label amigável
STATUS_LABEL = {0: "Found", 1: "Not Found", 2: "Error", 3: "Skipped"}

# Validação mínima de email (sem depender de libs extra).
_EMAIL_RE = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]{2,}$")

_NIF_RE = re.compile(r"^\d{9}$")


def is_valid_nif(value: str) -> bool:
    """Valida um NIF português: 9 dígitos com dígito de controlo (módulo 11).

    O dígito de controlo é o último e resulta de somar os 8 primeiros dígitos
    multiplicados por pesos decrescentes de 9 a 2; o resto da divisão por 11 dá
    o dígito (0 quando o resto é 0 ou 1).
    """
    text = str(value or "").strip()
    if not _NIF_RE.match(text):
        return False
    if text[0] in "04" or text[0] == "0":
        # Primeiro dígito define o tipo de contribuinte (1/2/3/5/6/7/8/9).
        return False
    total = sum(int(digit) * weight for digit, weight in zip(text[:8], range(9, 1, -1)))
    check = 11 - (total % 11)
    if check >= 10:
        check = 0
    return check == int(text[8])


def normalize_nif(value: str) -> str:
    """NIF sem espaços nem pontuação (`500 189 412` → `500189412`)."""
    return re.sub(r"\D", "", str(value or ""))

# Cada site nomeia os campos à sua maneira (`name`, `fullname`, `display_name`,
# `gravatar_username`…). Estas tabelas traduzem tudo para um perfil comum, para
# que a UI mostre o mesmo tipo de detalhe em todas as plataformas.
_NAME_KEYS = ("name", "fullname", "display_name", "displayname", "nickname", "gravatar_username")
_BIO_KEYS = ("bio", "about", "description", "bio_text", "summary", "tagline")
_FOLLOWERS_KEYS = ("followers", "follower_count", "followers_count", "subscribers")
_JOINED_KEYS = ("created", "created_at", "joined", "registered", "since", "member_since")
_LINK_KEYS = ("links", "website", "blog", "homepage", "url", "github", "twitter", "instagram", "linkedin")
_AVATAR_KEYS = ("avatar", "avatar_url", "gravatar_url", "image", "image_url", "profile_image", "photo")
# Contadores que interessam apresentar lado a lado com o nome.
_METRIC_KEYS = (
    "followers", "following", "public_repos", "public_gists", "packages", "packages_count",
    "models", "datasets", "spaces", "ranking", "reputation", "karma", "posts", "stars",
)
# Campos internos do motor que não são dados do perfil.
_OWN_KEYS = {"id", "uid", "type", "state", "is_email", "status"}

_EMAIL_IN_TEXT_RE = re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}")
_URL_IN_TEXT_RE = re.compile(r"https?://[^\s,;)\]]+")


def _first(extra: Dict[str, Any], keys: Iterable[str]) -> Optional[str]:
    for key in keys:
        value = extra.get(key)
        if value is None:
            continue
        text = str(value).strip()
        if text and text.lower() not in {"none", "null", ""}:
            return text
    return None


def _split_links(value: Optional[str]) -> List[str]:
    """`links` vem ora como uma lista, ora como uma string com vários URLs."""
    if not value:
        return []
    found = _URL_IN_TEXT_RE.findall(value)
    if found:
        return [url.rstrip(".,;) ") for url in found]
    return [part.strip() for part in re.split(r"[,;\s]+", value) if part.strip().startswith("http")]


def _value_list(value: Any) -> List[str]:
    if isinstance(value, (list, tuple, set)):
        return [str(v).strip() for v in value if str(v).strip()]
    if isinstance(value, str):
        return [value.strip()] if value.strip() else []
    return []


def _profile_of(extra: Dict[str, Any], media: Dict[str, Any]) -> Dict[str, Any]:
    """Campos de apresentação comuns, independentes do site."""
    links: List[str] = []
    for key in _LINK_KEYS:
        for value in _value_list(extra.get(key)):
            links.extend(_split_links(value) or [value])
    # `links` pode trazer handles soltos (ex.: "https://x.com/k, https://ig/k").
    for key in ("links", "website", "blog", "homepage"):
        links.extend(_split_links(extra.get(key)))
    deduped: List[str] = []
    for link in links:
        if link and link not in deduped:
            deduped.append(link)

    metrics = {key: extra[key] for key in _METRIC_KEYS if extra.get(key) not in (None, "", [])}
    avatar = None
    for key in _AVATAR_KEYS:
        value = media.get(key)
        if value and isinstance(value, str) and value.startswith("http"):
            avatar = value
            break

    return {
        "display_name": _first(extra, _NAME_KEYS),
        "bio": _first(extra, _BIO_KEYS),
        "avatar": avatar,
        "followers": _first(extra, _FOLLOWERS_KEYS),
        "joined": _first(extra, _JOINED_KEYS),
        "links": deduped[:12],
        "metrics": {k: v for k, v in list(metrics.items())[:8]},
        "fields": {
            key: value
            for key, value in extra.items()
            if key not in _OWN_KEYS and isinstance(value, (str, int, float)) and value not in (None, "")
        },
    }


def _leads_from(hit: Dict[str, Any]) -> Dict[str, List[str]]:
    """Emails e URLs que o perfil revela (o `extra` do Pypi traz mesmo um email)."""
    texts: List[str] = list(hit.get("profile", {}).get("links") or [])
    texts.extend(str(v) for v in (hit.get("profile", {}).get("fields") or {}).values())
    bio = (hit.get("profile") or {}).get("bio")
    if bio:
        texts.append(bio)
    if hit.get("url"):
        texts.append(hit["url"])
    blob = " | ".join(t for t in texts if t)

    emails: List[str] = []
    for match in _EMAIL_IN_TEXT_RE.findall(blob):
        low = match.lower()
        if low not in emails and not low.endswith(("example.com", "sentry.io")):
            emails.append(low)

    urls: List[str] = []
    for candidate in _URL_IN_TEXT_RE.findall(blob):
        url = candidate.rstrip(".,;) ")
        if url and url not in urls:
            urls.append(url)
    return {"emails": emails[:10], "urls": urls[:20]}


def _confidence_of(raw_results: List[Any]) -> Dict[str, str]:
    """Score do user-scanner (`likely/candidate/conflicting`) por site.

    As âncoras (nome, bio, emails, links) são construídas a partir dos perfis
    encontrados e cada perfil é pontuado **contra** elas. Só marcar tudo como
    `confirmed` não distinguia nada: o que interessa saber é quais as plataformas
    que partilham identidade com as outras (mesmo nome/links) e quais são
    homónimos que só coincidem no handle.
    """
    if not _USER_SCANNER_AVAILABLE or us_confidence is None:
        return {}
    confirmed = [r for r in raw_results if str(getattr(r, "status", "")) == "Found"]
    if not confirmed:
        return {}
    try:
        anchors = us_confidence.build_anchors(confirmed)
    except Exception as exc:  # pragma: no cover - depende da biblioteca
        logger.warning("Falha a construir âncoras OSINT: %s", exc)
        return {}
    scores: Dict[str, str] = {}
    for item in confirmed:
        try:
            scores[str(getattr(item, "site_name", ""))] = us_confidence.score(item, anchors, False).value
        except Exception:
            continue
    return scores


def _pivots_of(raw_results: List[Any]) -> List[Dict[str, Any]]:
    """Contas cruzadas: handles/links que apontam para outras plataformas."""
    if not _USER_SCANNER_AVAILABLE or us_pivots is None:
        return []
    try:
        extracted = us_pivots.select_pivots(us_pivots.extract_pivots(raw_results), "all")
    except Exception as exc:  # pragma: no cover - depende da biblioteca
        logger.warning("Falha a extrair pivots OSINT: %s", exc)
        return []
    out: List[Dict[str, Any]] = []
    for pivot in extracted:
        out.append({
            "handle": getattr(pivot, "username", None),
            "kind": getattr(getattr(pivot, "kind", None), "value", None),
            "source_site": getattr(pivot, "source_site", None),
            "source_key": getattr(pivot, "source_key", None),
            "site": getattr(pivot, "site", None),
            "url": getattr(pivot, "url", None) or None,
        })
    return out


def _stats_of(hits: List[Dict[str, Any]], pivots: List[Dict[str, Any]]) -> Dict[str, Any]:
    found = [h for h in hits if str(h.get("status", "")).lower() == "found"]
    named = [h for h in found if (h.get("profile") or {}).get("display_name")]
    with_avatar = [h for h in found if (h.get("profile") or {}).get("avatar")]
    emails: List[str] = []
    urls: List[str] = []
    for hit in found:
        leads = hit.get("leads") or {}
        emails.extend(leads.get("emails") or [])
        urls.extend(leads.get("urls") or [])
    return {
        "platforms_found": len(found),
        "platforms_with_name": len(named),
        "platforms_with_avatar": len(with_avatar),
        "names": sorted({(h["profile"] or {})["display_name"] for h in named})[:10],
        "emails": sorted(set(emails))[:10],
        "pivot_count": len(pivots),
        "pivot_sites": sorted({p.get("site") for p in pivots if p.get("site")}),
    }


def _today() -> str:
    return datetime.now(timezone.utc).isoformat()


def _result_to_hit(result: Any) -> Dict[str, Any]:
    data = result.to_dict() if hasattr(result, "to_dict") else dict(result)
    extra = data.get("extra") or {}
    media = data.get("media") or {}
    if not isinstance(extra, dict):
        extra = {}
    if not isinstance(media, dict):
        media = {}
    hit = {
        "status": STATUS_LABEL.get(data.get("status"), str(data.get("status"))),
        "site_name": data.get("site_name") or "",
        "category": data.get("category") or "",
        "url": data.get("url") or None,
        "reason": data.get("reason") or None,
        "extra": extra,
        "media": media,
    }
    hit["profile"] = _profile_of(extra, media)
    hit["leads"] = _leads_from(hit)
    return hit


def _build_graph(
    hits: List[Dict[str, Any]],
    target: str,
    kind: str,
    pivots: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    """Grafo alvo → plataformas encontradas → contas cruzadas.

    As contas cruzadas (pivôs) são o que torna o grafo útil: mostram plataformas
    que não foram testadas mas para onde o perfil aponta (ex.: o GitHub do alvo
    declara o Instagram e o X).
    """
    nodes: List[Dict[str, Any]] = [
        {
            "id": target,
            "label": target,
            "group": kind,
            "url": None,
            "details": f"Alvo da pesquisa OSINT ({kind})",
        }
    ]
    edges: List[Dict[str, Any]] = []
    found_hits = [h for h in hits if str(h.get("status")).lower() in {"found", "taken"}]
    site_node_ids: Dict[str, str] = {}
    for h in found_hits:
        site = h.get("site_name") or "unknown"
        node_id = f"{site}:{h.get('url') or site}"
        site_node_ids[site.lower()] = node_id
        profile = h.get("profile") or {}
        bits = [profile.get("display_name"), profile.get("bio")]
        metrics = profile.get("metrics") or {}
        if metrics:
            bits.append(" · ".join(f"{k}: {v}" for k, v in metrics.items()))
        nodes.append(
            {
                "id": node_id,
                "label": site,
                "group": h.get("category") or "site",
                "url": h.get("url"),
                "details": " · ".join(b for b in bits if b) or (h.get("reason") or ""),
                "avatar": profile.get("avatar"),
                "confidence": h.get("confidence"),
            }
        )
        edges.append({"source": target, "target": node_id, "label": "encontrado em"})

    for pivot in pivots or []:
        site = pivot.get("site") or pivot.get("source_key") or "pivot"
        url = pivot.get("url")
        pivot_id = f"cross:{site}:{pivot.get('handle') or ''}"
        if any(n["id"] == pivot_id for n in nodes):
            continue
        nodes.append(
            {
                "id": pivot_id,
                "label": f"{site}",
                "group": "cross",
                "url": url,
                "details": f"conta cruzada: {pivot.get('handle')} (via {pivot.get('source_site')}/{pivot.get('source_key')})",
                "avatar": None,
                "confidence": "cross",
            }
        )
        origin = site_node_ids.get(str(pivot.get("source_site") or "").lower())
        edges.append({
            "source": origin or target,
            "target": pivot_id,
            "label": f"expõe {pivot.get('source_key') or 'link'}",
        })
    return {"nodes": nodes, "edges": edges}


async def _check_categories(names: List[str], target: str, *, is_email: bool) -> List[Any]:
    """Corre várias categorias em paralelo, com um limite de concorrência.

    Cada categoria faz dezenas/centenas de pedidos a sites externos; correr tudo
    ao mesmo tempo faz os sites bloquear (mais erros e menos resultados), por
    isso o limite é baixo e as falhas de uma categoria não abortam as outras.
    """
    semaphore = asyncio.Semaphore(_MAX_PARALLEL_CATEGORIES)

    async def run(name: str) -> List[Any]:
        async with semaphore:
            try:
                return await us_engine.check_category(name, target, is_email=is_email)
            except Exception as exc:
                logger.warning("Categoria OSINT '%s' falhou para %s: %s", name, target, exc)
                return []

    batches = await asyncio.gather(*(run(name) for name in names))
    merged: List[Any] = []
    for batch in batches:
        merged.extend(batch)
    return merged


def _fmt_money(value: Any) -> Optional[str]:
    """Formata um valor em euros de forma legível (M€/k€)."""
    try:
        amount = float(value)
    except (TypeError, ValueError):
        return None
    if amount >= 1_000_000:
        return f"{amount / 1_000_000:.2f} M€"
    if amount >= 1_000:
        return f"{amount / 1_000:.1f} k€"
    return f"{amount:.2f} €"


def _nif_hit(
    label: str,
    *,
    name: Optional[str],
    metrics: Dict[str, Any],
    fields: Dict[str, Any],
    url: Optional[str] = None,
    details: str = "",
    emails: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """Converte um bloco de dados internos num hit compatível com os do scanner."""
    return {
        "status": "Found",
        "site_name": label,
        "category": "Dados internos",
        "url": url,
        "reason": details or None,
        "extra": fields,
        "media": {},
        "profile": {
            "display_name": name,
            "bio": details or None,
            "avatar": None,
            "followers": None,
            "joined": None,
            "links": [url] if url else [],
            "metrics": {k: v for k, v in metrics.items() if v not in (None, "", 0)},
            "fields": {k: v for k, v in fields.items() if isinstance(v, (str, int, float)) and v not in (None, "")},
        },
        "leads": {"emails": list(emails or []), "urls": [url] if url else []},
        "confidence": "confirmed",
    }


def scan_nif(nif: str) -> Dict[str, Any]:
    """Ficha de um NIF: validação + cruzamento com os dados internos do IQ OS.

    Não faz scan externo. A ideia é aproveitar o que já está indexado
    (contribuintes, contratos, societário, CIRE, cadastro, ontologia e pessoas)
    para responder «o que sabemos sobre este NIF» num só pedido.
    """
    from api import contribuintes_service  # import tardio: evita ciclos

    raw = str(nif or "").strip()
    normalized = normalize_nif(raw)
    if not _NIF_RE.match(normalized):
        raise ValueError("NIF inválido: escreva 9 dígitos (ex.: 500189412).")
    if not is_valid_nif(normalized):
        raise ValueError(
            f"NIF {normalized} inválido: o dígito de controlo não confere. "
            "Confirme os 9 dígitos."
        )

    t0 = time.time()
    hits: List[Dict[str, Any]] = []
    pivots: List[Dict[str, Any]] = []
    internal_url = f"/empresas-iq/{normalized}"

    detail: Dict[str, Any] = {}
    try:
        detail = contribuintes_service.detail(normalized) or {}
    except Exception as exc:  # pragma: no cover - depende do índice
        logger.warning("Falha a ler contribuintes do NIF %s: %s", normalized, exc)
        detail = {"error": str(exc)}

    name = detail.get("name") if isinstance(detail, dict) else None
    if detail.get("error"):
        hits.append(_nif_hit(
            "Contribuintes (IQ OS)",
            name=None,
            metrics={},
            fields={"nif": normalized, "erro": detail["error"]},
            details="Não há registo deste NIF no índice de contribuintes.",
        ))

    # -- uma entrada por fonte que contribuiu para o registo agregado ---------
    for source in getattr(contribuintes_service, "SOURCES", []):
        block = detail.get(f"src_{source['id']}")
        if not isinstance(block, dict) or not block.get("count"):
            continue
        parts = block.get("parts") or {}
        metrics: Dict[str, Any] = {"registos": block.get("count")}
        if block.get("value"):
            metrics["valor"] = _fmt_money(block.get("value"))
        for role, data in list(parts.items())[:3]:
            metrics[role] = data.get("count")
        fields = {
            "nif": normalized,
            "nomes": block.get("names") or [],
            "papeis": block.get("roles") or [],
            "primeiro": (block.get("first") or "")[:10] or None,
            "ultimo": (block.get("last") or "")[:10] or None,
            "detalhe": block.get("detail") or {},
        }
        hits.append(_nif_hit(
            str(block.get("label") or source["label"]),
            name=name,
            metrics=metrics,
            fields=fields,
            url=internal_url,
            details=(
                f"{block.get('count')} registo(s)"
                + (f" · {_fmt_money(block.get('value'))}" if block.get("value") else "")
                + (f" · papéis: {', '.join(block.get('roles') or [])}" if block.get("roles") else "")
            ),
        ))

    # -- cadastro de entidades ------------------------------------------------
    try:
        from api.elasticsearch_client import get_entity_by_nif

        entity = get_entity_by_nif(normalized) or {}
        if entity and not entity.get("error"):
            hits.append(_nif_hit(
                "Cadastro · contratos agregados",
                name=entity.get("name") or name,
                metrics={
                    "contratos": entity.get("contracts_count"),
                    "valor": _fmt_money(entity.get("total_value")),
                    "como adjudicatário": entity.get("as_adjudicatario_count"),
                    "como adjudicante": entity.get("as_adjudicante_count"),
                },
                fields={
                    "nif": normalized,
                    "pais": entity.get("country"),
                    "fonte": entity.get("source"),
                },
                url=internal_url,
                details=f"{entity.get('country') or ''} · {entity.get('contracts_count') or 0} contratos".strip(" ·"),
            ))
    except Exception as exc:  # pragma: no cover
        logger.debug("Cadastro de entidades indisponível para %s: %s", normalized, exc)

    # -- relações de ontologia ------------------------------------------------
    try:
        from api.elasticsearch_client import get_entity_relations

        relations = get_entity_relations(normalized) or {}
        if relations.get("total"):
            for item in (relations.get("items") or [])[:20]:
                pivots.append({
                    "handle": item.get("other_ref"),
                    "kind": item.get("kind") or "relation",
                    "source_site": "Ontologia",
                    "source_key": item.get("kind"),
                    "site": item.get("other_name") or item.get("other_ref"),
                    "url": f"/empresas-iq/{item.get('other_ref')}" if item.get("other_ref") else None,
                })
            hits.append(_nif_hit(
                "Relações (ontologia)",
                name=name,
                metrics={"relações": relations.get("total")},
                fields={"por tipo": relations.get("by_kind") or {}},
                url=internal_url,
                details=", ".join(f"{k}: {v}" for k, v in (relations.get("by_kind") or {}).items()),
            ))
    except Exception as exc:  # pragma: no cover
        logger.debug("Ontologia indisponível para %s: %s", normalized, exc)

    # -- pessoas (quadro societário / intervenientes) -------------------------
    try:
        from api.elasticsearch_client import get_person_by_nif

        person = get_person_by_nif(normalized) or {}
        if person and not person.get("error"):
            hits.append(_nif_hit(
                "Quadro societário (pessoas)",
                name=person.get("name") or name,
                metrics={},
                fields={"nif": normalized, "papeis": person.get("roles") or []},
                details="Pessoa presente nas publicações societárias.",
            ))
    except Exception as exc:  # pragma: no cover
        logger.debug("Pessoas indisponível para %s: %s", normalized, exc)

    # -- dossiê detalhado (contratos, cargos, insolvências, sinais) -----------
    dossier: Dict[str, Any] = {}
    try:
        from api import padroes_service

        dossier = padroes_service.entity_dossier(normalized) or {}
        if dossier.get("nome"):
            name = dossier["nome"] or name
        resumo = dossier.get("resumo") or {}
        cargos = dossier.get("cargos_sociais") or []
        insolvencias = dossier.get("insolvencias") or []
        sinais = dossier.get("sinais") or []

        if resumo or cargos or insolvencias:
            lidos = len(dossier.get("contratos") or [])
            total_contratos = dossier.get("contratos_total") or lidos
            parcial = lidos < total_contratos
            hits.append(_nif_hit(
                "Dossiê de contratos",
                name=name,
                metrics={
                    "contratos": total_contratos,
                    "valor total": _fmt_money(resumo.get("valor_total")),
                    "adjudicantes": resumo.get("adjudicantes_distintos"),
                    "ajuste direto": (
                        f"{float(resumo['taxa_ajuste_direto']) * 100:.0f}%"
                        if resumo.get("taxa_ajuste_direto") is not None else None
                    ),
                },
                fields={
                    "nif": normalized,
                    "anos": resumo.get("anos") or [],
                    "desvio mediano": resumo.get("desvio_mediano"),
                    "pais": dossier.get("pais"),
                    "contratos_lidos": lidos,
                    "amostra_parcial": parcial,
                },
                url=internal_url,
                details=(
                    f"{total_contratos} contratos"
                    + (f" · {_fmt_money(resumo.get('valor_total'))}" if resumo.get("valor_total") else "")
                    # Os valores/desvios são calculados sobre os contratos lidos,
                    # não sobre o total: dizê-lo evita ler um número parcial como
                    # se fosse o universo todo.
                    + (f" · valores sobre amostra de {lidos}" if parcial else "")
                ),
            ))

        for person in cargos[:20]:
            pivots.append({
                "handle": person.get("nif"),
                "kind": "cargo",
                "source_site": "Societário",
                "source_key": (person.get("cargos") or [{}])[0].get("role"),
                "site": person.get("nome"),
                "url": f"/pessoas-iq/{person.get('nif')}" if person.get("nif") else None,
            })

        if insolvencias:
            hits.append(_nif_hit(
                "Insolvências · detalhe",
                name=name,
                metrics={"processos": dossier.get("insolvencias_total") or len(insolvencias)},
                fields={
                    "nif": normalized,
                    "ultimos": [
                        f"{item.get('data') or ''} {item.get('especie') or ''} {item.get('ato') or ''}".strip()
                        for item in insolvencias[:5]
                    ],
                },
                details=f"{dossier.get('insolvencias_total') or len(insolvencias)} processo(s) no CIRE",
            ))

        if sinais:
            hits.append(_nif_hit(
                "Sinais de risco",
                name=name,
                metrics={"sinais": len(sinais)},
                fields={"sinais": [f"{s.get('padrao')}: {s.get('detalhe')}" for s in sinais]},
                details="; ".join(str(s.get("detalhe")) for s in sinais[:3]),
            ))
    except Exception as exc:  # pragma: no cover - depende de muitos índices
        logger.warning("Dossiê de contratos indisponível para %s: %s", normalized, exc)

    # -- contas cruzadas: nomes alternativos também são pistas ---------------
    for alt in (detail.get("names") or [])[:4]:
        if name and str(alt).strip().lower() == str(name).strip().lower():
            continue
        pivots.append({
            "handle": None,
            "kind": "alias",
            "source_site": "Contribuintes",
            "source_key": "names",
            "site": str(alt),
            "url": None,
        })

    duration = round(time.time() - t0, 2)
    stats = _stats_of(hits, pivots)
    stats["nif_valid"] = True
    stats["related"] = sorted({str(p.get("site")) for p in pivots if p.get("kind") in {"parent_company", "relation"} and p.get("site")})
    stats["aliases"] = sorted({str(p.get("site")) for p in pivots if p.get("kind") == "alias" and p.get("site")})[:10]
    stats["people"] = sorted({str(p.get("site")) for p in pivots if p.get("kind") == "cargo" and p.get("site")})[:20]
    # Para um NIF não há "sites" de plataformas: o que interessa são entidades
    # e pessoas relacionadas, que ficam em `related`/`people`.
    stats["pivot_sites"] = []
    stats["names"] = sorted({n for n in [name] if n} | set(stats.get("names") or []))

    return {
        "target": normalized,
        "kind": "nif",
        "total": len(hits),
        "found": len(hits),
        "not_found": 0,
        "errors": 0,
        "duration_s": duration,
        "category": "dados internos",
        "hits": hits,
        "pivots": pivots,
        "stats": stats,
        "graph": _build_nif_graph(normalized, hits, pivots, name),
    }


def _build_nif_graph(
    nif: str,
    hits: List[Dict[str, Any]],
    pivots: List[Dict[str, Any]],
    name: Optional[str],
) -> Dict[str, Any]:
    """Grafo do NIF: entidade → fontes internas → pessoas/relações."""
    label = name or nif
    nodes: List[Dict[str, Any]] = [
        {"id": nif, "label": label, "group": "nif", "url": f"/empresas-iq/{nif}",
         "details": f"NIF {nif}", "avatar": None, "confidence": "confirmed"},
    ]
    edges: List[Dict[str, Any]] = []
    for hit in hits:
        node_id = f"src:{hit['site_name']}"
        nodes.append({
            "id": node_id,
            "label": hit["site_name"],
            "group": "fonte",
            "url": hit.get("url"),
            "details": hit.get("reason") or "",
            "avatar": None,
            "confidence": "confirmed",
        })
        edges.append({"source": nif, "target": node_id, "label": "consta em"})
    for pivot in pivots:
        site = pivot.get("site") or pivot.get("handle") or "?"
        node_id = f"pv:{pivot.get('kind')}:{pivot.get('handle') or site}"
        if any(n["id"] == node_id for n in nodes):
            continue
        nodes.append({
            "id": node_id,
            "label": str(site),
            "group": "cross",
            "url": pivot.get("url"),
            "details": f"{pivot.get('kind')} via {pivot.get('source_site')}",
            "avatar": None,
            "confidence": "cross",
        })
        edges.append({"source": nif, "target": node_id, "label": str(pivot.get("kind") or "ligado a")})
    return {"nodes": nodes, "edges": edges}


async def scan_target(
    target: str,
    kind: str,
    category: Optional[str] = None,
    full_scan: bool = False,
    categories: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """Executa a recolha para o alvo e devolve resultado normalizado + grafo.

    `username`/`email` vão ao user-scanner (uma ou **várias** categorias em
    conjunto, com paralelismo limitado e deduplicação por plataforma); `nif` é
    validado e cruzado com os dados internos (contribuintes, contratos,
    societário, CIRE, cadastro, ontologia e pessoas).
    """
    target = (target or "").strip()
    if not target:
        raise ValueError("Alvo vazio: indique um username, um email ou um NIF.")
    if kind == "nif":
        # Recolha síncrona (várias pesquisas ao Elasticsearch): correr num thread
        # para não bloquear o event loop do servidor.
        return await asyncio.to_thread(scan_nif, target)
    if kind == "email" and not _EMAIL_RE.match(target):
        raise ValueError("Email inválido: escreva um endereço como nome@dominio.com.")
    if kind not in OSINT_KINDS:
        raise ValueError(f"Tipo de alvo '{kind}' não suportado. Use: {', '.join(OSINT_KINDS)}.")
    is_email = kind == "email"
    if not _USER_SCANNER_AVAILABLE or us_engine is None:
        raise ValueError("Módulo OSINT externo (user_scanner) não está instalado neste ambiente.")

    available = us_engine.load_categories(is_email=is_email)
    by_lower = {name.lower(): name for name in available}

    # Aceita `categories` (várias) e `category` (uma, compatibilidade).
    requested: List[str] = []
    for raw in list(categories or []) + ([category] if category else []):
        name = by_lower.get(str(raw).strip().lower())
        if not name:
            raise ValueError(f"Categoria '{raw}' não encontrada. Disponíveis: {list(available.keys())}")
        if name not in requested:
            requested.append(name)

    if not requested and not full_scan:
        fallback = DEFAULT_CATEGORY.get(kind, next(iter(available), None))
        if available and fallback not in available:
            # Não cair em silêncio numa categoria arbitrária: avisar no registo e
            # preferir uma categoria conhecida e razoável para email/social.
            logger.warning(
                "Categoria por defeito '%s' não existe para %s; a usar a primeira disponível",
                fallback,
                kind,
            )
        chosen = fallback if available and fallback in available else next(iter(available), None)
        if chosen:
            requested = [chosen]

    t0 = time.time()
    raw_results: List[Any] = []
    if full_scan:
        raw_results = await us_engine.check_all(target, is_email=is_email)
    elif len(requested) == 1:
        raw_results = await us_engine.check_category(requested[0], target, is_email=is_email)
    elif requested:
        raw_results = await _check_categories(requested, target, is_email=is_email)
    duration = round(time.time() - t0, 2)

    # Deduplicação: a mesma plataforma pode aparecer em duas categorias; fica o
    # primeiro resultado, porque a ordem de `raw_results` é estável — o que
    # torna o resultado reprodutível entre execuções iguais.
    seen: set = set()
    unique: List[Any] = []
    per_category: Dict[str, int] = {}
    for item in raw_results:
        site = str(getattr(item, "site_name", ""))
        category_of = str(getattr(item, "category", "") or "?")
        per_category[category_of] = per_category.get(category_of, 0) + 1
        if site in seen:
            continue
        seen.add(site)
        unique.append(item)

    hits = [_result_to_hit(r) for r in unique]
    scores = _confidence_of(unique)
    for hit in hits:
        hit["confidence"] = scores.get(hit["site_name"])
    pivots = _pivots_of(unique)
    found = sum(1 for h in hits if str(h["status"]).lower() == "found")
    not_found = sum(1 for h in hits if str(h["status"]).lower() == "not found")
    errors = sum(1 for h in hits if str(h["status"]).lower() == "error")

    return {
        "target": target,
        "kind": kind,
        "total": len(hits),
        "found": found,
        "not_found": not_found,
        "errors": errors,
        "duration_s": duration,
        "category": requested[0] if len(requested) == 1 else None,
        "categories": requested,
        "platforms_per_category": per_category,
        "hits": hits,
        "pivots": pivots,
        "stats": _stats_of(hits, pivots),
        "graph": _build_graph(hits, target, kind, pivots),
    }


def _search_tokens(values: Iterable[Any]) -> List[str]:
    """Palavras pesquisáveis a partir de nomes/aliases.

    `names`/`pivot_sites` são keywords: só casam com o valor completo
    («Johnson & Johnson»). Indexar as palavras (sem acentos e maiúsculas) é o que
    permite encontrar um scan escrevendo apenas «johnson» ou «cilag».
    """
    tokens: set = set()
    for value in values:
        text = unicodedata.normalize("NFKD", str(value or ""))
        text = "".join(ch for ch in text if not unicodedata.combining(ch)).lower()
        for token in re.split(r"[^a-z0-9]+", text):
            if len(token) >= 3:
                tokens.add(token)
    return sorted(tokens)[:80]


def _indexable_facets(hits: List[Dict[str, Any]], pivots: List[Dict[str, Any]]) -> Dict[str, List[str]]:
    """Facetas pesquisáveis: nomes, emails, sites e contas cruzadas.

    `hits` é guardado como objecto opaco (não pesquisável, para não inflacionar
    o mapeamento), por isso o que interessa procurar é repetido aqui como keyword.
    """
    names: List[str] = []
    emails: List[str] = []
    sites: List[str] = []
    for hit in hits:
        if str(hit.get("status", "")).lower() != "found":
            continue
        profile = hit.get("profile") or {}
        if profile.get("display_name"):
            names.append(str(profile["display_name"]).lower())
        for email in (hit.get("leads") or {}).get("emails") or []:
            emails.append(str(email).lower())
        if hit.get("site_name"):
            sites.append(str(hit["site_name"]).lower())
    pivot_sites = sorted({str(p.get("site")) for p in pivots if p.get("site")})
    aliases = sorted({str(p.get("site")) for p in pivots if p.get("kind") == "alias" and p.get("site")})
    return {
        "names": sorted(set(names)),
        "emails": sorted(set(emails)),
        "sites": sorted(set(sites)),
        "pivot_sites": pivot_sites,
        "aliases": aliases,
        "tokens": _search_tokens(list(names) + list(aliases) + list(pivot_sites)),
    }


def _save_doc_id(target: str, kind: str) -> str:
    # Id estável para poder atualizar pesquisas repetidas do mesmo alvo.
    digest = hashlib.sha256(f"{kind}:{target}".encode("utf-8")).hexdigest()[:32]
    return f"osint:{kind}:{target}:{digest}"


def save_scan(result: Dict[str, Any]) -> Dict[str, Any]:
    """Guarda o resultado de um scan no índice finance_osint.

    O id é estável por alvo, por isso o documento é actualizado — mas os perfis
    **não** são substituídos às cegas: uma execução fraca (os sites bloqueiam de
    forma intermitente, já se viu o mesmo alvo dar 8, 4 e 1 resultados seguidos)
    apagaria o que já se tinha encontrado. Os perfis vistos em execuções
    anteriores que agora não responderam ficam marcados com `stale`.
    """
    es = get_es_client()
    if not es:
        return {"saved": False, "error": "Elasticsearch indisponível"}
    ensure_indices(es)

    target = result["target"]
    kind = result["kind"]
    doc_id = _save_doc_id(target, kind)
    hits = result.get("hits", [])
    pivots = result.get("pivots", [])

    fresh_found = [h for h in hits if str(h.get("status", "")).lower() == "found"]
    fresh_sites = {str(h.get("site_name")) for h in fresh_found}
    carried: List[Dict[str, Any]] = []
    try:
        previous = es.get(index=OSINT_INDEX, id=doc_id).get("_source") or {}
    except Exception:
        previous = {}
    for old in previous.get("hits") or []:
        site = str(old.get("site_name"))
        if str(old.get("status", "")).lower() != "found" or site in fresh_sites:
            continue
        # Não voltou a aparecer nesta execução: mantém-se, com o que já se sabia.
        carried.append({**old, "stale": True, "last_seen": old.get("last_seen") or previous.get("scanned_at")})

    merged_found = [{**h, "stale": False, "last_seen": _today()} for h in fresh_found] + carried
    merged_sites = {str(h.get("site_name")) for h in merged_found}
    merged = merged_found + [
        h for h in hits if str(h.get("status", "")).lower() != "found"
    ]

    stats = dict(result.get("stats") or {})
    stats["platforms_found"] = len(merged_found)
    stats["found_this_run"] = len(fresh_found)
    stats["carried_over"] = len(carried)
    stats.setdefault("platforms_with_name", sum(1 for h in merged_found if (h.get("profile") or {}).get("display_name")))
    stats.setdefault("platforms_with_avatar", sum(1 for h in merged_found if (h.get("profile") or {}).get("avatar")))

    doc = {
        "target": target,
        "kind": kind,
        "category": result.get("category"),
        "categories": result.get("categories") or [],
        "found": len(merged_found),
        "total": result.get("total", 0),
        "not_found": result.get("not_found", 0),
        "errors": result.get("errors", 0),
        "duration_s": result.get("duration_s"),
        "hits": merged,
        "pivots": pivots,
        "stats": stats,
        "graph": _build_graph(merged, target, kind, pivots),
        "scanned_at": _today(),
        **_indexable_facets(merged_found, pivots),
    }
    try:
        es.index(index=OSINT_INDEX, id=doc_id, document=doc, refresh=True)
        return {"saved": True, "saved_id": doc_id, "carried_over": len(carried)}
    except Exception as exc:
        logger.warning("Falha ao guardar scan OSINT %s: %s", doc_id, exc)
        return {"saved": False, "error": str(exc)}


def get_saved_scan(doc_id: str) -> Optional[Dict[str, Any]]:
    es = get_es_client()
    if not es:
        return None
    try:
        resp = es.get(index=OSINT_INDEX, id=doc_id)
        doc = resp.get("_source", {})
        doc["id"] = doc_id
        return doc
    except Exception:
        return None


def search_saved_scans(q: Optional[str] = None, kind: Optional[str] = None, size: int = 20, from_: int = 0) -> Dict[str, Any]:
    es = get_es_client()
    if not es:
        return {"total": 0, "items": [], "error": "Elasticsearch indisponível"}
    ensure_indices(es)

    must: List[Dict[str, Any]] = []
    if q:
        must.append({
            "multi_match": {
                "query": q,
                "fields": [
                    "target^3", "category", "names^2", "emails^2", "sites", "pivot_sites",
                    "aliases^2", "tokens^2",
                    "hits.site_name", "hits.category",
                ],
                "operator": "and",
            }
        })
    if kind:
        must.append({"term": {"kind": kind}})

    body = {
        "query": {"bool": {"must": must}} if must else {"match_all": {}},
        "sort": [{"scanned_at": {"order": "desc"}}],
        "from": from_,
        "size": size,
    }
    try:
        resp = es.search(index=OSINT_INDEX, body=body)
        hits = resp.get("hits", {}).get("hits", [])
        total = (resp.get("hits", {}).get("total") or {}).get("value", 0)
        items: List[Dict[str, Any]] = []
        for h in hits:
            doc = h.get("_source", {})
            found_hits = [x for x in (doc.get("hits") or []) if str(x.get("status")).lower() == "found"]
            items.append({
                "id": h.get("_id"),
                "target": doc.get("target"),
                "kind": doc.get("kind"),
                "category": doc.get("category"),
                "found": len(found_hits),
                "total": doc.get("total", 0),
                "scanned_at": doc.get("scanned_at"),
                "top_sites": [x.get("site_name") for x in found_hits[:5]],
                "names": (doc.get("names") or [])[:5],
                "emails": (doc.get("emails") or [])[:5],
                "pivots": len(doc.get("pivots") or []),
                "stats": doc.get("stats") or {},
            })
        return {"total": total, "items": items, "from_": from_, "size": size}
    except Exception as exc:
        return {"total": 0, "items": [], "error": str(exc)}


def delete_saved_scan(doc_id: str) -> Dict[str, Any]:
    es = get_es_client()
    if not es:
        return {"deleted": False, "error": "Elasticsearch indisponível"}
    try:
        es.delete(index=OSINT_INDEX, id=doc_id, refresh=True)
        return {"deleted": True}
    except Exception as exc:
        return {"deleted": False, "error": str(exc)}


# --------------------------------------------------------------- exportação
_PDF_SUPPORTED = True
try:  # pragma: no cover - depende do extra do user-scanner
    from user_scanner.core import pdf_generator as us_pdf
except Exception:  # pragma: no cover
    us_pdf = None  # type: ignore[assignment]
    _PDF_SUPPORTED = False


def scan_to_csv(doc: Dict[str, Any]) -> str:
    """CSV com uma linha por plataforma encontrada (para abrir no Excel)."""
    import csv
    import io

    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\n")
    writer.writerow([
        "alvo", "tipo", "plataforma", "categoria", "confianca", "nome", "seguidores",
        "adesao", "bio", "url", "emails", "links",
    ])
    for hit in doc.get("hits") or []:
        if str(hit.get("status", "")).lower() != "found":
            continue
        profile = hit.get("profile") or {}
        leads = hit.get("leads") or {}
        writer.writerow([
            doc.get("target", ""),
            doc.get("kind", ""),
            hit.get("site_name", ""),
            hit.get("category", ""),
            hit.get("confidence") or "",
            profile.get("display_name") or "",
            profile.get("followers") or "",
            profile.get("joined") or "",
            (profile.get("bio") or "").replace("\n", " "),
            hit.get("url") or "",
            "; ".join(leads.get("emails") or []),
            "; ".join(profile.get("links") or []),
        ])
    return buffer.getvalue()


def scan_to_pdf(doc: Dict[str, Any]) -> Optional[bytes]:
    """Relatório PDF gerado pelo próprio user-scanner (se o extra estiver instalado)."""
    if not _PDF_SUPPORTED or us_pdf is None:
        return None
    # O gerador espera objetos com `to_dict()`; reconstruímos a partir do que guardámos.
    class _Hit:
        def __init__(self, data: Dict[str, Any]) -> None:
            self._data = data
            self.status = data.get("status", "")
            self.reason = data.get("reason")
            self.username = doc.get("target")
            self.site_name = data.get("site_name", "")
            self.category = data.get("category", "")
            self.url = data.get("url") or ""
            self.extra = data.get("extra") or {}
            self.media = data.get("media") or {}

        def to_dict(self) -> Dict[str, Any]:
            return {
                "status": self.status,
                "reason": self.reason or "",
                "username": self.username,
                "site_name": self.site_name,
                "category": self.category,
                "url": self.url,
                "extra": self.extra,
                "media": self.media,
            }

    hits = [_Hit(h) for h in (doc.get("hits") or [])]
    try:
        return us_pdf.generate_pdf_report(
            target=str(doc.get("target") or ""),
            scan_type=str(doc.get("kind") or "username"),
            results=hits,
            total_modules=int(doc.get("total") or len(hits)),
            include_media=True,
        )
    except Exception as exc:  # pragma: no cover - falha do gerador
        logger.warning("Falha a gerar PDF OSINT de %s: %s", doc.get("id"), exc)
        return None
