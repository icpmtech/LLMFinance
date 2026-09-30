"""Confirma que a diretiva de idioma está ativa e que o LLM responde em português.

Corre-se dentro do contentor, com o venv do backend:
    docker cp _probe_pt_language.py finance-llm-mirofish:/tmp/probe.py
    docker exec -w /app/backend finance-llm-mirofish .venv/bin/python /tmp/probe.py
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, "/app/backend")

from app.utils.llm_client import LLMClient, _iq_os_apply_reply_language  # noqa: E402

print("MIROFISH_REPLY_LANGUAGE =", os.getenv("MIROFISH_REPLY_LANGUAGE"))

mensagens = [
    {"role": "system", "content": "你是一个社会学研究员，负责生成社交媒体人物的设定。"},
    {"role": "user", "content": "请为一家破产的纺织公司写一段简短的社交媒体简介。"},
]
aplicado = _iq_os_apply_reply_language(list(mensagens))
print("primeira mensagem depois da diretiva:")
print(aplicado[0]["content"][:220])
print("---")
print("mensagem de sistema original preservada:", "你是一个社会学研究员" in aplicado[0]["content"])
print("---")

cliente = LLMClient()
resposta = cliente.chat(aplicado, temperature=0.4, max_tokens=200)
print("resposta do modelo:")
print(resposta)
