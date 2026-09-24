"""Ingestão de registos LEI do GLEIF (golden copy → ficheiro + Elasticsearch).

Uso:
    python _gleif_ingest.py                 # Portugal (18k registos), via API oficial
    python _gleif_ingest.py PT ES           # Portugal + Espanha
    python _gleif_ingest.py --source file   # reindexar data/gleif/lei.jsonl
    python _gleif_ingest.py --source golden-copy --path lei2-latest.zip
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from api import gleif_service as service  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="Ingestão de registos LEI (GLEIF).")
    parser.add_argument("countries", nargs="*", default=None, help="Códigos ISO (ex.: PT ES)")
    parser.add_argument("--source", default="api", help="api | file | golden-copy | golden-copy-download")
    parser.add_argument("--path", default=None, help="Ficheiro golden copy (ZIP/CSV/XML/JSON)")
    parser.add_argument("--limit", type=int, default=None, help="Máximo de registos")
    parser.add_argument("--no-replace", action="store_true", help="Acrescentar em vez de substituir")
    args = parser.parse_args()

    result = service.ingest(
        source=args.source,
        countries=args.countries or None,
        path=args.path,
        limit=args.limit,
        replace=not args.no_replace,
        wait=True,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
    return 0 if result.get("status") == "done" else 1


if __name__ == "__main__":
    raise SystemExit(main())
