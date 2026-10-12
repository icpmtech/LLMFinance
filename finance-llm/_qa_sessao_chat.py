"""Cria (ou revoga) uma sessão de QA para validar o `/chat` no browser.

Uso:
    python _qa_sessao_chat.py criar    -> imprime o token
    python _qa_sessao_chat.py revogar <token>

Script descartável: só existe para a validação da página do chat. Revogar no fim.
"""
from __future__ import annotations

import sys

sys.path.insert(0, ".")

from api import auth_service  # noqa: E402


def main() -> int:
    acao = (sys.argv[1] if len(sys.argv) > 1 else "criar").lower()

    if acao == "revogar":
        if len(sys.argv) < 3:
            print("falta o token")
            return 2
        removidas = auth_service.revoke_session(sys.argv[2])
        print(f"sessao revogada: {removidas}")
        return 0

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
