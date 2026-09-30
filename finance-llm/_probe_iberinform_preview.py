import json
import sys

sys.path.insert(0, r"c:\LLMFinance\finance-llm")

source = {
    "name": "Iberinform PT — Diretório por distrito/concelho",
    "description": "Empresas do diretório Iberinform.pt por distrito e concelho, com detalhe de ficha.",
    "url": "https://www.iberinform.pt/diretorio/evora/alandroal/pagina/1",
    "enabled": False,
    "fetcher": "http",
    "list": {"selector": "table.table-hover.tabla-directorio-geografico tbody tr", "type": "css"},
    "fields": [
        {"name": "nome", "label": "Nome", "selector": "a h3::text", "type": "css", "max_length": 400},
        {"name": "url", "label": "URL", "selector": "a::attr(href)", "type": "css", "max_length": 1024},
        {"name": "distrito", "label": "Distrito", "selector": "td.hidden-xs::text", "type": "css", "max_length": 120},
        {"name": "concelho", "label": "Concelho", "selector": "td:not(.hidden-xs)::text", "type": "css", "max_length": 120},
        {"name": "nif", "label": "NIF", "selector": "a::attr(href)", "type": "css", "regex": r"/empresa/(\d+)/", "max_length": 20},
    ],
    "pagination": {"selector": "a[aria-label='Next']", "type": "css", "attr": "href", "max_pages": 2},
    "detail": {"enabled": True, "selector": "section.section-company-data", "max_items": 3, "delay": 1.0, "max_chars": 8000},
    "options": {"impersonate": "chrome", "timeout": 30},
    "tags": ["empresas", "iberinform", "diretorio"],
    "id_fields": ["nif", "url"],
    "title_field": "nome",
    "summary_field": "nome",
}

from api import scraper_service

res = scraper_service.preview_source(source, limit=8, max_pages=1)
print(json.dumps(res, ensure_ascii=False, indent=2))
