#!/usr/bin/env python3
"""O que tem o `/opt/data/.env` do Hermes, e o que diz o `config.yaml`.

Corre **dentro** do contentor (`docker exec -i <contentor> python3 -`).

Serve para comparar o PC (onde o agente funciona) com a VM (onde diz
"not connected to any AI provider"). O `.env` e grande (27 KB) e tem centenas de
chaves: imprimir so os nomes dos providers e se teem valor evita despejar
segredos no ecra e deixa ver a diferenca de relance.
"""
from __future__ import annotations

import os
import re

ENV = "/opt/data/.env"
CONFIG = "/opt/data/config.yaml"

# Nomes que interessam: qualquer coisa que pareca credencial ou escolha de modelo.
PADRAO = re.compile(
    r"(_API_KEY|_KEY|_TOKEN|OPENROUTER|ANTHROPIC|OPENAI|DEEPSEEK|GEMINI|GOOGLE|"
    r"NOUS|GROQ|MISTRAL|XAI|TOGETHER|PERPLEXITY|MOONSHOT|QWEN|DASHSCOPE|"
    r"HERMES_MODEL|_MODEL|_PROVIDER)",
    re.I,
)


def ler_env(caminho: str) -> dict[str, str]:
    campos: dict[str, str] = {}
    try:
        with open(caminho, encoding="utf-8", errors="replace") as f:
            for linha in f:
                linha = linha.strip()
                if not linha or linha.startswith("#") or "=" not in linha:
                    continue
                chave, _, valor = linha.partition("=")
                campos[chave.strip()] = valor.strip().strip('"').strip("'")
    except OSError as exc:
        print(f"  nao consegui ler {caminho}: {exc}")
    return campos


print(f"=== {ENV} ===")
if not os.path.exists(ENV):
    print("  NAO EXISTE")
else:
    print(f"  tamanho: {os.path.getsize(ENV)} bytes")
    campos = ler_env(ENV)
    print(f"  chaves no total: {len(campos)}")

    com_valor = sorted(k for k, v in campos.items() if v and PADRAO.search(k))
    sem_valor = sorted(k for k, v in campos.items() if not v and PADRAO.search(k))

    print(f"\n  providers COM valor ({len(com_valor)}):")
    for k in com_valor:
        v = campos[k]
        # Mostra so o comprimento e os primeiros 6 caracteres. Chega para
        # distinguir "configurado" de "vazio" sem publicar a chave.
        print(f"    {k:38s} {len(v):3d} chars  {v[:6]}...")

    if sem_valor:
        print(f"\n  providers SEM valor ({len(sem_valor)}):")
        for k in sem_valor:
            print(f"    {k}")

print()
print(f"=== {CONFIG}: ambiente/modelo ===")
if not os.path.exists(CONFIG):
    print("  NAO EXISTE")
else:
    try:
        with open(CONFIG, encoding="utf-8", errors="replace") as f:
            linhas = f.read().splitlines()
    except OSError as exc:
        print(f"  nao consegui ler: {exc}")
        linhas = []

    dentro = False
    for i, linha in enumerate(linhas):
        if re.match(r"^model:\s*$", linha):
            dentro = True
        elif dentro and re.match(r"^[a-zA-Z_]", linha):
            dentro = False
        if dentro and not linha.strip().startswith("#"):
            print(f"  {linha.rstrip()}")
        # Tambem interessa onde o Hermes guarda o estado de autenticacao.
    print()
    print("  --- referencias a provider/auth no ficheiro ---")
    for i, linha in enumerate(linhas, 1):
        if re.search(r"(provider|auth|model:)", linha, re.I) and not linha.strip().startswith("#"):
            print(f"    {i}: {linha.rstrip()[:100]}")

print()
print("=== HOME e ficheiros de autenticacao ===")
print(f"  HOME={os.environ.get('HOME')}  USER={os.environ.get('USER')}")
for nome in (".env", "config.yaml", "auth.json", ".hermes", "state.db"):
    caminho = os.path.join("/opt/data", nome)
    existe = os.path.exists(caminho)
    extra = f"  {os.path.getsize(caminho)} bytes" if existe and os.path.isfile(caminho) else ""
    print(f"  {caminho:32s} {'sim' if existe else 'NAO'}{extra}")
