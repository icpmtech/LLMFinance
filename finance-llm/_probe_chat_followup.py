"""Valida o **seguimento** (2 turnos com contexto) e o **raciocínio** do Hermes Agent.

Duas perguntas:
1. o segundo turno só faz sentido com o primeiro no histórico («soma 5 a esse número»);
2. o «thinking» do agente chega ao chat no campo `thinking`.

Corre contra o container do agente (host:8642), pelo mesmo caminho que o `/chat`:
`chat_gateways.ask()` -> `jarvis_gateway.invoke("agent.ask")` -> agente.

    python _probe_chat_followup.py
"""
from __future__ import annotations

import asyncio
import re
import sys
import time

sys.path.insert(0, ".")

from api import chat_gateways as gateways  # noqa: E402
from api.models import ChatMessage  # noqa: E402

T1 = "Pensa num número inteiro entre 10 e 20 à tua escolha e responde apenas com esse número."
T2 = "Soma 5 ao número que pensaste e responde apenas com o resultado."


def _numero(texto: str) -> int | None:
    achados = re.findall(r"\d+", texto)
    return int(achados[0]) if achados else None


async def main() -> int:
    conversa = [ChatMessage(role="user", content=T1)]
    inicio = time.time()
    primeiro = await gateways.ask(conversa, "hermes-agent")
    resposta1 = str(primeiro["message"].content or "")
    print(f"turno 1 ({time.time() - inicio:.1f}s): {resposta1[:120]!r}")
    raciocinio1 = primeiro.get("thinking") or ""
    print(f"  thinking: {len(raciocinio1)} caracteres | {raciocinio1[:160]!r}")

    numero = _numero(resposta1)
    conversa.append(ChatMessage(role="assistant", content=resposta1))
    conversa.append(ChatMessage(role="user", content=T2))

    inicio = time.time()
    segundo = await gateways.ask(conversa, "hermes-agent")
    resposta2 = str(segundo["message"].content or "")
    print(f"turno 2 ({time.time() - inicio:.1f}s): {resposta2[:120]!r}")
    raciocinio2 = segundo.get("thinking") or ""
    print(f"  thinking: {len(raciocinio2)} caracteres | {raciocinio2[:160]!r}")

    falhas = 0
    if numero is None:
        print("X  o turno 1 nao devolveu numero: nao da para validar o seguimento")
        falhas += 1
    else:
        esperado = numero + 5
        obtido = _numero(resposta2)
        if obtido == esperado:
            print(f"OK  seguimento: pensou {numero}, o turno 2 devolveu {obtido} (= {numero} + 5)")
        else:
            print(f"X   seguimento: pensou {numero}, esperava {esperado}, veio {obtido!r}")
            falhas += 1

    if raciocinio1 or raciocinio2:
        print("OK  raciocinio capturado do agente")
    else:
        print("X   sem raciocinio nos dois turnos (o modelo pode nao ter raciocinado)")
        falhas += 1

    return 1 if falhas else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
