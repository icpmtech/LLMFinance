"""Interface de linha de comandos do IQ OS.

Exemplos:
    python -m cli status
    python -m cli auth login ana@empresa.pt
    python -m cli contracts search "reabilitação de edifícios" --year 2025 --size 5
    python -m cli companies get 503140600
    python -m cli market quote AAPL --period 1y
    python -m cli forecast AAPL --days 10
    python -m cli users list

Todas as respostas podem ser obtidas em JSON com `--json`, para uso em scripts.
"""
from __future__ import annotations

import argparse
import getpass
import json
import sys
import webbrowser
from typing import Any, Callable, Dict, List, Optional

from cli import __version__, config as cli_config, format as fmt
from cli.client import ApiError, Client


# --------------------------------------------------------------- utilitários
def emit(args: argparse.Namespace, data: Any) -> None:
    """Imprime a resposta em JSON quando pedido (`--json`)."""
    if getattr(args, "json_output", False):
        print(json.dumps(data, ensure_ascii=False, indent=2, default=str))


def is_json(args: argparse.Namespace) -> bool:
    return bool(getattr(args, "json_output", False))


def ask_password(confirm: bool = False, label: str = "Palavra-passe") -> str:
    """Pede a palavra-passe sem a mostrar no ecrã."""
    first = getpass.getpass(f"{label}: ")
    if not confirm:
        return first
    second = getpass.getpass("Repita a palavra-passe: ")
    if first != second:
        raise ApiError("As palavras-passe não coincidem.", code="invalid_input")
    return first


def build_client(args: argparse.Namespace) -> Client:
    return Client(
        cli_config.resolve_api_url(getattr(args, "api", None)),
        cli_config.resolve_token(getattr(args, "token", None)),
    )


def require_session(client: Client) -> Dict[str, Any]:
    """Garante que há sessão válida antes de comandos autenticados."""
    if not client.token:
        raise ApiError("Sem sessão. Use `cli auth login <email>` primeiro.", code="no_session")
    return client.me()


# ------------------------------------------------------------------- status
def cmd_status(args: argparse.Namespace, client: Client) -> int:
    """Estado da API, do Elasticsearch e da sessão."""
    info: Dict[str, Any] = {"api_url": client.base_url}
    try:
        health = client.health()
        info["api"] = {"online": True, "detail": health}
    except ApiError as error:
        info["api"] = {"online": False, "error": error.message}
        emit(args, info)
        if not is_json(args):
            print(fmt.fail(f"API indisponível em {client.base_url}"))
            print(fmt.field("detalhe", error.message))
            print(fmt.dim("  Arranque o backend: python -m uvicorn api.main:app --port 8002"))
        return 1

    try:
        elastic = client.get("/elastic/status", timeout=30)
        info["elasticsearch"] = elastic
    except ApiError as error:
        info["elasticsearch"] = {"error": error.message}

    try:
        contracts = client.get("/contracts/status", timeout=60)
        info["contracts"] = contracts
    except ApiError as error:
        info["contracts"] = {"error": error.message}

    session: Dict[str, Any] = {"authenticated": False}
    if client.token:
        try:
            me = client.me()
            session = {"authenticated": True, "email": me.get("email"), "name": me.get("name"), "role": me.get("role")}
        except ApiError as error:
            session = {"authenticated": False, "error": error.message}
    info["session"] = session

    emit(args, info)
    if is_json(args):
        return 0

    print(fmt.title("IQ OS"), fmt.dim(f"v{__version__}"))
    print(fmt.field("API", f"{client.base_url} {fmt.ok('online')}"))
    detail = info["api"]["detail"]
    if isinstance(detail, dict) and detail.get("models"):
        print(fmt.field("", fmt.dim("modelos: " + ", ".join(str(m) for m in detail["models"]))))

    elastic = info.get("elasticsearch") or {}
    if elastic.get("error"):
        print(fmt.field("Elasticsearch", fmt.fail(elastic["error"])))
    else:
        version = elastic.get("version") or elastic.get("es_version") or "—"
        print(fmt.field("Elasticsearch", f"{fmt.ok('ligado')} {fmt.dim(str(version))}"))
        indices = elastic.get("indices")
        if isinstance(indices, dict):
            for name, count in list(indices.items())[:8]:
                print(fmt.field("", f"{name}: {fmt.number(count) if isinstance(count, (int, float)) else count}"))

    contracts = info.get("contracts") or {}
    if contracts.get("error"):
        print(fmt.field("Contratos", fmt.fail(contracts["error"])))
    else:
        years = contracts.get("years") or []
        span = f"{min(years)}–{max(years)}" if years else "—"
        print(fmt.field("Contratos", f"{fmt.number(contracts.get('total'))} documentos · {span}"))

    if session.get("authenticated"):
        print(fmt.field("Sessão", f"{fmt.ok(session['email'])} {fmt.dim('(' + str(session.get('role')) + ')')}"))
    else:
        print(fmt.field("Sessão", fmt.warn("sem sessão iniciada") + fmt.dim(" · cli auth login")))
    return 0


# --------------------------------------------------------------------- auth
def cmd_auth_login(args: argparse.Namespace, client: Client) -> int:
    password = args.password or ask_password()
    result = client.login(args.email, password, remember=args.remember)
    cli_config.update_config(
        token=result.get("token"),
        email=result.get("user", {}).get("email"),
        api_url=client.base_url,
    )
    emit(args, result)
    if not is_json(args):
        user = result.get("user", {})
        print(fmt.ok(f"Sessão iniciada como {user.get('name')} <{user.get('email')}>"))
        print(fmt.field("Perfil", user.get("role")))
        print(fmt.field("Expira", fmt.short_date(result.get("expires_at"), with_time=True)))
        print(fmt.field("Guardado em", fmt.dim(str(cli_config.config_path()))))
    return 0


