import sys
sys.path.insert(0, r"c:\LLMFinance\finance-llm")
from api import scraper_service
src = {
    "name": "Iberinform regex repro",
    "url": "https://www.iberinform.pt/diretorio/evora/alandroal/pagina/1",
    "enabled": False,
    "fetcher": "http",
    "list": {"selector": "table.table-hover.tabla-directorio-geografico tbody tr", "type": "css"},
    "fields": [
        {"name": "url", "selector": "a::attr(href)", "type": "css", "max_length": 1024},
        {"name": "nif", "selector": "a::attr(href)", "type": "css", "regex": r"/empresa/(\d+)/", "max_length": 20},
    ],
    "pagination": {"selector": "a[aria-label='Next']", "type": "css", "attr": "href", "max_pages": 1},
}
res = scraper_service.preview_source(src, limit=3, max_pages=1)
for it in res['items']:
    print(it['data'])
