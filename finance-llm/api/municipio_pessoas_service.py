"""Recolha e normalização de executivos municipais (cm-*.pt).

O módulo lê páginas de executivo das câmaras municipais portuguesas, extrai os
membros do executivo (presidente, vice-presidentes, vereadores) com nome, cargo,
pelouro, partido e foto, e guarda tudo num índice próprio (`finance_municipio_pessoas`)
para ser pesquisável no PessoasIQ.

Cada documento representa uma pessoa num cargo numa câmara num dado momento.
"""
from __future__ import annotations

import json
import logging
import re
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple
from urllib.parse import urljoin, urlparse

import httpx
from bs4 import BeautifulSoup

from api.elasticsearch_client import (
    MUNICIPIO_PESSOAS_INDEX,
    ensure_indices,
    get_es_client,
)

logger = logging.getLogger(__name__)

DEFAULT_DATA_DIR = Path(__file__).resolve().parents[1] / "data" / "municipio_pessoas"
CACHE_TTL_SECONDS = 24 * 60 * 60
_LOCK = threading.Lock()

USER_AGENT = "IQOS/1.0 (analise politica; contacto@icpm.tech)"


def _data_dir() -> Path:
    path = DEFAULT_DATA_DIR
    path.mkdir(parents=True, exist_ok=True)
    return path


def _cache_path(name: str) -> Path:
    return _data_dir() / f"{name}.json"


def _now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _normalize_name(name: str) -> str:
    return re.sub(r"\s+", " ", name).strip()


def _split_pelouros(pelouro_part: str) -> List[str]:
    """Divide pelouros pelo padrão 'Pelouro do/da/de...'.

    O texto vem como 'Pelouro da X, Pelouro da Y e Pelouro da Z'. Separamos
    por vírgula e por 'e' antes de 'Pelouro'.
    """
    # Normaliza separadores para vírgula.
    text = re.sub(r"\s+e\s+(?=Pelouro)", ", ", pelouro_part, flags=re.IGNORECASE)
    return [p.strip() for p in text.split(",") if p.strip().lower().startswith("pelouro")]


def _normalize_party(raw: str) -> str:
    """Normaliza siglas/partidos extraídos do texto do site."""
    if not raw:
        return ""
    # Corrige extrações truncadas como "PP.IL" vindas de `[^-]+$` no fim.
    raw = raw.strip()
    if raw.lower() in ("pp.il", "pp.il."):
        return "PPD/PSD.CDS-PP.IL"
    if raw == "PP" or raw == "PP.":
        return "PS"
    return raw


