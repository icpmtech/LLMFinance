"""Testa o template do Parlamento com o motor de recolha (inclui postback)."""
import sys, json
sys.path.insert(0, ".")

from api import scraper_service as scraper
from api import scraper_templates as templates

entry = templates.get_template("parlamento-deputados")
source = templates.build_source("parlamento-deputados")
print("source:", json.dumps({k: v for k, v in source.items() if k in ("id", "url", "fetcher", "pagination", "id_fields", "title_field")}, ensure_ascii=False, indent=2))

# http_version=2 força HTTP/1.1 no curl_cffi, evitando stalls com IPv6 do parlamento.pt
source["options"]["timeout"] = 30
source["options"]["http_version"] = 2
source["detail"]["enabled"] = True
source["detail"]["delay"] = 0.4
stats = {}
total = 0
for page_number, page, items in scraper._walk_source(source, max_pages=2, stats=stats):
    total += len(items)
    print(f"page {page_number}: {len(items)} itens")
    for it in items[:2]:
        print("   ", it.get("title"), "|", it["data"].get("bid"), "|", it["data"].get("partido"), "|", it["data"].get("circulo"))
        print("    url:", it.get("url"))
        print("    texto:", (it.get("text") or "")[:240].replace("\n", " "))
        # Mostrar detalhes biográficos específicos se existirem
        for key in ("biografia_data_nascimento", "biografia_habilitacoes", "biografia_profissao"):
            val = it["data"].get(key)
            if val:
                print(f"    {key}: {val}")
print("TOTAL (2 páginas):", total)
print("stats:", stats)
