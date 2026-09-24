"""Recolha de dados públicos de uma pessoa (redes sociais + internet) para o PessoasIQ.

O PessoasIQ sabe quem é a pessoa (ficha do societário e dos processos do CIRE).
Este módulo vai buscar o que é **público** sobre ela — LinkedIn, TikTok, Facebook
e internet — e guarda tudo no índice `finance_social`, ligado à pessoa por
`person_nif`. De cada página ficam título, texto, imagem e vídeo, e cada texto
leva sentimento (léxico local, sem gastar tokens de IA).

Porque é que isto funciona assim
--------------------------------
As redes sociais não servem conteúdo de perfis a robôs sem sessão. Em vez de
falhar, a recolha:
1. pesquisa na internet pelo nome (com o NIF e as empresas conhecidas, para
   desambiguar homónimos);
2. classifica cada ligação por plataforma (`linkedin.com/in/...`, `tiktok.com/@`,
   `facebook.com/...`);
3. lê cada ligação com o coletor da plataforma, que sabe explicar a diferença
   entre «bloqueado», «precisa de credenciais» e «sem conteúdo»;
4. tudo o que não se conseguiu abrir fica registado como **ligação** (título e
   resumo devolvidos pelo motor de pesquisa), para a evidência não se perder.

O resultado por fonte diz sempre o que aconteceu, para a UI poder explicá-lo.
"""
from __future__ import annotations

import hashlib
import logging
import re
import time
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple
from urllib.parse import urlparse

from api import scraper_sentiment
from api import social_collectors as collectors
from api.elasticsearch_client import (
    get_person_by_nif,
    index_social_items,
)

logger = logging.getLogger(__name__)

#: Fontes que podem ser recolhidas para uma pessoa (`media` = imagens e vídeos).
SOURCES = ("media", "internet", "linkedin", "tiktok", "facebook")

#: Rótulos para a UI.
SOURCE_LABELS = {
    "media": "Imagens e vídeos",
    "internet": "Internet",
    "linkedin": "LinkedIn",
    "tiktok": "TikTok",
    "facebook": "Facebook",
}

#: Estados possíveis de uma fonte nesta recolha.
STATUSES = ("ok", "empty", "blocked", "credentials", "error", "skipped")

#: Domínios considerados «rede social» (para não os repetir em `internet`).
_SOCIAL_HOSTS = ("linkedin.com", "tiktok.com", "facebook.com", "instagram.com", "twitter.com", "x.com")

#: Sufixos de firma que atrapalham a pesquisa de pessoas coletivas.
_COMPANY_SUFFIX_RE = re.compile(
    r"\s*[-–,]?\s*\b(LDA|LDA\.|SA|S\.A\.|SGPS|UNIPESSOAL|E\.I\.R\.L|CRL|EPE)\b\.?\s*$",
    re.I,
)

#: Nº máximo de imagens e de vídeos guardados por pessoa.
MAX_IMAGES = 16
MAX_VIDEOS = 10
MAX_PAGES_PER_SOURCE = 8
DEFAULT_LIMIT = 8


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _sentiment(text: str) -> Optional[Dict[str, Any]]:
    """Sentimento de um texto (léxico local; devolve `None` se não houver texto)."""
    text = (text or "").strip()
    if len(text) < 8:
        return None
    try:
        result = scraper_sentiment.analyze_lexicon(text)
    except Exception as exc:  # pragma: no cover - salvaguarda
        logger.debug("Sentimento falhou: %s", exc)
        return None
    label = str(result.get("label") or "").strip().lower()
    if not label:
        return None
    return {
        "label": label,
        "polarity": float(result.get("polarity") or 0.0),
        "engine": "lexicon",
    }


def _host(url: str) -> str:
    try:
        return (urlparse(url).netloc or "").lower().removeprefix("www.")
    except Exception:
        return ""


def _source_for_url(url: str) -> str:
    """Plataforma de uma ligação (para separar o que é rede social do resto)."""
    host = _host(url)
    if "linkedin.com" in host:
        return "linkedin"
    if "tiktok.com" in host:
        return "tiktok"
    if "facebook.com" in host or "fb.com" in host:
        return "facebook"
    return "internet"


