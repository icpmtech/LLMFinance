import os, time, json
from elasticsearch import Elasticsearch
from api.elasticsearch_client import CONTRATOS_ES_INDEX, _contratos_es_value_source

es = Elasticsearch([os.getenv("ELASTICSEARCH_URL", "http://127.0.0.1:9200")], request_timeout=120)
value_source = _contratos_es_value_source("valor_adjudicado")
body = {
    "size": 0,
    "track_total_hits": True,
    "query": {"match_all": {}},
    "aggs": {
        "total_value": {"sum": value_source},
        "avg_value": {"avg": value_source},
        "max_value": {"max": value_source},
        "by_year": {
            "terms": {"field": "ano", "size": 50, "order": {"_key": "desc"}},
            "aggs": {"total_value": {"sum": value_source}},
        },
        "by_month": {
            "date_histogram": {
                "field": "fecha_publicacion",
                "calendar_interval": "month",
                "format": "yyyy-MM",
                "min_doc_count": 1,
                "missing": "2000-01",
            }
        },
        "value_distribution": {
            "histogram": {
                "script": value_source["script"],
                "interval": 100000,
                "min_doc_count": 1,
            }
        },
        "top_organos": {
            "terms": {
                "field": "organo_nombre.keyword",
                "size": 8,
                "order": {"total_value": "desc"},
            },
            "aggs": {"total_value": {"sum": value_source}},
        },
        "top_adjudicatarios": {
            "terms": {
                "field": "adjudicatario_nombre.keyword",
                "size": 8,
                "order": {"total_value": "desc"},
            },
            "aggs": {"total_value": {"sum": value_source}},
        },
        "top_cpv": {
            "nested": {"path": "cpv"},
            "aggs": {
                "codes": {
                    "terms": {
                        "field": "cpv.code",
                        "size": 8,
                        "order": {"total_value": "desc"},
                    },
                    "aggs": {
                        "nombre": {"top_hits": {"size": 1, "_source": ["cpv.code", "cpv.nombre"]}},
                        "total_value": {
                            "reverse_nested": {},
                            "aggs": {"value": {"sum": value_source}},
                        },
                    },
                }
            },
        },
        "procedure_types": {"terms": {"field": "procedimiento_label", "size": 20, "missing": "N/A"}},
        "contract_types": {"terms": {"field": "tipo_contrato_label", "size": 20, "missing": "N/A"}},
    },
}

s = time.time()
try:
    r = es.search(index=CONTRATOS_ES_INDEX, body=body, request_timeout=120)
    print("took", time.time() - s, "total", r["hits"]["total"]["value"])
    print("aggs present:", list(r["aggregations"].keys()))
except Exception as e:
    print("ERR after", time.time() - s, type(e).__name__, e)
