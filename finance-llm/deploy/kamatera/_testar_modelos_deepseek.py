#!/usr/bin/env python3
"""Qual dos nomes de modelo da DeepSeek responde mesmo?

Corre dentro do contentor:  docker exec -i iqos-hermes-agent python3 -

A lista de `/v1/models` devolve `deepseek-flash` e `deepseek-v4-pro`, mas o
`config.yaml` do PC (que servia de referencia) diz `deepseek-chat`. Listar nao e
o mesmo que conseguir falar: um nome pode aparecer na lista e recusar pedidos, e
outro pode nao aparecer e funcionar por alias.

Um `GET /models` a 200 so prova que a chave autentica. O que decide e um
`POST /chat/completions` a serio -- que e exatamente o que o Jarvis vai fazer.
"""
from __future__ import annotations

import json
import urllib.error
import urllib.request

ENV = "/opt/data/.env"
URL = "https://api.deepseek.com/v1/chat/completions"

CANDIDATOS = ["deepseek-chat", "deepseek-flash", "deepseek-v4-pro", "deepseek-reasoner"]


def ler_chave(caminho: str, nome: str) -> str:
    with open(caminho, encoding="utf-8", errors="replace") as f:
        for linha in f:
            if linha.startswith(nome + "="):
                return linha.split("=", 1)[1].strip().strip('"').strip("'")
    return ""


chave = ler_chave(ENV, "DEEPSEEK_API_KEY")
if not chave:
    raise SystemExit("sem chave em " + ENV)

print(f"=== POST /chat/completions, com cada nome ({len(chave)} caracteres de chave) ===")
for modelo in CANDIDATOS:
    corpo = json.dumps({
        "model": modelo,
        "messages": [{"role": "user", "content": "diz apenas: ok"}],
        "max_tokens": 10,
        "stream": False,
    }).encode()
    pedido = urllib.request.Request(
        URL, data=corpo, method="POST",
        headers={"Authorization": f"Bearer {chave}", "Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(pedido, timeout=45) as r:
            dados = json.loads(r.read() or b"{}")
            resposta = (dados.get("choices") or [{}])[0].get("message", {}).get("content", "")
            usado = dados.get("model")
            print(f"  {modelo:22s} HTTP {r.status}  ->  {resposta.strip()[:40]!r}  (modelo: {usado})")
    except urllib.error.HTTPError as e:
        detalhe = e.read()[:160]
        try:
            detalhe = json.loads(detalhe).get("error", {}).get("message", detalhe)
        except Exception:  # noqa: BLE001
            pass
        print(f"  {modelo:22s} HTTP {e.code}  ->  {detalhe}")
    except Exception as e:  # noqa: BLE001
        print(f"  {modelo:22s} falhou: {type(e).__name__}: {e}")
