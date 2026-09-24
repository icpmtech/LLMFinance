"""Corre `ensure_indices` com log DEBUG para ver o erro do put_mapping."""
import logging
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

logging.basicConfig(level=logging.DEBUG, format="%(levelname)s %(name)s: %(message)s")

from api import elasticsearch_client as esc  # noqa: E402

es = esc.get_es_client()
esc.ensure_indices(es)
existing = es.indices.get_mapping(index=esc.PEOPLE_INDEX)[esc.PEOPLE_INDEX]["mappings"].get("properties", {})
print("sources:", existing.get("sources"))
print("roles.tribunal:", (existing.get("roles") or {}).get("properties", {}).get("tribunal"))
