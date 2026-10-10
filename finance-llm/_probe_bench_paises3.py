"""Probe 3: valor/entidades em ES e FR (nomes, ids, CPV)."""
from __future__ import annotations

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
        print(f"{nome}: ERRO {type(exc).__name__} {str(exc)[:220]}")
        return None


# (a) ES: sum com script + filtro de valor positivo
resp = tentar(
    "ES sum(script) + rank",
    "contratos_es",
    {
        "size": 0,
        "query": {"range": {"valor_adjudicado": {"gt": 0}}},
        "aggs": {
            "s": {"stats": {"field": "valor_adjudicado"}},
            "pc": {"percentiles": {"field": "valor_adjudicado", "percents": [25, 50, 75]}},
            "top": {
                "terms": {"field": "adjudicatario_nombre.keyword", "size": 3, "order": {"v": "desc"}},
                "aggs": {"v": {"sum": {"script": {"source": "Math.max(doc['valor_adjudicado'].size() != 0 ? doc['valor_adjudicado'].value : 0.0, doc['valor_base'].size() != 0 ? doc['valor_base'].value : 0.0)"}}}},
            },
        },
    },
)
if resp:
    aggs = resp["aggregations"]
    print("   ES stats:", {k: aggs["s"].get(k) for k in ("count", "sum", "avg")}, "pct:", aggs["pc"]["values"])
    print("   ES top:", [(b["key"][:26], b["doc_count"], round(b["v"]["value"] or 0)) for b in aggs["top"]["buckets"]])

# (b) FR: nomes preenchidos?
resp = tentar(
    "FR nomes/ids",
    "contratos_fr",
    {
        "size": 0,
        "track_total_hits": True,
        "aggs": {
            "total": {"value_count": {"field": "doc_id"}},
            "acheteur_nom_ok": {"filter": {"exists": {"field": "acheteur_nom"}}, "aggs": {"n": {"cardinality": {"field": "acheteur_nom.keyword"}}}},
            "acheteur_id_ok": {"filter": {"exists": {"field": "acheteur_id"}}, "aggs": {"n": {"cardinality": {"field": "acheteur_id"}}}},
            "titulaires_ok": {"filter": {"nested": {"path": "titulaires", "query": {"exists": {"field": "titulaires.id"}}}}, "aggs": {"n": {"nested": {"path": "titulaires"}, "aggs": {"d": {"cardinality": {"field": "titulaires.id"}}}}}},
            "adj_nom_ok": {"filter": {"exists": {"field": "adjudicatario_nom"}}, "aggs": {"n": {"cardinality": {"field": "adjudicatario_nom.keyword"}}}},
        },
    },
)
if resp:
    aggs = resp["aggregations"]
    print("   FR total:", aggs["total"]["value"])
    print("   FR acheteur_nom preenchido:", aggs["acheteur_nom_ok"]["doc_count"], "distintos:", aggs["acheteur_nom_ok"]["n"]["value"])
    print("   FR acheteur_id preenchido:", aggs["acheteur_id_ok"]["doc_count"], "distintos:", aggs["acheteur_id_ok"]["n"]["value"])
    print("   FR titulaires com id:", aggs["titulaires_ok"]["doc_count"], "titulares distintos:", aggs["titulaires_ok"]["n"]["d"]["value"])
    print("   FR adjudicatario_nom preenchido:", aggs["adj_nom_ok"]["doc_count"], "distintos:", aggs["adj_nom_ok"]["n"]["value"])

# (c) FR: rank nested por titulaires.id com nomes por top_hits
resp = tentar(
    "FR rank titulares (nested)",
    "contratos_fr",
    {
        "size": 0,
        "query": {"range": {"valor": {"gt": 0}}},
        "aggs": {
            "s": {"stats": {"field": "valor"}},
            "tit": {
                "nested": {"path": "titulaires"},
                "aggs": {
                    "top": {
                        "terms": {"field": "titulaires.id", "size": 3, "order": {"v": "desc"}},
                        "aggs": {"nome": {"top_hits": {"size": 1, "_source": True}}, "v": {"reverse_nested": {}, "aggs": {"sum": {"sum": {"field": "valor"}}}}},
                    }
                },
            },
            "acheteurs": {
                "terms": {"field": "acheteur_id", "size": 3, "order": {"v": "desc"}},
                "aggs": {"nome": {"top_hits": {"size": 1, "_source": ["acheteur_nom", "acheteur_id"]}}, "v": {"sum": {"field": "valor"}}},
            },
        },
    },
)
if resp:
    aggs = resp["aggregations"]
    print("   FR stats:", {k: aggs["s"].get(k) for k in ("count", "sum", "avg")})
    for b in aggs["tit"]["top"]["buckets"]:
        hits = b["nome"]["hits"]["hits"]
        nome = (hits[0]["_source"].get("nom") if hits else None) or ""
        print(f"    titular {b['key']} {nome[:30]} {b['doc_count']} {round(b['v']['sum']['value'] or 0)}")
    for b in aggs["acheteurs"]["buckets"]:
        hits = b["nome"]["hits"]["hits"]
        src = hits[0]["_source"] if hits else {}
        print(f"    acheteur {b['key']} {str(src.get('acheteur_nom'))[:30]} {b['doc_count']} {round(b['v']['value'] or 0)}")

# (d) CPV por país com valor (para a página «tudo por CPV»)
for indice, campo_valor, nested_cpv in (
    ("contratos", {"field": "precoContratual"}, "cpv"),
    ("contratos_es", {"field": "valor_adjudicado"}, "cpv"),
    ("contratos_fr", {"field": "valor"}, "cpv"),
):
    resp = tentar(
        f"{indice}: cpv por valor",
        indice,
        {
            "size": 0,
            "query": {"range": {campo_valor["field"]: {"gt": 0}}},
            "aggs": {
                "cpv": {
                    "nested": {"path": nested_cpv},
                    "aggs": {
                        "codes": {
                            "terms": {"field": "cpv.code", "size": 3, "order": {"v": "desc"}},
                            "aggs": {"v": {"reverse_nested": {}, "aggs": {"sum": {"sum": campo_valor}, "pc": {"percentiles": {"field": campo_valor["field"], "percents": [50]}}}}},
                        }
                    },
                }
            },
        },
    )
    if resp:
        for b in resp["aggregations"]["cpv"]["codes"]["buckets"]:
            print(f"    {indice} cpv {b['key']:12} {b['doc_count']:>7} valor={round(b['v']['sum']['value'] or 0):>15} mediana={b['v']['pc']['values'].get('50.0')}")
