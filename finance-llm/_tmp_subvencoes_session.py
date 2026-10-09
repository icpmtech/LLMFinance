"""TEMPORÁRIO — cria uma sessão para validação manual e imprime o token.

Usa-se só durante a validação da página de subvenções no browser. No fim deve ser
apagado e a sessão revogada (o script imprime também o `session_id`).
"""
from __future__ import annotations

import json
import sys

sys.path.insert(0, "c:/LLMFinance/finance-llm")

from api import auth_service  # noqa: E402


def main() -> int:
    users = auth_service.list_users(limit=200)
    admin = next((u for u in users if (u.get("role") or "") == "admin"), None)
    if not admin:
        print("sem conta admin neste ambiente")
        return 1
    criada = auth_service.create_session(admin, user_agent="validacao-subvencoes", ip="127.0.0.1")
    print(json.dumps({
        "email": admin.get("email"),
        "role": admin.get("role"),
        "session_id": criada.get("session_id") or criada.get("id"),
        "token": criada.get("token"),
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
