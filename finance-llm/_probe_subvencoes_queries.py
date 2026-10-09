"""Probe: valida pesquisa, resumo e fichas do modulo de subvencoes."""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from api import subvencoes_service as sub  # noqa: E402

OUT = ROOT / "_probe_subvencoes_queries.json"
relatorio = {}

# 1) resumo
r = sub.resumo()
relatorio["resumo"] = {
    "erro": r.get("error"),
    "kpis": r.get("kpis"),
    "por_ano": r.get("por_ano"),
    "top_entidades": (r.get("top_entidades") or [])[:5],
    "top_beneficiarios": (r.get("top_beneficiarios") or [])[:5],
    "por_tipo_beneficiario": r.get("por_tipo_beneficiario"),
    "meses": len(r.get("por_mes") or []),
    "primeiros_meses": (r.get("por_mes") or [])[:3],
}

# 2) pesquisa simples
s = sub.search(ano=2025, size=3)
relatorio["search_2025"] = {
    "erro": s.get("error"),
    "total": s.get("total"),
    "kpis": s.get("kpis", {}).get("montante"),
    "facets": {k: v[:4] for k, v in (s.get("facets") or {}).items()},
    "primeiro": (s.get("items") or [{}])[0],
}

# 3) pesquisa por NIF de beneficiario
nif = (s.get("items") or [{}])[0].get("nif_beneficiario")
relatorio["beneficiario"] = nif
relatorio["ficha_beneficiario"] = {
    k: v
    for k, v in (sub.por_beneficiario(nif or "500051054") or {}).items()
    if k not in ("items",)
}
relatorio["ficha_beneficiario"]["items"] = len((sub.por_beneficiario(nif or "500051054") or {}).get("items") or [])

# 4) pesquisa por NIF de entidade
relatorio["ficha_entidade"] = {
    k: v for k, v in (sub.por_entidade("500051054") or {}).items() if k not in ("items",)
}

# 5) pesquisa sem acentos (world_folding)
sem_acentos = sub.search(q="municipio de almada", size=2)
relatorio["sem_acentos"] = {"total": sem_acentos.get("total"), "erro": sem_acentos.get("error")}

# 6) filtro por montante
grandes = sub.search(montante_min=1000000, size=3, sort="montante")
relatorio["grandes"] = {
    "total": grandes.get("total"),
    "montante_total": grandes.get("kpis", {}).get("montante"),
    "top": [
        {"beneficiario": i.get("beneficiario"), "montante": i.get("montante"), "ano": i.get("ano")}
        for i in (grandes.get("items") or [])
    ],
}

# 7) pesquisa por texto na finalidade
texto = sub.search(q="teatro", size=2)
relatorio["texto_finalidade"] = {"total": texto.get("total"), "erro": texto.get("error")}

OUT.write_text(json.dumps(relatorio, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
print("escrito:", OUT)
print("resumo kpis:", relatorio["resumo"]["kpis"])
print("por ano:", [(a["ano"], a["registos"], a["montante"]) for a in relatorio["resumo"]["por_ano"]])
print("search 2025 total:", relatorio["search_2025"]["total"])
print("sem acentos:", relatorio["sem_acentos"])
print("grandes:", relatorio["grandes"]["total"], relatorio["grandes"]["montante_total"])
print("teatro:", relatorio["texto_finalidade"])
print("beneficiario nif:", relatorio["beneficiario"], relatorio["ficha_beneficiario"]["total"])
print("entidade 500051054:", relatorio["ficha_entidade"]["total"], relatorio["ficha_entidade"]["montante"])
