"""Testar o módulo de CRM (`/crm/*`) de ponta a ponta.

Cria um utilizador de QA temporário, exercita as rotas (contas, contactos,
oportunidades, atividades, ligação ao EmpresasIQ e indicadores) e limpa tudo no
fim — incluindo os registos no Elasticsearch.

Correr:  python _test_crm_api.py
"""
import sys
import uuid

sys.path.insert(0, ".")

from fastapi.testclient import TestClient  # noqa: E402

from api.elasticsearch_client import CRM_INDEX, AUTH_USERS_INDEX, get_es_client  # noqa: E402
from api.main import app  # noqa: E402

EMAIL = "crm.qa@iqos.local"
PASSWORD = f"Qa!{uuid.uuid4().hex[:12]}"

client = TestClient(app)
failures = []


def check(label, condition, extra=""):
    status = "OK " if condition else "FALHA"
    print(f"  [{status}] {label}{f' — {extra}' if extra else ''}")
    if not condition:
        failures.append(label)


def cleanup(user_id):
    es = get_es_client()
    if not es:
        print("  (sem Elasticsearch: limpeza impossível)")
        return
    try:
        if user_id:
            es.delete_by_query(
                index=CRM_INDEX,
                body={"query": {"term": {"owner_id": user_id}}},
                refresh=True,
                conflicts="proceed",
            )
        es.delete_by_query(
            index=AUTH_USERS_INDEX,
            body={"query": {"term": {"email": EMAIL}}},
            refresh=True,
            conflicts="proceed",
        )
        print("  limpeza: registos de CRM e conta de QA removidos")
    except Exception as exc:  # pragma: no cover
        print(f"  limpeza falhou: {exc}")


print("=== 1. Sessão de QA ===")
register = client.post(
    "/auth/register",
    json={"name": "QA CRM", "email": EMAIL, "password": PASSWORD},
)
if register.status_code == 409:
    # Conta já existente de uma execução anterior: entra em vez de criar.
    register = client.post("/auth/login", json={"email": EMAIL, "password": PASSWORD})
if register.status_code in (200, 201):
    payload = register.json()
    token = payload["token"]
    user_id = payload["user"]["id"]
    print(f"  sessão criada para {EMAIL} ({user_id})")
else:
    print(f"  não foi possível obter sessão: {register.status_code} {register.text[:200]}")
    sys.exit(1)

headers = {"Authorization": f"Bearer {token}"}

print("\n=== 2. Autenticação obrigatória ===")
check("sem token devolve 401", client.get("/crm/meta").status_code == 401)
check("token inválido devolve 401", client.get("/crm/meta", headers={"Authorization": "Bearer x"}).status_code == 401)

print("\n=== 3. GET /crm/meta ===")
meta = client.get("/crm/meta", headers=headers)
check("200", meta.status_code == 200, str(meta.status_code))
meta = meta.json()
check("fases completas", meta.get("deal_stages") == ["prospeccao", "qualificacao", "proposta", "negociacao", "ganho", "perdido"])
check("âmbito individual", meta.get("scope") == "own", str(meta.get("scope")))

print("\n=== 4. Contas ===")
created = client.post(
    "/crm/accounts",
    headers=headers,
    json={"name": "QA Cliente Sintético", "sector": "Tecnologia", "city": "Lisboa", "tags": ["qa", "teste"]},
)
check("criar conta devolve 201", created.status_code == 201, f"{created.status_code} {created.text[:160]}")
account = created.json()["item"] if created.status_code == 201 else {}
account_id = account.get("id")
check("conta com id", bool(account_id), str(account_id))
check("estado por omissão", account.get("status") == "prospect", str(account.get("status")))
check("etiquetas guardadas", account.get("tags") == ["qa", "teste"], str(account.get("tags")))

blank = client.post("/crm/accounts", headers=headers, json={"sector": "Sem nome"})
check("conta sem nome devolve 400", blank.status_code == 400, str(blank.status_code))

patched = client.patch(f"/crm/accounts/{account_id}", headers=headers, json={"status": "cliente", "employees": 42})
check("atualizar conta", patched.status_code == 200 and patched.json()["item"]["status"] == "cliente", str(patched.status_code))
check("campo numérico convertido", patched.json()["item"].get("employees") == 42, str(patched.json()["item"].get("employees")))
check("nome preservado no PATCH parcial", patched.json()["item"].get("name") == "QA Cliente Sintético")

listing = client.get("/crm/accounts?q=QA", headers=headers)
items = listing.json().get("items", [])
check("pesquisa encontra a conta", any(item["id"] == account_id for item in items), f"{len(items)} itens")
listing = client.get("/crm/accounts?status=prospect", headers=headers)
check("filtro por estado exclui a conta (cliente)", all(item["id"] != account_id for item in listing.json().get("items", [])))

print("\n=== 5. Contactos e oportunidades ===")
contact = client.post(
    "/crm/contacts",
    headers=headers,
    json={"name": "Ana QA", "account_id": account_id, "title": "Diretora Financeira", "email": "ana@qa.local", "is_primary": True},
)
check("criar contacto", contact.status_code == 201, str(contact.status_code))
contact_id = contact.json()["item"]["id"] if contact.status_code == 201 else None

deal = client.post(
    "/crm/deals",
    headers=headers,
    json={"title": "Licenças IQ OS", "account_id": account_id, "contact_id": contact_id, "amount": 25000, "stage": "proposta", "probability": 60, "expected_close_date": "2026-12-31"},
)
check("criar oportunidade", deal.status_code == 201, f"{deal.status_code} {deal.text[:160]}")
deal_item = deal.json()["item"] if deal.status_code == 201 else {}
deal_id = deal_item.get("id")
check("valor ponderado calculado", deal_item.get("weighted_amount") == 15000.0, str(deal_item.get("weighted_amount")))
check("moeda por omissão", deal_item.get("currency") == "EUR", str(deal_item.get("currency")))

