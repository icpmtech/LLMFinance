"""Testa o modelo de contratos com pedidos frescos e reporta o que falha.

Corre contra a API em execução (`/llm/modelo/chat`) com a camada do agente
desligada, para medir o **modelo**, não o RAG. Cada caso declara o que se espera
e o que constituiria uma invenção.
"""
from __future__ import annotations

import json
import re
import sys
import time
import urllib.request

BASE = "http://127.0.0.1:8000"

CONTRATO = (
    "Contrato 900001 - Aquisição de reagentes de laboratório\n"
    "Adjudicante: Instituto Superior Técnico\n"
    "Adjudicatário: LABQUIMICA - EQUIPAMENTOS E REAGENTES, LDA\n"
    "Tipo: Aquisição de bens móveis\n"
    "Procedimento: Concurso público\n"
    "Preço contratual: 15430.75\n"
    "Descrição: Reagentes e consumíveis para o laboratório de química analítica"
)

CASOS = [
    {
        "nome": "contrato_grounding",
        "instrucao": "Descreve este contrato público português.",
        "dados": CONTRATO,
        # tudo o que aparecer no texto e não esteja no input é invenção
        "permitidos": {"900001", "15430.75", "15430,75", "15 430,75"},
    },
    {
        "nome": "auditar",
        "instrucao": "Audita este contrato e aponta os riscos de contratação pública.",
        "dados": CONTRATO,
        "permitidos": {"900001", "15430.75", "15430,75", "15 430,75"},
    },
    {
        "nome": "pergunta_cidada",
        "instrucao": "Explica a um cidadão, sem jargão, o que foi comprado e por quanto.",
        "dados": CONTRATO,
        "permitidos": {"900001", "15430.75", "15430,75", "15 430,75"},
    },
]

_NUM = re.compile(r"\d[\d\s.,]*\d|\d")


def pedir(instrucao: str, dados: str) -> dict:
    corpo = json.dumps(
        {
            "instrucao": instrucao,
            "dados": dados,
            "max_tokens": 160,
            "temperatura": 0.2,
            "usar_rag": False,
            "usar_memoria": False,
            "usar_skills": False,
            "raciocinio": False,
        }
    ).encode()
    req = urllib.request.Request(
        f"{BASE}/llm/modelo/chat",
        data=corpo,
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=900) as resp:
        return json.load(resp)


def numeros_inventados(texto: str, permitidos: set[str]) -> list[str]:
    fora = []
    for bruto in _NUM.findall(texto):
        limpo = bruto.replace(" ", "").strip(".")
        if not limpo:
            continue
        if limpo in permitidos or limpo.replace(",", ".") in permitidos:
            continue
        try:
            valor = float(limpo.replace(".", "").replace(",", ".")) if "," in limpo else float(limpo)
        except ValueError:
            continue
        # 15430.75 escrito como 15430,75 ou 15 430,75
        if abs(valor - 15430.75) < 0.01 or abs(valor - 900001) < 0.01:
            continue
        fora.append(bruto.strip())
    return fora


def main() -> int:
    falhas = 0
    for caso in CASOS:
        inicio = time.time()
        try:
            resposta = pedir(caso["instrucao"], caso["dados"])
        except Exception as exc:  # noqa: BLE001
            print(f"[{caso['nome']}] ERRO: {exc}", flush=True)
            falhas += 1
            continue
        texto = resposta.get("resposta", "")
        segundos = time.time() - inicio
        inventados = numeros_inventados(texto, caso["permitidos"])
        print(f"\n=== {caso['nome']} ({segundos:.0f}s) ===", flush=True)
        print(texto, flush=True)
        if inventados:
            print(f"! NÚMEROS INVENTADOS: {inventados}", flush=True)
            falhas += 1
    print(f"\ntotal de casos com problema: {falhas}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
