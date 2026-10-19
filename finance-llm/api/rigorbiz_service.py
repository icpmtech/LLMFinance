"""Serviço de pesquisa no diretório RigorBiz.

Oferece duas vertentes:
1. **Tempo real**: consulta o site da RigorBiz diretamente (POST ao endpoint
   interno `_empresas_procurar_get_list.php`) — útil para pesquisas
   pontuais e para empresas ainda não indexadas.
2. **Local**: pesquisa as empresas recolhidas em ``data/rigorbiz`` e,
   quando disponível, no índice Elasticsearch ``finance_rigorbiz``.
"""
from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

from api.elasticsearch_client import get_es_client

logger = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / "data" / "rigorbiz"
JSONL_PATH = DATA_DIR / "rigorbiz_empresas.jsonl"
JSON_PATH = DATA_DIR / "rigorbiz_empresas.json"

INDEX = "finance_rigorbiz"

# Campos pesquisáveis no site (filtros) — guardados para uso futuro.
_FILTERS = ("localizacao", "cae", "const_dt_ini", "const_dt_fim", "insol_tipo", "situacao")


def _read_jsonl(limit: Optional[int] = None) -> List[Dict[str, Any]]:
    items: List[Dict[str, Any]] = []
    if not JSONL_PATH.exists():
        return items
    with JSONL_PATH.open("r", encoding="utf-8") as fh:
        for idx, line in enumerate(fh):
            if limit is not None and idx >= limit:
                break
            line = line.strip()
            if not line:
                continue
            try:
                items.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return items


def _matches(item: Dict[str, Any], q: str) -> bool:
    q_lower = q.lower()
    for field in ("name", "nif", "cae_code", "cae_description", "location"):
        value = str(item.get(field) or "").lower()
        if q_lower in value:
            return True
    return False


def _parse_cae(desc: str) -> tuple:
    m = re.search(r"(\d{4,5})\s*-\s*(.+)", desc)
    if m:
        return m.group(1), m.group(2).strip()
    return "", desc


def local_search(
    q: Optional[str] = None,
    cae: Optional[str] = None,
    location: Optional[str] = None,
    sort: str = "relevance",
    size: int = 20,
    offset: int = 0,
) -> Dict[str, Any]:
    """Pesquisa simples no ficheiro JSONL recolhido."""
    items = _read_jsonl()
    if q:
        items = [i for i in items if _matches(i, q)]
    if cae:
        items = [i for i in items if str(i.get("cae_code") or "").startswith(str(cae))]
    if location:
        loc = location.lower()
        items = [i for i in items if loc in str(i.get("location") or "").lower()]
    total = len(items)
    return {"items": items[offset : offset + size], "total": total, "offset": offset, "size": size}


def local_detail(nif: str) -> Optional[Dict[str, Any]]:
    for item in _read_jsonl():
        if str(item.get("nif") or "") == str(nif):
            return item
    return None


def es_search(
    q: Optional[str] = None,
    cae: Optional[str] = None,
    location: Optional[str] = None,
    sort: str = "relevance",
    size: int = 20,
    offset: int = 0,
) -> Dict[str, Any]:
    """Pesquisa no índice Elasticsearch ``finance_rigorbiz`` quando existir."""
    client = get_es_client()
    if not client:
        return {"error": "Elasticsearch indisponível", "items": [], "total": 0}
    try:
        if not client.indices.exists(index=INDEX):
            return {"error": f"Índice {INDEX} não existe", "items": [], "total": 0}
    except Exception as exc:
        return {"error": str(exc), "items": [], "total": 0}

    must: List[Dict[str, Any]] = []
    if q and str(q).strip():
        must.append(
            {
                "multi_match": {
                    "query": str(q).strip(),
                    "fields": ["name^4", "nif^3", "cae_description^2", "location"],
                    "operator": "and",
                }
            }
        )
    if cae:
        must.append({"prefix": {"cae_code": str(cae)}})
    if location:
        must.append({"match": {"location": str(location)}})

    body: Dict[str, Any] = {
        "query": {"bool": {"must": must}} if must else {"match_all": {}},
        "from": offset,
        "size": size,
        "track_total_hits": True,
        "sort": [{"_score": "desc"}] if (sort == "relevance" and q) else [{"name.keyword": "asc"}],
    }
    try:
        resp = client.search(index=INDEX, body=body)
        hits = resp.get("hits", {}).get("hits", [])
        total = resp.get("hits", {}).get("total", {})
        total_value = total.get("value", 0) if isinstance(total, dict) else total
        items = [h.get("_source", {}) for h in hits]
        return {"items": items, "total": int(total_value), "offset": offset, "size": size}
    except Exception as exc:
        logger.warning("Pesquisa Elasticsearch RigorBiz falhou: %s", exc)
        return {"error": str(exc), "items": [], "total": 0}


def es_detail(nif: str) -> Optional[Dict[str, Any]]:
    client = get_es_client()
    if not client:
        return None
    try:
        if not client.indices.exists(index=INDEX):
            return None
        resp = client.search(index=INDEX, body={"query": {"term": {"nif": str(nif)}}, "size": 1})
        hits = resp.get("hits", {}).get("hits", [])
        return hits[0].get("_source") if hits else None
    except Exception as exc:
        logger.warning("Detalhe Elasticsearch RigorBiz falhou para %s: %s", nif, exc)
        return None


def search(
    q: Optional[str] = None,
    cae: Optional[str] = None,
    location: Optional[str] = None,
    sort: str = "relevance",
    size: int = 20,
    offset: int = 0,
    use_es: bool = True,
) -> Dict[str, Any]:
    """Pesquisa no índice Elastic se disponível; senão no JSONL local."""
    if use_es:
        es_result = es_search(q=q, cae=cae, location=location, sort=sort, size=size, offset=offset)
        if not es_result.get("error"):
            return {**es_result, "source": "elasticsearch", "index": INDEX}
    return {**local_search(q=q, cae=cae, location=location, sort=sort, size=size, offset=offset), "source": "jsonl", "index": None}


def detail(nif: str, use_es: bool = True) -> Optional[Dict[str, Any]]:
    if use_es:
        item = es_detail(nif)
        if item:
            return {**item, "source": "elasticsearch", "index": INDEX}
    item = local_detail(nif)
    if item:
        return {**item, "source": "jsonl", "index": None}
    return None


def meta() -> Dict[str, Any]:
    """Metadados do diretório local: total e opções."""
    items = _read_jsonl()
    client = get_es_client()
    es_available = False
    es_count = 0
    if client:
        try:
            es_available = bool(client.indices.exists(index=INDEX))
            if es_available:
                es_count = int(client.count(index=INDEX).get("count", 0))
        except Exception:
            pass
    return {
        "local_count": len(items),
        "jsonl": str(JSONL_PATH),
        "json": str(JSON_PATH),
        "elasticsearch_available": es_available,
        "elasticsearch_count": es_count,
        "index": INDEX,
    }
