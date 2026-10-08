"""Validação de ponta a ponta contra o backend no Docker.

1. abre uma sessão temporária do utilizador que tem a chave DeepSeek;
2. corre `/deep-search/search` e confirma que cada contrato traz `links`;
3. corre `/deep-search/ask` com o **DeepSeek** e guarda a resposta;
4. revoga a sessão temporária.

A chave e o token nunca são impressos.
"""
import json
import sys
import time
from pathlib import Path

import httpx

sys.path.insert(0, r"C:\LLMFinance\finance-llm")
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from api import auth_service, providers_service as providers  # noqa: E402
from api.elasticsearch_client import get_es_client  # noqa: E402

BASE = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8002"
DESTINO = Path(r"C:\LLMFinance\finance-llm\logs\_resposta_deepseek_docker.txt")
PERGUNTA = "Quais são os maiores contratos de 2026 e quem os ganhou?"
BACKEND = "deepseek:deepseek-chat"

es = get_es_client()
hits = es.search(index=providers.PROVIDER_KEYS_INDEX, body={"size": 20, "_source": ["keys"]})["hits"]["hits"]
user_id = next(h["_id"] for h in hits if (h.get("_source") or {}).get("keys", {}).get("deepseek"))
utilizador = auth_service.load_user(user_id) if hasattr(auth_service, "load_user") else {"id": user_id}
sessao = auth_service.create_session(utilizador, ttl=__import__("datetime").timedelta(minutes=20))
cabecalhos = {"Authorization": f"Bearer {sessao['token']}"}
print(f"sessão temporária criada para {user_id} (id {sessao['session']['id'][:8]}…)")

try:
    # --- 1. recuperação: cada contrato traz ligações para as fichas ---
    with httpx.Client(timeout=300.0) as cliente:
        r = cliente.get(
            f"{BASE}/deep-search/search",
            params={"q": PERGUNTA, "sources": "contracts", "mode": "hybrid", "per_source": 4, "max_sources": 4},
            headers=cabecalhos,
        )
        r.raise_for_status()
        dados = r.json()
    contratos = [s for s in dados.get("sources") or [] if s.get("scope") == "contracts"]
    com_ligacoes = [s for s in contratos if len(s.get("links") or []) >= 2]
    print(f"\nsearch: {len(contratos)} contratos, {len(com_ligacoes)} com ligações")
    for fonte in contratos[:2]:
        print(f"  [{fonte['n']}] {json.dumps(fonte.get('meta') or {}, ensure_ascii=False)[:130]}")
        for ligacao in fonte.get("links") or []:
            destino = f"{ligacao['view']}:{ligacao['arg']}" if ligacao["view"] else "(sem NIF)"
            print(f"        {ligacao['label']:<20} {str(ligacao['text'])[:34]:<36} -> {destino}")
    if not com_ligacoes:
        print("FALHA: os contratos não trazem ligações.")

    # --- 2. resposta do DeepSeek ---
    print(f"\n--- /deep-search/ask com {BACKEND} ---")
    texto = []
    mercado = None
    t0 = time.perf_counter()
    with httpx.Client(timeout=600.0) as cliente:
        with cliente.stream(
            "POST",
            f"{BASE}/deep-search/ask",
            json={"question": PERGUNTA, "backend": BACKEND, "sources": ["contracts"], "mode": "hybrid",
                  "per_source": 6, "max_sources": 12},
            headers=cabecalhos,
        ) as resposta:
            evento = None
            for linha in resposta.iter_lines():
                if linha.startswith("event:"):
                    evento = linha[6:].strip()
                elif linha.startswith("data:"):
                    try:
                        carga = json.loads(linha[5:].strip())
                    except json.JSONDecodeError:
                        continue
                    if evento == "sources":
                        print(f"  fontes: {len(carga.get('sources') or [])} em {carga.get('took_ms')} ms · "
                              f"modelo {carga.get('model')}")
                    elif evento == "error":
                        print(f"  ERROR: {carga}")
                    elif evento == "done":
                        mercado = carga.get("mercado") or []
                        texto.append(carga.get("answer") or "")
                    evento = None
    resposta_final = "".join(texto)
    duracao = time.perf_counter() - t0
    print(f"  resposta: {len(resposta_final)} caracteres em {duracao:.1f}s · "
          f"{len(mercado or [])} referências de mercado")
    DESTINO.write_text(
        f"pergunta: {PERGUNTA}\nmodelo: {BACKEND}\ntempo: {duracao:.0f}s\n\n"
        + "\n".join(json.dumps(m, ensure_ascii=False) for m in (mercado or []))
        + f"\n\n{resposta_final}\n",
        encoding="utf-8",
    )
    print(f"  guardada em {DESTINO}")
    if not resposta_final.strip() or resposta_final.startswith("⚠️"):
        print("FALHA: sem resposta do modelo.")
finally:
    auth_service.revoke_session(sessao["session"]["id"])
    print("\nsessão temporária revogada.")