def cmd_auth_register(args: argparse.Namespace, client: Client) -> int:
    password = args.password or ask_password(confirm=True)
    result = client.register(
        args.name,
        args.email,
        password,
        title=args.title,
        organization=args.organization,
    )
    cli_config.update_config(
        token=result.get("token"),
        email=result.get("user", {}).get("email"),
        api_url=client.base_url,
    )
    emit(args, result)
    if not is_json(args):
        user = result.get("user", {})
        print(fmt.ok(f"Conta criada: {user.get('name')} <{user.get('email')}>"))
        print(fmt.field("Perfil", f"{user.get('role')} (a primeira conta é administradora)"))
        print(fmt.field("Sessão", fmt.green("iniciada automaticamente")))
    return 0


def cmd_auth_whoami(args: argparse.Namespace, client: Client) -> int:
    me = require_session(client)
    emit(args, me)
    if is_json(args):
        return 0
    print(fmt.field("Nome", me.get("name")))
    print(fmt.field("Email", me.get("email")))
    print(fmt.field("Perfil", me.get("role")))
    if me.get("title") or me.get("organization"):
        print(fmt.field("Cargo", f"{me.get('title') or '—'} · {me.get('organization') or '—'}"))
    print(fmt.field("Conta criada", fmt.short_date(me.get("created_at"))))
    print(fmt.field("Último login", fmt.short_date(me.get("last_login_at"), with_time=True)))
    print(fmt.field("Inícios sessão", fmt.number(me.get("login_count"))))
    preferences = me.get("preferences") or {}
    if preferences:
        print(fmt.field("Preferências", ", ".join(f"{k}={v}" for k, v in preferences.items())))
    return 0


def cmd_auth_logout(args: argparse.Namespace, client: Client) -> int:
    if client.token:
        try:
            client.logout()
        except ApiError as error:
            if not is_json(args):
                print(fmt.warn(f"A API recusou o pedido ({error.message}); a sessão local é removida à mesma."))
    cli_config.update_config(token=None, email=None)
    emit(args, {"ok": True})
    if not is_json(args):
        print(fmt.ok("Sessão terminada e token removido."))
    return 0


def cmd_auth_sessions(args: argparse.Namespace, client: Client) -> int:
    require_session(client)
    if args.revoke_others:
        result = client.revoke_other_sessions()
        emit(args, result)
        if not is_json(args):
            print(fmt.ok(result.get("message", "Sessões terminadas.")))
        return 0

    sessions: List[Dict[str, Any]] = client.sessions()
    emit(args, sessions)
    if is_json(args):
        return 0
    if not sessions:
        print(fmt.warn("Sem sessões ativas."))
        return 0
    rows = [
        [
            "atual" if item.get("current") else "",
            fmt.short_date(item.get("created_at"), with_time=True),
            fmt.short_date(item.get("last_seen_at"), with_time=True),
            fmt.short_date(item.get("expires_at")),
            item.get("ip") or "—",
            fmt.truncate(item.get("user_agent") or "—", 34),
        ]
        for item in sessions
    ]
    print(fmt.table(["", "início", "atividade", "expira", "ip", "cliente"], rows))
    return 0


def cmd_auth_password(args: argparse.Namespace, client: Client) -> int:
    require_session(client)
    current = args.current or ask_password(label="Palavra-passe atual")
    new = args.new or ask_password(confirm=True, label="Nova palavra-passe")
    result = client.change_password(current, new)
    emit(args, result)
    if not is_json(args):
        print(fmt.ok(result.get("message", "Palavra-passe atualizada.")))
    return 0


def cmd_auth_profile(args: argparse.Namespace, client: Client) -> int:
    require_session(client)
    payload: Dict[str, Any] = {}
    for field, value in (
        ("name", args.name),
        ("title", args.title),
        ("organization", args.organization),
        ("phone", args.phone),
        ("locale", args.locale),
        ("timezone", args.timezone),
    ):
        if value is not None:
            payload[field] = value
    preferences = {}
    for field, value in (
        ("default_view", args.default_view),
        ("dock_position", args.dock_position),
        ("sidebar_hidden", args.sidebar_hidden),
        ("reduced_motion", args.reduced_motion),
    ):
        if value is not None:
            preferences[field] = value
    if preferences:
        payload["preferences"] = preferences
    if not payload:
        raise ApiError("Nada para alterar. Use --name, --title, --default-view, …", code="invalid_input")
    updated = client.patch("/auth/me", payload=payload)
    emit(args, updated)
    if not is_json(args):
        print(fmt.ok(f"Perfil atualizado: {updated.get('name')}"))
        print(fmt.field("Preferências", json.dumps(updated.get("preferences") or {}, ensure_ascii=False)))
    return 0


def party_name(party: Any, index: int = 0) -> str:
    """Extrai o nome de uma parte do contrato (`ContractParty`)."""
    if not isinstance(party, dict):
        return str(party or "—")
    parsed = party.get("parsed") or []
    if isinstance(parsed, list) and len(parsed) > index and isinstance(parsed[index], dict):
        if parsed[index].get("nome"):
            return str(parsed[index]["nome"])
    raw = party.get("raw") or []
    if isinstance(raw, list) and raw:
        return str(raw[0])
    return str(party.get("nome") or "—")


