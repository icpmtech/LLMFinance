"""Testa o template do Parlamento com o motor de recolha (inclui postback)."""
import sys, json
sys.path.insert(0, ".")

from api import scraper_service as scraper
from api import scraper_templates as templates

entry = templates.get_template("parlamento-deputados")
source = templates.build_source("parlamento-deputados")
print("source:", json.dumps({k: v for k, v in source.items() if k in ("id", "url", "fetcher", "pagination", "id_fields", "title_field")}, ensure_ascii=False, indent=2))

stats = {}
total = 0
for page_number, page, items in scraper._walk_source(source, max_pages=3, stats=stats):
    total += len(items)
    print(f"page {page_number}: {len(items)} itens")
    for it in items[:2]:
        print("   ", it.get("title"), "|", it["data"].get("bid"), "|", it["data"].get("partido"), "|", it["data"].get("circulo"))
        print("    url:", it.get("url"))
        print("    texto:", (it.get("text") or "")[:160].replace("\n", " "))
print("TOTAL (3 páginas):", total)
print("stats:", stats)
