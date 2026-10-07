"""Testa a resposta da Pesquisa profunda com o **fornecedor configurado pelo
utilizador**, criando uma sessão temporária e revogando-a no fim.

O servidor sem sessão não consegue resolver a chave do fornecedor (cai no modelo
local `gpt2`), por isso é preciso um token. Esta sessão é criada e apagada aqui —
não se toca nas sessões existentes.

Uso:
    QA_BACKEND=http://127.0.0.1:8011 python logs/_qa_sessao_ask.py "pergunta"
"""
from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

import httpx

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))
os.environ.setdefault("PYTHONIOENCODING", "utf-8")

from api import auth_service  # noqa: E402

BACKEND = os.environ.get("QA_BACKEND", "http://127.0.0.1:8002").rstrip("/")
EMAIL = os.environ.get("QA_EMAIL", "")


def main() -> int:
    pergunta = sys.argv[1] if len(sys.argv) > 1 else "Quantos contratos tem a CLARANET II SOLUTIONS e qual o valor total adjudicado?"

    utilizadores = auth_service.list_users(limit=50)
    if EMAIL:
        utilizador = next((u for u in utilizadores if u.get("email") == EMAIL), None)
    else:
        # Prefere um administrador: tem acesso a todos os âmbitos.
        utilizador = next((u for u in utilizadores if (u.get("role") or "") == "admin"), None) or (utilizadores[0] if utilizadores else None)
    if not utilizador:
        print("FALHA: não encontrei nenhum utilizador")
        return 1
    print(f"utilizador : {utilizador.get('email')} ({utilizador.get('role')}) | backend {BACKEND}")

    sessao = auth_service.create_session(utilizador, user_agent="qa-deep-ask", ip="127.0.0.1")
    token = sessao.get("token") or sessao.get("access_token")
    session_id = sessao.get("session_id")
    print(f"sessão     : criada (id {session_id}); a revogar no fim")

    try:
        cabecalhos = {"Authorization": f"Bearer {token}"}
        meta = httpx.get(f"{BACKEND}/deep-search/meta", headers=cabecalhos, timeout=60).json()
        print(f"predefinição: backend={meta.get('defaults', {}).get('backend')!r} tem-sessao={meta.get('has_session')}")
        print()

        pedido = {"question": pergunta, "mode": "hybrid", "max_sources": 8, "temperature": 0.2, "max_tokens": 700}
        tokens = 0
        resposta = ""
        ordem: list[str] = []
        t0 = time.time()
        primeiro = None
        citacoes = 0
        seguimentos: list[str] = []

        with httpx.stream("POST", f"{BACKEND}/deep-search/ask", json=pedido, headers=cabecalhos, timeout=300) as fluxo:
            if fluxo.status_code != 200:
                print(f"FALHA: HTTP {fluxo.status_code}")
                return 1
            nome, dados = None, None
            for linha in fluxo.iter_lines():
                if linha.startswith(":"):
                    continue
                if linha.startswith("event:"):
                    nome = linha[6:].strip()
                elif linha.startswith("data:"):
                    dados = linha[5:].strip()
                elif linha == "" and (nome or dados):
                    if not nome and dados:
                        nome = "token"
                    if nome == "token":
                        tokens += 1
                        if primeiro is None:
                            primeiro = time.time() - t0
                        try:
                            resposta += json.loads(dados).get("token", "")
                        except Exception:  # noqa: BLE001
                            pass
                    else:
                        ordem.append(nome)
                        if nome == "sources":
                            carga = json.loads(dados or "{}")
                            print(f"  sources: {len(carga.get('sources') or [])} fontes | modo={carga.get('mode')} "
                                  f"| texto={carga.get('text_lists')} vetor={carga.get('vector_lists')} "
                                  f"| saltados={carga.get('vector_skipped')}")
                        elif nome == "meta":
                            print(f"  meta: {json.loads(dados or '{}').get('model')}")
                        elif nome == "done":
                            carga = json.loads(dados or "{}")
                            citacoes = len(carga.get("citations") or [])
                            seguimentos = list(carga.get("suggestions") or [])
                            print(f"  done: citacoes={citacoes} | sugestoes={len(seguimentos)}")
                    nome, dados = None, None

        gasto = time.time() - t0
        print()
        print(f"eventos      : {' -> '.join(ordem)}")
        print(f"1.º token    : {f'{primeiro:.1f}s' if primeiro else 'nunca'} | total {gasto:.1f}s | {tokens} pedaços")
        print(f"resposta     : {len(resposta)} caracteres | citações na resposta: {citacoes}")
        print(f"seguimentos  : {seguimentos[:2]}")
        print()
        print("---- resposta ----")
        print(resposta[:1800])

        problemas = []
        if not resposta.strip():
            problemas.append("resposta vazia")
        if resposta.strip().startswith("⚠️"):
            problemas.append(f"a resposta é um aviso de erro: {resposta[:120]!r}")
        if tokens < 5:
            problemas.append(f"poucos pedaços de token ({tokens})")
        print()
        if problemas:
            print("PROBLEMAS:")
            for p in problemas:
                print(f"  - {p}")
            return 1
        print("tudo verificado")
        return 0
    finally:
        if session_id:
            try:
                auth_service.revoke_session(session_id)
                print(f"\n(limpeza: sessão {session_id} revogada)")
            except Exception as erro:  # noqa: BLE001
                print(f"\n(atenção: não consegui revogar a sessão {session_id}: {erro})")


if __name__ == "__main__":
    raise SystemExit(main())
