"""Prova: o agente usa as skills do IQ OS (pesquisa-total e websearch)?

Envia tarefas ao gateway OpenAI-compatível do Hermes Agent e mostra a resposta,
o tempo e as ferramentas que o agente decidiu usar (via /v1/toolsets para saber
o que está ligado e pelo conteúdo da resposta para saber o que fez).

    python _probe_agent_skills.py [tarefa]
"""

from __future__ import annotations

import json
import os
import sys
import time

import httpx

URL = os.getenv("HERMES_AGENT_URL", "http://127.0.0.1:8642")
KEY = os.getenv("HERMES_API_KEY", "iqos-hermes-api-key-please-change")

TASKS = {
    "pesquisa": (
        "Usa a pesquisa total do IQ OS para me dizeres quantos resultados existem "
        "sobre «EDP» em cada âmbito. Dá as contagens por âmbito e cita o âmbito "
        "onde há mais. Responde em português de Portugal, curto."
    ),
    "web": (
        "Procura na web notícias recentes sobre contratos públicos em Portugal e "
        "dá-me 3 notícias com o título, o URL e a data. Responde em português de "
        "Portugal."
    ),
}


def main() -> int:
    which = (sys.argv[1] if len(sys.argv) > 1 else "pesquisa").lower()
    task = TASKS.get(which, " ".join(sys.argv[1:]))

    with httpx.Client(timeout=600.0) as client:
        try:
            toolsets = client.get(
                f"{URL}/v1/toolsets", headers={"Authorization": f"Bearer {KEY}"}
            )
            print("toolsets:", toolsets.status_code, len(toolsets.text))
        except Exception as exc:  # pragma: no cover - diagnóstico
            print("toolsets falhou:", exc)

        t0 = time.time()
        resp = client.post(
            f"{URL}/v1/chat/completions",
            headers={"Authorization": f"Bearer {KEY}", "Content-Type": "application/json"},
            json={
                "model": "hermes-agent",
                "messages": [{"role": "user", "content": task}],
                "stream": False,
            },
        )
        elapsed = time.time() - t0
        print(f"\nPOST /v1/chat/completions -> {resp.status_code} em {elapsed:.1f}s")
        if resp.status_code != 200:
            print(resp.text[:800])
            return 1
        data = resp.json()
        choice = (data.get("choices") or [{}])[0]
        message = choice.get("message") or {}
        content = message.get("content") or ""
        print("\n--- resposta ---")
        print(content)
        calls = message.get("tool_calls") or []
        if calls:
            print("\n--- tool_calls ---")
            for call in calls:
                fn = (call.get("function") or {})
                print(f"- {fn.get('name')}: {str(fn.get('arguments'))[:200]}")
        if data.get("usage"):
            print("\nusage:", json.dumps(data["usage"], ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
