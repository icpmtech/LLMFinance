"""Teste rápido do enriquecimento OSINT (ficheiro temporário)."""
import json
import sys

import httpx

sys.path.insert(0, "c:/LLMFinance/finance-llm")
from api import auth_service

BASE = "http://127.0.0.1:8002"
user = auth_service.get_user_by_email("teste@teste.com")
headers = {"Authorization": "Bearer " + auth_service.create_session(user)["token"]}


def line(label, value):
    print(f"{label:<24} {value}")


with httpx.Client(timeout=300, headers=headers) as c:
    r = c.post(BASE + "/osint/scan", json={
        "target": "kaifcodec", "kind": "username", "category": "dev", "save": True,
    })
    d = r.json()
    line("scan", f"{r.status_code} found={d['found']}/{d['total']} cat={d['category']}")

    print("\n--- perfis encontrados ---")
    for h in [x for x in d["hits"] if x["status"] == "Found"]:
        p = h.get("profile") or {}
        metrics = ", ".join(f"{k}={v}" for k, v in (p.get("metrics") or {}).items())
        line(f"  {h['site_name']}",
             f"nome={p.get('display_name')!r} avatar={'sim' if p.get('avatar') else '-'} "
             f"conf={h.get('confidence')}")
        if p.get("bio"):
            print(f"      bio: {p['bio'][:90]}")
        if metrics:
            print(f"      {metrics}")
        if p.get("links"):
            print(f"      links: {p['links'][:3]}")
        if (h.get("leads") or {}).get("emails"):
            print(f"      EMAILS: {h['leads']['emails']}")

    print("\n--- contas cruzadas (pivots) ---")
    for p in d.get("pivots", []):
        line(f"  {p.get('site')}", f"{p.get('kind')} via {p.get('source_site')}/{p.get('source_key')} "
                                  f"handle={p.get('handle')} url={p.get('url') or '-'}")

    line("\nstats", json.dumps(d.get("stats"), ensure_ascii=False))

    g = d["graph"]
    line("grafo", f"nodes={len(g['nodes'])} edges={len(g['edges'])} "
                  f"grupos={sorted({n['group'] for n in g['nodes']})}")

    doc_id = d["saved_id"]
    detail = c.get(BASE + "/osint/saved/" + doc_id.replace(":", "%3A")).json()
    line("detalhe guardado", f"found={detail.get('found')} pivots={len(detail.get('pivots') or [])} "
                            f"names={detail.get('names')} emails={detail.get('emails')}")

    for fmt in ("json", "csv", "pdf"):
        rep = c.get(BASE + f"/osint/report/{doc_id.replace(':', '%3A')}?format={fmt}")
        ctype = (rep.headers.get("content-type") or "").split(";")[0]
        line(f"relatorio {fmt}", f"{rep.status_code} {len(rep.content)} bytes {ctype}")
