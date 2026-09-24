"""Validação funcional de todos os cliques/filtros do módulo GLEIF.

A ferramenta de browser do VS Code só consegue tirar capturas nesta sessão (o canal
de controlo CDP recusa ligação), pelo que os cliques são validados ao nível do
pedido: este script executa exatamente o que cada controlo da interface envia ao
backend e verifica o resultado.

Uso:
    python _gleif_validar_ui.py
"""
from __future__ import annotations

import sys
import time
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

import httpx

API = "http://127.0.0.1:8002"

RESULTS: List[tuple[str, bool, str]] = []


def check(label: str, condition: bool, detail: str = "") -> None:
    RESULTS.append((label, bool(condition), detail))
    mark = "OK  " if condition else "FALHA"
    print(f"  [{mark}] {label}" + (f" — {detail}" if detail else ""))


def get(path: str, timeout: float = 60.0) -> Any:
    with httpx.Client(timeout=timeout) as client:
        response = client.get(f"{API}{path}")
        response.raise_for_status()
        return response.json()


def timed(path: str) -> tuple[Any, float]:
    start = time.perf_counter()
    payload = get(path)
    return payload, (time.perf_counter() - start) * 1000


def main() -> int:
    print("== metadados / estado (carregamento inicial da app) ==")
    meta, ms = timed("/gleif/meta")
    check("GET /gleif/meta", bool(meta.get("index")), f"{ms:.0f} ms · índice {meta.get('index')}")
    status, ms = timed("/gleif/status")
    count = status.get("elasticsearch", {}).get("count", 0)
    check("GET /gleif/status", count > 0, f"{ms:.0f} ms · {count} LEI indexados")

    facets: Dict[str, List[Dict[str, Any]]] = status.get("facets", {})
    check(
        "facetas com volumetria (os 7 filtros da UI)",
        all(facets.get(key) for key in ("country", "region", "status", "category", "legal_form", "verification", "lou")),
        " · ".join(f"{key}={len(facets.get(key) or [])}" for key in sorted(facets)),
    )

    print("\n== caixa de pesquisa: escrever + Enter ==")
    for text in ("GALP", "SONAE", "EDP"):
        payload, ms = timed(f"/gleif/search?q={text}&size=25&from=0")
        check(f"pesquisar «{text}»", payload.get("total", 0) > 0, f"{payload.get('total')} registos em {ms:.0f} ms")

    print("\n== chips de exemplo ==")
    for text in ("EDP", "SONAE", "GALP", "PT-13", "ACTIVE"):
        payload = get(f"/gleif/search?q={text}&size=25&from=0")
        check(f"exemplo «{text}»", len(payload.get("items", [])) > 0, f"{payload.get('total')} registos")

    print("\n== sugestões (dropdown enquanto se escreve) ==")
    suggestions = get("/gleif/suggest?q=revis&size=8")
    first = (suggestions.get("suggestions") or [{}])[0]
    check("GET /gleif/suggest", bool(first.get("lei")), f"{len(suggestions.get('suggestions', []))} sugestões · 1.ª: {first.get('name')}")
    if first.get("lei"):
        payload = get(f"/gleif/search?q={first['lei']}&size=25&from=0")
        item = (payload.get("items") or [{}])[0]
        check("clicar na sugestão abre o registo", item.get("lei") == first["lei"], f"{item.get('legal_name')}")

    print("\n== selects de faceta (um por um) ==")
    # O nome do campo no documento não é sempre igual ao parâmetro da rota.
    FIELD = {"verification": "corroboration_level", "lou": "managing_lou"}
    for key in ("country", "region", "status", "category", "legal_form", "verification", "lou"):
        values = facets.get(key) or []
        if not values:
            check(f"filtro {key}", False, "sem valores no índice")
            continue
        value = values[0]["key"]
        payload, ms = timed(f"/gleif/search?{key}={httpx.QueryParams({key: value})[key]}&size=5&from=0")
        items = payload.get("items", [])
        field = FIELD.get(key, key)
        matches = all((item.get(field) or "") == value for item in items)
        check(
            f"filtro {key}={value}",
            payload.get("total", 0) > 0 and bool(items) and matches,
            f"{payload.get('total')} registos em {ms:.0f} ms · 1.º: {(items[0].get('legal_name') if items else '—')}",
        )

    print("\n== filtros combinados (como a UI envia) ==")
    payload = get("/gleif/search?country=PT&region=PT-11&status=ACTIVE&size=5&from=0")
    check(
        "PT + Lisboa + ativas",
        payload.get("total", 0) > 0 and all(i.get("country") == "PT" and i.get("region") == "PT-11" and i.get("status") == "ACTIVE" for i in payload["items"]),
        f"{payload.get('total')} registos",
    )
    payload = get("/gleif/search?country=ES&category=GENERAL&verification=FULLY_CORROBORATED&size=5&from=0")
    check(
        "ES + genéricas + totalmente corroboradas",
        payload.get("total", 0) > 0 and all(i.get("category") == "GENERAL" and i.get("corroboration_level") == "FULLY_CORROBORATED" for i in payload["items"]),
        f"{payload.get('total')} registos",
    )

    print("\n== limpar filtros (chip ✕ / limpar tudo) ==")
    payload = get("/gleif/search?size=5&from=0")
    check("sem filtros", payload.get("total", 0) == count, f"{payload.get('total')} registos (todo o índice)")

    print("\n== ordenação ==")
    for sort, label in (("relevance", "relevância"), ("name", "nome A→Z"), ("updated", "atualização recente"), ("registered", "registo recente")):
        payload = get(f"/gleif/search?sort={sort}&size=5&from=0")
        items = payload.get("items", [])
        check(f"ordenar por {label}", len(items) == 5, f"1.º: {items[0]['legal_name'][:40]}")

    print("\n== paginação ==")
    page1 = get("/gleif/search?sort=name&size=25&from=0")
    page2 = get("/gleif/search?sort=name&size=25&from=25")
    check(
        "página seguinte (from=25)",
        page1["items"][0]["lei"] != page2["items"][0]["lei"],
        f"{page1['items'][0]['legal_name'][:26]} → {page2['items'][0]['legal_name'][:26]}",
    )

    print("\n== ficha do LEI ==")
    sample = page1["items"][0]
    detail, ms = timed(f"/gleif/records/{sample['lei']}")
    check(
        "abrir ficha",
        detail.get("lei") == sample["lei"] and bool(detail.get("legal_name")),
        f"{detail.get('legal_name')} · {detail.get('city')} · {detail.get('corroboration_level')} em {ms:.0f} ms",
    )
    check(
        "ficha traz endereço, forma jurídica e datas",
        bool(detail.get("address_lines")) and bool(detail.get("legal_form")) and bool(detail.get("initial_registration_date")),
        f"{detail.get('address_lines')} · forma {detail.get('legal_form')} · desde {detail.get('initial_registration_date')}",
    )

    print("\n== «ver no mapa» a partir da ficha ==")
    payload = get(f"/gleif/map?level=region&region={sample['region']}")
    check(
        f"mapa com o filtro da ficha ({sample['region']})",
        payload.get("regions") and all(r["key"] == sample["region"] for r in payload["regions"]),
        f"{payload['regions'][0]['count']} LEI em {payload['regions'][0]['label']}",
    )
    payload = get(f"/gleif/map?level=region&country={sample['country']}")
    check(
        f"mapa com o pais da ficha ({sample['country']})",
        payload.get("regions") and all(r["key"].startswith(sample["country"]) for r in payload["regions"]),
        f"{len(payload['regions'])} regiões",
    )

    print("\n== mapa: níveis e filtros ==")
    countries, ms = timed("/gleif/map?level=country")
    check(
        "nível «Países»",
        len(countries["regions"]) == 2,
        " · ".join(f"{r['key']}: {r['count']:,}".replace(",", " ") for r in countries["regions"]) + f" em {ms:.0f} ms",
    )
    regions, ms = timed("/gleif/map?level=region")
    check("nível «Regiões»", len(regions["regions"]) > 50, f"{len(regions['regions'])} regiões em {ms:.0f} ms")
    accounted = sum(r["count"] for r in regions["regions"]) + (regions.get("missing") or 0)
    check(
        "regiões + sem região = total que corresponde aos filtros",
        accounted == (regions.get("matched") or count),
        f"{sum(r['count'] for r in regions['regions'])} com região + {regions.get('missing')} sem = {accounted} de {count}",
    )
    pt_only = get("/gleif/map?level=region&country=PT")
    pt_accounted = sum(r["count"] for r in pt_only["regions"]) + (pt_only.get("missing") or 0)
    check("filtro de país no mapa (PT cobre 18 544)", pt_accounted == 18544, f"{pt_accounted} LEI (esperado 18 544)")
    check(
        "vista por país cobre todos os registos",
        sum(r["count"] for r in countries["regions"]) == count,
        f"{sum(r['count'] for r in countries['regions'])} de {count}",
    )

    print("\n== ingestão (ecrã) ==")
    jobs = get("/gleif/jobs")
    check("listar tarefas", isinstance(jobs.get("jobs"), list), f"{len(jobs['jobs'])} tarefas nesta sessão")
    with httpx.Client(timeout=60) as client:
        csv = client.get(f"{API}/gleif/export.csv?limit=5")
        first_line = csv.text.splitlines()[0] if csv.text else ""
        check("exportar CSV", csv.status_code == 200 and first_line.startswith("lei,"), f"{len(csv.text)} B · {first_line[:48]}…")
        unauthorized = client.post(f"{API}/gleif/ingest", json={"source": "file"})
        check("esvaziar/recolher exige sessão", unauthorized.status_code == 401, f"HTTP {unauthorized.status_code}")

    print("\n== páginas da interface ==")
    for path in ("/gleif", "/gleif/mapa", "/gleif/ingestao"):
        with httpx.Client(timeout=30) as client:
            response = client.get(f"{API}{path}", headers={"Accept": "text/html"})
        check(f"SPA {path}", response.status_code == 200 and "index-" in response.text, f"{len(response.content)} B")

    failed = [label for label, ok, _ in RESULTS if not ok]
    print("\n" + "=" * 62)
    print(f"{len(RESULTS) - len(failed)}/{len(RESULTS)} verificações OK")
    if failed:
        print("falhas: " + ", ".join(failed))
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
