"""Sonda das empresas/entidades globais (todas as fontes do IQ OS).

Uso: c:/LLMFinance/.venv/Scripts/python.exe _test_companies_global.py [termo]
"""
import os
import sys
import time

sys.path.insert(0, r"c:/LLMFinance/finance-llm")
os.environ.setdefault("ELASTICSEARCH_URL", "http://127.0.0.1:9200")

from api import companies_global_service as service  # noqa: E402


def main() -> None:
    term = sys.argv[1] if len(sys.argv) > 1 else "EDP"

    started = time.time()
    summary = service.sources_summary()
    print(f"== /companies-global/sources ({time.time() - started:.1f}s) erro={summary.get('error')}")
    for card in summary.get("items", []):
        print(
            f"  {card['id']:<18} {card['label']:<20} país={card.get('country')!r:<4}"
            f" disp={card.get('available')} ({card.get('available_label')})"
            f" docs={card.get('documents')} bloqueada={bool(card.get('blocked'))}"
        )

    for termo, source in ((term, "all"), ("Renfe", "organo_es"), ("RENFE VIAJEROS", "adjudicataria_es"), ("Sonae", "entity")):
        started = time.time()
        res = service.search(termo, source=source, size=6)
        print(f"\n== search(q={termo!r}, source={source}) -> {res.get('total')} em {res.get('took_ms')} ms (sonda {time.time() - started:.1f}s)")
        for card in res.get("sources", []):
            flag = "ERRO" if card.get("error") else "ok"
            print(f"     [{flag}] {card['id']:<18} {card['label']:<20} total={card['total']:<8} devolvidos={card['returned']}")
            if card.get("error"):
                print(f"           {card['error']}")
        for row in res.get("items", [])[:6]:
            print(
                f"  {row['source']:<18} {str(row['name'])[:44]:<46} nif={row['nif']:<12}"
                f" contratos={row['contracts_count']} valor={row['total_value']}"
            )
            print(f"      {row['detail'][:80]} | open={row['open']}")


if __name__ == "__main__":
    main()
