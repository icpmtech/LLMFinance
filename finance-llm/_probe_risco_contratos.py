"""Sonda: o NIF `A61129086` (CLARANET SAU) tem mesmo 18 contratos como adjudicatária?

O cadastro diz `contracts_count: 0` e a triagem do risco encontrou 18 — importa saber
qual dos dois está errado antes de mostrar o número na UI.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from api.elasticsearch_client import CONTRIBUINTES_INDEX, get_es_client  # noqa: E402
from api.padroes_service import PT  # noqa: E402
from api.risco_service import _cadastro, _contratos_da_empresa, _client  # noqa: E402

NIFS = ["A61129086", "503412031", "510728189", "505309947", "513606084"]


def main() -> None:
    client = _client(None) or get_es_client()
    if client is None:
        print("ES indisponível")
        return

    print("== cadastro vs contratos (adjudicatária) ==")
    for nif in NIFS:
        doc = _cadastro(client, nif)
        contratos, total = _contratos_da_empresa(client, PT, nif, limit=3)
        exemplos = " | ".join(
            f"{row.get('ano')} {round(row.get('valor') or 0)}€ {(row.get('adjudicatarios') or [{}])[0].get('nome')}"
            for row in contratos[:2]
        )
        print(
            f"  {nif}: cadastro={doc.get('name')!r} contracts_count={doc.get('contracts_count')} "
            f"adjudicante={doc.get('contracts_as_adjudicante')} adjudicatario={doc.get('contracts_as_adjudicatario')} "
            f"| contratos index={total} → {exemplos}"
        )

    print("\n== contagem direta no índice `contratos` ==")
    for nif in NIFS:
        count = client.count(
            index=PT.index,
            body={"query": {"nested": {"path": "adjudicatarios.parsed", "query": {"term": {"adjudicatarios.parsed.nif": nif}}}}},
        )["count"]
        print(f"  {nif}: {count}")

    print("\n== doc do cadastro de A61129086 (fontes) ==")
    resp = client.search(
        index=CONTRIBUINTES_INDEX,
        body={"size": 1, "track_total_hits": False, "query": {"term": {"nif": "A61129086"}}},
    )
    for hit in (resp.get("hits") or {}).get("hits") or []:
        src = hit["_source"]
        for chave in sorted(src):
            if chave.startswith("src_") or chave in {"contracts_count", "contracts_as_adjudicatario", "contracts_value", "name", "names", "country", "type"}:
                valor = src[chave]
                texto = str(valor)
                print(f"  {chave}: {texto[:220]}")


if __name__ == "__main__":
    main()
