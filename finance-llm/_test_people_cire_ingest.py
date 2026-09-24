"""Testa a ingestão de pessoas do CIRE no PessoasIQ (amostra limitada).

Uso:
    python _test_people_cire_ingest.py [limite_publicacoes]

Sem argumento usa 500 publicações. Com `0` corre o CIRE inteiro.
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from api.elasticsearch_client import (  # noqa: E402
    get_es_client,
    get_person_by_nif,
    index_people_from_cire,
    people_status,
    search_people,
)


def main() -> int:
    limit = int(sys.argv[1]) if len(sys.argv) > 1 else 500
    progress: dict = {}
    result = index_people_from_cire(
        limit=limit or None,
        progress=progress,
        papeis=None,
    )
    print("progresso:", progress)
    print("resultado:", {k: v for k, v in result.items() if k != "people"})

    status = people_status()
    print("índice:", status.get("index"), "| documentos:", status.get("documents"))
    print("por fonte:", status.get("by_source"))
    print("top cargos:", (status.get("top_roles") or [])[:6])

    page = search_people(role="Administrador da insolvência", size=3)
    print("pesquisa por cargo:", page.get("total"), "resultados")
    for item in page.get("items") or []:
        nif = item.get("nif")
        person = get_person_by_nif(nif)
        roles = person.get("roles") or []
        print(f"   {nif} {person.get('name')} | cargos: {len(roles)} | 1.º: {roles[0].get('role')} em {roles[0].get('company_name')}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
