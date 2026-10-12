"""Cria (ou revoga) uma sessão de QA para validar o `/chat` no browser.

Uso:
    python _qa_sessao_chat.py criar    -> imprime o token
    python _qa_sessao_chat.py revogar <token>

Script descartável: só existe para a validação da página do chat. Revogar no fim.

Nota: `auth_service.revoke_session()` quer o **id** da sessão (o documento no
índice), não o token — o token é um JWT em que o `sid` vai no corpo. É esse que
se extrai aqui.
"""
from __future__ import annotations

import base64
import json
import sys

sys.path.insert(0, ".")

from api import auth_service  # noqa: E402


def _sid_do_token(token: str) -> str:
    """Id da sessão a partir do JWT (segundo segmento, base64url sem padding)."""
    partes = token.split(".")
    if len(partes) < 2:
        raise SystemExit("token inválido")
    corpo = partes[1] + "=" * (-len(partes[1]) % 4)
    # O `json.loads` aceita `bytes`, mas aí tenta detetar a codificação e falha
    # com o JWT real («can't decode byte 0xb8 in position 0»): decodificar primeiro.
    dados = json.loads(base64.urlsafe_b64decode(corpo.encode("ascii")).decode("utf-8"))
    sid = dados.get("sid")
    if not sid:
        raise SystemExit("o token não traz `sid`")
    return str(sid)


def main() -> int:
    acao = (sys.argv[1] if len(sys.argv) > 1 else "criar").lower()

    if acao == "revogar":
        if len(sys.argv) < 3:
            print("falta o token")
            return 2
        sid = _sid_do_token(sys.argv[2])
        revogada = auth_service.revoke_session(sid)
        print(f"sessao {sid[:12]}… revogada: {revogada}")
        return 0 if revogada else 1

    utilizadores = auth_service.list_users(limit=200)
    admin = next((u for u in utilizadores if (u.get("role") or "") == "admin"), None)
    if not admin:
        print("sem conta de administrador neste ambiente")
        return 1
    sessao = auth_service.create_session(admin, user_agent="qa-chat-gateway", ip="127.0.0.1")
    print(sessao.get("token") or "")
    return 0


if __name__ == "__main__":
    sys.exit(main())
