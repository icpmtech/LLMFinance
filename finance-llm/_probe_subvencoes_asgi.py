"""Prova das rotas de **subvenções públicas** em processo (sem servidor).

Usa o `TestClient` do FastAPI (**sem** `with`, para não correr o *lifespan* e não
carregar modelos) e substitui a dependência de sessão por uma sessão falsa, para
verificar os códigos de resposta reais das rotas e o contrato dos dados.

Não precisa do Elasticsearch: com o ES indisponível as rotas de leitura devolvem
503 e as de gestão continuam a responder. Os testes que exigem dados reais são
feitos à parte, contra os ficheiros de `data/subvencoes`.
"""
from __future__ import annotations

import sys

sys.path.insert(0, "c:/LLMFinance/finance-llm")

from pathlib import Path  # noqa: E402

from fastapi.testclient import TestClient  # noqa: E402

from api import main as api_main  # noqa: E402
from api import subvencoes_service as subvencoes  # noqa: E402
from api.auth_routes import CurrentSession, UserResponse, require_session  # noqa: E402

PASSED: list[str] = []
FAILED: list[str] = []


def check(label: str, condition: bool, detail: str = "") -> None:
    (PASSED if condition else FAILED).append(label)
    print(("  ok  " if condition else "FAIL  ") + label + (f"  [{detail}]" if detail and not condition else ""))


