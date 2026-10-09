"""Valida a ontologia, as analogias e a análise (IA e Hermes) pelo nginx.

Usa uma sessão temporária do utilizador que tem a chave DeepSeek, para a análise
poder correr com um modelo a sério; no fim revoga-a.
"""
import datetime
import json
import sys
import time
from pathlib import Path

import httpx

sys.path.insert(0, r"C:\LLMFinance\finance-llm")
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from api import auth_service, providers_service as providers  # noqa: E402
from api.elasticsearch_client import get_es_client  # noqa: E402

BASE = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:4180/api"
PERGUNTA = "licenças de software e serviços de informática"
DESTINO = Path(r"C:\LLMFinance\finance-llm\logs\_analise_ontologia.txt")

print(f"base: {BASE}")

# --- sessão temporária (a análise com o modelo precisa da chave do utilizador) ---
hits = get_es_client().search(index=providers.PROVIDER_KEYS_INDEX, body={"size": 20, "_source": ["keys"]})["hits"]["hits"]
user_id = next(h["_id"] for h in hits if (h.get("_source") or {}).get("keys", {}).get("deepseek"))
sessao = auth_service.create_session({"id": user_id}, ttl=datetime.timedelta(minutes=20))
cabecalhos = {"Authorization": f"Bearer {sessao['token']}"}
print(f"sessão temporária: {sessao['session']['id'][:8]}…")

try:
    with httpx.Client(timeout=600.0, headers=cabecalhos) as cliente:
        # 1. fontes (o mesmo que a página já tem depois de responder)
        t0 = time.perf_counter()
        r = cliente.get(f"{BASE}/deep-search/search", params={"q": PERGUNTA, "sources": "contracts", "mode": "hybrid", "per_source": 8, "max_sources": 12})
        r.raise_for_status()
        fontes = r.json()["sources"]
        print(f"\n1. fontes: {len(fontes)} em {time.perf_counter()-t0:.1f}s")
        enviar = [
            {"n": f["n"], "id": f["id"], "scope": f["scope"], "title": f["title"], "subtitle": f["subtitle"],
             "date": f.get("date"), "open": f.get("open"), "meta": f.get("meta") or {}, "links": f.get("links") or []}
            for f in fontes
        ]

        # 2. ontologia
        t0 = time.perf_counter()
        r = cliente.post(f"{BASE}/deep-search/ontology", json={"sources": enviar, "enrich": True})
        r.raise_for_status()
        ontologia = r.json()
        print(f"\n2. ontologia: {r.status_code} em {time.perf_counter()-t0:.1f}s · "
              f"{ontologia['totals']['nodes']} nós · {ontologia['totals']['edges']} arestas · {ontologia['totals']['by_type']}")
        print(f"   legenda: {[(e['type'], e['count']) for e in ontologia['legend']]}")
        for nota in ontologia["meta"]["notes"]:
            print(f"   nota: {nota}")
        for aresta in ontologia["edges"][:5]:
            print(f"   {aresta['label']:<18} {aresta['source'][:30]:<32} -> {aresta['target'][:30]} ({aresta['count']})")
        print(f"   mermaid: {len(ontologia['mermaid'].splitlines())} linhas")
        # O envelope tem de trazer o que o GraphCanvas/toStudioGraph esperam.
        faltam = [c for c in ("dimension_a", "metric", "directed", "notes", "limits") if c not in ontologia["meta"]]
        print(f"   envelope: {'OK' if not faltam else 'FALTAM ' + str(faltam)}")

        # 3. analogias
        t0 = time.perf_counter()
        r = cliente.post(f"{BASE}/deep-search/analogies", json={"sources": enviar, "contracts": 3, "similar": 3})
        r.raise_for_status()
        analogias = r.json()
        print(f"\n3. analogias: {r.status_code} em {time.perf_counter()-t0:.1f}s · {json.dumps(analogias['totals'], ensure_ascii=False)}")
        for item in analogias["items"]:
            print(f"   [{item['contrato']['id']}] {item['contrato']['title'][:50]}")
            print(f"       {item['contrato']['preco']} · CPV {item['contrato']['cpv']} · {(item['posicao'] or {}).get('frase')}")
            for sem in item["semelhantes"]:
                desvio = f"{sem['desvio_pct']:+.1f}%" if sem.get("desvio_pct") is not None else "—"
                print(f"       · {sem['title'][:46]:<48} {sem['preco']:>12} ({desvio:>7}) · {sem.get('porque')}")

        # 4. análise pela IA (DeepSeek)
        t0 = time.perf_counter()
        r = cliente.post(f"{BASE}/deep-search/analysis", json={
            "question": PERGUNTA, "sources": enviar, "ontology": ontologia, "analogies": analogias,
            "engine": "modelo", "backend": "deepseek:deepseek-chat",
        })
        r.raise_for_status()
        modelo = r.json()
        print(f"\n4. análise (modelo): {r.status_code} em {time.perf_counter()-t0:.1f}s · motor={modelo['motor']} · modelo={modelo['modelo']} · {len(modelo['texto'])} car.")
        if modelo.get("error"):
            print(f"   ERRO: {modelo['error']}")
        print("   " + (modelo["texto"][:400].replace("\n", "\n   ") or "(vazio)"))

        # 5. análise pelo Hermes
        t0 = time.perf_counter()
        r = cliente.post(f"{BASE}/deep-search/analysis", json={
            "question": PERGUNTA, "sources": enviar, "ontology": ontologia, "analogies": analogias,
            "engine": "hermes", "depth": "rapida",
        })
        r.raise_for_status()
        hermes = r.json()
        print(f"\n5. análise (Hermes): {r.status_code} em {time.perf_counter()-t0:.1f}s · motor={hermes['motor']} · modo={hermes.get('modo')} · "
              f"{len(hermes['texto'])} car. · {len(hermes.get('evidencias') or [])} evidências · {len(hermes.get('passos') or [])} passos")
        if hermes.get("error"):
            print(f"   ERRO: {hermes['error']}")
        print("   " + (hermes["texto"][:300].replace("\n", "\n   ") or "(sem texto)"))

        DESTINO.write_text(
            "=== ONTOLOGIA ===\n" + json.dumps(ontologia, ensure_ascii=False, indent=1)[:4000]
            + "\n\n=== ANALOGIAS ===\n" + json.dumps(analogias, ensure_ascii=False, indent=1)[:6000]
            + f"\n\n=== ANÁLISE (modelo {modelo.get('modelo')}) ===\n{modelo['texto']}"
            + f"\n\n=== ANÁLISE (Hermes, modo {hermes.get('modo')}) ===\n{hermes['texto']}\n",
            encoding="utf-8",
        )
        print(f"\nguardado em {DESTINO}")
finally:
    auth_service.revoke_session(sessao["session"]["id"])
    print("sessão temporária revogada.")
