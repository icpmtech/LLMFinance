"""Probe 2: runtime mappings no ES e qualidade dos dados FR."""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from api.elasticsearch_client import get_es_client

client = get_es_client(request_timeout=180)


def tentar(nome, indice, body):
    try:
        resp = client.search(index=indice, body=body)
        print(f"{nome}: OK")
        return resp
    except Exception as exc:
        print(f"{nome}: ERRO {type(exc).__name__} {str(exc)[:200]}")
        return None


# 1) runtime mapping robusto para o valor espanhol, usado em stats/percentiles/range
runtime = {
    "valor_bench": {
        "type": "double",
        "script": {
            "source": (
                "double a = doc.containsKey('valor_adjudicado') && !doc['valor_adjudicado'].empty ? doc['valor_adjudicado'].value : 0.0; "
                "double b = doc.containsKey('valor_base') && !doc['valor_base'].empty ? doc['valor_base'].value : 0.0; "
                "return Math.max(a, b);"
            )
        },
    }
}
resp = tentar(
    "ES runtime + stats/percentiles/range",
    "contratos_es",
    {
        "size": 0,
        "runtime_mappings": runtime,
        "query": {"range": {"valor_bench": {"gt": 0}}},
        "aggs": {
            "s": {"stats": {"field": "valor_bench"}},
            "pc": {"percentiles": {"field": "valor_bench", "percents": [25, 50, 75]}},
            "top": {"terms": {"field": "adjudicatario_nombre.keyword", "size": 3, "order": {"v": "desc"}}, "aggs": {"v": {"sum": {"field": "valor_bench"}}}},
        },
    },
)
if resp:
    aggs = resp["aggregations"]
    print("   stats:", {k: aggs["s"].get(k) for k in ("count", "sum", "avg")})
    print("   pct:", aggs["pc"]["values"])
    print("   top:", [(b["key"][:30], b["doc_count"], round(b["v"]["value"] or 0)) for b in aggs["top"]["buckets"]])

# 2) ES: nome do adjudicatário vs órgão por CPV
resp = tentar(
    "ES cpv+entidade",
    "contratos_es",
    {
        "size": 0,
        "query": {"nested": {"path": "cpv", "query": {"prefix": {"cpv.code": "79341000"}}}},
        "aggs": {
            "orgaos": {"terms": {"field": "organo_nombre.keyword", "size": 3, "order": {"v": "desc"}}, "aggs": {"v": {"sum": {"field": "valor_adjudicado"}}}},
            "adjs": {"terms": {"field": "adjudicatario_nombre.keyword", "size": 3, "order": {"v": "desc"}}, "aggs": {"v": {"sum": {"field": "valor_adjudicado"}}}},
        },
    },
)
if resp:
    aggs = resp["aggregations"]
    print("   ES órgãos:", [(b["key"][:28], b["doc_count"]) for b in aggs["orgaos"]["buckets"]])
    print("   ES adjs:", [(b["key"][:28], b["doc_count"]) for b in aggs["adjs"]["buckets"]])

# 3) FR: amostra + valor por campo + adjudicatario_nom preenchido?
resp = tentar("FR amostra", "contratos_fr", {"size": 2, "query": {"match_all": {}}, "_source": ["doc_id", "ano", "valor", "montant", "montant_estime", "adjudicatario_nom", "acheteur_nom", "titulaires", "code_cpv", "lieu_execution_code", "adjudicatario_id"]})
if resp:
    for hit in resp["hits"]["hits"]:
        src = hit["_source"]
        print("   ", json.dumps({k: (v if not isinstance(v, list) else [str(x)[:60] for x in v]) for k, v in src.items()}, ensure_ascii=False)[:420])

resp = tentar(
    "FR: montant vs valor vs titulaires",
    "contratos_fr",
    {
        "size": 0,
        "track_total_hits": True,
        "aggs": {
            "com_valor": {"filter": {"range": {"valor": {"gt": 0}}}, "aggs": {"s": {"stats": {"field": "valor"}}}},
            "com_montant": {"filter": {"range": {"montant": {"gt": 0}}}, "aggs": {"s": {"stats": {"field": "montant"}}}},
            "com_adj_nome": {"filter": {"range": {"valor": {"gt": 0}}, "must": []}, "aggs": {"n": {"cardinality": {"field": "adjudicatario_nom.keyword"}}}},
            "adj_nao_vazio": {"filter": {"wildcard": {"adjudicatario_nom.keyword": "*"}}, "aggs": {"n": {"cardinality": {"field": "adjudicatario_nom.keyword"}}}},
            "acheteur_nao_vazio": {"filter": {"wildcard": {"acheteur_nom.keyword": "*"}}, "aggs": {"n": {"cardinality": {"field": "acheteur_nom.keyword"}}}},
            "anos": {"terms": {"field": "ano", "size": 4, "order": {"_key": "desc"}}},
        },
    },
)
if resp:
    aggs = resp["aggregations"]
    print("   FR total:", resp["hits"]["total"]["value"])
    print("   FR com valor>0:", aggs["com_valor"]["doc_count"], "stats:", {k: aggs["com_valor"]["s"].get(k) for k in ("sum", "avg")})
    print("   FR com montant>0:", aggs["com_montant"]["doc_count"], "stats:", {k: aggs["com_montant"]["s"].get(k) for k in ("sum", "avg")})
    print("   FR adjudicatario_nom distintos (não vazios):", aggs["adj_nao_vazio"]["doc_count"], aggs["adj_nao_vazio"]["n"]["value"])
    print("   FR acheteur_nom distintos (não vazios):", aggs["acheteur_nao_vazio"]["doc_count"], aggs["acheteur_nao_vazio"]["n"]["value"])
