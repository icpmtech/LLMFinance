#!/usr/bin/env python3
"""Confirma que o Hermes da VM fala mesmo com o DeepSeek.

Corre dentro do contentor:  docker exec -i iqos-hermes-agent python3 -

A primeira versao desta verificacao usou `$DEEPSEEK_API_KEY` do ambiente do shell.
Estava errada: a chave vive no `/opt/data/.env`, que o **Hermes** le por si;
nao e uma variavel de ambiente do contentor. O `sh` expandia-a para vazio, o
cabecalho saia `Bearer ` e o DeepSeek respondia 401 -- um falso negativo que
parecia "chave invalida".

Aqui a chave e lida do ficheiro, como o Hermes a le.
"""
from __future__ import annotations

import json
import os
import ssl
import urllib.error
import urllib.request

ENV = "/opt/data/.env"


def ler_chave(caminho: str, nome: str) -> str:
    with open(caminho, encoding="utf-8", errors="replace") as f:
        for linha in f:
            if linha.startswith(nome + "="):
                return linha.split("=", 1)[1].strip().strip('"').strip("'")
    return ""


chave = ler_chave(ENV, "DEEPSEEK_API_KEY")
print(f"chave em {ENV}: {'sim' if chave else 'NAO'}"
      + (f" ({len(chave)} caracteres, comeca em {chave[:6]}...)" if chave else ""))

if not chave:
    raise SystemExit("  sem chave: o Hermes nao se consegue ligar a nada.")

print()
print("=== api.deepseek.com/v1/models ===")
# `-m 25`: o DeepSeek pode ser lento a primeira resposta. O contexto TLS vem do
# sistema; se falhar, e problema de rede do contentor, e vale a pena distinguir.
ctx = ssl.create_default_context()
pedido = urllib.request.Request(
    "https://api.deepseek.com/v1/models",
    headers={"Authorization": f"Bearer {chave}"},
)
try:
    with urllib.request.urlopen(pedido, timeout=25, context=ctx) as r:
        corpo = json.loads(r.read() or b"{}")
        modelos = [m.get("id") for m in corpo.get("data", [])]
        print(f"  HTTP {r.status} -- a chave serve")
        print(f"  modelos disponiveis: {modelos}")
        alvo = "deepseek-chat"
        if alvo in modelos:
            print(f"  '{alvo}' esta na lista: e contra este que o agente vai falar")
        else:
            print(f"  AVISO: '{alvo}' nao aparece na lista do provider")
except urllib.error.HTTPError as e:
    print(f"  HTTP {e.code} -- a chave foi recusada")
    print(f"  corpo: {e.read()[:300]!r}")
except Exception as e:  # noqa: BLE001
    print(f"  falhou antes de chegar ao provider: {type(e).__name__}: {e}")

print()
print("=== o que o Hermes diz da sua propria configuracao ===")
for nome in ("model.provider", "model.default", "model.base_url"):
    caminho_estado = "/opt/data/state.db"
    print(f"  {nome} (do config.yaml, via hermes config get):", end=" ")
    os.system(f"hermes config get {nome} 2>/dev/null | tr -d '\\n'")
    print()

print()
print("=== ultimas linhas sobre provider/auth ===")
os.system("tail -c 200000 /opt/data/logs/gateways/default/current 2>/dev/null "
          "| grep -i -E 'provider|auth|deepseek|api key' | tail -12")
