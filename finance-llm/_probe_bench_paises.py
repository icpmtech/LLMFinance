"""Probe dos índices de ES/FR para o benchmark multi-país."""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from api.elasticsearch_client import get_es_client

client = get_es_client(request_timeout=180)

for indice in ("contratos", "contratos_es", "contratos_fr"):
    try:
        total = client.count(index=indice).get("count", 0)
    except Exception as exc:
        print(f"{indice}: ERRO {exc}")
        continue
    print(f"{indice}: {total} documentos")
    if not total:
        continue
    mapping = client.indices.get_mapping(index=indice)
    props = list(mapping.values())[0]["mappings"].get("properties", {})
    campos = ["ano", "Ano", "cpv", "code_cpv", "valor", "montant", "valor_adjudicado", "valor_base",
              "precoContratual", "adjudicatario_nom", "acheteur_nom", "organo_nombre", "adjudicatario_nombre",
              "adjudicatario_nif", "adjudicatario_id", "acheteur_id", "organo_id",
              "date_notification", "date_publication", "fecha_adjudicacion", "fecha_publicacion",
              "lieu_execution_code", "nuts", "localidad", "dataCelebracaoContrato"]
    print("  campos presentes:", [c for c in campos if c in props])
    print("  exemplo cpv:", props.get("cpv"))


def tentar(nome, indice, body):
    inicio = time.perf_counter()
    try:
        resp = client.search(index=indice, body=body)
        print(f"{nome}: OK ({time.perf_counter() - inicio:.1f}s)")
        return resp
    except Exception as exc:
        print(f"{nome}: ERRO {type(exc).__name__} {str(exc)[:220]}")
        return None


# ES: valor robusto (script) em stats/percentiles; rank plano por adjudicatário; cpv nested
es_valor = {
    "script": {
        "source": "Math.max(doc.containsKey(params.adj) && !doc[params.adj].empty ? doc[params.adj].value : 0.0, doc.containsKey(params.base) && !doc[params.base].empty ? doc[params.base].value : 0.0)",
        "params": {"adj": "valor_adjudicado", "base": "valor_base"},
        "lang": "painless",
    }
}
es_positivo = {
    "bool": {
        "should": [
            {"range": {"valor_adjudicado": {"gt": 0}}},
            {"range": {"valor_base": {"gt": 0}}},
        ],
        "minimum_should_match": 1,
    }
}
resp = tentar(
    "ES stats+pct (script)",
    "contratos_es",
    {
        "size": 0,
        "query": {"match_all": {}},
        "aggs": {
            "p": {
                "filter": es_positivo,
                "aggs": {
                    "s": {"stats": {"script": es_valor}},
                    "pc": {"percentiles": {"script": es_valor, "percents": [25, 50, 75]}},
                },
            }
        },
    },
)
if resp:
    p = resp["aggregations"]["p"]
    print("   ES stats:", {k: p["s"].get(k) for k in ("count", "sum", "avg")})
    print("   ES pct:", p["pc"]["values"])

resp = tentar(
    "ES rank plano (terms + sum)",
    "contratos_es",
    {
        "size": 0,
        "query": {"match_all": {}},
        "aggs": {
            "top": {
                "terms": {"field": "adjudicatario_nombre.keyword", "size": 3, "order": {"v": "desc"}},
                "aggs": {"v": {"sum": es_valor}},
            }
        },
    },
)
if resp:
    print("   ES top:", [(b["key"][:34], b["doc_count"], round(b["v"]["value"] or 0)) for b in resp["aggregations"]["top"]["buckets"]])

resp = tentar(
    "ES cpv nested",
    "contratos_es",
    {
        "size": 0,
        "query": {"match_all": {}},
        "aggs": {"cpv": {"nested": {"path": "cpv"}, "aggs": {"codes": {"terms": {"field": "cpv.code", "size": 3}, "aggs": {"d": {"top_hits": {"size": 1, "_source": True}}}}}}},
    },
)
if resp:
    print("   ES cpv:", [(b["key"], b["doc_count"]) for b in resp["aggregations"]["cpv"]["codes"]["buckets"]])

# FR: valor em campo, rank plano, cpv nested, ano
fr_valor = {"field": "valor"}
resp = tentar(
    "FR stats+pct",
    "contratos_fr",
    {"size": 0, "query": {"match_all": {}}, "aggs": {"p": {"filter": {"range": {"valor": {"gt": 0}}}, "aggs": {"s": {"stats": {"field": "valor"}}, "pc": {"percentiles": {"field": "valor", "percents": [25, 50, 75]}}}}}},
)
if resp:
    p = resp["aggregations"]["p"]
    print("   FR stats:", {k: p["s"].get(k) for k in ("count", "sum", "avg")}, "pct:", p["pc"]["values"])

resp = tentar(
    "FR rank plano",
    "contratos_fr",
    {"size": 0, "query": {"match_all": {}}, "aggs": {"top": {"terms": {"field": "adjudicatario_nom.keyword", "size": 3, "order": {"v": "desc"}}, "aggs": {"v": {"sum": {"field": "valor"}}}}}},
)
if resp:
    print("   FR top:", [(b["key"][:34], b["doc_count"], round(b["v"]["value"] or 0)) for b in resp["aggregations"]["top"]["buckets"]])

resp = tentar(
    "FR cpv nested + anos",
    "contratos_fr",
    {"size": 0, "query": {"match_all": {}}, "aggs": {"cpv": {"nested": {"path": "cpv"}, "aggs": {"codes": {"terms": {"field": "cpv.code", "size": 3}}}}, "anos": {"terms": {"field": "ano", "size": 5, "order": {"_key": "desc"}}}}},
)
if resp:
    print("   FR cpv:", [(b["key"], b["doc_count"]) for b in resp["aggregations"]["cpv"]["codes"]["buckets"]])
    print("   FR anos:", [(b["key"], b["doc_count"]) for b in resp["aggregations"]["anos"]["buckets"]])

resp = tentar("ES anos", "contratos_es", {"size": 0, "aggs": {"anos": {"terms": {"field": "ano", "size": 5, "order": {"_key": "desc"}}}}})
if resp:
    print("   ES anos:", [(b["key"], b["doc_count"]) for b in resp["aggregations"]["anos"]["buckets"]])
