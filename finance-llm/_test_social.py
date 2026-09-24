"""Testes do módulo de pesquisa social (coletores, serviço, índice e agenda).

Corre as quatro plataformas ao vivo (o que exigir credenciais é reportado como
tal, não como falha), grava, indexa e pesquisa. Não depende da API estar up.

Uso:
    python _test_social.py            # tudo
    python _test_social.py --fast     # sem recolhas de rede
"""
from __future__ import annotations

import argparse
import json
import sys

from api import social_collectors as collectors
from api import social_scheduler as scheduler
from api import social_service as social


PASSES: list[str] = []
FAILURES: list[str] = []
WARNINGS: list[str] = []


def check(label: str, condition: bool, detail: str = "") -> None:
    mark = "OK  " if condition else "FALHA"
    line = f"  [{mark}] {label}" + (f" — {detail}" if detail else "")
    print(line)
    (PASSES if condition else FAILURES).append(label)


def warn(label: str, detail: str = "") -> None:
    print(f"  [AVISO] {label}" + (f" — {detail}" if detail else ""))
    WARNINGS.append(label)


def section(title: str) -> None:
    print(f"\n=== {title}")


def test_catalog() -> None:
    section("Catálogo de plataformas")
    catalog = collectors.platform_catalog()
    ids = [entry["id"] for entry in catalog]
    check("quatro plataformas no catálogo", ids == ["linkedin", "reddit", "tiktok", "facebook"], str(ids))
    for entry in catalog:
        kinds = ", ".join(kind["id"] for kind in entry["kinds"])
        print(f"       {entry['label']}: {kinds}")
    reddit_search = next(k for k in catalog[1]["kinds"] if k["id"] == "search")
    check("pesquisa do Reddit marcada como «exige credenciais»", reddit_search["credentials"])
    check("Facebook marcado como «exige credenciais»", catalog[3]["kinds"][0]["credentials"])
    check("LinkedIn não exige credenciais", not catalog[0]["kinds"][0]["credentials"])

    templates = social.templates()
    check("galeria com templates", len(templates) >= 5, f"{len(templates)} templates")
    channel = social.channel_from_template("tiktok-hashtag", {"target": "benfica"})
    check("template gera canal normalizado", channel["platform"] == "tiktok" and channel["target"] == "benfica")
    check("canal tem agenda sugerida", bool(channel["schedule"]["cron"]), channel["schedule"]["cron"])


def test_definitions() -> None:
    section("Definições: validação e segredos")
    try:
        social.normalize_channel({"platform": "orkut", "kind": "perfil", "target": "x"})
        check("plataforma desconhecida é recusada", False, "não levantou erro")
    except ValueError as exc:
        check("plataforma desconhecida é recusada", "desconhecida" in str(exc).lower(), str(exc)[:60])

    try:
        social.normalize_channel({"platform": "reddit", "kind": "subreddit", "target": "x", "schedule": {"cron": "99 99 * * *"}})
        check("cron inválido é recusado", False, "não levantou erro")
    except ValueError as exc:
        check("cron inválido é recusado", True, str(exc)[:60])

    channel = social.normalize_channel(
        {
            "platform": "reddit",
            "kind": "search",
            "target": "EDP",
            "name": "Reddit · EDP",
            "options": {"client_secret": "segredo-123", "proxy": "http://proxy:1"},
            "schedule": {"cron": "0 * * * *"},
        }
    )
    public = social.channel_public(channel)
    check("segredo é mascarado na API", public["options"]["client_secret"] == "••••••", str(public["options"]))
    check("proxy não é mascarado", public["options"]["proxy"] == "http://proxy:1")
    check("canal sabe que exige credenciais", public["requires_credentials"])
    masked = social.channel_public(
        social.normalize_channel({"platform": "reddit", "kind": "search", "target": "EDP"})
    )
    check("sem credenciais o estado é «faltam»", masked["credentials"]["ok"] is False, str(masked["credentials"]["missing"]))


def _preview(
    label: str,
    payload: dict,
    limit: int = 3,
    expect_ok: bool = True,
    expect_status: str = "",
    tolerate: tuple[str, ...] = (),
) -> dict:
    print(f"\n  · {label} …")
    result = social.preview_channel(payload, limit=limit)
    status = result.get("status")
    if status in tolerate:
        # Condição externa (bloqueio de IP, credenciais em falta): não é defeito
        # do módulo — o contrato é devolver um estado explicativo com indicação.
        check(f"{label}: estado explicativo «{status}»", bool(result.get("error")))
        print(f"       indicação: {result.get('hint') or '—'}")
        warn(f"{label} indisponível neste ambiente", str(result.get("error"))[:80])
        return result
    if expect_ok:
        check(f"{label}: recolha ok", result.get("ok") is True, f"status={status} erro={result.get('error')}")
        for item in (result.get("items") or [])[:limit]:
            metrics = item.get("metrics") or {}
            print(
                f"       {item['platform']:9} | {(item.get('title') or item.get('text') or '')[:58]!r}"
                f" | {item.get('author') or '—'} | {metrics}"
            )
        for note in result.get("notes") or []:
            print(f"       nota: {note}")
    else:
        check(
            f"{label}: estado esperado «{expect_status}»",
            status == expect_status,
            f"status={status} erro={result.get('error')}",
        )
        if result.get("hint"):
            print(f"       indicação: {result['hint']}")
    return result


