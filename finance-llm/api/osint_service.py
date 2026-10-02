"""Serviço OSINT baseado no user-scanner (kaifcodec/user-scanner).

Integra a engine de username/email do user-scanner com o Elasticsearch do IQ OS,
guardando cada pesquisa no índice ``finance_osint`` e devolvendo um grafo simples
para visualização das plataformas encontradas.
"""
from __future__ import annotations

import asyncio
import hashlib
import logging
import re
import time
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List, Optional, Tuple

from user_scanner.core import confidence as us_confidence
from user_scanner.core import engine as us_engine
from user_scanner.core import pivots as us_pivots

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

# Status numéricos do user-scanner -> label amigável
STATUS_LABEL = {0: "Found", 1: "Not Found", 2: "Error", 3: "Skipped"}

# Validação mínima de email (sem depender de libs extra).
_EMAIL_RE = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]{2,}$")

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


async def scan_target(target: str, kind: str, category: Optional[str] = None, full_scan: bool = False) -> Dict[str, Any]:
    """Executa um scan user-scanner e devolve resultado normalizado + grafo."""
    target = (target or "").strip()
    if not target:
        raise ValueError("Alvo vazio: indique um username ou um email.")
    if kind == "email" and not _EMAIL_RE.match(target):
        raise ValueError("Email inválido: escreva um endereço como nome@dominio.com.")
    is_email = kind == "email"
    categories = us_engine.load_categories(is_email=is_email)

    chosen_category = None
    if category:
        chosen_category = next((c for c in categories if c.lower() == category.lower()), None)
        if not chosen_category:
            raise ValueError(f"Categoria '{category}' não encontrada. Disponíveis: {list(categories.keys())}")
    elif not full_scan:
        fallback = DEFAULT_CATEGORY.get(kind, list(categories.keys())[0] if categories else None)
        if categories and fallback not in categories:
            # Não cair em silêncio numa categoria arbitrária: avisar no registo e
            # preferir uma categoria conhecida e razoável para email/social.
            logger.warning(
                "Categoria por defeito '%s' não existe para %s; a usar a primeira disponível",
                fallback,
                kind,
            )
        chosen_category = fallback if categories and fallback in categories else (list(categories.keys())[0] if categories else None)

    t0 = time.time()
    raw_results: List[Any] = []
    if full_scan or not chosen_category:
        raw_results = await us_engine.check_all(target, is_email=is_email)
    else:
        raw_results = await us_engine.check_category(chosen_category, target, is_email=is_email)
    duration = round(time.time() - t0, 2)

    hits = [_result_to_hit(r) for r in raw_results]
    scores = _confidence_of(raw_results)
    for hit in hits:
        hit["confidence"] = scores.get(hit["site_name"])
    pivots = _pivots_of(raw_results)
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
        "category": chosen_category,
        "hits": hits,
        "pivots": pivots,
        "stats": _stats_of(hits, pivots),
        "graph": _build_graph(hits, target, kind, pivots),
    }


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
    return {
        "names": sorted(set(names)),
        "emails": sorted(set(emails)),
        "sites": sorted(set(sites)),
        "pivot_sites": sorted({str(p.get("site")) for p in pivots if p.get("site")}),
    }


def _save_doc_id(target: str, kind: str) -> str:
    # Id estável para poder atualizar pesquisas repetidas do mesmo alvo.
    digest = hashlib.sha256(f"{kind}:{target}".encode("utf-8")).hexdigest()[:32]
    return f"osint:{kind}:{target}:{digest}"


def save_scan(result: Dict[str, Any]) -> Dict[str, Any]:
    """Guarda o resultado de um scan no índice finance_osint."""
    es = get_es_client()
    if not es:
        return {"saved": False, "error": "Elasticsearch indisponível"}
    ensure_indices(es)

    target = result["target"]
    kind = result["kind"]
    doc_id = _save_doc_id(target, kind)
    hits = result.get("hits", [])
    pivots = result.get("pivots", [])
    doc = {
        "target": target,
        "kind": kind,
        "category": result.get("category"),
        "found": result.get("found", 0),
        "total": result.get("total", 0),
        "not_found": result.get("not_found", 0),
        "errors": result.get("errors", 0),
        "duration_s": result.get("duration_s"),
        "hits": hits,
        "pivots": pivots,
        "stats": result.get("stats", {}),
        "graph": result.get("graph", {}),
        "scanned_at": _today(),
        **_indexable_facets(hits, pivots),
    }
    try:
        es.index(index=OSINT_INDEX, id=doc_id, document=doc, refresh=True)
        return {"saved": True, "saved_id": doc_id}
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
