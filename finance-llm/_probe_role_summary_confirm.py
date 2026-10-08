"""Confirma a variante rápida: cache-busting, valores iguais e erro do `max` em nome."""
import copy
import random
import sys
import time

sys.path.insert(0, "c:/LLMFinance/finance-llm")

from api.elasticsearch_client import get_es_client, get_entity_role_summary  # noqa: E402

es = get_es_client(request_timeout=900)


class Recorder:
    def __init__(self, real):
        self.real = real
        self.body = None

    def search(self, **kwargs):
        self.body = copy.deepcopy(kwargs.get("body"))
        raise StopIteration

    def __getattr__(self, name):
        return getattr(self.real, name)


rec = Recorder(es)
try:
    get_entity_role_summary(role="adjudicante", top_n=25, min_contracts=1, es=rec)
except StopIteration:
    pass
base = rec.body


def execute(body, label):
    t0 = time.perf_counter()
    try:
        resp = es.search(index="contratos", body=body, preference=str(random.random()))
        dt = time.perf_counter() - t0
        print(f"{label:46s} {dt:7.2f}s took={resp.get('took')}ms")
        return resp
    except Exception as exc:  # noqa: BLE001
        print(f"{label:46s} {time.perf_counter() - t0:7.2f}s ERRO: {str(exc)[:260]}")
        return None


def prime(body, n=12):
    out = []
    for path in ("adjudicantes", "adjudicatarios"):
        for b in body["aggs"][path]["by_nif"]["buckets"][:n]:
            name = b.get("name")
            if isinstance(name, dict) and "hits" in name:
                hits = name["hits"]["hits"]
                label = hits[0]["_source"]["nome"] if hits else None
            else:
                label = name
            out.append((b["key"], b["doc_count"], round(b.get("total_value", {}).get("value", {}).get("value") or 0), label))
    return out


def cheap_years(body):
    for path in ("adjudicantes", "adjudicatarios"):
        body["aggs"][path]["aggs"]["by_nif"]["aggs"]["years"] = {
            "reverse_nested": {},
            "aggs": {"min": {"min": {"field": "Ano"}}, "max": {"max": {"field": "Ano"}}},
        }


def max_name(body):
    for path in ("adjudicantes", "adjudicatarios"):
        body["aggs"][path]["aggs"]["by_nif"]["aggs"]["name"] = {"max": {"field": f"{path}.parsed.nome"}}


b_base = copy.deepcopy(base)
r_base = execute(b_base, "base (sem preference fixa)")

b_fast = copy.deepcopy(base)
cheap_years(b_fast)
r_fast = execute(b_fast, "years min/max (cache-bust)")

if r_base and r_fast:
    a, b = prime(r_base["aggregations"]), prime(r_fast["aggregations"])
    print("valores iguais?", a == b)
    for x, y in zip(a[:3], b[:3]):
        print("   base :", x)
        print("   fast :", y)

b_max = copy.deepcopy(base)
max_name(b_max)
execute(b_max, "nome por max (ver erro completo)")
