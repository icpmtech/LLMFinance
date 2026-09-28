"""Verificação HTTP das rotas /padroes/* (API local em 8002)."""
from __future__ import annotations

import json
import sys
import time

import httpx

BASE = "http://127.0.0.1:8002"
Q = {"pais": "PT", "ano_from": 2020, "ano_to": 2024, "per_year": 400}


def show(path: str, params: dict | None = None, method: str = "GET") -> dict | None:
    started = time.perf_counter()
    try:
        if method == "POST":
            response = httpx.post(f"{BASE}{path}", timeout=300)
        else:
            response = httpx.get(f"{BASE}{path}", params=params, timeout=600)
        elapsed = time.perf_counter() - started
        body = response.json()
        print(f"{path:52s} {response.status_code}  {elapsed:6.1f}s  {type(body).__name__}")
        return body if response.status_code < 400 else None
    except Exception as exc:  # noqa: BLE001
        print(f"{path:52s} FALHOU: {type(exc).__name__}: {str(exc)[:120]}")
        return None


anomalies = show("/padroes/anomalies", {**Q, "limit": 3, "min_score": 0.8})
if anomalies:
    print("   total:", anomalies["total"], "| 1.º score:", anomalies["items"][0]["score"] if anomalies["items"] else "—")

entities = show("/padroes/entities", {**Q, "limit": 3})
if entities:
    print("   total:", entities["total"], "| 1.ª:", (entities["items"][0]["nome"] if entities["items"] else "—"))

relations = show("/padroes/relations", Q)
if relations:
    print(
        "   nós:", len(relations["nodes"]),
        "arestas:", len(relations["edges"]),
        "laços:", len(relations["lacos"]),
        "concentração:", len(relations["concentracao"]),
        "insolventes:", len(relations["insolventes"]),
    )
    if relations["nodes"]:
        print("   nó exemplo:", json.dumps(relations["nodes"][0], ensure_ascii=False)[:200])

news = show("/padroes/news", {**Q, "limit": 3})
if news:
    print("   procuradas:", news.get("procuradas"), "| itens:", news.get("total"))

dossier = show("/padroes/entity/500205698", {"pais": "PT"})
if dossier:
    print("   nome:", dossier["nome"], "| contratos:", dossier["contratos_total"], "| sinais:", len(dossier["sinais"]))

show("/padroes/cache/clear", method="POST")
sys.exit(0)
