"""Prova da API de relatórios contra o backend a correr (temporário).

Executa o fluxo completo com duas contas reais: um cliente cria o pedido e
declara o pagamento; um administrador (backoffice) confirma o pagamento, avança
o estado e anexa o relatório; o cliente volta a consultar e descarrega.

No fim limpa o que criou (`data/reports/reports.json` volta a ficar sem pedidos)
para não deixar lixo na plataforma.
"""
from __future__ import annotations

import json
import sys

import httpx

sys.path.insert(0, "c:/LLMFinance/finance-llm")

from api import auth_service  # noqa: E402
from api import reports_store  # noqa: E402

BASE = "http://127.0.0.1:8002"
PASSED: list[str] = []
FAILED: list[str] = []


def check(label: str, condition: bool, detail: str = "") -> None:
    (PASSED if condition else FAILED).append(label)
    print(("  ok  " if condition else "FAIL  ") + label + (f"  [{detail}]" if detail and not condition else ""))


def session_for(email: str) -> dict:
    user = auth_service.get_user_by_email(email)
    if not user:
        raise SystemExit(f"Sem conta {email} neste ambiente.")
    created = auth_service.create_session(user)
    token = created.get("token") or ""
    return {"email": email, "role": user.get("role"), "headers": {"Authorization": f"Bearer {token}"}}


