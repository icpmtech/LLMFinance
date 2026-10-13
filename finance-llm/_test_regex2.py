from bs4 import BeautifulSoup
import httpx, re
from urllib.parse import urljoin
url='https://www.cm-porto.pt/executivo'
html=httpx.get(url, headers={'User-Agent':'IQOS/1.0'}, follow_redirects=True).text
soup=BeautifulSoup(html,'html.parser')
content=soup.select('.content.col-md-4')[0]
for link in content.find_all('a', href=re.compile(r'/executivo/')):
    print('href:', link.get('href'))
    style = link.get('style') or ''
    print('style:', style)
    m = re.search(r'background-image\s*:\s*url\(["\']?([^"\')]+)["\']?\)', style)
    print('match:', m.group(1) if m else None)
