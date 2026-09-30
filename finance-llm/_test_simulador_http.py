"""Valida o Simulador IQ OS pelo HTTP: cria sessão, lança uma simulação curta
e vai mostrando o progresso — serve para confirmar que os textos gerados saem
em português (diretiva de idioma) e que os endpoints de resultados respondem.

Uso:
    python _test_simulador_http.py [rondas]
"""
from __future__ import annotations

import json
import sys
import time

import httpx

ROOT = "http://127.0.0.1:8002"
ROUNDS = int(sys.argv[1]) if len(sys.argv) > 1 else 2

sys.path.insert(0, ".")
from api import auth_service  # noqa: E402


def main() -> int:
    users = auth_service.list_users(5)
    if not users:
        print("sem utilizadores na base — nada a testar")
        return 1
    admin = next((u for u in users if str(u.get("role")) == "admin"), users[0])
    session = auth_service.create_session(admin, user_agent="teste-simulador")
    headers = {"Authorization": f"Bearer {session['token']}"}
    print(f"sessão criada para {admin.get('email')} ({admin.get('role')})")

    with httpx.Client(base_url=ROOT, headers=headers, timeout=120) as client:
        runs = client.get("/mirofish/runs", params={"limit": 5, "enrich": 2}).json()
        print(f"\n=== /mirofish/runs: {runs['count']} simulações ===")
        for run in runs["runs"]:
            print(f"  {run['simulation_id']} · {run['state']['label']:<12} · {run['title'][:48]}")

        payload = {
            "source": "sistema",
            "params": {},
            "title": "Teste PT — panorama do sistema",
            "platform": "parallel",
            "max_rounds": ROUNDS,
            "steps": {"graph": True, "prepare": True, "run": True, "report": False},
        }
        job = client.post("/mirofish/simulations", json=payload).json()
        print(f"\n=== trabalho {job['id']} iniciado ({ROUNDS} rondas) ===")

        simulation_id = ""
        deadline = time.time() + 1500
        seen = 0
        while time.time() < deadline:
            time.sleep(10)
            state = client.get(f"/mirofish/jobs/{job['id']}").json()
            for entry in state["log"][seen:]:
                print(f"  [{entry['at']}] {entry['message'][:150]}")
            seen = len(state["log"])
            simulation_id = str((state.get("result") or {}).get("simulation_id") or simulation_id)
            if state["status"] != "running":
                print(f"\n>>> estado final: {state['status']} · passo {state['step']} · {state['progress']}%")
                if state.get("error"):
                    print(">>> erro:", state["error"])
                    if state.get("hint"):
                        print(">>> dica:", state["hint"])
                break

        if len(sys.argv) > 2 and simulation_id:
            overview = client.get(f"/mirofish/runs/{simulation_id}", params={"actions": 3}).json()
            print("\n=== amostra de resultados ===")
            print("título:", overview["simulation"]["title"])
            print("estado:", overview["state"]["label"], "| rondas:", overview["metrics"]["rounds_total"])
            for agent in overview["cast"][:2]:
                print(f"  agente: {agent['name']} ({agent['entity_type']}) · ações {agent['actions_total']}")
                print(f"    bio: {(agent['bio'] or '')[:160]}")
            for action in overview["actions"][:2]:
                print(f"  ação: {action['agent_name']} ({action['action']}) · {action['content'][:160]}")
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
