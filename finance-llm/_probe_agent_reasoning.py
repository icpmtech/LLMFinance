"""Confirma que o raciocínio vem no modo **não-stream**.

A documentação do agente diz que `choices[0].message.reasoning_content` traz o
raciocínio do turno também em `stream: false` (e `delta.reasoning_content` no
stream). Se for verdade, o `jarvis_agent.ask()` pode recolher o «thinking» sem
passar a fazer *streaming* — muito menos código e menos risco.

    python _probe_agent_reasoning.py
"""
from __future__ import annotations

import json
import sys

sys.path.insert(0, ".")

import httpx  # noqa: E402

from api import jarvis_agent  # noqa: E402

TAREFA = "Que ferramentas tens disponíveis? Responde numa lista curta."


def main() -> int:
    url = f"{jarvis_agent.base_url()}/v1/chat/completions"
    corpo = {"model": jarvis_agent.MODEL, "messages": [{"role": "user", "content": TAREFA}], "stream": False}
    resposta = httpx.post(url, json=corpo, headers=jarvis_agent._headers(), timeout=300.0)
    print(f"HTTP {resposta.status_code}")
    if resposta.status_code != 200:
        print(resposta.text[:300])
        return 1
    dados = resposta.json()
    mensagem = (dados.get("choices") or [{}])[0].get("message") or {}
    print(f"chaves de choices[0].message: {sorted(mensagem)}")
    for chave, valor in mensagem.items():
        texto = valor if isinstance(valor, str) else json.dumps(valor, ensure_ascii=False)
        print(f"  {chave}: {type(valor).__name__} ({len(texto)} chars)")
        print(f"    {texto[:300]!r}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
