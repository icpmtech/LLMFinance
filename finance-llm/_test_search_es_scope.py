"""Sonda da Pesquisa total: âmbito Contratos ES (PLACSP) e sugestões.

Uso: c:/LLMFinance/.venv/Scripts/python.exe _test_search_es_scope.py [termo]
"""
import json
import sys
import time
import urllib.parse
import urllib.request

BASE = "http://127.0.0.1:8002"
TERM = sys.argv[1] if len(sys.argv) > 1 else "Renfe"


def get(path: str) -> dict:
    with urllib.request.urlopen(f"{BASE}{path}", timeout=120) as res:
        return json.loads(res.read().decode("utf-8"))


def main() -> None:
    started = time.time()
    data = get(f"/search/unified?q={urllib.parse.quote(TERM)}&scope=all&size=5")
    print(f"== /search/unified q={TERM!r} -> {data.get('total')} resultados em {data.get('took_ms')} ms")
    for group in data.get("groups", []):
        flag = "ERRO" if group.get("error") else "ok"
        print(f"  [{flag}] {group['scope']:<12} total={group['total']:<8} itens={len(group['items'])}")
        if group.get("error"):
            print(f"        {group['error']}")
        if group["scope"] in ("contracts_es", "entities_es"):
            for item in group["items"][:3]:
                extra = item.get("extra") or {}
                print(f"        · {item['title'][:70]}")
                print(f"          {item['subtitle'][:80]}")
                print(f"          valor={extra.get('valor')} contratos={extra.get('contratos')} ano={extra.get('ano')}")
                print(f"          badges={item['badges']} open={item['open']}")
                print(f"          url={(item['url'] or '')[:90]}")

    only = get(f"/search/unified?q={urllib.parse.quote(TERM)}&scope=contracts_es&size=3")
    print(f"== só contracts_es -> {only.get('total')} em {only.get('took_ms')} ms")

    ent = get(f"/search/unified?q={urllib.parse.quote(TERM)}&scope=entities_es&size=6")
    group = (ent.get("groups") or [{}])[0]
    print(f"== só entities_es -> {group.get('total')} entidades em {ent.get('took_ms')} ms")
    for item in group.get("items", []):
        print(f"  {item['badges'][0] if item['badges'] else '?':<24} {item['title'][:56]:<58} {item['snippet'][:46]}")
        print(f"      open={item['open']}")

    suggest = get("/search/suggest?q=Ren")
    print(f"== /search/suggest q=Ren -> {len(suggest.get('items', []))} sugestões")
    for entry in suggest.get("items", [])[:10]:
        print(f"  {entry.get('scope'):<12} {str(entry.get('text'))[:60]:<62} {entry.get('hint')}")

    print(f"== total {time.time() - started:.1f} s")


if __name__ == "__main__":
    main()
