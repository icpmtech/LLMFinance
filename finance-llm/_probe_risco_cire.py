"""Sonda: encontrar uma empresa **insolvente** (papel Insolvente no CIRE) com contratos.

Serve para validar o filtro por papel: sem ele, bancos/AT/SS apareciam como
insolventes por serem credores.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from api.elasticsearch_client import CONTRIBUINTES_INDEX, get_es_client  # noqa: E402
from api.padroes_service import CIRE_INDEX, _client  # noqa: E402


def main() -> None:
    client = _client(None) or get_es_client()
    if client is None:
        print("ES indisponível")
        return

    cire = client.search(
        index=CIRE_INDEX,
        body={
            "size": 0,
            "track_total_hits": False,
            "query": {"nested": {"path": "intervenientes", "query": {"match": {"intervenientes.papel": "Insolvente"}}}},
            "aggs": {
                "nifs": {
                    "nested": {"path": "intervenientes"},
                    "aggs": {
                        "nif": {
                            "terms": {"field": "intervenientes.nif", "size": 40},
                            "aggs": {
                                "papeis": {"terms": {"field": "intervenientes.papel", "size": 5}},
                            },
                        }
                    },
                }
            },
        },
        request_timeout=60,
    )
    baldes = ((cire.get("aggregations") or {}).get("nifs") or {}).get("nif", {}).get("buckets") or []
    print(f"candidatos no CIRE: {len(baldes)}")
    testados = 0
    for balde in baldes:
        nif = balde["key"]
        papeis = [item["key"] for item in balde.get("papeis", {}).get("buckets") or []]
        if not any("nsolvente" in papel for papel in papeis):
            continue
        contratos = client.count(
            index="contratos",
            body={
                "query": {
                    "nested": {
                        "path": "adjudicatarios.parsed",
                        "query": {"term": {"adjudicatarios.parsed.nif": nif}},
                    }
                }
            },
            request_timeout=60,
        )["count"]
        nome = client.search(
            index=CONTRIBUINTES_INDEX,
            body={"size": 1, "track_total_hits": False, "_source": ["name"], "query": {"term": {"nif": nif}}},
            request_timeout=30,
        )
        hits = (nome.get("hits") or {}).get("hits") or []
        print(f"  {nif} · contratos={contratos} · papeis={papeis} · nome={(hits[0]['_source']['name'] if hits else '?')}")
        testados += 1
        if testados >= 8:
            break


if __name__ == "__main__":
    main()
