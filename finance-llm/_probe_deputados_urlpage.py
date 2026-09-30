import httpx
from bs4 import BeautifulSoup

url = "https://www.parlamento.pt/deputadogp/paginas/deputados.aspx"
s = httpx.Client(timeout=30, follow_redirects=True, headers={"User-Agent": "Mozilla/5.0"})

first_names = []
for qs in ["", "?page=2", "?Page=2", "?p=2", "?pagina=2", "?BID=&PageIndex=2"]:
    r = s.get(url + qs)
    soup = BeautifulSoup(r.text, "html.parser")
    rows = soup.select(".row.margin_h0.margin-Top-15")
    fn = [row.find("a", href=True).get_text(strip=True) for row in rows[:3] if row.find("a", href=True)]
    print(repr(qs), r.status_code, len(rows), fn)
