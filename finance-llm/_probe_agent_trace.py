"""Sonda 2: rotas do agente + o que aparece quando ele usa uma ferramenta.

Complementa `_probe_agent_thinking.py`: a primeira sonda mostrou que uma tarefa
trivial devolve só `content`. Aqui vê-se (a) o que o agente expõe em `/openapi.json`
e (b) o que sai no *stream* quando o agente tem de correr uma ferramenta — para
saber se existe um traço de raciocínio para mostrar no chat.

    python _probe_agent_trace.py
"""
from __future__ import annotations

import json
import sys

sys.path.insert(0, ".")

import httpx  # noqa: E402

from api import jarvis_agent  # noqa: E402

TAREFA = "Que ferramentas tens disponíveis? Responde numa lista curta."


def rotas() -> None:
    print("=== GET /openapi.json (rotas do agente) ===")
    for caminho in ("/openapi.json", "/docs/openapi.json"):
        try:
            resposta = httpx.get(f"{jarvis_agent.base_url()}{caminho}", timeout=20.0)
        except Exception as erro:  # noqa: BLE001
            print(f"  {caminho}: falhou ({erro})")
            continue
        print(f"  {caminho}: HTTP {resposta.status_code}")
        if resposta.status_code != 200:
            continue
        try:
            dados = resposta.json()
        except Exception:  # noqa: BLE001
            print("  (nao e JSON)")
            continue
        for rota, metodos in (dados.get("paths") or {}).items():
            print(f"    {rota}  ->  {','.join(sorted(metodos))}")
        return


def com_ferramentas() -> None:
    print("=== stream=True com tarefa que pode usar ferramentas ===")
    url = f"{jarvis_agent.base_url()}/v1/chat/completions"
    corpo = {"model": jarvis_agent.MODEL, "messages": [{"role": "user", "content": TAREFA}], "stream": True}
    tipos: dict[str, int] = {}
    amostras: dict[str, str] = {}
    try:
        with httpx.stream("POST", url, json=corpo, headers=jarvis_agent._headers(), timeout=300.0) as fluxo:
            print(f"  HTTP {fluxo.status_code}")
            for linha in fluxo.iter_lines():
                if not linha or not linha.startswith("data: "):
                    continue
                corpo_linha = linha[6:].strip()
                if corpo_linha == "[DONE]":
                    continue
                try:
                    evento = json.loads(corpo_linha)
                except json.JSONDecodeError:
                    continue
                for escolha in evento.get("choices") or []:
                    delta = escolha.get("delta") or {}
                    for chave, valor in delta.items():
                        etiqueta = f"delta.{chave}"
                        tipos[etiqueta] = tipos.get(etiqueta, 0) + 1
                        amostras.setdefault(etiqueta, json.dumps(valor, ensure_ascii=False)[:200])
    except Exception as erro:  # noqa: BLE001
        print(f"  falhou: {erro}")
        return
    for etiqueta, contagem in sorted(tipos.items(), key=lambda par: -par[1]):
        print(f"  {contagem:>5}  {etiqueta}")
        print(f"         amostra: {amostras.get(etiqueta, '')}")


if __name__ == "__main__":
    rotas()
    com_ferramentas()
