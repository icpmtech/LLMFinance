"""Depura a atualização do mapeamento de `finance_people` (campos novos)."""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from api import elasticsearch_client as esc  # noqa: E402

es = esc.get_es_client()
existing = es.indices.get_mapping(index=esc.PEOPLE_INDEX)[esc.PEOPLE_INDEX]["mappings"].get("properties", {})
missing = esc._missing_mapping_fields(existing, esc.INDEX_MAPPINGS[esc.PEOPLE_INDEX]["properties"])
print("faltam:", json.dumps(missing, ensure_ascii=False)[:800])
if missing:
    try:
        es.indices.put_mapping(index=esc.PEOPLE_INDEX, body={"properties": missing})
        print("put_mapping OK")
    except Exception as exc:
        print("put_mapping ERRO:", type(exc).__name__, str(exc)[:800])
else:
    print("(nada em falta)")