def test_live_collectors() -> None:
    section("Coletores ao vivo (sem credenciais)")
    _preview("LinkedIn · microsoft", {"platform": "linkedin", "kind": "company", "target": "microsoft"})
    _preview(
        "Reddit · r/investimentos",
        {"platform": "reddit", "kind": "subreddit", "target": "investimentos"},
        # O Reddit bloqueia IPs de datacenter: «blocked» é o estado correto e o
        # módulo tem de o explicar (proxy/credenciais), não escondê-lo.
        tolerate=("blocked",),
    )
    _preview("TikTok · #portugal", {"platform": "tiktok", "kind": "hashtag", "target": "portugal"})
    _preview(
        "TikTok · vídeo oembed",
        {
            "platform": "tiktok",
            "kind": "video",
            "target": "https://www.tiktok.com/@tiktok/video/6718335390845095173",
        },
    )
    section("Coletores que exigem credenciais")
    _preview(
        "Facebook · nasa (sem token)",
        {"platform": "facebook", "kind": "page", "target": "nasa"},
        expect_ok=False,
        expect_status="credentials",
    )
    _preview(
        "Reddit · pesquisa (sem OAuth)",
        {"platform": "reddit", "kind": "search", "target": "EDP"},
        expect_ok=False,
        expect_status="credentials",
    )


def test_store_and_index() -> None:
    section("Canais, execução, gravação e indexação")
    channel = social.upsert_channel(
        {
            "id": "teste-linkedin-microsoft",
            "name": "Teste · LinkedIn Microsoft",
            "platform": "linkedin",
            "kind": "company",
            "target": "microsoft",
            "enabled": False,
            "limit": 5,
            "tags": ["teste"],
            "schedule": {"cron": "0 8 * * *"},
        }
    )
    check("canal guardado", channel["id"] == "teste-linkedin-microsoft")
    check("canal aparece na listagem", any(c["id"] == channel["id"] for c in social.list_channels()))

    listed = social.get_channel(channel["id"])
    check("segredos ausentes da leitura", "••••••" not in json.dumps(listed, ensure_ascii=False))

    meta = social.execute_run_sync(channel["id"], trigger="teste")
    check(
        "execução concluída",
        meta.get("status") in ("ok", "empty", "blocked"),
        f"status={meta.get('status')} erro={meta.get('error')}",
    )
    print(f"       itens={meta.get('items_count')} indexados={meta.get('indexed_count')} segundos={meta.get('seconds')}")
    print(f"       métricas: likes={meta.get('likes')} comentários={meta.get('comments')} vistas={meta.get('views')}")
    if meta.get("sentiment_count"):
        print(f"       sentimento: {meta.get('sentiment_count')} publicações classificadas")
    for note in meta.get("notes") or []:
        print(f"       nota: {note}")

    runs = social.list_runs(channel["id"])
    check("execução no histórico", bool(runs) and runs[0]["run_id"] == meta["run_id"])
    if meta.get("items_count"):
        items = social.read_run_items(meta["run_id"], channel["id"], limit=5)
        check("JSONL com as publicações", items["count"] > 0, f"{items['count']} itens")

    section("Pesquisa no índice")
    result = social.search_items(q="", platform="linkedin", size=5, sort="recent")
    if result.get("error"):
        check("pesquisa no Elasticsearch", False, str(result["error"])[:120])
    else:
        check("pesquisa no Elasticsearch", True, f"total={result.get('total')}")
        for hit in (result.get("items") or [])[:3]:
            print(f"       {hit.get('platform')} | {(hit.get('title') or '')[:52]!r} | likes={hit.get('likes')}")
        aggs = (result.get("facets") or {}).get("platforms") or []
        print(f"       facetas por plataforma: {[(b['key'], b['count']) for b in aggs]}")

    # Limpeza do canal de teste (o histórico fica em disco).
    social.delete_channel(channel["id"])
    check("canal de teste removido", social.get_channel(channel["id"]) is None)


def test_scheduler() -> None:
    section("Agendador (cron)")
    state = scheduler.status()
    print(f"       disponível={state.get('available')} jobs={state.get('jobs_total')} erro={state.get('error')}")
    check("agendador carregável", state.get("available") is not None)
    reloaded = scheduler.reload_jobs()
    check("recarregar jobs não rebenta", "jobs" in reloaded)


def main() -> int:
    parser = argparse.ArgumentParser(description="Testes do módulo de pesquisa social.")
    parser.add_argument("--fast", action="store_true", help="Saltar as recolhas de rede.")
    args = parser.parse_args()

    test_catalog()
    test_definitions()
    if not args.fast:
        test_live_collectors()
    test_store_and_index()
    test_scheduler()

    print("\n" + "=" * 60)
    print(f"Passaram: {len(PASSES)} · Falharam: {len(FAILURES)} · Avisos: {len(WARNINGS)}")
    if WARNINGS:
        for label in WARNINGS:
            print(f"  ! {label}")
    if FAILURES:
        for label in FAILURES:
            print(f"  ✗ {label}")
    return 1 if FAILURES else 0


if __name__ == "__main__":
    sys.exit(main())
