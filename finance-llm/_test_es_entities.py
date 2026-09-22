"""Sonda das entidades do PLACSP (órgãos adjudicantes e adjudicatárias).

Uso: c:/LLMFinance/.venv/Scripts/python.exe _test_es_entities.py [termo]
"""
import os
import sys
import time

sys.path.insert(0, r"c:/LLMFinance/finance-llm")
os.environ.setdefault("ELASTICSEARCH_URL", "http://127.0.0.1:9200")

from api.elasticsearch_client import search_contratos_es_entities  # noqa: E402


def run(term: str) -> None:
    started = time.time()
    res = search_contratos_es_entities(q=term or None, size=8)
    print(f"== q={term!r} total={res.get('total')} by_kind={res.get('by_kind')} erro={res.get('error')} ({time.time() - started:.1f}s)")
    for item in res.get("items", []):
        print(
            f"  {item['kind']:<14} {str(item['name'])[:58]:<60} n={item['count']:<7}"
            f" valor={item['total_value']} cidade={item['city']!r} nif={item['nif']!r} ano={item['last_year']}"
        )


if __name__ == "__main__":
    run(sys.argv[1] if len(sys.argv) > 1 else "Renfe")
    run("")
