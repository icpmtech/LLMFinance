import re, time
import httpx
from bs4 import BeautifulSoup

base = "https://www.parlamento.pt"
s = httpx.Client(timeout=60, follow_redirects=True, headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"})


def get(url, tries=4):
    last = None
    for i in range(tries):
        try:
            return s.get(url)
        except Exception as exc:  # noqa: BLE001
            last = exc
            time.sleep(2 + i * 2)
    raise last


r = get(base + "/deputadogp/paginas/deputados.aspx")
soup = BeautifulSoup(r.text, "html.parser")
row = soup.select(".row.margin_h0.margin-Top-15")[0]
print("=== ROW HTML ===")
print(row.prettify()[:2500])

print("\n=== BIO: div.col-xs-12 ===")
b = get(base + "/DeputadoGP/Paginas/Biografia.aspx?BID=7489")
bs = BeautifulSoup(b.text, "html.parser")
for i, div in enumerate(bs.select("div.col-xs-12")):
    txt = div.get_text(" ", strip=True)
    print(i, len(txt), repr(txt[:140]))
