"""Sonda: associar fontes do sistema ao Public Data e reconstruir o mundo.

    c:\\LLMFinance\\.venv\\Scripts\\python.exe _probe_world_sources.py [--keep]

Faz o percurso completo pela API (como o utilizador faria na página World):

1. `GET /world/sources` — catálogo com volumetria e o que está associado;
2. `PUT /world/sources` — associa **todas** as fontes do sistema;
3. `POST /world/rebuild` — reconstrói o mundo com as fontes novas;
4. confirma o efeito: eventos novos (`publicacao_societaria`, `marca_registada`,
   `mencao`), identificadores LEI, métricas do registo, grafo do pipeline com as
   fontes associadas e Mermaid válido.

Sem `--keep`, no fim repõe as fontes por omissão (o mundo fica como estava até
nova reconstrução) e apaga a conta de QA.
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parent))

BASE = "http://127.0.0.1:8002"
EMAIL = "qa.sources@iqos.dev"
PASSWORD = "QaSources!2026"

ALL_SOURCES = [
    "contratos",
    "contratos_es",
    "cire",
    "pessoas",
    "contribuintes",
    "entidades",
    "gleif",
    "societario",
    "marcas",
    "firmas",
    "sociais",
    "recolha",
]

failures: list[str] = []


def check(label: str, ok: bool, detail: str = "") -> None:
    print(f"{'OK  ' if ok else 'FALHA'} {label}{(' — ' + detail) if detail else ''}")
    if not ok:
        failures.append(label)


def main() -> int:
    keep = "--keep" in sys.argv
    client = httpx.Client(base_url=BASE, timeout=900.0)

    before = client.get("/world/sources").json()
    check(
        "GET /world/sources",
        len(before.get("sources") or []) >= 10,
        f"{len(before.get('sources') or [])} fontes no catálogo, associadas: {', '.join(before.get('associated') or [])}",
    )
    print("    catálogo:")
    for source in before.get("sources") or []:
        # Marcadores ASCII: a consola do Windows (cp1252) não escreve «■».
        mark = "[x]" if source.get("associated") else ("[ ]" if source.get("exists") else "[?]")
        print(
            f"      {mark} {source['id']:<12} {source['index']:<28} {source.get('documents') or 0:>8} docs  "
            f"adapter={source.get('adapter'):<12} junção={source.get('join')}"
        )

    response = client.post(
        "/auth/register",
        json={"name": "QA Sources", "email": EMAIL, "password": PASSWORD, "title": "QA"},
    )
    if response.status_code == 201:
        token = response.json().get("token")
    else:
        response = client.post("/auth/login", json={"email": EMAIL, "password": PASSWORD, "remember": False})
        token = response.json().get("token") if response.status_code == 200 else None
    check("sessão de QA", bool(token), str(response.status_code))
    if not token:
        return 1
    headers = {"Authorization": f"Bearer {token}"}

    response = client.put("/world/sources", headers=headers, json={"ids": ALL_SOURCES})
    payload = response.json() if response.status_code == 200 else {}
    check(
        "PUT /world/sources (todas)",
        response.status_code == 200 and set(ALL_SOURCES) <= set(payload.get("associated") or []),
        f"associadas: {', '.join(payload.get('associated') or [])}",
    )

    started = time.time()
    response = client.post(
        "/world/rebuild",
        headers=headers,
        json={"contract_sample": 8000, "entity_limit": 2000, "wait": True},
    )
    summary = response.json() if response.status_code == 200 else {}
    check(
        "POST /world/rebuild (com todas as fontes)",
        response.status_code == 200 and bool(summary.get("entities")),
        f"{summary.get('entities')} entidades, {summary.get('events')} eventos, "
        f"{summary.get('relations')} relações, {summary.get('history')} períodos em {round(time.time() - started, 1)}s",
    )
    extra = summary.get("extra") or {}
    if extra:
        print("    fontes adicionais:")
        for key, value in extra.items():
            print(f"      {key}: {json.dumps(value, ensure_ascii=False)}")
    check(
        "fontes associadas registadas na reconstrução",
        set(ALL_SOURCES) <= set(summary.get("sources_associated") or []),
        ", ".join(summary.get("sources_associated") or []),
    )
    registo = extra.get("registo") or {}
    check(
        "registo enriqueceu entidades (nome/país/LEI/métricas)",
        int(registo.get("enriched") or 0) > 0,
        f"{registo.get('enriched')} enriquecidas de {registo.get('records')} registos "
        f"({registo.get('by_name')} por designação, {registo.get('ignored')} ignoradas)",
    )
    for key, label in (("societario", "publicações societárias"), ("propriedade", "marcas/firmas"), ("mencoes", "menções")):
        block = extra.get(key) or {}
        check(
            f"fonte {key} produziu {label}",
            bool(block.get("events") or block.get("attributes")),
            json.dumps(block, ensure_ascii=False),
        )

    stats = client.get("/world/events/stats").json()
    kinds = {item["key"]: item["count"] for item in (stats.get("kinds") or [])}
    print(f"    eventos por tipo: {json.dumps(kinds, ensure_ascii=False)}")
    for kind, label in (
        ("publicacao_societaria", "publicações societárias"),
        ("marca_registada", "marcas"),
        ("mencao", "menções externas"),
    ):
        check(f"eventos de {label} no índice", int(kinds.get(kind) or 0) > 0, f"{kinds.get(kind, 0)}")

    # Identificadores LEI (só existem se a fonte GLEIF estiver associada).
    # A contagem direta no índice é o sinal fiável (a pesquisa por designação
    # apanha poucas entidades por página).
    lei_total = 0
    try:
        from api.elasticsearch_client import WORLD_STATE_INDEX, get_es_client

        es = get_es_client()
        if es is not None:
            lei_total = int(
                es.count(index=WORLD_STATE_INDEX, body={"query": {"exists": {"field": "identifiers.lei"}}})["count"]
            )
    except Exception as exc:  # pragma: no cover - depende do cluster
        print(f"    (contagem de LEI não feita: {exc})")
    check(
        "identificadores LEI ligados a entidades",
        lei_total > 0,
        f"{lei_total} entidades com LEI (junção por designação legal exata)",
    )

    pipeline = client.get("/world/pipeline/graph").json()
    public = next((node for node in pipeline.get("nodes") or [] if node["id"] == "public-data"), {})
    artifacts = public.get("artifacts") or []
    check(
        "grafo do pipeline mostra as fontes associadas",
        len(artifacts) >= len(ALL_SOURCES),
        f"{len(artifacts)} fontes no nó Public Data: " + ", ".join(item["label"] for item in artifacts),
    )
    check("pipeline Mermaid gerado", pipeline.get("mermaid", "").startswith("flowchart TD"), f"{len(pipeline.get('mermaid') or '')} chars")

    if not keep:
        response = client.put("/world/sources", headers=headers, json={"ids": None})
        restored = response.json().get("associated") if response.status_code == 200 else None
        print(f"    (fontes repostas: {', '.join(restored or [])})")
        try:
            from api.elasticsearch_client import get_es_client

            es = get_es_client()
            if es is not None:
                es.delete_by_query(index="finance_users", body={"query": {"term": {"email": EMAIL}}}, conflicts="proceed", refresh=True)
                es.delete_by_query(index="finance_sessions", body={"query": {"term": {"email": EMAIL}}}, conflicts="proceed", refresh=True)
                print("    (conta de QA removida)")
        except Exception as exc:  # pragma: no cover - limpeza best effort
            print(f"    (limpeza não feita: {exc})")

    print(f"\n=== {'TUDO OK' if not failures else 'FALHAS: ' + ', '.join(failures)} ===")
    return 0 if not failures else 1


if __name__ == "__main__":
    raise SystemExit(main())
