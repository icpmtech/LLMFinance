"""Sonda a API do Hermes Agent à procura de «thinking» (raciocínio/traço de ferramentas).

Corre contra o container do agente (host:8642). Não faz parte do produto: serve
para decidir *como* mostrar o raciocínio do agente no chat — sem isto estaríamos
a inventar um formato em vez de ler o que a API devolve.

    python _probe_agent_thinking.py
"""
from __future__ import annotations

import json
import sys

sys.path.insert(0, ".")

import httpx  # noqa: E402

from api import jarvis_agent  # noqa: E402

TAREFA = "Diz apenas: teste de sonda. Não uses ferramentas."


def _resumo(objeto: object, nivel: int = 0) -> None:
    """Imprime as chaves de um objeto JSON e o tipo/amostra de cada valor."""
    if nivel > 1 or not isinstance(objeto, dict):
        return
    for chave, valor in objeto.items():
        if isinstance(valor, (dict, list)):
            print(f"{'  ' * nivel}{chave}: {type(valor).__name__}({len(valor)})")
            if isinstance(valor, dict):
                _resumo(valor, nivel + 1)
            elif valor and isinstance(valor[0], dict):
                _resumo(valor[0], nivel + 1)
        else:
            texto = str(valor).replace("\n", " ")[:120]
            print(f"{'  ' * nivel}{chave}: {type(valor).__name__} = {texto}")


def sem_stream() -> None:
    print("=== POST /v1/chat/completions (stream=False) ===")
    url = f"{jarvis_agent.base_url()}/v1/chat/completions"
    corpo = {
        "model": jarvis_agent.MODEL,
        "messages": [{"role": "user", "content": TAREFA}],
        "stream": False,
    }
    try:
        resposta = httpx.post(url, json=corpo, headers=jarvis_agent._headers(), timeout=180.0)
    except Exception as erro:  # noqa: BLE001
        print(f"  falhou: {erro}")
        return
    print(f"  HTTP {resposta.status_code}")
    if resposta.status_code != 200:
        print("  " + resposta.text[:300])
        return
    dados = resposta.json()
    _resumo(dados)


def com_stream() -> None:
    print("=== POST /v1/chat/completions (stream=True) — tipos de evento ===")
    url = f"{jarvis_agent.base_url()}/v1/chat/completions"
    corpo = {
        "model": jarvis_agent.MODEL,
        "messages": [{"role": "user", "content": TAREFA}],
        "stream": True,
    }
    tipos: dict[str, int] = {}
    amostra: dict[str, str] = {}
    linhas = 0
    try:
        with httpx.stream("POST", url, json=corpo, headers=jarvis_agent._headers(), timeout=180.0) as fluxo:
            print(f"  HTTP {fluxo.status_code}")
            for linha in fluxo.iter_lines():
                if not linha:
                    continue
                linhas += 1
                if linha.startswith("data: "):
                    corpo_linha = linha[6:]
                    if corpo_linha.strip() == "[DONE]":
                        tipos["[DONE]"] = tipos.get("[DONE]", 0) + 1
                        continue
                    try:
                        evento = json.loads(corpo_linha)
                    except json.JSONDecodeError:
                        tipos["ilegivel"] = tipos.get("ilegivel", 0) + 1
                        continue
                        # chaves observadas no evento
                    for escolha in evento.get("choices") or []:
                        delta = escolha.get("delta") or {}
                        for chave, valor in delta.items():
                            rotulo = f"delta.{chave}"
                            tipos[rotulo] = tipos.get(rotulo, 0) + 1
                            amostra.setdefault(rotulo, json.dumps(valor, ensure_ascii=False)[:160])
                    for chave in evento:
                        if chave != "choices":
                            tipos[f"topo.{chave}"] = tipos.get(f"topo.{chave}", 0) + 1
                            amostra.setdefault(f"topo.{chave}", json.dumps(evento[chave], ensure_ascii=False)[:160])
                else:
                    tipos["linha_nao_data"] = tipos.get("linha_nao_data", 0) + 1
                    amostra.setdefault("linha_nao_data", linha[:160])
                if linhas > 4000:
                    print("  (corte às 4000 linhas)")
                    break
    except Exception as erro:  # noqa: BLE001
        print(f"  falhou: {erro}")
        return
    for rotulo, contagem in sorted(tipos.items(), key=lambda par: -par[1]):
        print(f"  {contagem:>5}  {rotulo}   {amostra.get(rotulo, '')}")


if __name__ == "__main__":
    print(f"agente em {jarvis_agent.base_url()}")
    sem_stream()
    com_stream()
