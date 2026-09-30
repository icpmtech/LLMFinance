import httpx
from bs4 import BeautifulSoup

url = "https://www.parlamento.pt/deputadogp/paginas/deputados.aspx"
resp = httpx.get(url, timeout=30, follow_redirects=True)
print("status", resp.status_code, "len", len(resp.text))

soup = BeautifulSoup(resp.text, "html.parser")
rows = soup.select(".row.margin_h0.margin-Top-15")
print("rows", len(rows))
for i, row in enumerate(rows[:5]):
    print("--- row", i)
    links = row.find_all("a", href=True)
    for a in links:
        print("LINK", repr(a.get_text(strip=True)), a["href"])
    spans = row.find_all("span")
    for s in spans:
        print("SPAN", repr(s.get_text(strip=True)))
