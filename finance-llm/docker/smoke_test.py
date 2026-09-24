#!/usr/bin/env python3
"""Smoke test dos endpoints da API IQ OS (corre bem dentro de Docker).

Uso::

    python docker/smoke_test.py --base-url http://backend:8000
    python docker/smoke_test.py --base-url http://127.0.0.1:8003 --ui-url http://127.0.0.1:4180
    python docker/smoke_test.py --json logs/smoke_test.json

Fases
-----
1. **Núcleo** — `/health`, `/`, `/openapi.json`, `/openapi/summary` e `/docs` têm de responder 2xx.
2. **Descoberta** — percorre o `/openapi.json` e chama *todos* os `GET` sem parâmetros de
   caminho. Classificação:

   * `2xx`               → **OK**
   * `400/401/403/422`   → **GUARDADO** (rota viva: falta token ou parâmetros)
   * `404`               → **AVISO** (rota declarada mas não encontrada)
   * `5xx` / exceção     → **FALHA**

3. **UI** (opcional, `--ui-url`) — a SPA tem de responder 200 em `/` e numa rota interna
   (`/empresas-iq`), com o `index.html` do Vite.

Credenciais (opcionais): `IQOS_API_TOKEN`, ou `IQOS_API_EMAIL` + `IQOS_API_PASSWORD`
(as mesmas variáveis do servidor MCP). Sem elas, as rotas guardadas contam como GUARDADO.

Saída: relatório no stdout (e JSON opcional) e código de saída 1 se houver FALHAS.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from typing import Any, Dict, List, Optional, Tuple

import requests

# Rotas que não devem ser chamadas às cegas: streaming, recolhas e exportações.
SKIP_SUBSTRINGS = (
    "/chat/stream",
    "/stream",
    "/collect",
    "/ingest",
    "/run",
    "/export",
    "/reindex",
    "/reprocess",
    "/delete",
    "/logout",
)

# Endpoints do núcleo: se um destes falhar, a solução não está de pé.
CORE_ENDPOINTS: Tuple[Tuple[str, str, Tuple[int, ...]], ...] = (
    ("/health", "estado do serviço (modelos e features)", (200,)),
    ("/", "raiz da API", (200,)),
    ("/openapi.json", "especificação OpenAPI", (200,)),
    ("/openapi/summary", "resumo do catálogo OpenAPI", (200,)),
    ("/openapi/export", "exportação da especificação", (200,)),
    ("/docs", "Swagger UI", (200,)),
)

OK_STATUSES = range(200, 300)
GUARDED_STATUSES = {400, 401, 403, 422}

# Rotas que devolvem o `index.html` da SPA quando o build existe **no backend**
# (`spa_index_response`). Em Docker o build é servido pelo nginx (serviço
# `frontend`) e o backend não o tem — 404 é o resultado esperado, não um erro.
SPA_PAGE_PATHS = {
    "/companies",
    "/companies/search",
    "/companies/dashboard",
    "/entities/dashboard",
    "/entities/adjudicantes",
    "/entities/adjudicatarios",
    "/entities/compare",
    "/adjudicantes",
    "/adjudicatarios",
    "/forecast",
    "/trading",
    "/ticker-detail",
    "/rag",
    "/elastic",
    "/contracts",
    "/contracts/dashboard",
    "/contracts/search",
    "/contracts/map",
    "/empresas-iq",
    "/crm",
    "/crm/contas",
    "/crm/contactos",
    "/crm/agenda",
    "/crm/relatorios",
    "/scraper",
    "/scraper/fontes",
    "/scraper/modelos",
    "/scraper/execucoes",
    "/scraper/pesquisa",
    "/scraper/agenda",
    "/pesquisa",
    "/sentimento",
    "/empresas-global",
    "/search360",
    "/search360/dossie",
    "/search360/projetos",
    "/search360/grafo",
    "/search360/biblioteca",
    "/hermes",
    "/office",
    "/office/documentos",
    "/office/dossies",
    "/search",
    "/import",
    "/cire",
}

# Endpoints que só respondem depressa depois de "aquecer": o RAG carrega o
# modelo de embeddings na primeira chamada (~85 s num container novo) e sem
# isto o teste falhava com ReadTimeout de 60 s.
COLD_START_PATHS = {"/rag/documents"}


class Report:
    """Acumula resultados e devolve um resumo legível."""

    def __init__(self) -> None:
        self.rows: List[Dict[str, Any]] = []

    def add(self, phase: str, method: str, path: str, outcome: str, status: Optional[int],
            ms: float, detail: str = "") -> None:
        self.rows.append(
            {
                "phase": phase,
                "method": method,
                "path": path,
                "outcome": outcome,
                "status": status,
                "ms": round(ms, 1),
                "detail": detail,
            }
        )

    def count(self, outcome: str) -> int:
        return sum(1 for r in self.rows if r["outcome"] == outcome)

    def failures(self) -> List[Dict[str, Any]]:
        return [r for r in self.rows if r["outcome"] == "FALHA"]

    def warnings(self) -> List[Dict[str, Any]]:
        return [r for r in self.rows if r["outcome"] == "AVISO"]

    def print_summary(self, max_detail: int = 25) -> None:
        print()
        print("=" * 78)
        print("SMOKE TEST IQ OS — RESUMO")
        print("=" * 78)
        print(f"  OK ............ {self.count('OK')}")
        print(f"  SPA ........... {self.count('SPA')}  (página da SPA: servida pelo nginx)")
        print(f"  GUARDADO ...... {self.count('GUARDADO')}")
        print(f"  AVISO ......... {self.count('AVISO')}")
        print(f"  FALHA ......... {self.count('FALHA')}")
        print(f"  (total: {len(self.rows)} pedidos)")

        for title, rows, marker in (
            ("FALHAS", self.failures(), "✗"),
            ("AVISOS", self.warnings(), "!"),
        ):
            if not rows:
                continue
            print()
            print(f"{title} ({len(rows)}):")
            for row in rows[:max_detail]:
                detail = f" — {row['detail']}" if row["detail"] else ""
                print(f"  {marker} {row['method']} {row['path']} -> {row['status']}{detail}")
            if len(rows) > max_detail:
                print(f"  ... e mais {len(rows) - max_detail}")

        slowest = sorted(self.rows, key=lambda r: r["ms"], reverse=True)[:5]
        if slowest:
            print()
            print("Mais lentos:")
            for row in slowest:
                print(f"  {row['ms']:>8.0f} ms  {row['method']} {row['path']} -> {row['status']}")

    def to_json(self) -> Dict[str, Any]:
        return {
            "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "totals": {
                "ok": self.count("OK"),
                "spa_page": self.count("SPA"),
                "guarded": self.count("GUARDADO"),
                "warning": self.count("AVISO"),
                "failure": self.count("FALHA"),
            },
            "results": self.rows,
        }


def login(base_url: str, timeout: float) -> Tuple[Optional[str], str]:
    """Devolve (token, motivo). Usa as variáveis de ambiente do servidor MCP."""
    token = os.getenv("IQOS_API_TOKEN") or os.getenv("FINANCE_API_TOKEN")
    if token:
        return token, "token de IQOS_API_TOKEN"

    email = os.getenv("IQOS_API_EMAIL")
    password = os.getenv("IQOS_API_PASSWORD")
    if not (email and password):
        return None, "sem credenciais (IQOS_API_TOKEN ou IQOS_API_EMAIL/IQOS_API_PASSWORD)"

    try:
        response = requests.post(
            f"{base_url}/auth/login",
            json={"email": email, "password": password},
            timeout=timeout,
        )
        if response.status_code // 100 == 2:
            data = response.json()
            token = data.get("token") or (data.get("user") or {}).get("token")
            if token:
                return token, f"login de {email}"
        return None, f"login de {email} falhou (HTTP {response.status_code})"
    except Exception as error:  # pragma: no cover - depende da rede
        return None, f"login de {email} rebentou: {error}"


def call(session: requests.Session, method: str, url: str, timeout: float,
         **kwargs: Any) -> Tuple[Optional[int], str, float]:
    """Executa um pedido e devolve (status, detalhe, ms). status None = exceção."""
    started = time.perf_counter()
    try:
        response = session.request(method, url, timeout=timeout, **kwargs)
        ms = (time.perf_counter() - started) * 1000
        detail = ""
        if response.status_code >= 400:
            detail = (response.text or "").strip().replace("\n", " ")[:160]
        return response.status_code, detail, ms
    except Exception as error:
        ms = (time.perf_counter() - started) * 1000
        return None, f"{type(error).__name__}: {error}"[:200], ms


def discover_get_paths(spec: Dict[str, Any]) -> List[str]:
    """Todos os caminhos GET sem parâmetros de caminho (`{...}`)."""
    paths: List[str] = []
    for path, methods in (spec.get("paths") or {}).items():
        if "get" not in (methods or {}):
            continue
        if "{" in path:
            continue
        if any(skip in path for skip in SKIP_SUBSTRINGS):
            continue
        paths.append(path)
    return sorted(set(paths))


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Smoke test dos endpoints do IQ OS.")
    parser.add_argument("--base-url", default=os.getenv("IQOS_API_URL", "http://127.0.0.1:8003"))
    parser.add_argument("--ui-url", default=os.getenv("IQOS_UI_URL", ""),
                        help="URL do frontend (nginx) para validar a SPA. Vazio = saltar.")
    parser.add_argument("--timeout", type=float, default=180.0)
    parser.add_argument("--ui-timeout", type=float, default=20.0)
    parser.add_argument("--json", dest="json_path", default="", help="Guardar relatório JSON.")
    parser.add_argument("--no-discovery", action="store_true", help="Só o núcleo (rápido).")
    args = parser.parse_args(argv)

    base_url = args.base_url.rstrip("/")
    report = Report()
    session = requests.Session()

    token, reason = login(base_url, args.timeout)
    print(f"Alvo: {base_url}")
    print(f"Autenticação: {reason}")
    if token:
        session.headers["Authorization"] = f"Bearer {token}"

    # ---------------------------------------------------------------- fase 1
    print()
    print("Fase 1 — núcleo")
    for path, label, expected in CORE_ENDPOINTS:
        status, detail, ms = call(session, "GET", base_url + path, args.timeout)
        if status is not None and status in expected:
            outcome = "OK"
        elif status is not None and status in GUARDED_STATUSES:
            outcome = "GUARDADO"
        elif status is None:
            outcome = "FALHA"
        else:
            outcome = "FALHA"
        report.add("core", "GET", path, outcome, status, ms, detail or label)
        mark = {"OK": "ok  ", "GUARDADO": "auth", "AVISO": "warn", "FALHA": "FAIL"}[outcome]
        print(f"  [{mark}] {status} {ms:7.0f} ms  {path:<22} {label}")

    # ---------------------------------------------------------------- fase 2
    if not args.no_discovery:
        print()
        print("Fase 2 — descoberta de GET sem parâmetros (via OpenAPI)")
        spec_status, spec_detail, spec_ms = call(session, "GET", base_url + "/openapi.json", args.timeout)
        if spec_status != 200:
            report.add("discovery", "GET", "/openapi.json", "FALHA", spec_status, spec_ms, spec_detail)
            print(f"  [FAIL] {spec_status} — não foi possível ler a especificação")
        else:
            try:
                spec = json.loads(requests.get(base_url + "/openapi.json", timeout=args.timeout).text)
            except Exception as error:
                spec = {}
                print(f"  [FAIL] especificação inválida: {error}")
            paths = discover_get_paths(spec)
            print(f"  {len(spec.get('paths') or {})} rotas na especificação; {len(paths)} GET sem parâmetros a testar")
            for path in paths:
                status, detail, ms = call(session, "GET", base_url + path, args.timeout)
                if status is not None and status in OK_STATUSES:
                    outcome = "OK"
                elif status in GUARDED_STATUSES:
                    outcome = "GUARDADO"
                elif status == 404:
                    outcome = "SPA" if path in SPA_PAGE_PATHS else "AVISO"
                else:
                    outcome = "FALHA"
                report.add("discovery", "GET", path, outcome, status, ms, detail)
                if outcome != "OK":
                    print(f"  [{outcome}] {status} {path}")
                elif path in COLD_START_PATHS or ms > 5000:
                    print(f"  [ok  ] {status} {path} — {ms / 1000:.1f} s (arranque frio)" if ms > 5000
                          else f"  [ok  ] {status} {path}")
            print(f"  OK: {report.count('OK')} · SPA: {report.count('SPA')} · guardado: {report.count('GUARDADO')} · "
                  f"aviso: {report.count('AVISO')} · falha: {report.count('FALHA')}")

    # ---------------------------------------------------------------- fase 3
    if args.ui_url:
        ui_url = args.ui_url.rstrip("/")
        print()
        print(f"Fase 3 — frontend ({ui_url})")
        for path, label in (("/", "index da SPA"), ("/empresas-iq", "rota interna da SPA")):
            status, detail, ms = call(session, "GET", ui_url + path, args.ui_timeout)
            body = ""
            if status == 200:
                try:
                    body = session.get(ui_url + path, timeout=args.ui_timeout).text
                except Exception:
                    body = ""
            expected_html = ("<div id=\"root\">" in body) or ("<html" in body.lower())
            outcome = "OK" if (status == 200 and expected_html) else "FALHA"
            if status == 200 and not expected_html:
                detail = "resposta 200 sem HTML da SPA"
            report.add("ui", "GET", path, outcome, status, ms, detail or label)
            mark = "ok  " if outcome == "OK" else "FAIL"
            print(f"  [{mark}] {status} {ms:7.0f} ms  {path:<14} {label}")

    # ---------------------------------------------------------------- resumo
    report.print_summary()

    if args.json_path:
        try:
            with open(args.json_path, "w", encoding="utf-8") as handle:
                json.dump(report.to_json(), handle, ensure_ascii=False, indent=2)
            print(f"\nRelatório guardado em {args.json_path}")
        except Exception as error:
            print(f"\nNão foi possível guardar o relatório: {error}")

    failed = len(report.failures())
    print()
    print("RESULTADO: " + ("OK" if failed == 0 else f"{failed} FALHA(S)"))
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
