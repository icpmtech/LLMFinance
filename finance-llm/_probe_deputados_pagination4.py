import httpx, re
from bs4 import BeautifulSoup
from urllib.parse import urljoin

url = "https://www.parlamento.pt/deputadogp/paginas/deputados.aspx"
s = httpx.Client(timeout=30, follow_redirects=True, headers={"User-Agent":"Mozilla/5.0"})

resp = s.get(url)
soup = BeautifulSoup(resp.text, "html.parser")

# all pagination targets
for a in soup.find_all("a", href=True):
    if "__doPostBack" in a["href"]:
        m = re.search(r"__doPostBack\('([^']+)'", a["href"])
        if m:
            txt = a.get_text(strip=True)
            cls = " ".join(a.get("class", []))
            print(repr(txt), m.group(1), cls)
