"""Espera pelo backend no Docker e confirma as três rotas novas pelo nginx."""
import json
import sys
import time

import httpx

sys.path.insert(0, r"C:\LLMFinance\finance-llm")
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

BASE = "http://127.0.0.1:4180/api"
PERGUNTA = "licenças de software"


def fontes() -> list:
    with httpx.Client(timeout=300.0) as cliente:
        r = cliente.get(
            f"{BASE}/deep-search/search",
            params={"q": PERGUNTA, "sources": "contracts", "mode": "text", "per_source": 4, "max_sources": 6},
        )
        r.raise_for_status()
        return r.json()["sources"]


# 1. espera pelo backend (o arranque leva minutos; o nginx dá 502 nesse intervalo)
limite = time.time() + 720
pronto = False
while time.time() < limite:
    try:
        r = httpx.get(f"{BASE}/deep-search/meta", timeout=10.0)
        if r.status_code == 200:
            pronto = True
            break
        print(f"  {time.strftime('%H:%M:%S')} meta -> {r.status_code}")
    except Exception as exc:  # noqa: BLE001
        print(f"  {time.strftime('%H:%M:%S')} meta -> {type(exc).__name__}")
    time.sleep(15)

if not pronto:
    print("backend não respondeu em 12 minutos")
    sys.exit(1)
print("backend a responder\n")

# 2. as três rotas novas
with httpx.Client(timeout=600.0) as cliente:
    recolha = fontes()
    enviar = [
        {"n": f["n"], "id": f["id"], "scope": f["scope"], "title": f["title"], "subtitle": f["subtitle"],
         "date": f.get("date"), "open": f.get("open"), "meta": f.get("meta") or {}, "links": f.get("links") or []}
        for f in recolha
    ]
    print(f"fontes: {len(enviar)}")

    for rota, corpo in (
        ("ontology", {"sources": enviar}),
        ("analogies", {"sources": enviar, "contracts": 2, "similar": 2}),
    ):
        t0 = time.perf_counter()
        r = cliente.post(f"{BASE}/deep-search/{rota}", json=corpo)
        dados = r.json()
        print(f"{rota}: {r.status_code} em {time.perf_counter()-t0:.1f}s · "
              f"{json.dumps(dados.get('totals') or {}, ensure_ascii=False)}")

    # análise pelo Hermes (não precisa de chave de modelo para responder)
    t0 = time.perf_counter()
    r = cliente.post(
        f"{BASE}/deep-search/analysis",
        json={"question": PERGUNTA, "sources": enviar, "engine": "hermes", "depth": "rapida"},
    )
    dados = r.json()
    print(f"analysis (hermes): {r.status_code} em {time.perf_counter()-t0:.1f}s · motor={dados.get('motor')} · "
          f"modo={dados.get('modo')} · {len(dados.get('texto') or '')} car. · {len(dados.get('evidencias') or [])} evidências")
    if dados.get("error"):
        print(f"   erro: {dados['error']}")

# 3. bundle servido
html = httpx.get("http://127.0.0.1:4180/", timeout=20.0).text
import re  # noqa: E402

bundles = sorted(set(re.findall(r"assets/index-[A-Za-z0-9_-]+\.js", html)))
print(f"\nbundle servido: {bundles}")
