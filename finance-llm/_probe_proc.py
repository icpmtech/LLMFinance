"""Sonda: procedimentos reais e o que conta como ajuste direto."""
from __future__ import annotations

import sys
import unicodedata

sys.path.insert(0, r"c:\LLMFinance\finance-llm")

from api import padroes_global as g  # noqa: E402
from api import padroes_service as service  # noqa: E402

client = g.get_es_client()
spec = service.COUNTRIES["PT"]
body = {
    "size": 0,
    "query": {"bool": {"filter": [{"range": {"Ano": {"gte": 2025, "lte": 2025}}}]}},
    "aggs": {
        "procedimentos": {"terms": {"field": spec.procedure_field, "size": 30}, "aggs": {"valor": {"sum": {"field": spec.value_field}}}}
    },
}
r = service._search(client, spec.index, body, timeout=120)
baldes = ((r.get("aggregations") or {}).get("procedimentos") or {}).get("buckets") or []
prefixos = spec.direct_award_prefixes


def sem_acento(texto: str) -> str:
    return "".join(ch for ch in unicodedata.normalize("NFKD", texto) if not unicodedata.combining(ch))


total = 0
conta_acento = 0
conta_sem_acento = 0
for b in baldes:
    chave = str(b.get("key") or "")
    doc = int(b.get("doc_count") or 0)
    total += doc
    casa_acento = chave.lower().startswith(prefixos)
    casa_sem = sem_acento(chave.lower()).startswith(prefixos)
    if casa_acento:
        conta_acento += doc
    if casa_sem:
        conta_sem_acento += doc
    print(f"{doc:>8}  {chave!r}  acento={casa_acento} sem_acento={casa_sem}")

print("total:", total)
print(f"com acento: {conta_acento} ({conta_acento / total * 100:.1f}%)")
print(f"sem acento: {conta_sem_acento} ({conta_sem_acento / total * 100:.1f}%)")
print("classificar:", g._classificar_ajuste_direto(spec, baldes))
