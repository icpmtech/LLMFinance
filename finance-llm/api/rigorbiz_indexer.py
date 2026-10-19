"""Indexação das empresas RigorBiz no Elasticsearch.

Lê ``data/rigorbiz/rigorbiz_empresas.jsonl`` e envia para o índice
``finance_rigorbiz``, usando ``nif`` como ``_id`` para evitar duplicados.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

from api.elasticsearch_client import RIGORBIZ_INDEX, ensure_indices, get_es_client
from api.rigorbiz_collector import JSONL_PATH

logger = logging.getLogger(__name__)


def _read_jsonl(path: Optional[Path] = None) -> List[Dict[str, Any]]:
    target = path or JSONL_PATH
    items: List[Dict[str, Any]] = []
    if not target.exists():
        return items
    with target.open("r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                items.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return items


def _prepare(item: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    nif = str(item.get("nif") or "").strip()
    if not nif:
        return None
    doc = {
        "name": item.get("name") or "",
        "nif": nif,
        "cae_code": str(item.get("cae_code") or ""),
        "cae_description": item.get("cae_description") or "",
        "location": item.get("location") or "",
        "path": item.get("path") or "",
        "source": item.get("source") or "rigorbiz",
        "source_url": item.get("source_url") or "",
        "collected_at": item.get("collected_at") or datetime.now(timezone.utc).isoformat(),
    }
    return doc


def index_items(items: Iterable[Dict[str, Any]]) -> Dict[str, Any]:
    """Indexa uma lista de itens RigorBiz no Elasticsearch."""
    client = get_es_client()
    if not client:
        return {"error": "Elasticsearch indisponível", "indexed": 0}
    ensure_indices(client)

    actions: List[Dict[str, Any]] = []
    for item in items:
        doc = _prepare(item)
        if not doc:
            continue
        actions.append({"_index": RIGORBIZ_INDEX, "_id": doc["nif"], "_source": doc})

    if not actions:
        return {"indexed": 0, "errors": 0, "index": RIGORBIZ_INDEX}

    from elasticsearch.helpers import bulk

    try:
        indexed, errors = bulk(client, actions, raise_on_error=False)
        client.indices.refresh(index=RIGORBIZ_INDEX)
        return {"index": RIGORBIZ_INDEX, "indexed": indexed, "errors": len(errors) if errors else 0}
    except Exception as exc:
        logger.exception("Falha a indexar RigorBiz")
        return {"error": str(exc), "indexed": 0, "index": RIGORBIZ_INDEX}


def index_all() -> Dict[str, Any]:
    """Indexa todas as empresas recolhidas no JSONL."""
    items = _read_jsonl()
    return {**index_items(items), "total_read": len(items)}


def count_indexed() -> int:
    client = get_es_client()
    if not client:
        return 0
    try:
        if not client.indices.exists(index=RIGORBIZ_INDEX):
            return 0
        return int(client.count(index=RIGORBIZ_INDEX).get("count", 0))
    except Exception as exc:
        logger.debug("Contagem RigorBiz falhou: %s", exc)
        return 0


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    print(json.dumps(index_all(), ensure_ascii=False, indent=2))
