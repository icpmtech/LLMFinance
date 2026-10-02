"""Enriquece entidades já indexadas com CAE recolhido do PNS/RNPC.

Uso:
    python _enrich_entities_cae.py [--nif NIF] [--limit N] [--dry-run]

Exemplos:
    python _enrich_entities_cae.py --nif 500189412
    python _enrich_entities_cae.py --limit 50
    python _enrich_entities_cae.py --limit 200 --dry-run
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from api.elasticsearch_client import get_es_client, ENTITIES_INDEX
from api.entities_service import enrich_entity_cae

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)


def enrich_one(nif: str, dry_run: bool = False) -> None:
    es = get_es_client()
    doc_id = f"{ENTITIES_INDEX}:{nif}"
    try:
        res = es.get(index=ENTITIES_INDEX, id=doc_id)
        doc = res["_source"]
    except Exception as exc:
        logger.error("NIF %s não encontrado: %s", nif, exc)
        return

    before = {k: doc.get(k) for k in ("cae_principal", "caes_secundarios")}
    enriched = enrich_entity_cae(doc, min_interval=0.6)
    after = {k: enriched.get(k) for k in ("cae_principal", "caes_secundarios")}
    logger.info("NIF %s | antes %s | depois %s", nif, before, after)

    if not dry_run:
        es.index(index=ENTITIES_INDEX, id=doc_id, document=enriched, refresh=True)
        logger.info("NIF %s reindexado", nif)
    else:
        print(json.dumps(after, ensure_ascii=False))


def enrich_many(limit: int, dry_run: bool = False) -> None:
    es = get_es_client()
    query = {
        "size": limit,
        "query": {
            "bool": {
                "must": [
                    {"exists": {"field": "nif"}},
                    {"term": {"country": "Portugal"}},
                ],
                "must_not": [
                    {"exists": {"field": "cae_principal"}},
                ],
            }
        },
        "sort": [{"total_value": {"order": "desc"}}],
    }
    res = es.search(index=ENTITIES_INDEX, body=query)
    hits = res["hits"]["hits"]
    logger.info("A enriquecer %d entidades", len(hits))

    updated = 0
    for hit in hits:
        doc = hit["_source"]
        nif = doc.get("nif")
        name = doc.get("name")
        if not nif or not name:
            continue
        try:
            enriched = enrich_entity_cae(doc, min_interval=0.6)
            if enriched.get("cae_principal"):
                if not dry_run:
                    es.index(index=ENTITIES_INDEX, id=hit["_id"], document=enriched)
                updated += 1
                logger.info("[%d/%d] %s - %s = %s", updated, len(hits), nif, name, enriched.get("cae_principal"))
            else:
                logger.info("[%d/%d] %s - %s = sem CAE", updated, len(hits), nif, name)
        except Exception as exc:
            logger.warning("Falha para %s: %s", nif, exc)

    if not dry_run and updated:
        es.indices.refresh(index=ENTITIES_INDEX)
    logger.info("Total atualizado: %d", updated)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--nif", help="NIF específico a enriquecer")
    parser.add_argument("--limit", type=int, default=0, help="Número de entidades a enriquecer")
    parser.add_argument("--dry-run", action="store_true", help="Não gravar no Elasticsearch")
    args = parser.parse_args()

    if args.nif:
        enrich_one(args.nif, dry_run=args.dry_run)
    elif args.limit > 0:
        enrich_many(args.limit, dry_run=args.dry_run)
    else:
        parser.print_help()
