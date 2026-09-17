"""Promove (ou despromove) uma conta a administrador.

Necessário para o primeiro acesso à área de administração: a primeira conta
criada no sistema fica automaticamente `admin`, mas se essa conta se perder é
preciso um caminho de recurso — este utilitário fala diretamente com o
Elasticsearch (não depende da API estar a correr).

Uso:

    python scripts/promote_admin.py --list
    python scripts/promote_admin.py --email alguem@exemplo.pt
    python scripts/promote_admin.py --email alguem@exemplo.pt --demote
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from api import auth_service as auth  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="Gerir o papel de administrador de uma conta.")
    parser.add_argument("--email", help="Email da conta a alterar")
    parser.add_argument("--demote", action="store_true", help="Voltar a `member` em vez de promover")
    parser.add_argument("--list", action="store_true", help="Listar contas e papéis")
    args = parser.parse_args()

    if args.list or not args.email:
        users = auth.list_users(limit=1000)
        if not users:
            print("Sem contas (Elasticsearch indisponível?).")
            return 1
        for user in users:
            print(f"{user.get('role', 'member'):7} {user.get('status', 'active'):9} {user.get('email')}")
        return 0

    try:
        user = auth.get_user_by_email(args.email)
    except auth.AuthError as error:
        print(f"Erro: {error.message}")
        return 2

    if not user:
        print(f"Conta não encontrada: {args.email}")
        return 3

    role = "member" if args.demote else "admin"
    try:
        updated = auth.update_user(str(user["id"]), {"role": role}, admin_fields=True)
    except auth.AuthError as error:
        print(f"Erro: {error.message}")
        return 4

    print(f"{updated.get('email')} → {updated.get('role')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