def fake_session(email: str, role: str) -> CurrentSession:
    display = email.split("@")[0]
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
    holder: dict[str, CurrentSession] = {"session": fake_session("prova@exemplo.pt", "member")}
    api_main.app.dependency_overrides[require_session] = lambda: holder["session"]
    cliente = TestClient(api_main.app, base_url="http://prova")

    # --- rotas registadas -------------------------------------------------
    # `app.routes` não serve: o `include_router` é preguiçoso (dá um
    # `_IncludedRouter`), pelo que a lista de caminhos vem do OpenAPI.
    caminhos = sorted(path for path in api_main.app.openapi()["paths"] if path.startswith("/subvencoes"))
    esperados = [
        "/subvencoes/amostra/{ano}",
        "/subvencoes/beneficiario/{nif}",
        "/subvencoes/entidade/{nif}",
        "/subvencoes/export.csv",
        "/subvencoes/ficheiros",
        "/subvencoes/indexar",
        "/subvencoes/jobs",
        "/subvencoes/jobs/{job_id}",
        "/subvencoes/ler",
        "/subvencoes/lotes",
        "/subvencoes/meta",
        "/subvencoes/resumo",
        "/subvencoes/search",
    ]
    check("13 rotas /subvencoes registadas", len(caminhos) == len(esperados), f"{len(caminhos)}: {caminhos}")
    check("todas as rotas esperadas existem", caminhos == esperados, str(caminhos))

    # --- metadados (não precisam do Elasticsearch) ------------------------
    r = cliente.get("/subvencoes/meta")
    check("GET /subvencoes/meta (200)", r.status_code == 200, r.text[:200])
    meta = r.json()
    check("meta: pasta correta", meta["dir"].replace("\\", "/").endswith("data/subvencoes"), meta["dir"])
    check("meta: env documentado", meta["dir_env"] == "SUBVENCOES_DATA_DIR", meta["dir_env"])
    check("meta: índice finance_subvencoes", meta["index"] == "finance_subvencoes", meta["index"])
    check("meta: 10 colunas do ficheiro", len(meta["colunas"]) == 10, str(len(meta["colunas"])))
    check(
        "meta: colunas pela ordem do ficheiro",
        [coluna["campo"] for coluna in meta["colunas"]]
        == [
            "nif_entidade",
            "entidade",
            "nif_beneficiario",
            "beneficiario",
            "montante",
            "data_decisao",
            "finalidade",
            "tipo_ato",
            "numero_ato",
            "data_ato",
        ],
        str([coluna["campo"] for coluna in meta["colunas"]]),
    )
    check("meta: ficheiros da pasta detetados", meta["ficheiros_disco"] >= 2, str(meta["ficheiros_disco"]))
    anos = {item["ano"] for item in meta["anos"]}
    check("meta: anos 2024 e 2025 (um na pasta, outro no nome)", {2024, 2025} <= anos, str(anos))
    check("meta: ficheiros contam como lidos", meta["lidos"] == 2, str(meta["lidos"]))
    check("meta: registos lidos somados", meta["registos_lidos"] > 400000, str(meta["registos_lidos"]))
    check(
        "meta: nada pendente de leitura",
        all(item["pendentes"] == 0 for item in meta["anos"]),
        str([(item["ano"], item["pendentes"]) for item in meta["anos"]]),
    )
    check(
        "meta: registos por ano (2024 + 2025 = total)",
        sum(item["registos"] for item in meta["anos"]) == meta["registos_lidos"],
        str([(item["ano"], item["registos"]) for item in meta["anos"]]),
    )

    r = cliente.get("/subvencoes/ficheiros")
    check("GET /subvencoes/ficheiros (200)", r.status_code == 200, r.text[:200])
    ficheiros = r.json()
    check("ficheiros: 2 ficheiros", ficheiros["total"] == 2, str(ficheiros["total"]))
    origens = {item["rel_path"]: item["ano_origem"] for item in ficheiros["items"]}
    check("ficheiros: ano da subpasta em 2024", origens.get("2024/lista-subvpublicas2024.ods") == "pasta", str(origens))
    check("ficheiros: ano do nome em 2025", origens.get("lista-subvpublicas2025_1.ods") == "nome", str(origens))

    r = cliente.get("/subvencoes/lotes")
    check("GET /subvencoes/lotes (200)", r.status_code == 200, r.text[:200])
    lotes = r.json()
    check("lotes: ficheiros lidos registados", lotes["total"] >= 2, str(lotes["total"]))
    check("lotes: registos somados", lotes["registos"] > 400000, str(lotes["registos"]))
    check("lotes: montante somado", lotes["montante"] > 1e10, str(lotes["montante"]))
    check(
        "lotes: manifesto guarda o nome do JSONL, nunca um caminho absoluto",
        all("jsonl" in lote and not Path(str(lote["jsonl"])).is_absolute() for lote in lotes["items"]),
        str([lote.get("jsonl") or lote.get("jsonl_path") for lote in lotes["items"]]),
    )
    check(
        "lotes: o JSONL resolve para um ficheiro existente",
        all(subvencoes.jsonl_path(lote) is not None and subvencoes.jsonl_path(lote).exists() for lote in lotes["items"]),
        str([str(subvencoes.jsonl_path(lote)) for lote in lotes["items"]]),
    )
    check(
        "lotes: caminho absoluto de outro sistema resolve pelo nome",
        subvencoes.jsonl_path({"jsonl_path": "C:\\outro\\sitio\\subv-z.jsonl"})
        == (subvencoes.normalized_dir() / "subv-z.jsonl"),
    )
    check("lotes: lote sem JSONL não resolve para o diretório atual", subvencoes.jsonl_path({}) is None)

    # --- amostra lida do disco (não precisa do Elasticsearch) -------------
    r = cliente.get("/subvencoes/amostra/2025?limit_items=3")
    check("GET /subvencoes/amostra/2025 (200)", r.status_code == 200, r.text[:200])
    amostra = r.json()
    check("amostra: ano 2025", amostra["ano"] == 2025, str(amostra["ano"]))
    check("amostra: registos lidos", amostra["total"] > 200000, str(amostra["total"]))
    check("amostra: 3 itens", len(amostra["items"]) == 3, str(len(amostra["items"])))
    primeiro = amostra["items"][0]
    check("amostra: doc_id com ano e linha", str(primeiro["doc_id"]).startswith("2025:"), str(primeiro.get("doc_id")))
    check("amostra: montante numérico", isinstance(primeiro.get("montante"), (int, float)), str(type(primeiro.get("montante"))))
    check("amostra: data normalizada", str(primeiro.get("data_decisao", ""))[:2] == "20", str(primeiro.get("data_decisao")))
    check("amostra: ano da decisão derivado", isinstance(primeiro.get("ano_decisao"), int), str(primeiro.get("ano_decisao")))
    check(
        "amostra: tipo de beneficiário classificado",
        primeiro.get("beneficiario_tipo") in subvencoes.TIPOS_BENEFICIARIO,
        str(primeiro.get("beneficiario_tipo")),
    )

    # --- leitura e indexação (trabalhos em segundo plano) -----------------
    r = cliente.post("/subvencoes/ler", json={"anos": [2024], "forcar": False})
    check("POST /subvencoes/ler (200)", r.status_code == 200, r.text[:250])
    job = r.json()
    check("ler: trabalho criado", job.get("tipo") == "ler" and bool(job.get("job_id")), str(job)[:150])
    if job.get("job_id"):
        r = cliente.get(f"/subvencoes/jobs/{job['job_id']}")
        check("GET /subvencoes/jobs/{id} (200)", r.status_code == 200, r.text[:200])

    r = cliente.get("/subvencoes/jobs")
    check("GET /subvencoes/jobs (200)", r.status_code == 200, r.text[:200])
    check("jobs: lista com o trabalho", r.json()["total"] >= 1, str(r.json()["total"]))

    r = cliente.get("/subvencoes/jobs/inexistente")
    check("job inexistente: 404", r.status_code == 404, str(r.status_code))

    r = cliente.post("/subvencoes/indexar", json={"anos": [2024], "forcar": False})
    check("POST /subvencoes/indexar (200)", r.status_code == 200, r.text[:250])

    # --- rotas que dependem do Elasticsearch -----------------------------
    for caminho in ("/subvencoes/resumo", "/subvencoes/search?q=teatro", "/subvencoes/beneficiario/500051054"):
        r = cliente.get(caminho)
        check(
            f"GET {caminho.split('?')[0]} responde sem estourar",
            r.status_code in (200, 404, 503),
            f"{r.status_code} {r.text[:120]}",
        )

    r = cliente.get("/subvencoes/export.csv")
    check(
        "GET /subvencoes/export.csv responde sem estourar",
        r.status_code in (200, 503),
        f"{r.status_code} {r.text[:120]}",
    )

    # --- validação de parâmetros -----------------------------------------
    r = cliente.get("/subvencoes/search?sort=inventado")
    check("ordenar inválido: 422", r.status_code == 422, str(r.status_code))
    r = cliente.get("/subvencoes/search?size=5000")
    check("tamanho acima do limite: 422", r.status_code == 422, str(r.status_code))
    r = cliente.get("/subvencoes/search?page=0")
    check("página 0: 422", r.status_code == 422, str(r.status_code))

    print(f"\n{len(PASSED)} verificações ok, {len(FAILED)} falhas")
    for item in FAILED:
        print("  -", item)
    return 1 if FAILED else 0


if __name__ == "__main__":
    sys.exit(main())