# ---------------------------------------------------------------- contratos
def cmd_contracts_search(args: argparse.Namespace, client: Client) -> int:
    payload = {
        "q": args.query,
        "year": args.year,
        "nif": args.nif,
        "region": args.region,
        "cpv_code": args.cpv,
        "min_price": args.min_price,
        "max_price": args.max_price,
        "start_date": args.start_date,
        "end_date": args.end_date,
        "size": args.size,
        "from": args.offset,
        "sort_by": args.sort,
        "sort_order": args.order,
    }
    result = client.post("/contracts/search", payload=payload, timeout=120)
    emit(args, result)
    if is_json(args):
        return 0
    items = result.get("items") or []
    print(fmt.title(f"{fmt.number(result.get('total'))} contratos"), fmt.dim(f"(a mostrar {len(items)})"))
    if not items:
        return 0
    rows = [
        [
            fmt.truncate(item.get("idcontrato"), 16),
            fmt.short_date(item.get("dataCelebracaoContrato") or item.get("dataPublicacao")),
            fmt.money(item.get("precoContratual")),
            fmt.truncate(party_name(item.get("adjudicantes")), 28),
            fmt.truncate(item.get("objectoContrato"), 54),
        ]
        for item in items
    ]
    print(fmt.table(["id", "data", "valor", "adjudicante", "objeto"], rows))
    return 0


def cmd_contracts_get(args: argparse.Namespace, client: Client) -> int:
    contract = client.get(f"/contracts/{args.idcontrato}", timeout=60)
    emit(args, contract)
    if is_json(args):
        return 0
    print(fmt.title(f"Contrato {contract.get('idcontrato')}"))
    print(fmt.field("Objeto", fmt.truncate(contract.get("objectoContrato"), 88)))
    print(fmt.field("Valor", fmt.money(contract.get("precoContratual"))))
    print(fmt.field("Celebrado", fmt.short_date(contract.get("dataCelebracaoContrato"))))
    print(fmt.field("Publicado", fmt.short_date(contract.get("dataPublicacao"))))
    adjudicantes = contract.get("adjudicantes")
    adjudicatarios = contract.get("adjudicatarios")
    if adjudicantes:
        print(fmt.field("Adjudicante", fmt.truncate(party_name(adjudicantes), 90)))
        if len(adjudicantes.get("parsed") or []) > 1:
            print(fmt.field("", fmt.dim("+ " + ", ".join(party_name({"parsed": [p]}) for p in adjudicantes["parsed"][1:4]))))
    if adjudicatarios:
        print(fmt.field("Adjudicatário", fmt.truncate(party_name(adjudicatarios), 90)))
        if len(adjudicatarios.get("parsed") or []) > 1:
            print(fmt.field("", fmt.dim("+ " + ", ".join(party_name({"parsed": [p]}) for p in adjudicatarios["parsed"][1:4]))))
    cpv = contract.get("cpv") or []
    if cpv:
        print(fmt.field("CPV", "; ".join(f"{c.get('code')} {fmt.truncate(c.get('description'), 40)}" for c in cpv[:4])))
    return 0


def cmd_contracts_analytics(args: argparse.Namespace, client: Client) -> int:
    result = client.get(
        "/contracts/analytics",
        params={"top_entities": args.top_entities, "top_cpv": args.top_cpv, "year": args.year},
        timeout=180,
    )
    emit(args, result)
    if is_json(args):
        return 0
    print(fmt.title("Análise de contratos"))
    print(fmt.field("Total", fmt.number(result.get("total"))))
    print(fmt.field("Valor total", fmt.money(result.get("total_value"))))
    print(fmt.field("Valor médio", fmt.money(result.get("avg_value"))))
    for label, key in (("Top adjudicantes", "top_adjudicantes"), ("Top adjudicatários", "top_adjudicatarios")):
        rows = result.get(key) or []
        if not rows:
            continue
        print(f"\n{fmt.bold(label)}")
        print(
            fmt.table(
                ["", "entidade", "contratos", "valor"],
                [
                    [
                        str(index + 1),
                        fmt.truncate(row.get("key"), 44),
                        fmt.number(row.get("count")),
                        fmt.money(row.get("total_value")),
                    ]
                    for index, row in enumerate(rows[: args.top_entities])
                ],
            )
        )
    cpv = result.get("top_cpv") or []
    if cpv:
        print(f"\n{fmt.bold('Top CPV')}")
        print(
            fmt.table(
                ["", "cpv", "contratos", "valor"],
                [
                    [
                        str(index + 1),
                        fmt.truncate(f"{row.get('key')} {row.get('description') or ''}", 50),
                        fmt.number(row.get("count")),
                        fmt.money(row.get("total_value")),
                    ]
                    for index, row in enumerate(cpv[: args.top_cpv])
                ],
            )
        )
    return 0


# ------------------------------------------------------------------ empresas
def cmd_companies_search(args: argparse.Namespace, client: Client) -> int:
    result = client.post(
        "/companies/search",
        payload={
            "query": args.query,
            "role": args.role,
            "region": args.region,
            "min_contracts": args.min_contracts,
            "year": args.year,
            "size": args.size,
        },
        timeout=180,
    )
    emit(args, result)
    if is_json(args):
        return 0
    items = result.get("items") or []
    print(
        fmt.title(f"{fmt.number(result.get('total'))} entidades"),
        fmt.dim(f"(adjudicantes {fmt.number(result.get('unique_adjudicantes'))} · adjudicatários {fmt.number(result.get('unique_adjudicatarios'))})"),
    )
    if not items:
        return 0
    rows = [
        [
            item.get("nif") or "—",
            fmt.truncate(item.get("name"), 42),
            fmt.number(item.get("contracts_total")),
            fmt.money(item.get("total_value")),
        ]
        for item in items
    ]
    print(fmt.table(["nif", "entidade", "contratos", "valor"], rows))
    return 0