def _is_social(url: str) -> bool:
    host = _host(url)
    return any(social in host for social in _SOCIAL_HOSTS)


def build_queries(person: Dict[str, Any], *, with_nif: bool = True) -> List[Dict[str, str]]:
    """Consultas de pesquisa para encontrar a pessoa na internet.

    O nome sozinho traz homónimos; por isso as consultas juntam o NIF e as
    empresas/funções conhecidas na ficha (é o que distingue duas pessoas com o
    mesmo nome).
    """
    name = str(person.get("name") or "").strip()
    if not name:
        return []
    nif = str(person.get("nif") or "").strip()
    queries: List[Dict[str, str]] = []

    def add(query: str, scope: str) -> None:
        query = re.sub(r"\s+", " ", query or "").strip()
        if query and all(entry["query"] != query for entry in queries):
            queries.append({"query": query, "scope": scope})

    base = f'"{name}"'
    if with_nif and nif:
        add(f"{base} {nif}", "internet")
        add(f"{base} NIF {nif}", "internet")
    add(base, "internet")
    add(f"{base} site:linkedin.com/in", "linkedin")
    add(f"{base} site:tiktok.com", "tiktok")
    add(f"{base} site:facebook.com", "facebook")

    # Empresas em que a pessoa tem cargos: desambiguam homónimos com muita força.
    companies = [str(c.get("name") or "").strip() for c in (person.get("companies") or [])[:2]]
    for company in companies:
        if company and company.lower() != name.lower():
            add(f"{base} \"{company}\"", "internet")

    # Firma sem sufixos (as pessoas coletivas aparecem escritas de várias formas).
    stripped = _COMPANY_SUFFIX_RE.sub("", name).strip()
    if stripped and stripped.lower() != name.lower() and len(stripped) > 5:
        add(f'"{stripped}"', "internet")
    return queries


