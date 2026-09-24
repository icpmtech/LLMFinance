"""Diagnóstico da agregação de contratos usada pelo índice de contribuintes.

Testa variantes da *composite aggregation* sobre `adjudicantes.parsed.nif` para
localizar o que faz o Elasticsearch falhar (erro 500 «read past EOF» nos
doc-values) quando o índice está a ser escrito por outro processo.
"""
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from api.elasticsearch_client import get_es_client  # noqa: E402


def composite(sub=None, size=2000):
    node = {
        "composite": {
            "size": size,
            "sources": [{"v": {"terms": {"field": "adjudicantes.parsed.nif"}}}],
        }
    }
    if sub:
        node["aggs"] = sub
    return {"n": {"nested": {"path": "adjudicantes.parsed"}, "aggs": {"c": node}}}


def probe(label, aggs):
    body = {"size": 0, "track_total_hits": False, "aggs": aggs}
    started = time.time()
    try:
        response = get_es_client().search(index="contratos", body=body, request_timeout=900)
        node = response["aggregations"]
        node = node["n"]["c"] if "n" in node else node["c"]
        print(f"[OK]     {label}: {len(node.get('buckets') or [])} buckets em {round(time.time() - started, 1)} s")
    except Exception as exc:  # noqa: BLE001 - é diagnóstico
        print(f"[FALHOU] {label}: {round(time.time() - started, 1)} s -> {str(exc)[:220]}")


def main():
    top = {"top": {"top_hits": {"size": 3, "_source": ["nome"]}}}
    value = {"back": {"reverse_nested": {}, "aggs": {"v": {"sum": {"field": "precoContratual"}}}}}
    dates = {
        "back": {
            "reverse_nested": {},
            "aggs": {
                "f": {"min": {"field": "dataCelebracaoContrato"}},
                "l": {"max": {"field": "dataCelebracaoContrato"}},
            },
        }
    }
    probe("composite puro", composite())
    probe("composite + top_hits", composite(top))
    probe("composite + soma de valores", composite(value))
    probe("composite + datas (min/max)", composite(dates))
    probe("composite + tudo (como no serviço)", composite({**top, **value, **dates}))
    for size in (500, 1000, 5000):
        probe(f"composite + tudo (size={size})", composite({**top, **value, **dates}))
        # ajusta o size no corpo, já que composite() usa 2000 por omissão
        aggs = composite({**top, **value, **dates})
        aggs["n"]["aggs"]["c"]["composite"]["size"] = size
        probe(f"composite + tudo (size={size})", aggs)


if __name__ == "__main__":
    main()
