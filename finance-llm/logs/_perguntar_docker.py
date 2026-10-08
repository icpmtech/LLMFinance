"""Pergunta ao backend no Docker e guarda a resposta em UTF-8 (para leitura).

Usagem: python logs/_perguntar_docker.py [base] [ambito]
"""
import json
import sys
import time
from pathlib import Path

import httpx

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

BASE = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8002"
AMBITOS = (sys.argv[2].split(",") if len(sys.argv) > 2 else ["contracts"])
PERGUNTA = "Compara o valor destes contratos com contratos semelhantes no mercado."
DESTINO = Path(r"C:\LLMFinance\finance-llm\logs\_resposta_comparar.txt")

texto: list[str] = []
mercado = None
t0 = time.perf_counter()
with httpx.Client(timeout=600.0) as cliente:
    with cliente.stream(
        "POST",
        f"{BASE}/deep-search/ask",
        json={
            "question": PERGUNTA,
            "sources": AMBITOS,
            "mode": "hybrid",
            "per_source": 8,
            "max_sources": 12,
        },
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
                    print(f"sources: {len(carga.get('sources') or [])} fontes em {carga.get('took_ms')} ms")
                    com_valor = [s for s in carga.get("sources") or [] if (s.get("meta") or {}).get("preco")]
                    print(f"  com valor: {len(com_valor)}")
                    for s in com_valor[:3]:
                        print(f"  [{s['n']}] {json.dumps(s.get('meta') or {}, ensure_ascii=False)}")
                elif evento == "error":
                    print(f"ERROR: {carga}")
                elif evento == "done":
                    mercado = carga.get("mercado") or []
                    texto.append(carga.get("answer") or "")
                evento = None

resposta_final = "".join(texto)
DESTINO.write_text(
    f"pergunta: {PERGUNTA}\nambitos: {AMBITOS}\ntempo: {time.perf_counter() - t0:.0f}s\n\n"
    f"--- referencia de mercado ({len(mercado or [])}) ---\n"
    + "\n".join(json.dumps(r, ensure_ascii=False) for r in (mercado or []))
    + f"\n\n--- resposta ({len(resposta_final)} caracteres) ---\n{resposta_final}\n",
    encoding="utf-8",
)
print(f"guardado em {DESTINO} · {time.perf_counter() - t0:.0f}s · {len(resposta_final)} caracteres")