def cmd_companies_get(args: argparse.Namespace, client: Client) -> int:
    company = client.get(f"/companies/{args.nif}", timeout=120)
    emit(args, company)
    if is_json(args):
        return 0
    print(fmt.title(company.get("name") or args.nif))
    print(fmt.field("NIF", company.get("nif")))
    print(fmt.field("Contratos", fmt.number(company.get("contracts_total"))))
    print(fmt.field("Valor total", fmt.money(company.get("total_value"))))
    for label, key in (("Como adjudicante", "adjudicante"), ("Como adjudicatário", "adjudicatario")):
        role = company.get(key)
        if isinstance(role, dict):
            print(
                fmt.field(
                    label,
                    f"{fmt.number(role.get('contracts_count'))} contratos · {fmt.money(role.get('total_value'))}",
                )
            )
    if company.get("trademarks_total"):
        print(fmt.field("Marcas INPI", fmt.number(company.get("trademarks_total"))))
    if company.get("firmas_total"):
        print(fmt.field("Firmas RNPC", fmt.number(company.get("firmas_total"))))
    recent = company.get("recent_contracts") or []
    if recent:
        print(f"\n{fmt.bold('Contratos recentes')}")
        print(
            fmt.table(
                ["id", "data", "valor", "objeto"],
                [
                    [
                        fmt.truncate(item.get("idcontrato"), 16),
                        fmt.short_date(item.get("dataCelebracaoContrato") or item.get("dataPublicacao")),
                        fmt.money(item.get("precoContratual")),
                        fmt.truncate(item.get("objectoContrato"), 60),
                    ]
                    for item in recent[:10]
                ],
            )
        )
    return 0


def cmd_companies_contracts(args: argparse.Namespace, client: Client) -> int:
    result = client.get(f"/companies/{args.nif}/contracts", params={"size": args.size, "role": args.role}, timeout=180)
    emit(args, result)
    if is_json(args):
        return 0
    items = result.get("items") or []
    print(fmt.title(f"{result.get('name') or args.nif}"), fmt.dim(f"{fmt.number(result.get('total'))} contratos"))
    print(
        fmt.table(
            ["id", "data", "valor", "objeto"],
            [
                [
                    fmt.truncate(item.get("idcontrato"), 16),
                    fmt.short_date(item.get("dataCelebracaoContrato") or item.get("dataPublicacao")),
                    fmt.money(item.get("precoContratual")),
                    fmt.truncate(item.get("objectoContrato"), 62),
                ]
                for item in items
            ],
        )
    )
    return 0


def cmd_companies_trademarks(args: argparse.Namespace, client: Client) -> int:
    result = client.get(f"/companies/{args.nif}/trademarks", params={"size": args.size}, timeout=180)
    emit(args, result)
    if is_json(args):
        return 0
    items = result.get("items") or []
    print(fmt.title("Marcas INPI"), fmt.dim(f"{fmt.number(result.get('total'))} registos"))
    print(
        fmt.table(
            ["marca", "titular", "estado", "semelhança"],
            [
                [
                    fmt.truncate(item.get("mark_name"), 34),
                    fmt.truncate(item.get("holder_name"), 30),
                    fmt.truncate(item.get("current_phase"), 26),
                    fmt.percent((item.get("holder_similarity") or 0) * 100, 1),
                ]
                for item in items
            ],
        )
    )
    return 0


def cmd_companies_firmas(args: argparse.Namespace, client: Client) -> int:
    result = client.get(f"/companies/{args.nif}/firmas", params={"size": args.size}, timeout=180)
    emit(args, result)
    if is_json(args):
        return 0
    items = result.get("items") or []
    print(fmt.title("Firmas RNPC"), fmt.dim(f"{fmt.number(result.get('total'))} registos"))
    print(
        fmt.table(
            ["firma", "nipc", "concelho", "semelhança"],
            [
                [
                    fmt.truncate(item.get("nome"), 40),
                    item.get("nipc") or "—",
                    fmt.truncate(item.get("concelho"), 22),
                    fmt.percent((item.get("name_similarity") or 0) * 100, 1),
                ]
                for item in items
            ],
        )
    )
    return 0


# ----------------------------------------------------------------- entidades
def cmd_entities_search(args: argparse.Namespace, client: Client) -> int:
    result = client.post(
        "/entities/search",
        payload={
            "query": args.query,
            "country": args.country,
            "only_with_nif": args.only_with_nif or None,
            "min_contracts": args.min_contracts,
            "role": args.role,
            "sort_by": args.sort,
            "size": args.size,
        },
        timeout=180,
    )
    emit(args, result)
    if is_json(args):
        return 0
    items = result.get("items") or []
    print(fmt.title(f"{fmt.number(result.get('total'))} entidades"))
    print(
        fmt.table(
            ["nif", "nome", "país", "contratos", "valor"],
            [
                [
                    item.get("nif") or "—",
                    fmt.truncate(item.get("name"), 40),
                    item.get("country_code") or "—",
                    fmt.number(item.get("contracts_count")),
                    fmt.money(item.get("total_value")),
                ]
                for item in items
            ],
        )
    )
    return 0


