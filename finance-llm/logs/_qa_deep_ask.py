"""Testa a resposta da «Pesquisa profunda» em SSE (`POST /deep-search/ask`).

Verifica o que a página realmente consome: ordem dos eventos, fontes numeradas,
tokens a chegar em fluxo, citações `[n]` e perguntas de seguimento no evento
`done`.

Uso:
    python logs/_qa_deep_ask.py                      (8002)
    QA_BACKEND=http://127.0.0.1:8011 python logs/_qa_deep_ask.py
    python logs/_qa_deep_ask.py "outra pergunta" --backend gpt2
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time

import httpx

BACKEND = os.environ.get("QA_BACKEND", "http://127.0.0.1:8002").rstrip("/")


def evento_para_texto(nome: str, dados: str) -> str:
    """Resumo legível de cada tipo de evento do servidor."""
    try:
        carga = json.loads(dados) if dados else {}
    except Exception:  # noqa: BLE001
        return f"{nome}: {dados[:120]!r}"
    if nome == "sources":
        fontes = carga.get("sources") or []
        return (
            f"sources: {len(fontes)} fontes | modo={carga.get('mode')} | "
            f"listas texto={carga.get('text_lists')} vetor={carga.get('vector_lists')} | "
            f"saltados={carga.get('vector_skipped')} | sem-limite={carga.get('unlimited')} | "
            f"citaveis-ate={carga.get('citable_max')} | sugestoes={len(carga.get('suggestions') or [])}"
        )
    if nome == "meta":
        return f"meta: modelo={carga.get('model')} backend={carga.get('backend')}"
    if nome == "done":
        return (
            f"done: citacoes={len(carga.get('citations') or [])} | "
            f"sugestoes={len(carga.get('suggestions') or [])} | {str(carga.get('suggestions'))[:160]}"
        )
    return f"{nome}: {str(carga)[:160]}"


def main() -> int:
    parser = argparse.ArgumentParser(description="Testa /deep-search/ask (SSE).")
    parser.add_argument("pergunta", nargs="?", default="Quantos contratos tem a CLARANET II SOLUTIONS e qual o valor total?")
    parser.add_argument("--backend", default="", help="Modelo (vazio = predefinição do servidor).")
    parser.add_argument("--max-sources", type=int, default=8)
    parser.add_argument("--mode", default="hybrid")
    parser.add_argument("--timeout", type=float, default=300.0)
    args = parser.parse_args()

    pedido = {
        "question": args.pergunta,
        "backend": args.backend,
        "mode": args.mode,
        "max_sources": args.max_sources,
        "temperature": 0.2,
        "max_tokens": 600,
    }
    print(f"POST {BACKEND}/deep-search/ask")
    print(f"  pergunta: {args.pergunta!r}")
    print(f"  backend : {args.backend or '(predefinição do servidor)'} | modo={args.mode} | max_sources={args.max_sources}")
    print()

    ordem: list[str] = []
    tokens = 0
    resposta = ""
    resposta_done = ""
    t0 = time.time()
    primeiro_token = None

    try:
        with httpx.stream("POST", f"{BACKEND}/deep-search/ask", json=pedido, timeout=args.timeout) as fluxo:
            if fluxo.status_code != 200:
                print(f"FALHA: HTTP {fluxo.status_code}")
                return 1
            nome, dados = None, None
            for linha in fluxo.iter_lines():
                if linha.startswith(":"):
                    continue  # comentário de keep-alive
                if linha.startswith("event:"):
                    nome = linha[6:].strip()
                elif linha.startswith("data:"):
                    dados = linha[5:].strip()
                elif linha == "" and (nome or dados):
                    # Os tokens vêm como `data: {...}` **sem** linha `event:`
                    # (convenção do chat). Sem tratar isto, o teste dizia «0
                    # tokens» com a resposta a chegar normalmente.
                    if not nome and dados:
                        nome = "token"
                    if nome == "token":
                        tokens += 1
                        if primeiro_token is None:
                            primeiro_token = time.time() - t0
                        try:
                            resposta += json.loads(dados).get("token", "")
                        except Exception:  # noqa: BLE001
                            pass
                    else:
                        ordem.append(nome)
                        print("  " + evento_para_texto(nome, dados or ""))
                        if nome == "done":
                            try:
                                resposta_done = json.loads(dados or "{}").get("answer") or ""
                            except Exception:  # noqa: BLE001
                                resposta_done = ""
                    nome, dados = None, None
    except Exception as erro:  # noqa: BLE001
        print(f"FALHA: {type(erro).__name__}: {erro}")
        return 1

    gasto = time.time() - t0
    quando = f"{primeiro_token:.1f}s" if primeiro_token is not None else "nunca"
    print()
    print(f"ordem dos eventos : {' -> '.join(ordem + [f'{tokens} tokens'])}")
    print(f"primeiro token    : {quando} | total {gasto:.1f}s | {tokens} pedacos de token")
    print(f"resposta          : {len(resposta)} caracteres (evento done: {len(resposta_done)})")
    print()
    print("---- resposta ----")
    print((resposta or resposta_done)[:2000])

    problemas = []
    if not ordem or ordem[0] != "sources":
        problemas.append("o evento `sources` devia vir primeiro (a página precisa das fontes para numerar as citações)")
    if tokens == 0:
        problemas.append("nenhum token recebido")
    if "done" not in ordem:
        problemas.append("sem evento `done`")
    if not resposta.strip():
        problemas.append("resposta vazia")
    print()
    if problemas:
        print("PROBLEMAS:")
        for p in problemas:
            print(f"  - {p}")
        return 1
    print("tudo verificado")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
