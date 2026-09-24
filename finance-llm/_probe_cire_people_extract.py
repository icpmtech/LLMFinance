"""Testa a extração de pessoas do CIRE (sem indexar) numa amostra de publicações."""
import importlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from api.elasticsearch_client import _iter_cire_publications, get_es_client  # noqa: E402

cire_people = importlib.import_module("collectors.cire_people")


def main() -> int:
    es = get_es_client()
    progress: dict = {}
    pubs = list(_iter_cire_publications(es, limit=400, page_size=200, progress=progress))
    print(f"publicações lidas: {len(pubs)}")

    docs = cire_people.extract_from_cire(pubs)
    print(f"pessoas (só singulares): {len(docs)}")
    docs_all = cire_people.extract_from_cire(pubs, include_companies=True)
    print(f"pessoas + empresas: {len(docs_all)}")

    docs_insolv = cire_people.extract_from_cire(pubs, papeis=["Insolvente", "Administrador da insolvência"])
    print(f"só insolventes/administradores: {len(docs_insolv)}")

    sample = max(docs, key=lambda d: d.get("roles_count") or 0)
    print("\n--- amostra (mais cargos) ---")
    print(json.dumps({k: v for k, v in sample.items() if k != "roles"}, ensure_ascii=False, indent=2))
    print(json.dumps(sample["roles"][:2], ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
