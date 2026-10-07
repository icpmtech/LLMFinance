"""Verificação da «Pesquisa profunda» no que está **servido**.

Valida pelo **conteúdo**, não pelo código HTTP: a SPA responde 200 a tudo
(`@app.get("/{full_path:path}")`), por isso um 200 pode ser o `index.html`.

Uso:
    python logs/_qa_pesquisa_profunda.py                      (8002 + 4180)
    QA_BACKEND=http://127.0.0.1:8011 python logs/_qa_pesquisa_profunda.py
"""
from __future__ import annotations

import json
import os
import sys

import httpx

BACKEND = os.environ.get("QA_BACKEND", "http://127.0.0.1:8002").rstrip("/")
FRONTEND = os.environ.get("QA_FRONTEND", "http://127.0.0.1:4180").rstrip("/")
HEADERS: dict = {}  # as rotas de leitura não exigem sessão

FALHAS: list[str] = []


def check(nome: str, ok: bool, detalhe: str = "") -> None:
    print(f"  {'OK ' if ok else 'FALHA'} {nome}{(' — ' + detalhe) if detalhe else ''}")
    if not ok:
        FALHAS.append(nome)


def json_de(url: str, *, post: dict | None = None) -> tuple[int, dict | None, str]:
    """Devolve (estado, json, corpo) e marca falha se não for JSON."""
    try:
        resposta = httpx.post(url, json=post, headers=HEADERS, timeout=120) if post is not None else httpx.get(url, headers=HEADERS, timeout=120)
    except Exception as erro:  # noqa: BLE001
        return 0, None, f"{type(erro).__name__}: {erro}"
    texto = resposta.text or ""
    try:
        return resposta.status_code, json.loads(texto), texto
    except Exception:  # noqa: BLE001
        return resposta.status_code, None, texto


print(f"\n== backend {BACKEND} ==")
estado, meta, corpo = json_de(f"{BACKEND}/deep-search/meta")
if meta is None:
    check("/deep-search/meta devolve JSON", False, f"estado {estado}: {corpo[:120]!r}")
else:
    check("/deep-search/meta devolve JSON", True)
    check("tem exemplos", bool(meta.get("examples")), str(len(meta.get("examples") or [])))
    limites = meta.get("limits") or {}
    check("limites.unlimited == 0", limites.get("unlimited") == 0, str(limites.get("unlimited")))
    check("limites.citable_max", bool(limites.get("citable_max")), str(limites.get("citable_max")))
    # `max_sources` é um objeto com default/min/max (não um número).
    max_sources = limites.get("max_sources") or {}
    check("limites.max_sources.max >= 120", (max_sources.get("max") or 0) >= 120, str(max_sources.get("max")))
    por_ambito = limites.get("per_source") or {}
    check("limites.per_source.max == 50", (por_ambito.get("max") or 0) == 50, str(por_ambito.get("max")))
    ambitos = meta.get("sources") or []
    check(f"{len(ambitos)} âmbitos servidos", len(ambitos) >= 15)
    modos = [m.get("id") for m in (meta.get("modes") or [])]
    check("modos hybrid/text/vector", set(modos) >= {"hybrid", "text", "vector"}, str(modos))

estado, sug, corpo = json_de(f"{BACKEND}/deep-search/suggest?q=CLARAN&limit=5")
if sug is None:
    check("/deep-search/suggest devolve JSON", False, f"estado {estado}: {corpo[:120]!r}")
else:
    itens = sug.get("items") or []
    check("/deep-search/suggest devolve JSON", True)
    check("sugestões para 'CLARAN'", bool(itens), str([i.get("text") for i in itens[:3]]))

estado, busca, corpo = json_de(f"{BACKEND}/deep-search/search?q=CLARANET%20II%20SOLUTIONS%20quanto%20contratos%3F&mode=hybrid&max_sources=40")
if busca is None:
    check("/deep-search/search devolve JSON", False, f"estado {estado}: {corpo[:120]!r}")
else:
    check("/deep-search/search devolve JSON", True)
    fontes = busca.get("sources") or []
    check("recupera fontes", len(fontes) > 0, f"{len(fontes)} fontes")
    check("modo híbrido reportado", busca.get("mode") == "hybrid", str(busca.get("mode")))
    check("consulta BM25 sem interrogativas", "quanto" not in (busca.get("text_query") or "").lower(), repr(busca.get("text_query")))
    check("tem perguntas de seguimento", bool(busca.get("suggestions")), str((busca.get("suggestions") or [])[:1]))
    nomes = [s.get("scope") for s in fontes]
    print(f"     âmbitos: contracts={nomes.count('contracts')} entities={nomes.count('entities')} outros={len(nomes) - nomes.count('contracts') - nomes.count('entities')}")

estado, semlim, corpo = json_de(f"{BACKEND}/deep-search/search?q=contratos%20de%20saude&max_sources=0&per_source=50")
if semlim is None:
    check("max_sources=0 devolve JSON", False, f"estado {estado}: {corpo[:120]!r}")
else:
    check("max_sources=0 devolve JSON", True)
    total = len(semlim.get("sources") or [])
    check("«sem limite» traz muitas fontes", total > 12, f"{total} fontes")
    check("marcado como sem limite", bool(semlim.get("unlimited")), str(semlim.get("unlimited")))

print(f"\n== frontend {FRONTEND} ==")
try:
    pagina = httpx.get(f"{FRONTEND}/deep-search", timeout=60)
    corpo = pagina.text or ""
    check("/deep-search serve a SPA", "<div id=\"root\"" in corpo or "<script" in corpo, f"{len(corpo)} bytes")
    cabecalhos = {k.lower(): v for k, v in pagina.headers.items()}
    print(f"     cache-control: {cabecalhos.get('cache-control')!r}")
except Exception as erro:  # noqa: BLE001
    check("/deep-search serve a SPA", False, f"{type(erro).__name__}: {erro}")

print()
if FALHAS:
    print(f"{len(FALHAS)} VERIFICAÇÕES FALHARAM: {', '.join(FALHAS)}")
    sys.exit(1)
print("tudo verificado")
