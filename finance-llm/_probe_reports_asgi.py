"""Prova das rotas de relatórios **em processo** (sem servidor nem Elasticsearch).

Usa o `ASGITransport` do httpx (não corre o *lifespan*, portanto não carrega
modelos) e substitui a dependência de sessão por sessões falsas com os papéis
que interessam: cliente (`member`), administrador/backoffice e uma conta
marcada como backoffice pela configuração.

Valida o ciclo completo — pedido → pagamento → confirmação → relatório gerado →
download — mais as permissões (403 para quem não é do backoffice), os limites do
catálogo e a configuração da administração. No fim limpa os pedidos criados.
"""
from __future__ import annotations

import sys

import httpx

sys.path.insert(0, "c:/LLMFinance/finance-llm")

from fastapi.testclient import TestClient  # noqa: E402

from api import auth_service  # noqa: E402
from api import main as api_main  # noqa: E402
from api import reports_store  # noqa: E402
from api.auth_routes import CurrentSession, UserResponse, require_session  # noqa: E402

PASSED: list[str] = []
FAILED: list[str] = []


def check(label: str, condition: bool, detail: str = "") -> None:
    (PASSED if condition else FAILED).append(label)
    print(("  ok  " if condition else "FAIL  ") + label + (f"  [{detail}]" if detail and not condition else ""))


def fake_session(email: str, role: str, name: str = "") -> CurrentSession:
    display = name or email.split("@")[0]
    return CurrentSession(
        user=UserResponse(
            id=f"u-{email}",
            email=email,
            name=display,
            role=role,
            initials=(display[:2] or "??").upper(),
            status="active",
            locale="pt-PT",
            timezone="Europe/Lisbon",
        ),
        session_id="s-prova",
        token="t-prova",
    )


