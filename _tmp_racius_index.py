"""Indexa a recolha nacional no ES local e no ES da VM, sem duplicados.

- Le `data/racius/racius_cae_nacional.json`.
- Indexa nos dois clusters (local 9200, VM via tunel 19200).
- Valida: conta documentos vs. NIFs distintos e remove duplicados por NIF
  (mantem o documento mais recente).
"""
from __future__ import annotations

import json
import logging
import sys
import time
from pathlib import Path
from typing import Any, Dict, List

from elasticsearch import Elasticsearch
from elasticsearch.helpers import bulk

sys.path.insert(0, r"C:\LLMFinance\finance-llm")
from api.elasticsearch_client import index_directory_items  # noqa: E402
from collectors import racius  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("racius-index")

INDEX = "finance_racius"
JSON_FILE = Path(r"C:\LLMFinance\finance-llm\data\racius\racius_cae_nacional.json")
ALVOS = {
    "local": "http://127.0.0.1:9200",
    "vm": "http://127.0.0.1:19200",
}


def duplicados_por_nif(es: Elasticsearch, index: str, size: int = 500) -> List[Dict[str, Any]]:
    """NIFs com mais de um documento (a causa de duplicados no indice)."""
    body = {
        "size": 0,
        "aggs": {
            "por_nif": {
                "terms": {"field": "nif", "size": size, "min_doc_count": 2, "shard_size": 5000}
            }
        },
        "query": {"exists": {"field": "nif"}},
    }
    resp = es.search(index=index, body=body)
    return [b for b in resp["aggregations"]["por_nif"]["buckets"] if b["key"]]


def remover_duplicados(es: Elasticsearch, index: str) -> int:
    """Remove documentos extra por NIF, mantendo o mais recente."""
    removidos = 0
    for _ in range(20):  # poucas rondas: cada uma resolve o lote atual
        dups = duplicados_por_nif(es, index)
        if not dups:
            break
        for bucket in dups:
            nif = bucket["key"]
            hits = es.search(
                index=index,
                body={
                    "size": 50,
                    "query": {"term": {"nif": nif}},
                    "sort": [{"scraped_at": {"order": "desc"}}],
                    "_source": False,
                },
            )["hits"]["hits"]
            extras = hits[1:]
            if not extras:
                continue
            actions = [{"_op_type": "delete", "_index": index, "_id": h["_id"]} for h in extras]
            bulk(es, actions, refresh=False, raise_on_error=False)
            removidos += len(extras)
        logger.info("duplicados removidos: %s", removidos)
    return removidos


def validar(es: Elasticsearch, index: str, nome: str) -> None:
    total = es.count(index=index)["count"]
    resp = es.search(index=index, body={"size": 0, "aggs": {"n": {"cardinality": {"field": "nif", "precision_threshold": 40000}}}})
    distintos = resp["aggregations"]["n"]["value"]
    dups = duplicados_por_nif(es, index, size=10)
    logger.info(
        "%s: docs=%s nifs_distintos=%s nifs_repetidos=%s %s",
        nome, total, distintos, len(dups), [d["key"] for d in dups[:5]],
    )


def indexar(url: str, items: List[Dict[str, Any]], nome: str) -> None:
    es = Elasticsearch([url], request_timeout=120)
    if not es.ping():
        logger.error("%s: sem ligacao a %s", nome, url)
        return
    resultado = index_directory_items(
        INDEX,
        source_id=racius.SOURCE_ID,
        source_name="Racius · Diretório de empresas (PT)",
        run_id=time.strftime("%Y%m%dT%H%M%S", time.gmtime()),
        items=[racius._as_item(doc) for doc in items],
        trigger="script",
        flattened_fields=("ficha",),
        es=es,
    )
    logger.info("%s: %s indexadas, %s erros", nome, resultado.get("indexed_count"), resultado.get("error_count"))
    removidos = remover_duplicados(es, INDEX)
    logger.info("%s: %s duplicados removidos", nome, removidos)
    validar(es, INDEX, nome)


def main() -> int:
    items = json.loads(JSON_FILE.read_text(encoding="utf-8"))
    alvo = (sys.argv[1] if len(sys.argv) > 1 else "ambos").lower()
    logger.info("a indexar %s empresas (%s)", len(items), alvo)
    for nome, url in ALVOS.items():
        if alvo not in ("ambos", nome):
            continue
        indexar(url, items, nome)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