def _slug(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")


def _fetch_html(url: str, timeout: float = 30.0) -> Optional[str]:
    try:
        with httpx.Client(
            timeout=timeout,
            headers={"User-Agent": USER_AGENT},
            follow_redirects=True,
        ) as client:
            resp = client.get(url)
            resp.raise_for_status()
            return resp.text
    except Exception as exc:
        logger.warning("Falha a obter %s: %s", url, exc)
        return None


def _parse_executivo_cm_porto(html: str, source_url: str) -> List[Dict[str, Any]]:
    """Extrai membros do executivo da página `/executivo` da Câmara do Porto."""
    soup = BeautifulSoup(html, "html.parser")
    base_url = "{0.scheme}://{0.netloc}".format(urlparse(source_url))
    items: List[Dict[str, Any]] = []

    for content in soup.select(".content.col-md-4"):
        text = content.get_text("\n", strip=True)
        lines = [line.strip() for line in text.splitlines() if line.strip()]
        if not lines:
            continue
        name = _normalize_name(lines[0])
        role_line = lines[1] if len(lines) > 1 else ""

        role = "Vereador"
        party = ""
        pelouros: List[str] = []

        if "Presidente da Câmara Municipal" in role_line:
            role = "Presidente"
        elif "Vice-Presidente" in role_line:
            role = "Vice-Presidente"

        if " - " in role_line:
            party = _normalize_party(role_line.rsplit(" - ", 1)[-1].strip())

        # Remove o prefixo do cargo/pelouro para extrair só os pelouros.
        pelouro_part = re.sub(
            r"^(Vereador[oa]?|Presidente da Câmara Municipal|Vice-Presidente da Câmara Municipal),?\s*",
            "",
            role_line.split(" - ")[0],
            flags=re.IGNORECASE,
        ).strip()
        if pelouro_part:
            pelouros = [
                p for p in _split_pelouros(pelouro_part)
                if p.lower().startswith("pelouro")
            ]

        # Procura foto no elemento ou no link individual: o site usa `imageBg`
        # com `background-image:url("...")` em vez de `<img>`.
        photo_url = None
        profile_url = None
        for link in content.find_all("a", href=re.compile(r"executivo/")):
            href = link.get("href", "")
            if not profile_url and href:
                profile_url = urljoin(base_url, href)
            style = link.get("style") or ""
            m = re.search(r'background-image\s*:\s*url\("?([^"\)]+)"?\)', style)
            if m and not photo_url:
                photo_url = urljoin(base_url, m.group(1).strip().replace("&quot;", "").replace("\"", ""))
            if profile_url and photo_url:
                break

        if not photo_url:
            img = content.find("img")
            if img:
                src = img.get("src") or img.get("data-src") or ""
                if src:
                    photo_url = urljoin(base_url, src)

        items.append({
            "name": name,
            "role": role,
            "party": party,
            "pelouros": pelouros,
            "concelho": "Porto",
            "district": "Porto",
            "source_url": source_url,
            "profile_url": profile_url,
            "photo_url": photo_url,
            "source": "cm-porto",
            "raw_role": role_line,
        })

    return items


def _build_doc_id(item: Dict[str, Any]) -> str:
    return f"{item['source']}-{_slug(item['concelho'])}-{_slug(item['name'])}"


def _read_cache(name: str) -> Optional[Dict[str, Any]]:
    path = _cache_path(name)
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        cached_at = data.get("cached_at", "")
        if cached_at:
            try:
                dt = datetime.fromisoformat(cached_at.replace("Z", "+00:00"))
                age = (datetime.now(timezone.utc) - dt).total_seconds()
                if age > CACHE_TTL_SECONDS:
                    return None
            except Exception:
                return None
        return data
    except Exception as exc:
        logger.debug("Cache %s inválida: %s", name, exc)
        return None


def _write_cache(name: str, payload: Dict[str, Any]) -> None:
    path = _cache_path(name)
    try:
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception as exc:
        logger.warning("Não foi possível guardar cache %s: %s", name, exc)


def scrape_cm_porto(refresh: bool = False) -> Dict[str, Any]:
    """Recolhe o executivo da Câmara Municipal do Porto."""
    cache_name = "cm_porto_executivo"
    if not refresh:
        cached = _read_cache(cache_name)
        if cached:
            return cached

    url = "https://www.cm-porto.pt/executivo"
    html = _fetch_html(url)
    if not html:
        return {"error": "Não foi possível obter a página", "url": url}

    items = _parse_executivo_cm_porto(html, url)
    now = _now_iso()
    for item in items:
        item["doc_id"] = _build_doc_id(item)
        item["ingested_at"] = now
        item["updated_at"] = now

    payload = {
        "cached_at": now,
        "url": url,
        "concelho": "Porto",
        "district": "Porto",
        "total": len(items),
        "items": items,
    }
    _write_cache(cache_name, payload)
    return payload


def index_municipio_pessoas(items: Iterable[Dict[str, Any]], es: Optional[Any] = None) -> Dict[str, Any]:
    """Indexa documentos no índice `finance_municipio_pessoas`."""
    from elasticsearch import Elasticsearch
    from elasticsearch.helpers import bulk

    client = es or get_es_client()
    if not client:
        return {"error": "Elasticsearch indisponível", "indexed": 0}
    ensure_indices(client)

    actions = []
    now = _now_iso()
    for item in items:
        doc = dict(item)
        doc.setdefault("ingested_at", now)
        doc.setdefault("updated_at", now)
        doc_id = doc.get("doc_id") or _build_doc_id(doc)
        actions.append({
            "_op_type": "index",
            "_index": MUNICIPIO_PESSOAS_INDEX,
            "_id": doc_id,
            **doc,
        })

    if not actions:
        return {"indexed": 0}
    try:
        indexed, errors = bulk(client, actions, raise_on_error=False)
        client.indices.refresh(index=MUNICIPIO_PESSOAS_INDEX)
        return {"indexed": indexed, "errors": len(errors) if errors else 0}
    except Exception as exc:
        return {"error": str(exc), "indexed": 0}


def search_municipio_pessoas(
    q: Optional[str] = None,
    district: Optional[str] = None,
    concelho: Optional[str] = None,
    party: Optional[str] = None,
    role: Optional[str] = None,
    size: int = 50,
    page: int = 1,
    es: Optional[Any] = None,
) -> Dict[str, Any]:
    """Pesquisa no índice `finance_municipio_pessoas`."""
    client = es or get_es_client()
    if not client:
        return {"error": "Elasticsearch indisponível", "items": [], "total": 0}
    ensure_indices(client)

    must: List[Dict[str, Any]] = []
    filters: List[Dict[str, Any]] = []

    if q:
        must.append({
            "bool": {
                "should": [
                    {"match_phrase": {"name": {"query": q, "boost": 6}}},
                    {"match": {"name": {"query": q, "operator": "and", "boost": 3}}},
                    {"wildcard": {"party.keyword": {"value": f"*{q}*", "case_insensitive": True}}},
                    {"wildcard": {"role": {"value": f"*{q}*", "case_insensitive": True}}},
                    {"wildcard": {"role_keyword": {"value": f"*{q}*", "case_insensitive": True}}},
                    {"wildcard": {"concelho.keyword": {"value": f"*{q}*", "case_insensitive": True}}},
                    {"wildcard": {"pelouros": {"value": f"*{q}*", "case_insensitive": True}}},
                ],
                "minimum_should_match": 1,
            }
        })
    if district:
        filters.append({"wildcard": {"district.keyword": {"value": f"*{district}*", "case_insensitive": True}}})
    if concelho:
        filters.append({"wildcard": {"concelho.keyword": {"value": f"*{concelho}*", "case_insensitive": True}}})
    if party:
        filters.append({"wildcard": {"party.keyword": {"value": f"*{party}*", "case_insensitive": True}}})
    if role:
        filters.append({"wildcard": {"role.keyword": {"value": f"*{role}*", "case_insensitive": True}}})

    bool_query: Dict[str, Any] = {}
    if must:
        bool_query["must"] = must
    if filters:
        bool_query["filter"] = filters

    query = {"bool": bool_query} if bool_query else {"match_all": {}}
    from_ = max(0, (page - 1) * size)

    body = {
        "query": query,
        "from": from_,
        "size": max(1, min(size, 500)),
        "sort": [{"_score": {"order": "desc"}}, {"name.keyword": {"order": "asc"}}],
        "track_total_hits": True,
    }

    try:
        resp = client.search(index=MUNICIPIO_PESSOAS_INDEX, body=body)
        total = resp["hits"]["total"]["value"]
        return {
            "total": total,
            "page": page,
            "size": size,
            "items": [{**hit["_source"], "doc_id": hit["_id"]} for hit in resp["hits"]["hits"]],
        }
    except Exception as exc:
        return {"error": str(exc), "items": [], "total": 0}


def stats(es: Optional[Any] = None) -> Dict[str, Any]:
    """Resumo do índice de executivos municipais."""
    client = es or get_es_client()
    if not client:
        return {"error": "Elasticsearch indisponível"}
    ensure_indices(client)
    try:
        count = client.count(index=MUNICIPIO_PESSOAS_INDEX).get("count", 0)
        if not count:
            return {"index": MUNICIPIO_PESSOAS_INDEX, "documents": 0}
        resp = client.search(
            index=MUNICIPIO_PESSOAS_INDEX,
            body={
                "size": 0,
                "aggs": {
                    "by_concelho": {"terms": {"field": "concelho.keyword", "size": 50}},
                    "by_party": {"terms": {"field": "party.keyword", "size": 50}},
                    "by_role": {"terms": {"field": "role.keyword", "size": 20}},
                },
            },
        )
        aggs = resp.get("aggregations", {})
        return {
            "index": MUNICIPIO_PESSOAS_INDEX,
            "documents": count,
            "by_concelho": [{"key": b["key"], "count": b["doc_count"]} for b in aggs.get("by_concelho", {}).get("buckets", [])],
            "by_party": [{"key": b["key"], "count": b["doc_count"]} for b in aggs.get("by_party", {}).get("buckets", [])],
            "by_role": [{"key": b["key"], "count": b["doc_count"]} for b in aggs.get("by_role", {}).get("buckets", [])],
        }
    except Exception as exc:
        return {"error": str(exc)}


def refresh_cm_porto() -> Dict[str, Any]:
    """Recolhe e indexa o executivo da Câmara do Porto."""
    data = scrape_cm_porto(refresh=True)
    if data.get("error"):
        return data
    items = data.get("items", [])
    result = index_municipio_pessoas(items)
    return {
        "refreshed_at": _now_iso(),
        "concelho": "Porto",
        "total": len(items),
        "indexed": result.get("indexed"),
        "errors": result.get("errors"),
    }