def main() -> int:
    holder: dict[str, CurrentSession] = {}
    api_main.app.dependency_overrides[require_session] = lambda: holder["session"]
    cliente = fake_session("cliente@exemplo.pt", "member", "Cliente Exemplo")
    admin = fake_session("admin@exemplo.pt", "admin", "Admin Exemplo")
    equipa = fake_session("equipa@exemplo.pt", "member", "Equipa Backoffice")
    outro = fake_session("outro@exemplo.pt", "member", "Outro")
    # Cenário real: a administração marca a equipa como backoffice de relatórios.
    reports_store.save_settings({"backoffice_users": ["equipa@exemplo.pt"]}, actor="admin@exemplo.pt")

    # `TestClient` sem `with` não corre o lifespan (não carrega modelos).
    c = TestClient(api_main.app, base_url="http://prova")
    holder["session"] = cliente
    if True:
        r = c.get("/reports/catalogue")
        check("GET /reports/catalogue", r.status_code == 200, r.text[:200])
        catalogue = r.json()
        check("4 pacotes no catálogo", len(catalogue["packages"]) == 4, str(len(catalogue["packages"])))
        check("número MB Way 919520386", catalogue["settings"]["mbway_number"] == "919520386", catalogue["settings"]["mbway_number"])
        check("chave de API nunca exposta", "mbway_api_key" not in catalogue["settings"])

        # pedido pago
        r = c.post(
            "/reports/requests",
            json={"package_id": "concorrencia", "targets": [{"name": "CILAG, LDA", "nif": "500697370"}, {"name": "Concorrente, SA", "nif": "501234567"}], "notes": "Prova", "mbway_phone": ""},
        )
        check("POST /reports/requests (201)", r.status_code == 201, r.text[:250])
        pedido = r.json()
        created_id = pedido["id"]
        check("estado aguarda_pagamento", pedido["status"] == "aguarda_pagamento", pedido["status"])
        check("total 130 €", abs(pedido["amounts"]["total"] - 130.0) < 0.01, str(pedido["amounts"]))
        check("alvos com NIF", pedido["targets_label"] == "CILAG, LDA (500697370), Concorrente, SA (501234567)", pedido["targets_label"])
        check("referência MB Way", bool(pedido["payment"]["mbway_reference"]), str(pedido["payment"]["mbway_reference"]))

        # outro utilizador não pode ver nem pagar
        holder["session"] = outro
        check("outro utilizador: 403 no detalhe", c.get(f"/reports/requests/{created_id}").status_code == 403)
        check("outro utilizador: 403 no pagamento", c.post(f"/reports/requests/{created_id}/payment", json={"method": "mbway"}).status_code == 403)
        check("outro utilizador: lista vazia", c.get("/reports/requests").json()["total"] == 0)
        check("outro utilizador: sem backoffice (403)", c.get("/reports/backoffice/inbox").status_code == 403)

        # cliente declara o pagamento
        holder["session"] = cliente
        r = c.post(f"/reports/requests/{created_id}/payment", json={"method": "mbway", "mbway_phone": "912345678", "note": "Paguei"})
        check("declarar pagamento", r.status_code == 200, r.text[:250])
        check("pagamento aguarda confirmação", r.json()["request"]["payment"]["status"] == "aguarda_confirmacao", r.json()["request"]["payment"]["status"])

        # backoffice (conta marcada nas definições)
        holder["session"] = equipa
        r = c.get("/reports/backoffice/inbox")
        check("GET /reports/backoffice/inbox", r.status_code == 200, r.text[:200])
        inbox = r.json()
        check("pedido na caixa de entrada", any(item["id"] == created_id for item in inbox["items"]))
        check("há pagamentos a confirmar", inbox["stats"]["awaiting_confirm"] >= 1, str(inbox["stats"]))
        check("notificação para o backoffice", inbox["unread"] >= 1, str(inbox["unread"]))

        r = c.post(f"/reports/backoffice/requests/{created_id}/payment", json={"action": "confirm", "note": "MB Way 912345678"})
        check("confirmar pagamento", r.status_code == 200 and r.json()["status"] == "pagamento_confirmado", r.text[:200])

        r = c.patch(f"/reports/backoffice/requests/{created_id}", json={"status": "em_producao", "note": "A produzir"})
        check("avançar para em_producao", r.status_code == 200 and r.json()["status"] == "em_producao", r.text[:200])

        r = c.post(f"/reports/backoffice/requests/{created_id}/note", json={"message": "Cliente prioritário", "internal": True})
        check("nota interna registada", r.status_code == 200 and "prioritário" in r.json()["internal_note"], r.text[:200])

        r = c.post(
            f"/reports/backoffice/requests/{created_id}/files",
            files={"file": ("relatorio cilag.pdf", b"%PDF-1.4 prova", "application/pdf")},
        )
        check("carregar relatório (marca gerado)", r.status_code == 200 and r.json()["status"] == "gerado", r.text[:250])
        ficheiro = r.json()["files"][0]
        check("nome do ficheiro saneado", ficheiro["name"] == "relatorio_cilag.pdf", ficheiro["name"])
        check("extensão perigosa recusada", c.post(f"/reports/backoffice/requests/{created_id}/files", files={"file": ("x.exe", b"MZ", "application/octet-stream")}).status_code == 400)

        # cliente vê e descarrega
        holder["session"] = cliente
        r = c.get("/reports/requests")
        meu = next((item for item in r.json()["items"] if item["id"] == created_id), None)
        check("cliente vê estado gerado", bool(meu) and meu["status"] == "gerado", str(meu and meu["status"]))
        check("nota interna escondida do cliente", bool(meu) and meu["internal_note"] == "" and all("prioritário" not in h["message"] for h in meu["history"]))
        r = c.get(f"/reports/requests/{created_id}/files/{ficheiro['id']}")
        check("download do relatório", r.status_code == 200 and r.content.startswith(b"%PDF"), str(r.status_code))
        check("download marca como entregue", c.get(f"/reports/requests/{created_id}").json()["status"] == "entregue")
        kinds = [item["kind"] for item in c.get("/reports/notifications").json()["items"]]
        check("cliente notificado", "gerado" in kinds and "pagamento" in kinds, str(kinds[:8]))
        check("marcar notificações lidas", c.post("/reports/notifications/read", json={}).json()["unread"] == 0)

        # pedido grátis e limites
        r = c.post("/reports/requests", json={"package_id": "corporativo", "targets": [{"name": "Grátis, Lda"}]})
        check("pedido grátis entra em produção", r.status_code == 201 and r.json()["status"] == "em_producao" and r.json()["amounts"]["total"] == 0)
        check("7 alvos na concorrência recusado", c.post("/reports/requests", json={"package_id": "concorrencia", "targets": [{"name": f"E{i}"} for i in range(7)]}).status_code == 400)
        check("pacote inexistente recusado", c.post("/reports/requests", json={"package_id": "nao-existe", "targets": [{"name": "A"}]}).status_code == 400)
        check("sem alvos recusado", c.post("/reports/requests", json={"package_id": "corporativo", "targets": []}).status_code == 400)

        # administração
        holder["session"] = admin
        check("GET /reports/admin/settings", c.get("/reports/admin/settings").status_code == 200)
        r = c.put("/reports/admin/settings", json={"mbway_number": "+351 919 520 386", "backoffice_users": ["outro@exemplo.pt"]})
        check("PUT settings normaliza o número", r.status_code == 200 and r.json()["mbway_number"] == "919520386", r.text[:200])
        check("chave de API fica mascarada", r.json()["mbway_api_set"] is False, r.text[:200])

        holder["session"] = outro
        check("conta promovida entra no backoffice", c.get("/reports/backoffice/inbox").status_code == 200)

        holder["session"] = admin
        c.put("/reports/admin/settings", json={"backoffice_users": []})
        r = c.get("/reports/backoffice/export.csv")
        check("exportação CSV", r.status_code == 200 and "Referência" in r.text, str(r.status_code))
        r = c.post("/reports/admin/catalogue", json={"id": "corporativo", "price": 0, "title": "Relatório Corporativo"})
        check("editar pacote no catálogo", r.status_code == 200, r.text[:200])
        holder["session"] = cliente
        check("cliente não edita catálogo (403)", c.post("/reports/admin/catalogue", json={"id": "x", "title": "X"}).status_code == 403)

    api_main.app.dependency_overrides.clear()
    print(f"\n{len(PASSED)} verificações ok, {len(FAILED)} falhas")
    for item in FAILED:
        print("  - " + item)
    return 1 if FAILED else 0


if __name__ == "__main__":
    try:
        code = main()
    finally:
        try:
            store = reports_store.load()
            removed = len(store["requests"]) + len(store["notifications"])
            store["requests"] = []
            store["notifications"] = []
            store["activity"] = []
            store["settings"]["backoffice_users"] = []
            reports_store._write_store(store)
            for folder in reports_store.FILES_DIR.glob("*"):
                if folder.is_dir():
                    for item in folder.glob("*"):
                        item.unlink(missing_ok=True)
                    folder.rmdir()
            print(f"limpeza: {removed} registos de prova removidos")
        except Exception as exc:  # noqa: BLE001
            print("limpeza falhou:", exc)
    sys.exit(code)