def cmd_entities_get(args: argparse.Namespace, client: Client) -> int:
    entity = client.get(f"/entities/{args.nif}", timeout=120)
    emit(args, entity)
    if is_json(args):
        return 0
    print(fmt.title(entity.get("name") or args.nif))
    print(fmt.field("NIF", entity.get("nif") or "—"))
    print(fmt.field("País", f"{entity.get('country') or '—'} {fmt.dim(entity.get('country_code') or '')}"))
    print(fmt.field("Contratos", fmt.number(entity.get("contracts_count"))))
    print(fmt.field("Valor total", fmt.money(entity.get("total_value"))))
    print(fmt.field("Adjudicante", f"{fmt.number(entity.get('as_adjudicante_count'))} · {fmt.money(entity.get('as_adjudicante_value'))}"))
    print(fmt.field("Adjudicatário", fmt.number(entity.get("as_adjudicatario_count"))))
    if entity.get("trademarks_total"):
        print(fmt.field("Marcas INPI", fmt.number(entity.get("trademarks_total"))))
    if entity.get("firmas_total"):
        print(fmt.field("Firmas RNPC", fmt.number(entity.get("firmas_total"))))
    return 0


def cmd_entities_stats(args: argparse.Namespace, client: Client) -> int:
    stats = client.get("/entities/stats", timeout=180)
    emit(args, stats)
    if is_json(args):
        return 0
    print(fmt.title("Estatísticas do cadastro de entidades"))
    print(fmt.field("Total", fmt.number(stats.get("total"))))
    print(fmt.field("Com NIF", fmt.number(stats.get("with_nif"))))
    print(fmt.field("Sem NIF", fmt.number(stats.get("without_nif"))))
    print(fmt.field("Contratos", fmt.number(stats.get("total_contracts"))))
    print(fmt.field("Valor total", fmt.money(stats.get("total_value"))))
    countries = stats.get("countries") or []
    if countries:
        print(f"\n{fmt.bold('Países')}")
        print(
            fmt.table(
                ["país", "entidades", "valor"],
                [[row.get("country"), fmt.number(row.get("count")), fmt.money(row.get("total_value"))] for row in countries[:12]],
            )
        )
    return 0


# ------------------------------------------------------------------ mercados
def cmd_market_tickers(args: argparse.Namespace, client: Client) -> int:
    result = client.get("/tickers", params={"query": args.query} if args.query else None, timeout=120)
    emit(args, result)
    if is_json(args):
        return 0
    # O endpoint devolve `{"tickers": [...]}` (símbolos indexados) ou uma lista
    # de resultados de pesquisa (símbolo + nome).
    items = result.get("tickers") if isinstance(result, dict) else result
    if isinstance(items, list) and items and all(isinstance(item, str) for item in items):
        print(fmt.title(f"{len(items)} tickers indexados"))
        for symbol in items[: args.size]:
            print(f"  · {symbol}")
        return 0
    if not isinstance(items, list):
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    print(fmt.title(f"{len(items)} tickers"))
    print(
        fmt.table(
            ["ticker", "nome", "bolsa", "tipo"],
            [
                [
                    item.get("symbol") or item.get("ticker") or "—",
                    fmt.truncate(item.get("name") or item.get("shortName"), 44),
                    item.get("exchange") or "—",
                    item.get("quoteType") or "—",
                ]
                for item in items[: args.size]
            ],
        )
    )
    return 0


def cmd_market_quote(args: argparse.Namespace, client: Client) -> int:
    symbol = args.ticker.upper()
    info = client.get(f"/tickers/{symbol}/info", timeout=120)
    emit(args, info)
    if is_json(args):
        return 0
    price = info.get("price") or info.get("regularMarketPrice") or info.get("current_price")
    change = info.get("change_percent") or info.get("regularMarketChangePercent")
    print(fmt.title(symbol), fmt.dim(str(info.get("name") or info.get("longName") or "")))
    print(fmt.field("Preço", f"{price if price is not None else '—'} {info.get('currency') or ''}".strip()))
    if change is not None:
        painted = fmt.green(f"+{change}%") if float(change) >= 0 else fmt.red(f"{change}%")
        print(fmt.field("Variação", painted))
    for label, key in (("Máximo dia", "day_high"), ("Mínimo dia", "day_low"), ("Volume", "volume"), ("Bolsa", "exchange")):
        if info.get(key) is not None:
            print(fmt.field(label, info.get(key)))
    return 0


def cmd_market_news(args: argparse.Namespace, client: Client) -> int:
    result = client.get(f"/tickers/{args.ticker.upper()}/news", params={"max_items": args.size}, timeout=120)
    emit(args, result)
    if is_json(args):
        return 0
    items = result.get("items") or result.get("news") or []
    print(fmt.title(f"Notícias de {args.ticker.upper()}"), fmt.dim(f"{len(items)} itens"))
    for item in items:
        published = fmt.short_date(item.get("published") or item.get("providerPublishTime"), with_time=True)
        print(f"\n{fmt.bold(fmt.truncate(item.get('title'), 90))}")
        print(fmt.dim(f"  {published} · {item.get('publisher') or item.get('provider') or '—'}"))
        if item.get("summary"):
            print(f"  {fmt.truncate(item['summary'], 130)}")
    return 0


def cmd_forecast(args: argparse.Namespace, client: Client) -> int:
    result = client.post(
        "/forecast",
        payload={
            "ticker": args.ticker.upper(),
            "days": args.days,
            "model": args.model,
            "period": args.period,
            "include_sentiment": args.sentiment,
        },
        timeout=600,
    )
    emit(args, result)
    if is_json(args):
        return 0
    print(fmt.title(f"Previsão {args.ticker.upper()}"), fmt.dim(f"modelo {args.model} · {args.days} dias"))
    predictions = result.get("predictions") or result.get("forecast") or []
    if predictions:
        print(
            fmt.table(
                ["#", "data", "valor"],
                [
                    [str(index + 1), row.get("date") or row.get("ds") or "—", f"{row.get('value', row.get('yhat', '—'))}"]
                    for index, row in enumerate(predictions)
                ],
            )
        )
    metrics = result.get("metrics") or {}
    for key in ("mae", "rmse", "mape"):
        if metrics.get(key) is not None:
            print(fmt.field(key.upper(), fmt.number(metrics[key]) if isinstance(metrics[key], int) else metrics[key]))
    return 0