def _search_all(
    queries: Sequence[Dict[str, str]],
    *,
    limit: int,
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """Corre as consultas e devolve `(resultados únicos, estado de cada consulta)`.

    Os motores gratuitos bloqueiam por ritmo: uma consulta que fique sem motor é
    repetida uma vez, depois de uma pequena pausa (a cache do coletor evita
    repetir pedidos já feitos).
    """
    results: List[Dict[str, Any]] = []
    report: List[Dict[str, Any]] = []
    seen: set = set()

    def run(entry: Dict[str, str], attempt: int) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
        outcome = collectors.search_web(entry["query"], limit=limit)
        rows: List[Dict[str, Any]] = []
        for row in outcome.get("items") or []:
            url = str(row.get("url") or "").strip()
            if not url or url in seen:
                continue
            seen.add(url)
            rows.append({
                "url": url,
                "title": row.get("title") or "",
                "snippet": row.get("snippet") or "",
                "engine": row.get("engine") or "",
                "scope": entry["scope"],
                "platform": _source_for_url(url),
            })
        return rows, {
            "query": entry["query"],
            "scope": entry["scope"],
            "engine": outcome.get("engine") or "",
            "items": len(rows),
            "attempt": attempt,
            "error": outcome.get("error") or None,
        }

    failed: List[Dict[str, str]] = []
    for entry in queries:
        rows, status = run(entry, 1)
        results.extend(rows)
        report.append(status)
        if not rows and status["error"]:
            failed.append(entry)

    if failed:
        time.sleep(3)
        for entry in failed:
            rows, status = run(entry, 2)
            if rows:
                results.extend(rows)
                report.append(status)
    return results, report


def _link_item(result: Dict[str, Any], person: Dict[str, Any], source: str) -> Dict[str, Any]:
    """Item de reserva: só a ligação e o resumo da pesquisa (nada foi aberto)."""
    nif = str(person.get("nif") or "")
    name = str(person.get("name") or "")
    url = result.get("url") or ""
    return {
        "platform": source,
        "kind": "link",
        "target": name or nif,
        "post_id": url,
        # `item_id` é o `_id` no Elasticsearch (a mesma ligação não duplica).
        "item_id": hashlib.sha1(f"{source}|link|{nif}|{url}".encode("utf-8")).hexdigest(),
        "url": url,
        "title": result.get("title") or result.get("url") or "",
        "text": result.get("snippet") or "",
        "author": name,
        "community": _host(result.get("url") or ""),
        "person_nif": nif,
        "person_name": name,
        "tags": ["pessoas-iq", f"pessoa:{nif}", source, "ligacao"],
        "collected_at": _now(),
        "sentiment": _sentiment(f"{result.get('title') or ''}. {result.get('snippet') or ''}"),
        "data": {"engine": result.get("engine"), "scope": result.get("scope"), "opened": False},
    }


def _collect_platform(
    source: str,
    results: Sequence[Dict[str, Any]],
    person: Dict[str, Any],
    *,
    limit: int,
    options: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Lê as ligações de uma fonte (coletor da plataforma ou leitura genérica)."""
    nif = str(person.get("nif") or "")
    name = str(person.get("name") or "")
    items: List[Dict[str, Any]] = []
    notes: List[str] = []
    status = "ok"
    checked = 0

    for result in results[: max(1, limit)]:
        url = str(result.get("url") or "")
        if not url:
            continue
        checked += 1
        outcome: Optional[Dict[str, Any]] = None
        try:
            if source == "tiktok" and re.search(r"/video/\d+", url):
                outcome = collectors.collect(
                    {"platform": "tiktok", "kind": "video", "target": url, "options": options or {}},
                    limit=1,
                )
                posts = outcome.get("items") or []
            elif source == "facebook" and not urlparse(url).path.strip("/").startswith(("login", "sharer")):
                outcome = collectors.collect(
                    {"platform": "facebook", "kind": "page", "target": url, "options": options or {}},
                    limit=limit,
                )
                posts = outcome.get("items") or []
            else:
                posts = [collectors.collect_web_page(url, options=options, target=name, tags=[source])]
            if outcome:
                notes.extend(outcome.get("notes") or [])
        except collectors.CollectorError as exc:
            status = "blocked" if exc.status == "blocked" else ("credentials" if exc.status == "credentials" else status)
            # As mensagens de bloqueio trazem o corpo da resposta: corta-se para a UI.
            notes.append(f"{SOURCE_LABELS.get(source, source)}: {str(exc)[:220]}")
            posts = []
        except Exception as exc:  # pragma: no cover - salvaguarda
            notes.append(f"{SOURCE_LABELS.get(source, source)}: {exc}")
            posts = []

        if not posts:
            # Não se perde a evidência: fica a ligação com o resumo da pesquisa.
            items.append(_link_item(result, person, source))
            continue

        for post in posts:
            post["person_nif"] = nif
            post["person_name"] = name
            post["tags"] = [*(post.get("tags") or []), "pessoas-iq", f"pessoa:{nif}", source]
            outcome_data = dict(post.get("data") or {})
            outcome_data.update({"opened": True, "source_url": url, "engine": result.get("engine")})
            post["data"] = outcome_data
            post["sentiment"] = _sentiment(f"{post.get('title') or ''}. {post.get('text') or ''}")
            items.append(post)

    if not results:
        status = "empty"
        notes.append(f"{SOURCE_LABELS.get(source, source)}: a pesquisa não devolveu ligações.")
    elif not any((item.get("data") or {}).get("opened") for item in items) and status == "ok":
        status = "blocked" if items else "empty"

    return {"status": status, "items": items, "notes": notes, "urls_checked": checked}


def _media_queries(person: Dict[str, Any]) -> List[str]:
    """Consultas para procurar imagens e vídeos da pessoa.

    As imagens e os vídeos não se procuram só pelo nome: acrescenta-se o NIF, a
    função mais recente (ex.: «administrador da insolvência») e uma empresa da
    ficha, que é o que distingue homónimos nas pesquisas de media. A última
    consulta é o nome sem aspas, para dar alcance quando as outras não chegam.
    """
    name = str(person.get("name") or "").strip()
    if not name:
        return []
    nif = str(person.get("nif") or "").strip()
    queries: List[str] = []
    if nif:
        queries.append(f'"{name}" {nif}')
    queries.append(f'"{name}"')

    contexts: List[str] = []
    for role in (person.get("latest_roles") or person.get("roles") or [])[:5]:
        label = str(role.get("role") or "").strip()
        if label and label not in contexts:
            contexts.append(label)
    for company in (person.get("companies") or [])[:1]:
        label = str(company.get("name") or "").strip()
        if label and label.lower() != name.lower():
            contexts.append(label)

    for context in contexts[:2]:
        queries.append(f'{name} {context}')
    queries.append(name)
    return list(dict.fromkeys(queries))


def _media_items(person: Dict[str, Any], *, max_images: int = MAX_IMAGES, max_videos: int = MAX_VIDEOS) -> List[Dict[str, Any]]:
    """Imagens e vídeos encontrados na internet para a pessoa.

    As imagens e os vídeos são **pesquisados à parte** do texto: a pesquisa de
    imagens devolve a imagem (e a página onde aparece) e a de vídeos devolve a
    ligação do vídeo com a miniatura. Ficam como itens próprios na ficha, para a
    galeria do PessoasIQ os mostrar.
    """
    nif = str(person.get("nif") or "")
    name = str(person.get("name") or "")
    if not name:
        return []

    queries = _media_queries(person)
    if not queries:
        return []

    items: List[Dict[str, Any]] = []
    seen: set = set()

    images: List[Dict[str, Any]] = []
    for query in queries:
        found = collectors.search_images(query, limit=max_images)
        for row in found.get("items") or []:
            url = str(row.get("image") or "")
            if not url or url in seen:
                continue
            seen.add(url)
            images.append({
                "type": "image",
                "url": url,
                "page_url": row.get("page_url") or "",
                "title": row.get("title") or "",
                "host": row.get("host") or "",
                "thumbnail": row.get("thumbnail") or "",
                "query": query,
            })
        if len(images) >= max_images:
            break

    videos: List[Dict[str, Any]] = []
    for query in queries:
        found = collectors.search_videos(query, limit=max_videos)
        for row in found.get("items") or []:
            url = str(row.get("url") or "")
            if not url or url in seen:
                continue
            seen.add(url)
            videos.append({
                "type": "video",
                "url": url,
                "title": row.get("title") or "",
                "host": row.get("host") or "",
                "thumbnail": row.get("thumbnail") or "",
                "description": row.get("description") or "",
                "publisher": row.get("publisher") or "",
                "duration": row.get("duration") or "",
                "published_at": row.get("published_at"),
                "query": query,
            })
        if len(videos) >= max_videos:
            break

    for image in images[:max_images]:
        items.append({
            "platform": "internet",
            "kind": "image",
            "target": name,
            "post_id": image["url"],
            "item_id": hashlib.sha1(f"internet|image|{nif}|{image['url']}".encode("utf-8")).hexdigest(),
            "url": image["page_url"] or image["url"],
            "title": image["title"][:300],
            "text": "",
            "author": image["host"],
            "community": image["host"],
            "image": image["url"],
            "images": [image["url"]],
            "person_nif": nif,
            "person_name": name,
            "tags": ["pessoas-iq", f"pessoa:{nif}", "media", "imagem", image["host"]],
            "collected_at": _now(),
            "data": {"thumbnail": image["thumbnail"], "query": image["query"], "opened": False, "media": "imagem"},
        })

    for video in videos[:max_videos]:
        items.append({
            "platform": "internet",
            "kind": "video",
            "target": name,
            "post_id": video["url"],
            "item_id": hashlib.sha1(f"internet|video|{nif}|{video['url']}".encode("utf-8")).hexdigest(),
            "url": video["url"],
            "title": video["title"][:300],
            "text": video["description"][:600],
            "author": video["publisher"] or video["host"],
            "community": video["host"],
            "video": video["url"],
            "videos": [video["url"]],
            "image": video["thumbnail"],
            "published_at": video["published_at"],
            "person_nif": nif,
            "person_name": name,
            "tags": ["pessoas-iq", f"pessoa:{nif}", "media", "video", video["host"]],
            "collected_at": _now(),
            "data": {
                "duration": video["duration"],
                "query": video["query"],
                "opened": True,
                "media": "video",
            },
            "metrics": {},
        })
    return items


def collect_person_social(
    nif: str,
    *,
    sources: Optional[Iterable[str]] = None,
    limit: int = DEFAULT_LIMIT,
    options: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Recolhe dados públicos de uma pessoa e guarda-os em `finance_social`.

    ``sources`` limita as fontes (por omissão todas). Devolve o que cada fonte
    conseguiu, quantos itens foram indexados e as ligações encontradas — mesmo
    quando as plataformas bloqueiam a leitura.
    """
    nif = str(nif or "").strip()
    if not nif:
        return {"error": "NIF em falta.", "sources": [], "items_indexed": 0}

    person = get_person_by_nif(nif)
    if person.get("error") or not person.get("name"):
        return {
            "error": person.get("error") or f"A pessoa {nif} não existe no PessoasIQ.",
            "nif": nif,
            "sources": [],
            "items_indexed": 0,
        }

    chosen = [s for s in (sources or SOURCES) if s in SOURCES] or list(SOURCES)
    limit = max(1, min(int(limit or DEFAULT_LIMIT), MAX_PAGES_PER_SOURCE))

    queries = build_queries(person)
    if not queries:
        return {"error": "Sem nome para pesquisar.", "nif": nif, "sources": [], "items_indexed": 0}

    results, search_report = _search_all(queries, limit=limit)
    for result in results:
        if result["platform"] not in chosen and result["platform"] != "internet":
            result["platform"] = "internet"

    per_source: List[Dict[str, Any]] = []
    total_items = 0
    total_indexed = 0
    for source in chosen:
        if source == "media":
            items = _media_items(person)
            channel = {
                "id": f"pessoa-{nif}-media",
                "name": f"{person.get('name')} · imagens e vídeos",
                "platform": "internet",
                "kind": "person",
                "person_nif": nif,
                "person_name": str(person.get("name") or ""),
            }
            indexed = index_social_items(channel, items, trigger="pessoa") if items else {"indexed_count": 0}
            images = sum(1 for item in items if item.get("kind") == "image")
            videos = sum(1 for item in items if item.get("kind") == "video")
            total_items += len(items)
            total_indexed += int(indexed.get("indexed_count") or 0)
            per_source.append({
                "source": source,
                "label": SOURCE_LABELS[source],
                "status": "ok" if items else "empty",
                "found": len(items),
                "urls_checked": 0,
                "items": len(items),
                "indexed": int(indexed.get("indexed_count") or 0),
                "notes": (
                    [f"{images} imagem(ns) e {videos} vídeo(s) guardados na ficha."]
                    if items
                    else ["A pesquisa de imagens e vídeos não devolveu resultados."]
                ),
                "links": [
                    {"url": item.get("url"), "title": item.get("title"), "platform": item.get("kind")}
                    for item in items[:12]
                ],
            })
            continue

        if source == "internet":
            candidates = [r for r in results if not _is_social(r["url"]) or r["platform"] == "internet"]
        else:
            candidates = [r for r in results if r["platform"] == source]

        outcome = _collect_platform(source, candidates, person, limit=limit, options=options)
        items = outcome["items"]
        channel = {
            "id": f"pessoa-{nif}-{source}",
            "name": f"{person.get('name')} · {SOURCE_LABELS.get(source, source)}",
            "platform": source,
            "kind": "person",
            "person_nif": nif,
            "person_name": str(person.get("name") or ""),
        }
        indexed = index_social_items(channel, items, trigger="pessoa") if items else {"indexed_count": 0}
        total_items += len(items)
        total_indexed += int(indexed.get("indexed_count") or 0)
        per_source.append({
            "source": source,
            "label": SOURCE_LABELS.get(source, source),
            "status": outcome["status"],
            "found": len(candidates),
            "urls_checked": outcome["urls_checked"],
            "items": len(items),
            "indexed": int(indexed.get("indexed_count") or 0),
            "notes": outcome["notes"][:6],
            "links": [
                {"url": item.get("url"), "title": item.get("title"), "platform": item.get("platform")}
                for item in items[:12]
            ],
        })

    return {
        "nif": nif,
        "name": person.get("name"),
        "collected_at": _now(),
        "queries": search_report,
        "sources": per_source,
        "items": total_items,
        "items_indexed": total_indexed,
        "engine_hint": "Instale `ddgs` ou configure BRAVE_API_KEY/SERPAPI_KEY para melhores resultados."
        if any(entry.get("error") for entry in search_report)
        else None,
    }
