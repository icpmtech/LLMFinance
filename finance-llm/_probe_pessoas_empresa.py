"""Empresas com pessoas e ficha de empresa (novas rotas do PessoasIQ)."""
from __future__ import annotations

import json
import os
import sys

os.environ.setdefault("ELASTICSEARCH_URL", "http://127.0.0.1:9200")

from api.elasticsearch_client import companies_with_people, company_people_from_index  # noqa: E402


def mostrar(res: dict) -> str:
    return json.dumps(res, ensure_ascii=False, indent=2)


if __name__ == "__main__":
    termo = sys.argv[1] if len(sys.argv) > 1 else "503106542"
    nif = sys.argv[2] if len(sys.argv) > 2 else termo

    print(f"=== empresas com pessoas (q={termo!r}) ===")
    print(mostrar(companies_with_people(termo, size=8)))

    print(f"\n=== ficha da empresa {nif} ===")
    ficha = company_people_from_index(nif, size=50)
    print(f"nome={ficha.get('name')!r} total={ficha.get('total')} pessoas={len(ficha.get('people') or [])}")
    for p in (ficha.get("people") or [])[:8]:
        print(
            f"  {p['nif']} {p['name'][:44]:<44} cargo={str(p.get('cargo'))[:26]:<26} "
            f"org={str(p.get('role_org'))[:24]:<24} cargos_empresa={p.get('cargos_empresa')} "
            f"data={str(p.get('date'))[:10]}"
        )