# --------------------------------------------------------------------- chat
def cmd_chat(args: argparse.Namespace, client: Client) -> int:
    result = client.post(
        "/chat",
        payload={"messages": [{"role": "user", "content": args.prompt}], "backend": args.backend},
        timeout=600,
    )
    emit(args, result)
    if is_json(args):
        return 0
    message = result.get("message") or {}
    print(message.get("content") if isinstance(message, dict) else message)
    tools = result.get("tools") or []
    if tools:
        print(fmt.dim(f"\nferramentas: {', '.join(str(t.get('name', t)) for t in tools)}"))
    return 0


# -------------------------------------------------------------------- users
def cmd_users_list(args: argparse.Namespace, client: Client) -> int:
    require_session(client)
    stats = client.stats()
    emit(args, stats)
    if is_json(args):
        return 0
    print(fmt.title("Contas"), fmt.dim(f"{fmt.number(stats.get('users'))} registadas · {fmt.number(stats.get('active_sessions'))} sessões ativas"))
    users = stats.get("users_list") or []
    if users:
        print(
            fmt.table(
                ["nome", "email", "perfil", "logins", "último login"],
                [
                    [
                        fmt.truncate(user.get("name"), 26),
                        fmt.truncate(user.get("email"), 34),
                        user.get("role"),
                        fmt.number(user.get("login_count")),
                        fmt.short_date(user.get("last_login_at"), with_time=True),
                    ]
                    for user in users
                ],
            )
        )
    return 0


# -------------------------------------------------------------- utilitários
def cmd_search(args: argparse.Namespace, client: Client) -> int:
    result = client.get("/elastic/search/global", params={"query": args.query, "size": args.size}, timeout=180)
    emit(args, result)
    if is_json(args):
        return 0
    print(fmt.title(f"Pesquisa global: {args.query}"))
    groups = result.get("results") or result.get("groups") or result
    if isinstance(groups, dict):
        for name, items in groups.items():
            if not isinstance(items, list) or not items:
                continue
            print(f"\n{fmt.bold(name)} ({len(items)})")
            for item in items[: args.size]:
                label = item.get("title") or item.get("name") or item.get("objectoContrato") or item.get("ticker")
                print(f"  · {fmt.truncate(label, 96)}")
    else:
        print(json.dumps(result, ensure_ascii=False, indent=2)[:4000])
    return 0


def cmd_open(args: argparse.Namespace, client: Client) -> int:
    paths = {
        "chat": "/chat",
        "dashboard": "/dashboard",
        "empresas-iq": "/empresas-iq",
        "contracts": "/contracts/search",
        "companies": "/entities/search",
        "markets": "/tickers",
        "forecast": "/forecast",
        "settings": "/settings",
    }
    view = args.view or "dashboard"
    url = f"{client.base_url}{paths.get(view, '/' + view)}"
    emit(args, {"url": url})
    if not is_json(args):
        print(fmt.ok(f"A abrir {url}"))
    if not args.print_only:
        webbrowser.open(url)
    return 0


def cmd_config(args: argparse.Namespace, client: Client) -> int:
    data = cli_config.load_config()
    redacted = {**data, "token": ("…" + data["token"][-8:]) if data.get("token") else None}
    emit(args, redacted)
    if not is_json(args):
        print(fmt.field("Ficheiro", str(cli_config.config_path())))
        print(fmt.field("API", client.base_url))
        print(fmt.field("Token", redacted.get("token") or fmt.dim("—")))
        print(fmt.field("Email", data.get("email") or fmt.dim("—")))
    return 0


# ------------------------------------------------------------------ parser
def global_flags() -> argparse.ArgumentParser:
    """Opções aceites em qualquer posição (antes ou depois do comando).

    O `default=SUPPRESS` evita que o subparser apague um valor já lido pelo
    parser principal quando a opção aparece antes do subcomando.
    """
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--api", default=argparse.SUPPRESS, help="URL da API (por omissão usa a configuração guardada)")
    parser.add_argument("--token", default=argparse.SUPPRESS, help="Token de sessão a usar nesta execução")
    parser.add_argument(
        "--json",
        dest="json_output",
        action="store_true",
        default=argparse.SUPPRESS,
        help="Saída em JSON",
    )
    parser.add_argument(
        "--no-color",
        action="store_true",
        default=argparse.SUPPRESS,
        help="Desativa cores",
    )
    return parser


GLOBAL_FLAGS = global_flags()


