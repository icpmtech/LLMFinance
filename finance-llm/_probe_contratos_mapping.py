"""Verifica os campos de `detail` das specs aninhadas (contratos e CIRE).

Duas perguntas:
  1. O `localExecucao` dos contratos (fonte da localizacao) esta na raiz?
  2. O `tribunal_comarca`/`especie`/`tipo` do CIRE esta na raiz ou dentro de
     `intervenientes`?

Um `top_hits` dentro de uma agregacao `nested` devolve o **objeto aninhado**,
por isso os campos da raiz so sao acessiveis por `reverse_nested`.
"""

from __future__ import annotations

import json

from elasticsearch import Elasticsearch

ES = "http://127.0.0.1:9200"


def root_and_nested(client: Elasticsearch, index: str, nested_path: str) -> None:
    mapping = client.indices.get_mapping(index=index)
    props = next(iter(mapping.values()))["mappings"].get("properties", {})
    node = props
    for step in nested_path.split("."):
        node = (node.get(step) or {}).get("properties") or {}
    print(f"{index}: raiz tem {len(props)} campos; {nested_path} tem {sorted(node)}")


def main() -> int:
    client = Elasticsearch(ES, request_timeout=180)

    root_and_nested(client, "contratos", "adjudicantes.parsed")

    mapping = client.indices.get_mapping(index="finance_cire")
    props = next(iter(mapping.values()))["mappings"].get("properties", {})
    intervenientes = (props.get("intervenientes") or {}).get("properties") or {}
    print("finance_cire.intervenientes:", sorted(intervenientes))
    for field in ("tribunal_comarca", "especie", "tipo"):
        print(f"  finance_cire raiz tem {field}: {field in props}")

    agg = client.search(
        index="contratos",
        size=0,
        aggs={"v": {"terms": {"field": "localExecucao", "size": 12}}},
    )
    print("localExecucao (valores mais frequentes):")
    for bucket in agg["aggregations"]["v"]["buckets"]:
        print(f"  {bucket['doc_count']:>8}  {json.dumps(bucket['key'], ensure_ascii=False)}")

    sample = client.search(
        index="contratos",
        size=0,
        query={"wildcard": {"localExecucao": {"value": "*,*,*"}}},
        track_total_hits=True,
    )
    print("contratos com 2+ virgulas em localExecucao:", sample["hits"]["total"]["value"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
