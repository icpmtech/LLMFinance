"""Lista as pessoas extraídas agora e compara com as que já estavam no PessoasIQ."""
from __future__ import annotations

import os
import sys

os.environ.setdefault("ELASTICSEARCH_URL", "http://127.0.0.1:9200")

from api.elasticsearch_client import company_publicacoes  # noqa: E402
from collectors.people_extractor import extract_from_publicacoes  # noqa: E402


def show(nif: str) -> None:
    items = (company_publicacoes(nif, size=1000) or {}).get("items", [])
    people = extract_from_publicacoes(items)
    print(f"\n=== {nif}: {len(people)} pessoas extraídas de {len(items)} publicações ===")
    for p in sorted(people, key=lambda x: str((x.get("roles") or [{}])[0].get("role") or "")):
        print(f"  {p['nif']:<10} {p['name'][:52]:<52} cargos={p.get('roles_count')} coletiva={p['is_company']}")
        for role in (p.get("roles") or [])[:4]:
            print(
                f"      {str(role.get('date'))[:10]} {str(role.get('event'))[:9]:<9} "
                f"{str(role.get('role'))[:32]:<32} org={str(role.get('role_org'))[:28]:<28} "
                f"empresa={str(role.get('company_name'))[:34]}"
            )


if __name__ == "__main__":
    for arg in sys.argv[1:]:
        show(arg)
