"""Sonda: de onde pode vir a localização (distrito/concelho) para os contribuintes.

Inspeciona amostras dos índices que alimentam `finance_contribuintes` para
perceber que campos de localização existem e como estão preenchidos.

Uso:  python _probe_contribuintes_local.py
"""
from __future__ import annotations

import json
from collections import Counter

from api.elasticsearch_client import ensure_indices, get_es_client

client = get_es_client()
if client is None:
    raise SystemExit("Elasticsearch indisponível")
ensure_indices(client)


def sample(index: str, fields: list[str], size: int = 3) -> None:
    print(f"\n=== {index}")
    try:
        resp = client.search(index=index, body={"size": size, "query": {"match_all": {}}})
    except Exception as exc:
        print(f"    ERRO: {exc}")
        return
    hits = resp.get("hits", {}).get("hits", [])
    print(f"    exemplos: {len(hits)}")
    for hit in hits:
        source = hit.get("_source", {})
        picked = {name: source.get(name) for name in fields if name in source}
        print("    " + json.dumps(picked, ensure_ascii=False)[:320])


def distinct(index: str, field: str, size: int = 12) -> None:
    try:
        resp = client.search(
            index=index,
            body={"size": 0, "aggs": {"values": {"terms": {"field": field, "size": size}}}},
        )
        buckets = resp.get("aggregations", {}).get("values", {}).get("buckets", [])
        total = resp.get("hits", {}).get("total", {})
        total_value = total.get("value") if isinstance(total, dict) else total
        print(f"\n--- {index} · {field} (docs={total_value})")
        for bucket in buckets:
            print(f"      {bucket['key']!r}: {bucket['doc_count']}")
    except Exception as exc:
        print(f"\n--- {index} · {field}: ERRO {exc}")


def location_coverage() -> None:
    """Quantos contribuintes têm cada subcampo de `location` preenchido."""
    print("\n=== cobertura de `location` em finance_contribuintes")
    fields = ["location.pais", "location.distrito", "location.concelho", "location.freguesia", "location.codigo_postal"]
    aggs = {f"has_{i}": {"filter": {"exists": {"field": field}}} for i, field in enumerate(fields)}
    try:
        resp = client.search(index="finance_contribuintes", body={"size": 0, "aggs": aggs})
    except Exception as exc:
        print(f"    ERRO: {exc}")
        return
    aggs_resp = resp.get("aggregations", {})
    for i, field in enumerate(fields):
        print(f"      {field}: {(aggs_resp.get(f'has_{i}') or {}).get('doc_count', 0)}")


def source_field_coverage() -> None:
    """Campos de localização presentes nos documentos-fonte (amostra dirigida)."""
    checks = [
        ("contratos", ["localExecucao", "NUTs"]),
        ("finance_entities", ["concelho", "distrito", "localExecucao", "municipality", "district", "nuts", "region"]),
        ("finance_publicacoes_mj", ["concelho", "distrito", "freguesia", "codigo_postal"]),
        ("finance_firmas", ["concelho", "distrito", "freguesia"]),
        ("finance_cire", ["concelho", "distrito", "tribunal_comarca"]),
    ]
    for index, fields in checks:
        sample(index, fields)
    for field in ("localExecucao", "NUTs"):
        distinct("contratos", field)
    # quantos contratos têm local de execução preenchido
    try:
        resp = client.search(
            index="contratos",
            body={
                "size": 0,
                "aggs": {
                    "total": {"value_count": {"field": "localExecucao"}},
                    "com_local": {"filter": {"exists": {"field": "localExecucao"}}},
                },
            },
        )
        aggs = resp.get("aggregations", {})
        print(f"\n--- contratos: com localExecucao = {(aggs.get('com_local') or {}).get('doc_count')}")
    except Exception as exc:
        print(f"\n--- contratos: ERRO {exc}")


def main() -> None:
    location_coverage()
    source_field_coverage()


if __name__ == "__main__":
    main()
