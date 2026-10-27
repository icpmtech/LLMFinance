"""Altera o email de uma conta e os registos que a referenciam.

O `_id` do documento em `finance_users` é o email normalizado, e vários módulos
guardam o email como chave do proprietário (perfil de CRM, favoritos e pesquisas
guardadas, análises, atribuição de alterações). Mudar só o documento da conta
deixava esses registos órfãos — o utilizador continuava a ver o endereço antigo e
perdia o acesso ao que era seu.

O que faz:

1. move o documento da conta (create no novo `_id`, delete no antigo), mantendo o
   `id` da conta — as sessões continuam válidas;
2. substitui o email antigo pelo novo nos índices que o usam como chave ou
   atribuição (ver `REFERENCIAS`);
3. regista um evento de auditoria.

O histórico (`finance_events`) **não** é reescrito por omissão: é o registo do que
aconteceu e não deve ser alterado. Use `--history` se quiser reescrevê-lo também.

Uso:

    python scripts/change_email.py --from antigo@exemplo.pt --to novo@exemplo.pt
    python scripts/change_email.py --from antigo@exemplo.pt --to novo@exemplo.pt --dry-run
    python scripts/change_email.py --from antigo@exemplo.pt --to novo@exemplo.pt --history
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from api import auth_service as auth  # noqa: E402
from api import events_service as events  # noqa: E402
from api.elasticsearch_client import (  # noqa: E402
    AUTH_SESSIONS_INDEX,
    AUTH_USERS_INDEX,
    SETTINGS_INDEX,
    get_es_client,
)

#: Índices onde o email identifica o dono do registo ou quem o alterou.
#: `finance_events` fica de fora de propósito (ver `--history`).
REFERENCIAS = (
    AUTH_SESSIONS_INDEX,
    "finance_crm_rbac",
    "finance_crm",
    "finance_user_state",
    "finance_analises_empresa",
    SETTINGS_INDEX,
    "finance_provider_keys",
    "finance_support_visitors",
    "finance_support_sessions",
    "finance_support_operators",
    "finance_auth_challenges",
)

HISTORICO = ("finance_events",)

#: Substitui o email em qualquer campo de texto do documento (inclui objetos e
#: listas aninhadas), sem tocar no `_id`.
REPLACE_SCRIPT = {
    "lang": "painless",
    "source": """
        void walk(def node, String from, String to) {
          if (node instanceof Map) {
            for (def entry : node.entrySet()) {
              def value = entry.getValue();
              if (value instanceof String) {
                if (value == from) { entry.setValue(to); }
              } else if (value instanceof Map || value instanceof List) {
                walk(value, from, to);
              }
            }
          } else if (node instanceof List) {
            for (int i = 0; i < node.size(); i++) {
              def value = node.get(i);
              if (value instanceof String) {
                if (value == from) { node.set(i, to); }
              } else if (value instanceof Map || value instanceof List) {
                walk(value, from, to);
              }
            }
          }
        }
        walk(ctx._source, params.from, params.to);
    """,
    "params": {"from": "", "to": ""},
}


def _move_account(client, origem: str, destino: str, *, dry_run: bool) -> str:
    """Move o documento da conta. Devolve o `id` da conta (quando conhecido)."""
    conta = auth.get_user_by_email(origem)
    if conta:
        if auth.get_user_by_email(destino):
            raise SystemExit(f"O destino {destino} já tem uma conta. Nada foi alterado.")
        if dry_run:
            print(f"[dry-run] moveria a conta {origem} -> {destino} (id {conta.get('id')})")
            return str(conta.get("id") or "")
        documento = {k: v for k, v in conta.items() if k != "_id"}
        documento["email"] = destino
        documento["updated_at"] = auth._now_iso()
        client.create(
            index=AUTH_USERS_INDEX,
            id=auth.normalize_email(destino),
            document=documento,
            refresh=True,
        )
        client.delete(index=AUTH_USERS_INDEX, id=auth.normalize_email(origem), refresh=True)
        print(f"conta movida: {origem} -> {destino} (id {conta.get('id')})")
        return str(conta.get("id") or "")

    atual = auth.get_user_by_email(destino)
    if not atual:
        raise SystemExit(f"Não existe conta em {origem} nem em {destino}.")
    print(f"conta já estava em {destino} (id {atual.get('id')}); a corrigir referências")
    return str(atual.get("id") or "")


def _replace_references(client, indices, origem: str, destino: str, *, dry_run: bool) -> dict:
    """Substitui o email antigo pelo novo nos índices indicados."""
    script = {**REPLACE_SCRIPT, "params": {"from": origem, "to": destino}}
    query = {"query_string": {"query": f'"{origem}"'}}
    resumo: dict[str, int] = {}

    for indice in indices:
        try:
            if not client.indices.exists(index=indice):
                continue
            encontrados = client.count(index=indice, body={"query": query}).get("count", 0)
        except Exception as error:  # noqa: BLE001 - índice ilegível não trava os restantes
            print(f"  {indice}: ignorado ({error})")
            continue
        if not encontrados:
            continue
        if dry_run:
            print(f"  [dry-run] {indice}: {encontrados} documento(s)")
            resumo[indice] = encontrados
            continue
        try:
            resposta = client.update_by_query(
                index=indice,
                body={"query": query, "script": script, "conflicts": "proceed"},
                refresh=True,
            )
            alterados = int(resposta.get("updated", 0))
            resumo[indice] = alterados
            print(f"  {indice}: {alterados}/{encontrados} documento(s) atualizado(s)")
        except Exception as error:  # noqa: BLE001
            print(f"  {indice}: falhou ({error})")
    return resumo


def main() -> int:
    parser = argparse.ArgumentParser(description="Alterar o email de uma conta e as referências.")
    parser.add_argument("--from", dest="origem", required=True, help="Email atual da conta")
    parser.add_argument("--to", dest="destino", required=True, help="Email novo")
    parser.add_argument("--dry-run", action="store_true", help="Mostrar o que mudaria, sem gravar")
    parser.add_argument("--history", action="store_true", help="Reescrever também o histórico de eventos")
    args = parser.parse_args()

    origem = auth.normalize_email(args.origem)
    destino = auth.normalize_email(args.destino)
    problema = auth.validate_email(destino)
    if problema:
        print(f"Email inválido: {problema}")
        return 2
    if origem == destino:
        print("O email de origem e de destino são iguais.")
        return 2

    client = get_es_client()
    if not client:
        print("Elasticsearch indisponível.")
        return 3

    print(f"{'[dry-run] ' if args.dry_run else ''}{origem} -> {destino}")
    conta_id = _move_account(client, origem, destino, dry_run=args.dry_run)

    indices = REFERENCIAS + (HISTORICO if args.history else ())
    resumo = _replace_references(client, indices, origem, destino, dry_run=args.dry_run)

    if not args.dry_run:
        events.log_event(
            "warning",
            "admin",
            f"Email da conta alterado: {origem} -> {destino}",
            data={
                "de": origem,
                "para": destino,
                "user_id": conta_id,
                "referencias": resumo,
                "historico": bool(args.history),
            },
            user_id=conta_id,
            user_email=destino,
        )

    total = sum(resumo.values())
    print(f"\nconcluído: {total} documento(s) referenciados" + (" (dry-run)" if args.dry_run else ""))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