moved = client.patch(f"/crm/deals/{deal_id}", headers=headers, json={"stage": "ganho"})
check("mover para ganho", moved.status_code == 200 and moved.json()["item"]["stage"] == "ganho", str(moved.status_code))
check("fecho registado ao ganhar", bool(moved.json()["item"].get("closed_at")), str(moved.json()["item"].get("closed_at")))

second = client.post(
    "/crm/deals",
    headers=headers,
    json={"title": "Formação", "account_id": account_id, "amount": 5000, "stage": "prospeccao"},
)
check("probabilidade por omissão na prospeção", second.json()["item"].get("probability") == 20, str(second.json()["item"].get("probability")))

print("\n=== 6. Atividades ===")
activity = client.post(
    "/crm/activities",
    headers=headers,
    json={"subject": "Reunião de kickoff", "account_id": account_id, "deal_id": deal_id, "type": "reuniao", "due_at": "2026-09-20", "priority": "alta"},
)
check("criar atividade", activity.status_code == 201, f"{activity.status_code} {activity.text[:160]}")
activity_id = activity.json()["item"]["id"] if activity.status_code == 201 else None
check("atividade não concluída", activity.json()["item"].get("done") is False)

done = client.patch(f"/crm/activities/{activity_id}", headers=headers, json={"done": True})
check("concluir atividade", done.json()["item"].get("done") is True and bool(done.json()["item"].get("done_at")))
pending = client.get("/crm/activities?done=false", headers=headers).json().get("items", [])
check("filtro de pendentes exclui a concluída", all(item["id"] != activity_id for item in pending))

print("\n=== 7. Timeline da conta ===")
timeline = client.get(f"/crm/accounts/{account_id}/timeline", headers=headers)
check("timeline devolve 200", timeline.status_code == 200, str(timeline.status_code))
body = timeline.json()
check("timeline reúne contactos/oportunidades/atividades",
      len(body.get("contacts", [])) == 1 and len(body.get("deals", [])) == 2 and len(body.get("activities", [])) == 1,
      f"{len(body.get('contacts', []))}/{len(body.get('deals', []))}/{len(body.get('activities', []))}")

print("\n=== 8. Indicadores (overview) ===")
overview = client.get("/crm/overview", headers=headers)
check("overview devolve 200", overview.status_code == 200, str(overview.status_code))
data = overview.json()
totals = data.get("totals", {})
check("contagens", totals.get("accounts") == 1 and totals.get("contacts") == 1, str(totals))
pipeline = data.get("pipeline", {})
check("pipeline aberto = 5000", pipeline.get("open_value") == 5000.0, str(pipeline.get("open_value")))
check("ponderado = 1000", pipeline.get("weighted_value") == 1000.0, str(pipeline.get("weighted_value")))
check("taxa de conversão 100% (1 ganha, 0 perdidas)", pipeline.get("win_rate") == 100.0, str(pipeline.get("win_rate")))
stages = {item["stage"]: item for item in data.get("by_stage", [])}
check("fases ordenadas", [item["stage"] for item in data.get("by_stage", [])][:4] == ["prospeccao", "qualificacao", "proposta", "negociacao"])
check("ganho com valor", stages.get("ganho", {}).get("value") == 25000.0, str(stages.get("ganho")))
check("top contas preenchido", bool(data.get("top_accounts")), str(data.get("top_accounts")))
check(
    "top contas com o nome da conta",
    any(item.get("name") == "QA Cliente Sintético" for item in data.get("top_accounts", [])),
    str(data.get("top_accounts")),
)

print("\n=== 9. Ligação ao EmpresasIQ ===")
search = client.get("/crm/entities/search?q=EDP&size=3", headers=headers)
check("pesquisa de entidades", search.status_code == 200 and len(search.json().get("items", [])) > 0, str(search.status_code))
candidate = next((item for item in search.json().get("items", []) if item.get("nif")), None)
if candidate:
    from_entity = client.post("/crm/accounts/from-entity", headers=headers, json={"nif": candidate["nif"], "tags": ["contratos"]})
    check("conta a partir de entidade", from_entity.status_code == 200, f"{from_entity.status_code} {from_entity.text[:160]}")
    linked = from_entity.json()
    check("conta ligada traz snapshot", bool((linked.get("item") or {}).get("entity")), str((linked.get("item") or {}).get("entity")))
    again = client.post("/crm/accounts/from-entity", headers=headers, json={"nif": candidate["nif"]})
    check("criar a partir da mesma entidade é idempotente", again.json().get("created") is False)
    synced = client.post(f"/crm/accounts/{linked['item']['id']}/sync-entity", headers=headers)
    check("sincronizar entidade", synced.status_code == 200 and bool(synced.json().get("item", {}).get("entity")), str(synced.status_code))
else:
    print("  (sem entidades com NIF: ligação ao EmpresasIQ não testada)")

print("\n=== 10. Apagar (arrasta os registos ligados) ===")
removed = client.delete(f"/crm/accounts/{account_id}", headers=headers)
check("apagar conta", removed.status_code == 200, str(removed.status_code))
check("cascata >= 4 registos", removed.json().get("cascaded", 0) >= 4, str(removed.json()))
check("timeline devolve 404", client.get(f"/crm/accounts/{account_id}/timeline", headers=headers).status_code == 404)

print("\n=== Limpeza ===")
cleanup(user_id)

print("\n" + ("TODOS OS TESTES PASSARAM" if not failures else f"FALHAS ({len(failures)}): " + "; ".join(failures)))
sys.exit(1 if failures else 0)
