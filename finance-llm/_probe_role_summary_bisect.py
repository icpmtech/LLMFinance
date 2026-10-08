"""Bisseção do agregado /companies/role-summary: onde é que os ~150 s são gastos."""
import copy
import sys
import time

sys.path.insert(0, "c:/LLMFinance/finance-llm")

from api.elasticsearch_client import get_es_client, get_entity_role_summary  # noqa: E402

es = get_es_client(request_timeout=900)


class Recorder:
    """Cliente falso que captura o corpo da pesquisa e delega o resto no real."""

    def __init__(self, real):
        self.real = real
        self.body = None

    def search(self, **kwargs):
        self.body = kwargs.get("body")
        raise StopIteration

    def __getattr__(self, name):
        return getattr(self.real, name)


rec = Recorder(es)
try:
    get_entity_role_summary(role="adjudicante", top_n=25, min_contracts=1, es=rec)
except StopIteration:
    pass
base = rec.body
print("aggs:", list(base["aggs"].keys()))


def run(label, body, profile=False):
    kwargs = {"index": "contratos", "body": body, "request_timeout": 900}
    if profile:
        kwargs["profile"] = True
    t0 = time.perf_counter()
    try:
        resp = es.search(**kwargs)
    except Exception as exc:  # noqa: BLE001
        print(f"{label:34s} EXCECAO {time.perf_counter() - t0:6.1f}s {type(exc).__name__}: {exc}")
        return None
    dt = time.perf_counter() - t0
    print(f"{label:34s} {dt:6.1f}s  took={resp.get('took')}ms")
    return resp


def variant(remove=(), replace=None):
    b = copy.deepcopy(base)
    for key in remove:
        b["aggs"].pop(key, None)
    if replace:
        replace(b)
    return b


run("0. completo", copy.deepcopy(base))
run("1. sem adjudicantes/adjudicatarios", variant(remove=("adjudicantes", "adjudicatarios")))
run("2. sem counterparties", variant(remove=("counterparties",)))
run("3. sem by_cpv", variant(remove=("by_cpv",)))
run("4. sem os 3 pesados", variant(remove=("adjudicantes", "adjudicatarios", "counterparties", "by_cpv")))
run("5. sem sub-agg years", variant(replace=lambda b: [b["aggs"]["adjudicantes"]["aggs"]["by_nif"]["aggs"].pop("years", None),
                                                       b["aggs"]["adjudicatarios"]["aggs"]["by_nif"]["aggs"].pop("years", None)] and None))


def _no_precision(b):
    for path in ("adjudicantes", "adjudicatarios"):
        b["aggs"][path]["aggs"]["nifs"]["cardinality"].pop("precision_threshold", None)


run("6. cardinality sem precision", variant(replace=_no_precision))


def _order_count(b):
    for path in ("adjudicantes", "adjudicatarios"):
        b["aggs"][path]["aggs"]["by_nif"]["terms"]["order"] = {"_count": "desc"}


run("7. ordenar por _count", variant(replace=_order_count))


def _no_top_hits(b):
    for path in ("adjudicantes", "adjudicatarios"):
        b["aggs"][path]["aggs"]["by_nif"]["aggs"].pop("name", None)
    b["aggs"]["counterparties"]["aggs"]["by_nif"]["aggs"].pop("name", None)
    b["aggs"]["by_cpv"]["aggs"]["codes"]["aggs"].pop("description", None)


run("8. sem top_hits (nomes)", variant(replace=_no_top_hits))

prof = run("9. profile do completo", copy.deepcopy(base), profile=True)
if prof:
    shards = prof.get("profile", {}).get("shards", [])
    collected = []
    for shard in shards:
        for search in shard.get("searches", []):
            for agg in search.get("aggregations", []):
                collected.append(agg)
    for agg in sorted(collected, key=lambda a: -(a.get("time_in_nanos") or 0))[:12]:
        print(f"   {round((agg.get('time_in_nanos') or 0) / 1e9, 1):6.1f}s  {agg.get('type'):10s} {agg.get('description')}")
