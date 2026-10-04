"""Inspecionar HTML da página de deputados para opções de paginação."""
from scrapling.fetchers import Fetcher
import re
url='https://www.parlamento.pt/deputadogp/paginas/deputados.aspx'
resp=Fetcher.get(url, stealthy_headers=True, timeout=120, http_version=1, retries=3)
html=getattr(resp,'text','')
print('len', len(html))
# procurar form e hidden fields
for m in re.finditer(r'<input[^>]*name="(__[^"]+)"[^>]*value="([^"]*)"', html):
    print(m.group(1), m.group(2)[:80])
print('--- postbacks ---')
for m in re.finditer(r'__doPostBack\([^)]*\)', html):
    print(m.group(0))
print('--- page size options? ---')
for m in re.finditer(r'(?i)(pagesize|page size|tamanho|resultados por p[áa]gina|ddl)', html):
    start=max(0,m.start()-100)
    end=min(len(html),m.end()+100)
    print(html[start:end].replace('\n',' '))
