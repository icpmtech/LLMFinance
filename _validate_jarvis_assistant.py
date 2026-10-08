"""Valida o Jarvis como **assistente**, no caminho real da interface.

1. `/jarvis/voice` — STT local (faster-whisper), TTS pt-PT (edge-tts) e palavra de ativação.
2. `/jarvis/ask` com delegação ao Hermes Agent — a resposta tem de trazer dados reais.
3. **Diálogo com contexto**: a segunda pergunta só faz sentido com o histórico da
   primeira («e quantos desses são de Espanha?») — prova que o histórico chega ao
   agente (persona + turnos anteriores) e não só ao planeador do Jarvis.

    python _validate_jarvis_assistant.py
"""

from __future__ import annotations

import json
import os
import sys
import time

import httpx

#: A consola do Windows (cp1252) não escreve caracteres como «→» ou «·» — sem isto o
#: script rebenta a imprimir a resposta que veio de UTF-8.
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:  # pragma: no cover - consolas antigas
    pass

BASE = "http://127.0.0.1:8002"
#: Conta de teste do IQ OS: sem sessão o Jarvis não tem fornecedor de IA e responde
#: em «modo factual». Com sessão usa o modelo configurado para a conta.
ACCOUNT = {"email": "teste@teste.com", "password": "teste123"}


def login_token(client: httpx.Client) -> str:
    token = os.getenv("JARVIS_VALIDATE_TOKEN")
    if token:
        print("sessão recebida por JARVIS_VALIDATE_TOKEN:", token[:12], "…")
        return token
    try:
        resp = client.post(f"{BASE}/auth/login", json=ACCOUNT)
        if resp.status_code == 200:
            token = resp.json().get("token") or ""
            print("sessão iniciada:", ACCOUNT["email"], "token", token[:12], "…")
            return token
        print("login falhou:", resp.status_code, resp.text[:200])
    except Exception as exc:
        print("login falhou:", exc)
    return ""

TURNO_1 = (
    "Delega no Hermes Agent: quantos resultados existem na pesquisa total do IQ OS "
    "sobre a empresa «Mota-Engil», por âmbito? Responde curto, com os números."
)
TURNO_2 = "E desses, quantos são contratos de Espanha? Usa o agente se for preciso."


def ask(client: httpx.Client, question: str, history: list[dict], headers: dict) -> dict:
    payload = {"question": question, "depth": "rapida", "history": history, "speak": False}
    t0 = time.time()
    resp = client.post(f"{BASE}/jarvis/ask", json=payload, headers=headers)
    elapsed = time.time() - t0
    print(f"\n>>> {question}\n    HTTP {resp.status_code} em {elapsed:.1f}s")
    if resp.status_code != 200:
        print("    ERRO:", resp.text[:600])
        return {}
    data = resp.json()
    print("--- resposta ---")
    print((data.get("answer") or "").strip()[:1400])
    usados = [f"{t.get('tool')}" for t in (data.get("tools_used") or [])]
    print("--- ferramentas usadas:", ", ".join(usados) or "(nenhuma)")
    fontes = data.get("sources") or []
    for fonte in fontes[:6]:
        print(f"    fonte: {fonte.get('label')} [{fonte.get('origin')}]")
    return data


def main() -> int:
    falhas: list[str] = []

    with httpx.Client(timeout=900.0) as client:
        token = login_token(client)
        headers = {"Authorization": f"Bearer {token}"} if token else {}

        voz = client.get(f"{BASE}/jarvis/voice")
        print("GET /jarvis/voice ->", voz.status_code)
        if voz.status_code == 200:
            v = voz.json()
            stt, tts, wake = v.get("stt") or {}, v.get("tts") or {}, v.get("wake") or {}
            print("  stt :", stt.get("engine"), stt.get("model"), stt.get("available"))
            print("  tts :", tts.get("engine"), tts.get("default_voice"), len(tts.get("voices") or []), "vozes")
            print("  wake:", wake.get("model"), wake.get("words"), wake.get("available"))
            if stt.get("engine") != "faster-whisper":
                falhas.append("STT não é faster-whisper")
            if (tts.get("default_voice") or "") != "pt-PT-RaquelNeural":
                falhas.append("voz por omissão não é pt-PT-RaquelNeural")
            if not wake.get("words"):
                falhas.append("palavra de ativação sem palavras")

        meta = client.get(f"{BASE}/jarvis/meta", headers=headers).json()
        agente = meta.get("agent") or {}
        print("\nGET /jarvis/meta -> gateways:", [g.get("id") for g in meta.get("gateways") or []])
        print("  agente:", json.dumps(agente, ensure_ascii=False)[:300])
        if not agente.get("available"):
            falhas.append("agente indisponível no /jarvis/meta")

        primeiro = ask(client, TURNO_1, [], headers)
        resposta_1 = (primeiro.get("answer") or "")
        if not any(char.isdigit() for char in resposta_1):
            falhas.append("turno 1 sem números (não consultou dados)")
        if "modo factual" in resposta_1:
            print("NOTA: o Jarvis respondeu em modo factual (sem modelo na conta).")

        historico = [
            {"role": "user", "content": TURNO_1},
            {"role": "assistant", "content": resposta_1[:4000]},
        ]
        segundo = ask(client, TURNO_2, historico, headers)
        resposta_2 = (segundo.get("answer") or "")
        if not resposta_2:
            falhas.append("turno 2 sem resposta")
        elif "Espanha" not in resposta_2 and "espanh" not in resposta_2.lower():
            falhas.append("turno 2 não falou de Espanha")

    print("\n================ resultado ================")
    if falhas:
        for falha in falhas:
            print("FALHOU:", falha)
        return 1
    print("OK: assistente com voz, agente e contexto de diálogo.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
