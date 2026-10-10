"""Sessão temporária para validar as páginas do Benchmark no browser.

Uso:
    python _tmp_bench_session.py list                 # lista utilizadores
    python _tmp_bench_session.py new <email>          # cria sessão e imprime o token
Apagar no fim da validação.
"""
from __future__ import annotations

import json
import sys

from api import auth_service as auth


def main() -> None:
    if len(sys.argv) < 2:
        print(__doc__)
        return
    if sys.argv[1] == "list":
        for user in auth.list_users(limit=50):
            print(user.get("id"), "|", user.get("email"), "|", user.get("name"), "|", user.get("role"))
        return
    if sys.argv[1] == "new":
        user = auth.get_user_by_email(sys.argv[2])
        if not user:
            print("sem utilizador", sys.argv[2])
            return
        sessao = auth.create_session(user, user_agent="validacao-benchmark")
        print(json.dumps({"token": sessao["token"], "user": user.get("email")}, ensure_ascii=False))
        return
    print("comando desconhecido")


if __name__ == "__main__":
    main()
