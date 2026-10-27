"""Verificação end-to-end do login em dois passos (script temporário)."""

from __future__ import annotations

import sys
import uuid

sys.path.insert(0, r"C:\LLMFinance\finance-llm")

from fastapi.testclient import TestClient

from api import auth_service as auth
from api import notification_email

codes: dict[str, str] = {}


def _capture(to: str, name: str, code: str, **kwargs: object) -> dict:
    codes["code"] = code
    return {"ok": True, "configured": True, "message": "capturado"}


notification_email.send_login_code_email = _capture  # type: ignore[assignment]

from api.main import app  # noqa: E402

EMAIL = f"mfa.e2e.{uuid.uuid4().hex[:8]}@example.test"
PASSWORD = "TesteMfa123"

failures: list[str] = []


def check(label: str, condition: bool, extra: object = "") -> None:
    print(("OK   " if condition else "FAIL ") + label + (f"  {extra}" if extra and not condition else ""))
    if not condition:
        failures.append(label)


def main() -> int:
    with TestClient(app) as client:
        user = auth.register_user(name="Teste MFA", email=EMAIL, password=PASSWORD)
        auth.update_user(str(user["id"]), {"status": "active", "role": "admin"}, admin_fields=True)

        login = client.post("/api/auth/login", json={"email": EMAIL, "password": PASSWORD})
        check("login normal (politica desligada) devolve token", login.status_code == 200 and bool(login.json().get("token")), login.text[:200])
        token = login.json().get("token", "")
        headers = {"Authorization": f"Bearer {token}"}

        status = client.get("/api/auth/mfa", headers=headers)
        check("GET /auth/mfa com politica desligada", status.status_code == 200 and status.json()["policy"] == "off", status.text[:300])
        check("mfa opcional por omissao", status.json()["required"] is False and status.json()["can_change"] is True)

        policy = client.get("/api/admin/auth/mfa", headers=headers)
        check("GET /admin/auth/mfa", policy.status_code == 200 and "policies" in policy.json(), policy.text[:300])

        saved = client.put(
            "/api/admin/auth/mfa",
            headers=headers,
            json={"policy": "admins", "code_ttl_seconds": 300, "max_attempts": 4, "resend_cooldown_seconds": 20},
        )
        check("PUT /admin/auth/mfa grava a politica", saved.status_code == 200 and saved.json()["policy"] == "admins", saved.text[:300])

        step1 = client.post("/api/auth/login", json={"email": EMAIL, "password": PASSWORD})
        body = step1.json()
        check("login passa a pedir codigo", step1.status_code == 200 and body.get("mfa_required") is True, step1.text[:300])
        check("login nao devolve token sem o codigo", not body.get("token"))
        check("codigo foi enviado por email", bool(codes.get("code")) and len(codes["code"]) == 6)
        check("email mascarado na resposta", "***@" in str(body.get("email")))
        challenge_id = body.get("challenge_id", "")

        wrong = "000000" if codes["code"] != "000000" else "111111"
        bad = client.post("/api/auth/mfa/verify", json={"challenge_id": challenge_id, "code": wrong})
        check("codigo errado e recusado", bad.status_code == 401 and "Restam 2" in bad.text, bad.text[:200])

        resend = client.post("/api/auth/mfa/resend", json={"challenge_id": challenge_id})
        check("reenvio imediato e travado pelo intervalo", resend.status_code == 429, resend.text[:200])

        good = client.post("/api/auth/mfa/verify", json={"challenge_id": challenge_id, "code": codes["code"]})
        check("codigo certo abre a sessao", good.status_code == 200 and bool(good.json().get("token")), good.text[:300])
        session_headers = {"Authorization": f"Bearer {good.json().get('token', '')}"}

        again = client.post("/api/auth/mfa/verify", json={"challenge_id": challenge_id, "code": codes["code"]})
        check("codigo nao serve duas vezes", again.status_code == 401, again.text[:200])

        current = client.get("/api/auth/mfa", headers=session_headers)
        check(
            "conta obrigada: nao pode desligar",
            current.status_code == 200 and current.json()["enforced"] is True and current.json()["can_change"] is False,
            current.text[:300],
        )
        disable = client.put("/api/auth/mfa", headers=session_headers, json={"enabled": False})
        check("PUT /auth/mfa recusa desligar quando e obrigatorio", disable.status_code == 409, disable.text[:200])

        client.put("/api/admin/auth/mfa", headers=headers, json={"policy": "off"})
        opt_in = client.put("/api/auth/mfa", headers=session_headers, json={"enabled": True})
        check("utilizador pode ativar MFA na propria conta", opt_in.status_code == 200 and opt_in.json()["user_enabled"] is True, opt_in.text[:300])

        step2 = client.post("/api/auth/login", json={"email": EMAIL, "password": PASSWORD})
        check("preferencia propria obriga ao codigo", step2.json().get("mfa_required") is True, step2.text[:200])
        verified = client.post("/api/auth/mfa/verify", json={"challenge_id": step2.json()["challenge_id"], "code": codes["code"]})
        check("login conclui com o codigo novo", verified.status_code == 200, verified.text[:200])

        admin_mfa = client.post(f"/api/admin/users/{user['id']}/mfa", headers=headers, json={"enabled": False})
        check("admin desliga MFA de uma conta", admin_mfa.status_code == 200 and admin_mfa.json()["user"]["mfa_enabled"] is False, admin_mfa.text[:300])

        step3 = client.post("/api/auth/login", json={"email": EMAIL, "password": PASSWORD})
        check("sem MFA volta ao login simples", step3.status_code == 200 and bool(step3.json().get("token")), step3.text[:200])

        auth.delete_account(str(user["id"]))
        client.put("/api/admin/auth/mfa", headers=headers, json={"policy": "off"})

    print("\nFALHAS:", failures or "nenhuma")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
