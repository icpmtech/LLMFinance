"""Bisseção honesta (request cache do ES sempre contornada com `preference`)."""
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
BASE = rec.body


def run(label, mutate=None):
    body = copy.deepcopy(BASE)
    if mutate:
        mutate(body)
    t0 = time.perf_counter()
    try:
        resp = es.search(index="contratos", body=body, preference=str(random.random()))
        dt = time.perf_counter() - t0
        buckets = resp["aggregations"]["adjudicatarios"]["by_nif"]["buckets"]
        first = buckets[0]
        val = first.get("total_value", {}).get("value", {}).get("value")
        print(f"{label:42s} {dt:7.1f}s took={resp.get('took'):>7}ms  top_adj={first['key']} n={first['doc_count']} v={round(val or 0)}")
    except Exception as exc:  # noqa: BLE001
        print(f"{label:42s} {time.perf_counter() - t0:7.1f}s ERRO {str(exc)[:110]}")


def drop_top_hits(b):
    for p in ("adjudicantes", "adjudicatarios"):
        b["aggs"][p]["aggs"]["by_nif"]["aggs"].pop("name", None)


def drop_years(b):
    for p in ("adjudicantes", "adjudicatarios"):
        b["aggs"][p]["aggs"]["by_nif"]["aggs"].pop("years", None)


def drop_cardinality(b):
    for p in ("adjudicantes", "adjudicatarios"):
        b["aggs"][p]["aggs"].pop("nifs", None)


def drop_counterparties(b):
    b["aggs"].pop("counterparties", None)


def keep_only_role_value(b):
    """Só o ranking por valor: sem nomes, sem anos, sem cardinalidade, sem contrapartes."""
    drop_top_hits(b)
    drop_years(b)
    drop_cardinality(b)
    drop_counterparties(b)
    for p in ("adjudicatarios",):
        b["aggs"].pop(p, None)


run("0. base")
run("1. sem top_hits", drop_top_hits)
run("2. sem years", drop_years)
run("3. sem top_hits nem years", lambda b: (drop_top_hits(b), drop_years(b)))
run("4. sem cardinality", drop_cardinality)
run("5. sem counterparties", drop_counterparties)
run("6. só ranking por valor", keep_only_role_value)
