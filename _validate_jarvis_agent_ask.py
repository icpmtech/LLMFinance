"""Testa o Jarvis pela API: modo de voz + integração com o Hermes Agent.

1. `/jarvis/voice`   — motores e vozes disponíveis (tem de ser `edge-tts`).
2. `/jarvis/speak`   — MP3 em pt-PT (voz predefinida e a alternativa).
3. `/jarvis/ask`     — «quais são as tuas skills?»: o plano tem de usar `agent.skills`
                       e a resposta traz as skills do agente.
4. `/jarvis/ask`     — delegação real (`agent.ask`): o agente corre a tarefa.
"""
from __future__ import annotations

import json
import os
import sys
import time
import urllib.request

BASE = os.getenv("JARVIS_BASE", "http://127.0.0.1:8002")


def get(path: str, timeout: float = 60.0):
    with urllib.request.urlopen(f"{BASE}{path}", timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def post(path: str, payload: dict, timeout: float = 600.0):
    body = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        f"{BASE}{path}", data=body, headers={"Content-Type": "application/json"}, method="POST"
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def show_answer(title: str, result: dict, question: str = "") -> None:
    print(f"\n=== {title} ===")
    if question:
        print("pergunta:", question)
    plan = result.get("plan") or {}
    print("plano:", plan.get("tools"), "| fonte:", plan.get("source"))
    used = result.get("tools_used") or []
    print("ferramentas usadas:", [(t.get("tool"), t.get("ok")) for t in used if isinstance(t, dict)])
    print("passos:")
    for step in (result.get("steps") or [])[:12]:
        extra = f"  [{step.get('tool')}]" if step.get("tool") else ""
        print(f"   - {step.get('kind'):<9} {step.get('label')}{extra}")
    answer = " ".join(str(result.get("answer") or "").split())
    print("resposta:", answer[:600])
    print("fontes:", [(s.get("origin"), s.get("label")) for s in (result.get("sources") or [])][:6])
    if result.get("audio"):
        print("áudio: presente na resposta (base64)")


def main() -> int:
    failures: list[str] = []

    voice = get("/jarvis/voice")
    tts, stt = voice.get("tts", {}), voice.get("stt", {})
    print("TTS:", tts.get("engine"), "| predefinida:", tts.get("default_voice"),
          "| vozes:", [v["id"] for v in tts.get("voices", [])][:4])
    print("STT:", stt.get("engine") or "browser", "|", (stt.get("note") or "")[:90])
    if tts.get("engine") != "edge-tts":
        failures.append("a síntese no servidor não está ativa")

    # `/jarvis/speak` devolve o MP3 cru (não JSON).
    body = json.dumps({"text": "Bom dia. Sou o Jarvis.", "voice": "pt-PT-RaquelNeural"}).encode()
    req = urllib.request.Request(
        f"{BASE}/jarvis/speak", data=body, headers={"Content-Type": "application/json"}, method="POST"
    )
    with urllib.request.urlopen(req, timeout=120) as resp:
        data = resp.read()
    print(f"/jarvis/speak -> {len(data)} bytes, {resp.headers.get('Content-Type')}")
    if len(data) < 5000 or data[:1] != b"\xff":
        failures.append("o áudio devolvido não parece MP3")

    # Pergunta sobre as skills do agente (rápida: só lê a lista).
    question = "Quais são as skills do agente Hermes?"
    asked = post("/jarvis/ask", {"question": question}, timeout=600)
    show_answer("skills do agente", asked, question)
    plan_tools = (asked.get("plan") or {}).get("tools") or []
    if not any(tool in {"agent.skills", "agent.ask"} for tool in plan_tools):
        failures.append(f"o plano não usou o gateway do agente: {plan_tools}")

    # Delegação real no agente (lento por natureza: ciclo autónomo).
    started = time.time()
    delegado = "delega no agente: responde apenas com as palavras jarvis-agente-ligado"
    delegated = post("/jarvis/ask", {"question": delegado}, timeout=900)
    show_answer(f"delegação no agente ({time.time() - started:.0f}s)", delegated, delegado)
    used = {t.get("tool") for t in (delegated.get("tools_used") or []) if isinstance(t, dict)}
    if "agent.ask" not in used:
        failures.append(f"a delegação não correu `agent.ask`: {sorted(used)}")
    ok_agent = any(
        t.get("tool") == "agent.ask" and t.get("ok") for t in (delegated.get("tools_used") or [])
        if isinstance(t, dict)
    )
    if not ok_agent:
        failures.append("a chamada `agent.ask` não teve sucesso")

    print("\n=== resultado ===")
    for failure in failures:
        print("FALHA:", failure)
    if failures:
        return 1
    print("OK: voz no servidor (edge-tts) + gateway do Hermes Agent no Jarvis.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
