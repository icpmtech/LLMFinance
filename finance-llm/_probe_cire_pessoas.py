"""Sondagem dos intervenientes do CIRE para alimentar o PessoasIQ.

Mostra exemplos por papel e a distribuição de NIF (pessoa singular vs pessoa
coletiva), para decidir o que entra no índice `finance_people`.
"""
import json
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from api.elasticsearch_client import CIRE_INDEX, get_es_client  # noqa: E402

PAPEIS = ["Administrador Insolvência", "Insolvente", "Credor", "Requerente", "Devedor"]


def main() -> int:
    es = get_es_client()
    for papel in PAPEIS:
        response = es.search(
            index=CIRE_INDEX,
            body={
                "size": 1,
                "query": {"nested": {"path": "intervenientes", "query": {"term": {"intervenientes.papel": papel}}}},
                "_source": ["pub_id", "processo", "processo_numero", "especie", "tipo", "tribunal_comarca", "insolvente", "intervenientes", "data_publicacao"],
            },
        )
        hits = response["hits"]["hits"]
        print(f"=== {papel} ===")
        if not hits:
            print("   (sem exemplos)")
            continue
        source = hits[0]["_source"]
        print("   processo:", source.get("processo"), "| numero:", source.get("processo_numero"), "| especie:", source.get("especie"))
        print("   tribunal:", source.get("tribunal_comarca"), "| insolvente:", source.get("insolvente"), "| data:", source.get("data_publicacao"))
        counts = Counter()
        for item in source.get("intervenientes") or []:
            nif = str(item.get("nif") or "")
            counts[item.get("papel") or "?"] += 1
            print(f"      {item.get('papel')} | {item.get('nome')} | nif={nif!r}")
        print("   papeis no doc:", dict(counts))
        print()
    return 0


if __name__ == "__main__":
    sys.exit(main())
