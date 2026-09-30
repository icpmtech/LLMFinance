import httpx, re
from bs4 import BeautifulSoup
from urllib.parse import urljoin

base = "https://www.parlamento.pt"
s = httpx.Client(timeout=30, follow_redirects=True, headers={"User-Agent": "Mozilla/5.0"})

r = s.get(base + "/deputadogp/paginas/deputados.aspx")
soup = BeautifulSoup(r.text, "html.parser")
row = soup.select(".row.margin_h0.margin-Top-15")[0]
print("=== ROW HTML ===")
print(row.prettify()[:3000])

print("\n=== BIO: div.col-xs-12 ===")
b = s.get(base + "/DeputadoGP/Paginas/Biografia.aspx?BID=7489")
bs = BeautifulSoup(b.text, "html.parser")
for i, div in enumerate(bs.select("div.col-xs-12")):
    txt = div.get_text(" ", strip=True)
    print(i, len(txt), repr(txt[:160]))
