from api import municipio_pessoas_service as m
import re
from bs4 import BeautifulSoup
from urllib.parse import urljoin
html = m._fetch_html('https://www.cm-porto.pt/executivo')
soup = BeautifulSoup(html, 'html.parser')
content = soup.select('.content.col-md-4')[0]
links = content.find_all('a', href=re.compile(r'executivo/'))
print('links count:', len(links))
link = links[0]
style = link.get('style') or ''
print('style repr:', repr(style))
pattern = r'background-image\s*:\s*url\(\"?([^\"\)]+)\"?\)'
m = re.search(pattern, style)
print('match:', m.group(1) if m else None)