def add_command(container: Any, name: str, **kwargs: Any) -> argparse.ArgumentParser:
    """Cria um subcomando que também aceita as opções globais."""
    return container.add_parser(name, parents=[GLOBAL_FLAGS], **kwargs)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="iq-os",
        description="CLI do IQ OS: contratos públicos, empresas, mercados, previsões e contas.",
        epilog="Exemplo: python -m cli contracts search \"obras\" --year 2025 --size 5",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        parents=[GLOBAL_FLAGS],
    )
    parser.add_argument("--version", action="version", version=f"IQ OS CLI {__version__}")

    sub = parser.add_subparsers(dest="command", metavar="<comando>")

    # status ---------------------------------------------------------------
    p = add_command(sub, "status", help="Estado da API, Elasticsearch e sessão")
    p.set_defaults(handler=cmd_status)

    # auth -----------------------------------------------------------------
    auth = add_command(sub, "auth", help="Contas: login, registo, sessões")
    auth_sub = auth.add_subparsers(dest="action", metavar="<ação>")

    p = add_command(auth_sub, "login", help="Iniciar sessão")
    p.add_argument("email")
    p.add_argument("--password", help="Palavra-passe (omitir para pedir de forma segura)")
    p.add_argument("--remember", action="store_true", help="Sessão de 30 dias")
    p.set_defaults(handler=cmd_auth_login)

    p = add_command(auth_sub, "register", help="Criar conta")
    p.add_argument("name")
    p.add_argument("email")
    p.add_argument("--password", help="Palavra-passe (omitir para pedir de forma segura)")
    p.add_argument("--title", help="Cargo")
    p.add_argument("--organization", help="Organização")
    p.set_defaults(handler=cmd_auth_register)

    p = add_command(auth_sub, "whoami", help="Dados da conta autenticada")
    p.set_defaults(handler=cmd_auth_whoami)

    p = add_command(auth_sub, "logout", help="Terminar a sessão atual")
    p.set_defaults(handler=cmd_auth_logout)

    p = add_command(auth_sub, "sessions", help="Listar (ou terminar) sessões ativas")
    p.add_argument("--revoke-others", action="store_true", help="Terminar todas as outras sessões")
    p.set_defaults(handler=cmd_auth_sessions)

    p = add_command(auth_sub, "password", help="Alterar a palavra-passe")
    p.add_argument("--current", help="Palavra-passe atual")
    p.add_argument("--new", help="Nova palavra-passe")
    p.set_defaults(handler=cmd_auth_password)

    p = add_command(auth_sub, "profile", help="Atualizar perfil e preferências")
    p.add_argument("--name")
    p.add_argument("--title")
    p.add_argument("--organization")
    p.add_argument("--phone")
    p.add_argument("--locale")
    p.add_argument("--timezone")
    p.add_argument("--default-view", dest="default_view")
    p.add_argument("--dock-position", dest="dock_position", choices=["bottom", "left", "right"])
    p.add_argument("--sidebar-hidden", dest="sidebar_hidden", type=lambda v: v.lower() in ("1", "true", "sim", "yes"))
    p.add_argument("--reduced-motion", dest="reduced_motion", type=lambda v: v.lower() in ("1", "true", "sim", "yes"))
    p.set_defaults(handler=cmd_auth_profile)

    # contracts ------------------------------------------------------------
    contracts = add_command(sub, "contracts", help="Contratos públicos")
    contracts_sub = contracts.add_subparsers(dest="action", metavar="<ação>")

    p = add_command(contracts_sub, "search", help="Pesquisar contratos")
    p.add_argument("query", nargs="?", help="Texto livre (objeto, entidade, CPV…)")
    p.add_argument("--year", type=int)
    p.add_argument("--nif", help="NIF do adjudicante ou adjudicatário")
    p.add_argument("--region", help="Região NUTS")
    p.add_argument("--cpv", help="Código CPV")
    p.add_argument("--min-price", dest="min_price", type=float)
    p.add_argument("--max-price", dest="max_price", type=float)
    p.add_argument("--start-date", dest="start_date")
    p.add_argument("--end-date", dest="end_date")
    p.add_argument("--size", type=int, default=10)
    p.add_argument("--offset", type=int, default=0)
    p.add_argument("--sort", default="dataPublicacao")
    p.add_argument("--order", default="desc", choices=["asc", "desc"])
    p.set_defaults(handler=cmd_contracts_search)

    p = add_command(contracts_sub, "get", help="Ficha de um contrato")
    p.add_argument("idcontrato")
    p.set_defaults(handler=cmd_contracts_get)

    p = add_command(contracts_sub, "analytics", help="Indicadores agregados")
    p.add_argument("--top-entities", dest="top_entities", type=int, default=8)
    p.add_argument("--top-cpv", dest="top_cpv", type=int, default=8)
    p.add_argument("--year", type=int)
    p.set_defaults(handler=cmd_contracts_analytics)

    # companies ------------------------------------------------------------
    companies = add_command(sub, "companies", help="Empresas e entidades nos contratos")
    companies_sub = companies.add_subparsers(dest="action", metavar="<ação>")

    p = add_command(companies_sub, "search", help="Pesquisar entidades")
    p.add_argument("query", nargs="?")
    p.add_argument("--role", choices=["all", "adjudicante", "adjudicatario"], default="all")
    p.add_argument("--region")
    p.add_argument("--min-contracts", dest="min_contracts", type=int, default=1)
    p.add_argument("--year", type=int)
    p.add_argument("--size", type=int, default=10)
    p.set_defaults(handler=cmd_companies_search)

    p = add_command(companies_sub, "get", help="Ficha da empresa")
    p.add_argument("nif")
    p.set_defaults(handler=cmd_companies_get)

    p = add_command(companies_sub, "contracts", help="Contratos de uma empresa")
    p.add_argument("nif")
    p.add_argument("--role", choices=["all", "adjudicante", "adjudicatario"], default="all")
    p.add_argument("--size", type=int, default=10)
    p.set_defaults(handler=cmd_companies_contracts)

    p = add_command(companies_sub, "trademarks", help="Marcas INPI")
    p.add_argument("nif")
    p.add_argument("--size", type=int, default=10)
    p.set_defaults(handler=cmd_companies_trademarks)

    p = add_command(companies_sub, "firmas", help="Firmas RNPC")
    p.add_argument("nif")
    p.add_argument("--size", type=int, default=10)
    p.set_defaults(handler=cmd_companies_firmas)

    # entities -------------------------------------------------------------
    entities = add_command(sub, "entities", help="Cadastro de entidades")
    entities_sub = entities.add_subparsers(dest="action", metavar="<ação>")

    p = add_command(entities_sub, "search", help="Pesquisar no cadastro")
    p.add_argument("query", nargs="?")
    p.add_argument("--country")
    p.add_argument("--only-with-nif", dest="only_with_nif", action="store_true")
    p.add_argument("--min-contracts", dest="min_contracts", type=int)
    p.add_argument("--role", choices=["all", "adjudicante", "adjudicatario"], default="all")
    p.add_argument("--sort", default="total_value")
    p.add_argument("--size", type=int, default=10)
    p.set_defaults(handler=cmd_entities_search)

    p = add_command(entities_sub, "get", help="Ficha da entidade")
    p.add_argument("nif")
    p.set_defaults(handler=cmd_entities_get)

    p = add_command(entities_sub, "stats", help="Estatísticas do cadastro")
    p.set_defaults(handler=cmd_entities_stats)

    # market ---------------------------------------------------------------
    market = add_command(sub, "market", help="Mercados: tickers, cotações e notícias")
    market_sub = market.add_subparsers(dest="action", metavar="<ação>")

    p = add_command(market_sub, "tickers", help="Listar/procurar tickers")
    p.add_argument("query", nargs="?")
    p.add_argument("--size", type=int, default=20)
    p.set_defaults(handler=cmd_market_tickers)

    p = add_command(market_sub, "quote", help="Cotação de um ticker")
    p.add_argument("ticker")
    p.set_defaults(handler=cmd_market_quote)

    p = add_command(market_sub, "news", help="Notícias de um ticker")
    p.add_argument("ticker")
    p.add_argument("--size", type=int, default=8)
    p.set_defaults(handler=cmd_market_news)

    # forecast / chat / users / search / open / config ---------------------
    p = add_command(sub, "forecast", help="Previsão de preços")
    p.add_argument("ticker")
    p.add_argument("--days", type=int, default=5)
    p.add_argument("--model", default="arima", choices=["arima", "kronos"])
    p.add_argument("--period", default="5y")
    p.add_argument("--sentiment", action="store_true", help="Incluir sentimento das notícias")
    p.set_defaults(handler=cmd_forecast)

    p = add_command(sub, "chat", help="Perguntar ao assistente")
    p.add_argument("prompt")
    p.add_argument("--backend", default="gpt2", choices=["gpt2", "mistral"])
    p.set_defaults(handler=cmd_chat)

    p = add_command(sub, "users", help="Administração de contas")
    users_sub = p.add_subparsers(dest="action", metavar="<ação>")
    p2 = add_command(users_sub, "list", help="Listar contas e sessões ativas")
    p2.set_defaults(handler=cmd_users_list)

    p = add_command(sub, "search", help="Pesquisa global no Elasticsearch")
    p.add_argument("query")
    p.add_argument("--size", type=int, default=5)
    p.set_defaults(handler=cmd_search)

    p = add_command(sub, "open", help="Abrir a plataforma no browser")
    p.add_argument("view", nargs="?", help="dashboard, chat, empresas-iq, contracts, companies, markets, settings…")
    p.add_argument("--print-only", dest="print_only", action="store_true", help="Só mostrar o URL")
    p.set_defaults(handler=cmd_open)

    p = add_command(sub, "config", help="Mostrar a configuração do CLI")
    p.set_defaults(handler=cmd_config)

    return parser


