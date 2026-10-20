# -*- coding: utf-8 -*-
import json, pathlib, collections
from api.transparencia_geo import resolver_local, _fold, ALIASES
p = pathlib.Path("data/entidade-transparencia/_normalized/declaracoes.jsonl")
locais = collections.Counter()
for line in p.open(encoding="utf-8"):
    d = json.loads(line)
    for it in (d.get("interesses") or []):
        t = it.get("tipo") or ""
        v = it.get("valores") or {}
        if "Atividades" in t or "Filia" in t:
            locais[(v.get("Local da sede") or "").strip()] += 1
        elif t == "Sociedades":
            locais[(v.get("Coluna col3") or "").strip()] += 1
total = sum(locais.values()); ok = 0; fail = []
for local, c in locais.items():
    if resolver_local(local): ok += c
    else: fail.append((c, local))
fail.sort(reverse=True)
out = {"total": total, "ok": ok, "pct": round(ok/total*100, 1), "falhas": fail[:20]}
pathlib.Path("_tmp_geo_report.json").write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
print(json.dumps({"total": total, "ok": ok, "pct": out["pct"]}))