def main() -> int:
    users = auth_service.list_users(limit=200)
    admin = next((u for u in users if (u.get("role") or "") == "admin"), None)
    member = next((u for u in users if (u.get("role") or "member") != "admin"), None)
    if not admin or not member:
        raise SystemExit("Preciso de uma conta admin e de uma conta member para a prova.")
    cliente = session_for(admin["email"] if member is None else member["email"])
    backoffice = session_for(admin["email"])
    print(f"cliente={cliente['email']} ({cliente['role']}) | backoffice={backoffice['email']} ({backoffice['role']})\n")

    created_id = ""
    with httpx.Client(timeout=60) as c:
        # 1) catálogo
        r = c.get(f"{BASE}/reports/catalogue", headers=cliente["headers"])
        check("GET /reports/catalogue", r.status_code == 200, r.text[:200])
        catalogue = r.json()
        check("catálogo tem 4 pacotes", len(catalogue.get("packages", [])) == 4, str(len(catalogue.get("packages", []))))
        check("número MB Way por omissão 919520386", catalogue["settings"]["mbway_number"] == "919520386", catalogue["settings"]["mbway_number"])
        check("resumo do cliente", c.get(f"{BASE}/reports/summary", headers=cliente["headers"]).status_code == 200)

        # 2) pedido pago
        r = c.post(
            f"{BASE}/reports/requests",
            headers=cliente["headers"],
            json={"package_id": "financeiro-detalhado", "targets": [{"name": "CILAG, LDA", "nif": "500697370"}], "notes": "Prova automática.", "mbway_phone": ""},
        )
        check("POST /reports/requests", r.status_code == 201, r.text[:250])
        pedido = r.json()
        created_id = pedido.get("id", "")
        check("estado inicial aguarda_pagamento", pedido.get("status") == "aguarda_pagamento", pedido.get("status"))
        check("total 24 €", abs(float(pedido["amounts"]["total"]) - 24.0) < 0.01, str(pedido["amounts"]))
        check("referência MB Way preenchida", bool(pedido["payment"]["mbway_reference"]), str(pedido["payment"]))
        reference = pedido["reference"]

        # 3) declarar pagamento
        r = c.post(f"{BASE}/reports/requests/{created_id}/payment", headers=cliente["headers"], json={"method": "mbway", "mbway_phone": "912345678", "note": "Paguei às 15h20"})
        check("POST pagamento declarado", r.status_code == 200, r.text[:250])
        declarado = r.json()["request"]
        check("pagamento aguarda_confirmacao", declarado["payment"]["status"] == "aguarda_confirmacao", declarado["payment"]["status"])
        check("telemóvel guardado", declarado["payment"]["mbway_phone"] == "912345678", declarado["payment"]["mbway_phone"])

        # 4) backoffice
        r = c.get(f"{BASE}/reports/backoffice/inbox", headers=backoffice["headers"])
        check("GET /reports/backoffice/inbox", r.status_code == 200, r.text[:200])
        inbox = r.json()
        check("pedido aparece na caixa", any(item["id"] == created_id for item in inbox["items"]), str(inbox["total"]))
        check("há pagamentos a confirmar", inbox["stats"]["awaiting_confirm"] >= 1, json.dumps(inbox["stats"]))
        check("notificação para o backoffice", inbox["unread"] >= 1, str(inbox["unread"]))

        r = c.post(f"{BASE}/reports/backoffice/requests/{created_id}/payment", headers=backoffice["headers"], json={"action": "confirm", "note": "MB Way 912345678"})
        check("confirmar pagamento", r.status_code == 200 and r.json()["status"] == "pagamento_confirmado", r.text[:200])

        r = c.patch(f"{BASE}/reports/backoffice/requests/{created_id}", headers=backoffice["headers"], json={"status": "em_producao", "note": "A produzir", "internal": False})
        check("avançar para em_producao", r.status_code == 200 and r.json()["status"] == "em_producao", r.text[:200])

        r = c.post(f"{BASE}/reports/backoffice/requests/{created_id}/note", headers=backoffice["headers"], json={"message": "Cliente prioritário", "internal": True})
        check("nota interna registada", r.status_code == 200 and "prioritário" in r.json()["internal_note"], r.text[:200])

        r = c.post(
            f"{BASE}/reports/backoffice/requests/{created_id}/files",
            headers=backoffice["headers"],
            files={"file": ("relatorio cilag.pdf", b"%PDF-1.4 prova automatica", "application/pdf")},
        )
        check("carregar relatório gerado", r.status_code == 200 and r.json()["status"] == "gerado", r.text[:250])
        ficheiro = r.json()["files"][0] if r.json().get("files") else {}

        # 5) o cliente vê o estado e descarrega
        r = c.get(f"{BASE}/reports/requests", headers=cliente["headers"])
        meu = next((item for item in r.json()["items"] if item["id"] == created_id), None)
        check("cliente vê estado gerado", bool(meu) and meu["status"] == "gerado", json.dumps(meu["status"] if meu else None))
        check("cliente NÃO vê a nota interna", bool(meu) and meu["internal_note"] == "" and all("prioritário" not in item["message"] for item in meu["history"]), "nota interna exposta")

        r = c.get(f"{BASE}/reports/requests/{created_id}/files/{ficheiro.get('id')}", headers=cliente["headers"])
        check("descarregar relatório", r.status_code == 200 and r.content.startswith(b"%PDF"), f"{r.status_code}")

        r = c.get(f"{BASE}/reports/notifications", headers=cliente["headers"])
        kinds = [item["kind"] for item in r.json()["items"]]
        check("cliente notificado (gerado/pagamento)", "gerado" in kinds and "pagamento" in kinds, str(kinds[:6]))

        # 6) pedido grátis entra em produção
        r = c.post(f"{BASE}/reports/requests", headers=cliente["headers"], json={"package_id": "corporativo", "targets": [{"name": "Grátis, Lda"}], "notes": ""})
        livre = r.json()
        check("pedido grátis entra em produção", r.status_code == 201 and livre["status"] == "em_producao" and livre["amounts"]["total"] == 0, str(livre.get("status")))

        # 7) limites e permissões
        r = c.post(f"{BASE}/reports/requests", headers=cliente["headers"], json={"package_id": "corporativo", "targets": [{"name": "A"}, {"name": "B"}]})
        check("limite de alvos recusado (400)", r.status_code == 400, f"{r.status_code} {r.text[:120]}")

        r = c.get(f"{BASE}/reports/backoffice/inbox", headers=cliente["headers"])
        check("cliente sem backoffice recebe 403", r.status_code == 403, str(r.status_code))

        # 8) configuração da administração
        r = c.get(f"{BASE}/reports/admin/settings", headers=backoffice["headers"])
        check("GET /reports/admin/settings", r.status_code == 200, r.text[:200])
        r = c.put(f"{BASE}/reports/admin/settings", headers=backoffice["headers"], json={"mbway_number": "+351 919 520 386", "backoffice_users": [cliente["email"]]})
        check("PUT settings normaliza o número", r.status_code == 200 and r.json()["mbway_number"] == "919520386", r.text[:200])
        r = c.get(f"{BASE}/reports/backoffice/inbox", headers=cliente["headers"])
        check("conta promovida a backoffice entra", r.status_code == 200, str(r.status_code))
        c.put(f"{BASE}/reports/admin/settings", headers=backoffice["headers"], json={"backoffice_users": []})

        # 9) exportação CSV
        r = c.get(f"{BASE}/reports/backoffice/export.csv", headers=backoffice["headers"])
        check("exportação CSV", r.status_code == 200 and "Referência" in r.text, str(r.status_code))

        # 10) entrega
        r = c.patch(f"{BASE}/reports/backoffice/requests/{created_id}", headers=backoffice["headers"], json={"status": "entregue", "note": "Entregue ao cliente."})
        check("marcar entregue", r.status_code == 200 and r.json()["status"] == "entregue", r.text[:200])

    print(f"\n{len(PASSED)} verificações ok, {len(FAILED)} falhas")
    if FAILED:
        for item in FAILED:
            print("  - " + item)
    print(f"referência usada: {reference if created_id else '—'}")
    return 1 if FAILED else 0


if __name__ == "__main__":
    try:
        code = main()
    finally:
        # Limpeza: não deixar pedidos de prova na plataforma.
        try:
            store = reports_store.load()
            removed = len(store["requests"]) + len(store["notifications"])
            store["requests"] = []
            store["notifications"] = []
            store["activity"] = []
            reports_store._write_store(store)
            for folder in reports_store.FILES_DIR.glob("*"):
                if folder.is_dir():
                    for item in folder.glob("*"):
                        item.unlink(missing_ok=True)
                    folder.rmdir()
            print(f"limpeza: {removed} registos de prova removidos")
        except Exception as exc:  # noqa: BLE001 - limpeza best effort
            print("limpeza falhou:", exc)
    sys.exit(code)