def _configure_stdio() -> None:
    """Evita quebras de codificação na consola do Windows (cp1252/cp850).

    Mantém a codificação nativa (para os acentos saírem corretos no terminal do
    utilizador) mas troca caracteres impossíveis por `?` em vez de rebentar, e
    avisa o formatador para usar símbolos ASCII quando necessário.
    """
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(errors="replace")  # type: ignore[attr-defined]
        except (AttributeError, ValueError, OSError):
            continue

    encoding = getattr(sys.stdout, "encoding", None) or "utf-8"
    try:
        "─✔·€…".encode(encoding, errors="strict")
        fmt.configure_unicode(True)
    except (LookupError, UnicodeEncodeError):
        fmt.configure_unicode(False)


def main(argv: Optional[List[str]] = None) -> int:
    _configure_stdio()
    parser = build_parser()
    args = parser.parse_args(argv)

    if getattr(args, "no_color", False):
        fmt.configure(False)

    handler: Optional[Callable[[argparse.Namespace, Client], int]] = getattr(args, "handler", None)
    if handler is None:
        # Sem subcomando: mostra o estado (comando mais útil por omissão).
        if args.command is None:
            return cmd_status(args, build_client(args))
        parser.print_help()
        return 2

    client = build_client(args)
    try:
        return handler(args, client)
    except ApiError as error:
        if is_json(args):
            print(json.dumps({"error": error.message, "status": error.status, "code": error.code}, ensure_ascii=False))
        else:
            print(fmt.fail(error.message), file=sys.stderr)
            if error.code == "no_session":
                print(fmt.dim("  → python -m cli auth login <email>"), file=sys.stderr)
            if error.code == "connection":
                print(fmt.dim("  → verifique se o backend está a correr (python -m cli status)"), file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print(fmt.warn("Interrompido."), file=sys.stderr)
        return 130
