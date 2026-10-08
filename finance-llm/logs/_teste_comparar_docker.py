"""Valida a correção «comparar valores de contratos» contra o backend no Docker.

Chama `/deep-search/search` (as fontes trazem `meta`?) e `/deep-search/ask`
(a resposta inclui a secção «Referência de mercado»?).
"""
import json
import sys
import time
from urllib.parse import quote

import httpx

BASE = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8002"
PERGUNTA = "Compara o valor destes contratos com contratos semelhantes no mercado."

print(f"base: {BASE}")

t0 = time.perf_counter()
with httpx.Client(timeout=180.0) as cliente:
    r = cliente.get(
        f"{BASE}/deep-search/search",
        params={"q": PERGUNTA, "mode": "hybrid", "per_source": 6, "max_sources": 12},
    )
    r.raise_for_status()
    dados = r.json()
print(f"search: {r.status_code} em {time.perf_counter() - t0:.1f}s · modo={dados.get('mode')} · fontes={len(dados.get('sources') or [])}")

com_valor = [s for s in dados.get("sources") or [] if (s.get("meta") or {}).get("preco")]
print(f"fontes com valor (meta.preco): {len(com_valor)}")
for s in (dados.get("sources") or [])[:5]:
    print(f"  [{s['n']}] {str(s['title'])[:50]} -> meta={json.dumps(s.get('meta') or {}, ensure_ascii=False)}")

if not com_valor:
    print("\nFALHOU: nenhuma fonte trouxe valor.")
    sys.exit(1)

# --- resposta completa (SSE) ---
print("\n--- /deep-search/ask (SSE) ---")
eventos = []
mercado = None
texto = []
t0 = time.perf_counter()
with httpx.Client(timeout=300.0) as cliente:
    with cliente.stream(
        "POST",
        f"{BASE}/deep-search/ask",
        json={"question": PERGUNTA, "mode": "hybrid", "per_source": 6, "max_sources": 12},
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
                if evento in ("sources", "meta", "done", "error"):
                    eventos.append(evento)
                if evento == "done":
                    mercado = carga.get("mercado")
                    texto.append(carga.get("answer") or "")
                elif evento == "sources":
                    print(f"  sources: {len(carga.get('sources') or [])} fontes ({carga.get('took_ms')} ms)")
                elif evento == "error":
                    print(f"  ERROR: {carga}")
                evento = None
print(f"ask: eventos={[e for e in eventos if e != 'message'][:6]} · {time.perf_counter() - t0:.1f}s")

print(f"\nmercado devolvido: {len(mercado or [])} referências")
for ref in (mercado or [])[:12]:
    print("  ", json.dumps(ref, ensure_ascii=False))

resposta = "".join(texto)
print(f"\n--- resposta ({len(resposta)} caracteres) ---")
print(resposta[:2200])

if not mercado:
    print("\nAVISO: a resposta não trouxe referência de mercado.")
    sys.exit(2)
print("\nOK: valores nas fontes e referência de mercado na resposta.")
