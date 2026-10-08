"""Mede variantes de otimização do agregado role-summary."""
import copy
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


def run(label, mutate=None, reps=1):
    best = None
    for _ in range(reps):
        body = copy.deepcopy(base)
        if mutate:
            mutate(body)
        t0 = time.perf_counter()
        try:
            resp = es.search(index="contratos", body=body)
            dt = time.perf_counter() - t0
            err = None
        except Exception as exc:  # noqa: BLE001
            dt = time.perf_counter() - t0
            err = f"{type(exc).__name__}: {str(exc)[:80]}"
            resp = None
        best = dt if best is None else min(best, dt)
    extra = ""
    if resp:
        try:
            b = resp["aggregations"]["adjudicatarios"]["by_nif"]["buckets"][0]
            extra = f"| 1º adjucatário: {b['doc_count']} contratos, nome={str(b.get('name'))[:60]}"
        except Exception:  # noqa: BLE001
            pass
    print(f"{label:40s} {best:7.1f}s {err or ''} {extra}")


def to_max_name(body):
    """top_hits -> max no campo keyword (não materializa hits)."""
    for path in ("adjudicantes", "adjudicatarios"):
        body["aggs"][path]["aggs"]["by_nif"]["aggs"]["name"] = {"max": {"field": f"{path}.parsed.nome"}}
    body["aggs"]["counterparties"]["aggs"]["by_nif"]["aggs"]["name"] = {"max": {"field": "adjudicatarios.parsed.nome"}}


def cheap_years(body):
    """stats -> min+max (sem count/sum/avg)."""
    for path in ("adjudicantes", "adjudicatarios"):
        body["aggs"][path]["aggs"]["by_nif"]["aggs"]["years"] = {
            "reverse_nested": {},
            "aggs": {"min": {"min": {"field": "Ano"}}, "max": {"max": {"field": "Ano"}}},
        }


def default_precision(body):
    for path in ("adjudicantes", "adjudicatarios"):
        body["aggs"][path]["aggs"]["nifs"]["cardinality"].pop("precision_threshold", None)


def drop_years(body):
    for path in ("adjudicantes", "adjudicatarios"):
        body["aggs"][path]["aggs"]["by_nif"]["aggs"].pop("years", None)


run("0. base", None, reps=2)
run("1. nomes por max", to_max_name, reps=2)
run("2. nomes max + years min/max", lambda b: (to_max_name(b), cheap_years(b)), reps=2)
run("3. nomes max + sem years", lambda b: (to_max_name(b), drop_years(b)), reps=2)
run("4. nomes max + years min/max + prec. default", lambda b: (to_max_name(b), cheap_years(b), default_precision(b)), reps=2)
run("5. só years min/max", cheap_years, reps=2)
run("6. sem precision (base)", default_precision, reps=2)
