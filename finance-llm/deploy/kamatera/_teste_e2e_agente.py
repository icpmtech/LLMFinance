#!/usr/bin/env python3
"""Teste ponta a ponta: o agente Hermes da VM responde a um pedido de chat?

Corre na VM:  ssh ... "python3 -" < _teste_e2e_agente.py

Fala com a API OpenAI-compativel do gateway (`127.0.0.1:8642/v1/chat/completions`),
que e exactamente o que o `JARVIS_AGENT_URL` do backend usa. E o unico teste que
prova a cadeia toda: API do agente -> config.yaml -> provider da solucao
(DeepSeek) -> resposta.

Passa pelo anfitriao porque o contentor do Hermes publica a porta em
`127.0.0.1:8642`; e o mesmo caminho que o backend usa por dentro da rede.
"""
from __future__ import annotations

import json
import urllib.error
import urllib.request

URL = "http://127.0.0.1:8642/v1/chat/completions"

# A chave da API do agente. E a de omissao do compose -- esta escrita la e ja foi
# assinalada como problema a resolver; aqui so serve para este teste.
CHAVE = "iqos-hermes-api-key-please-change"

corpo = json.dumps({
    "model": "hermes",
    "messages": [{"role": "user", "content": "Responde apenas com a palavra: operacional"}],
    "stream": False,
}).encode()

pedido = urllib.request.Request(
    URL, data=corpo, method="POST",
    headers={"Authorization": f"Bearer {CHAVE}", "Content-Type": "application/json"},
)

print("=== POST /v1/chat/completions no agente (8642) ===")
print("  (um turno de agente pode levar 30-90 s: ele pensa, pode chamar ferramentas)")
try:
    # `timeout` generoso de proposito: o agente nao e um endpoint de eco.
    with urllib.request.urlopen(pedido, timeout=180) as r:
        dados = json.loads(r.read() or b"{}")
        escolha = (dados.get("choices") or [{}])[0]
        texto = (escolha.get("message") or {}).get("content") or ""
        print(f"  HTTP {r.status}")
        print(f"  modelo devolvido: {dados.get('model')}")
        print(f"  finish_reason   : {escolha.get('finish_reason')}")
        print(f"  resposta        : {texto.strip()[:300]!r}")
        if texto.strip():
            print("\n  O agente respondeu: a cadeia esta completa.")
        else:
            print("\n  Respondeu vazio. Ver o log do contentor para o erro do provider.")
except urllib.error.HTTPError as e:
    corpo_erro = e.read()[:400]
    print(f"  HTTP {e.code}")
    print(f"  corpo: {corpo_erro!r}")
except Exception as e:  # noqa: BLE001
    print(f"  falhou: {type(e).__name__}: {e}")
