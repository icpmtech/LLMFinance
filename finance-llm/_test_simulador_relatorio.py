"""Gera e lê um relatório pelo HTTP do Simulador IQ OS (validação ponta a ponta).

Uso: python _test_simulador_relatorio.py [simulation_id]
"""
from __future__ import annotations

import json
import sys
import time

import httpx

ROOT = "http://127.0.0.1:8002"
sys.path.insert(0, ".")
from api import auth_service  # noqa: E402


def main() -> int:
    users = auth_service.list_users(5)
    admin = next((u for u in users if str(u.get("role")) == "admin"), users[0])
    session = auth_service.create_session(admin, user_agent="teste-relatorio")
    headers = {"Authorization": f"Bearer {session['token']}"}

    with httpx.Client(base_url=ROOT, headers=headers, timeout=180) as client:
        simulation_id = sys.argv[1] if len(sys.argv) > 1 else ""
        if not simulation_id:
            runs = client.get("/mirofish/runs", params={"limit": 6, "enrich": 6}).json()["runs"]
            print("=== simulações ===")
            for run in runs:
                live = run.get("live") or {}
                print(f"  {run['simulation_id']} · {run['state']['label']:<12} · rondas {live.get('round_current')}/{live.get('rounds_total')} · {live.get('progress')}%")
            concluidas = [r for r in runs if r["state"]["key"] == "completed"]
            em_curso = [r for r in runs if r["state"]["key"] == "running" and (r.get("live") or {}).get("progress", 0) == 100]
            escolhida = (concluidas or em_curso or runs)[0]
            simulation_id = escolhida["simulation_id"]
            print(f"\nsimulação escolhida: {simulation_id} ({escolhida['state']['label']})")

        overview = client.get(f"/mirofish/runs/{simulation_id}", params={"actions": 1}).json()
        print(f"estado na ficha: {overview['state']['key']} · ativa: {overview['active']}")

        status = client.get(f"/mirofish/runs/{simulation_id}/report").json()
        print(f"relatório antes: has_report={status['has_report']} status={status['status']['label']}")

        if not status["has_report"]:
            if overview["active"]:
                print("a interromper a execução para libertar o relatório…")
                print(client.post(f"/mirofish/runs/{simulation_id}/stop").json()["state"])
                time.sleep(5)
            pedido = client.post(f"/mirofish/runs/{simulation_id}/report", json={"force": False})
            if pedido.status_code >= 400:
                print("ERRO ao pedir relatório:", pedido.status_code, pedido.text[:400])
                return 1
            print("pedido aceite:", json.dumps(pedido.json()["status"], ensure_ascii=False))

        deadline = time.time() + 1500
        while time.time() < deadline:
            time.sleep(15)
            status = client.get(f"/mirofish/runs/{simulation_id}/report").json()
            estado = status["status"]["label"]
            marca = (status.get("report") or {}).get("chars", 0)
            print(f"  relatório: {estado} · id={status.get('report_id')} · {marca} caracteres")
            if status["has_report"] and status["status"]["key"] in {"completed", "failed", "error"}:
                break
            if status["status"]["key"] in {"failed", "error"}:
                break

        relatorio = status.get("report") or {}
        if relatorio:
            print("\n=== relatório ===")
            print("título:", relatorio.get("title"))
            print("secções:", [s["title"] for s in relatorio.get("sections", [])])
            print("palavras:", relatorio.get("words"))
            print("--- início do texto ---")
            print((relatorio.get("markdown") or "")[:900])
        else:
            print("sem relatório ainda:", json.dumps(status, ensure_ascii=False)[:400])

        resposta = client.post(
            f"/mirofish/runs/{simulation_id}/report/chat",
            json={"message": "Que setores apresentam maior risco e porquê?", "history": []},
        )
        if resposta.status_code < 400:
            data = resposta.json()
            print("\n=== conversa com o relatório ===")
            print(data["answer"][:400])
        else:
            print("\nconversa indisponível:", resposta.status_code, resposta.text[:200])
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
