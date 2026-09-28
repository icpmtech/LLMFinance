"""Porque é que a extração de pessoas não encontra nada numa entidade com publicações?

Compara uma entidade «vazia» (503106542) com uma com pessoas (502604751).
"""
from __future__ import annotations

import os
import sys

os.environ.setdefault("ELASTICSEARCH_URL", "http://127.0.0.1:9200")

from api.elasticsearch_client import company_publicacoes  # noqa: E402
from collectors.people_extractor import extract_from_publicacoes  # noqa: E402


def inspect(nif: str) -> None:
    res = company_publicacoes(nif, size=1000) or {}
    items = res.get("items", [])
    print(f"\n=== {nif}: {len(items)} publicações (total declarado {res.get('total')}) ===")
    sem_texto = 0
    for it in items[:6]:
        texto = (it.get("texto") or "")
        print(
            f"  pub={it.get('pub_id')} data={it.get('data_publicacao')} "
            f"acto={(it.get('acto') or '')[:52]!r} texto={len(texto)} chars "
            f"pessoas={len(it.get('pessoas') or [])} detalhe={bool(it.get('detalhe_url') or it.get('has_documento'))}"
        )
    for it in items:
        if not (it.get("texto") or "").strip():
            sem_texto += 1
    people = extract_from_publicacoes(items)
    print(f"  -> {len(people)} pessoas extraídas | {sem_texto}/{len(items)} publicações sem texto integral")


if __name__ == "__main__":
    for arg in (sys.argv[1:] or ["503106542", "502604751"]):
        inspect(arg)
