import httpx, re
from bs4 import BeautifulSoup

url = "https://www.parlamento.pt/deputadogp/paginas/deputados.aspx"
resp = httpx.get(url, timeout=30, follow_redirects=True)
soup = BeautifulSoup(resp.text, "html.parser")

# paginação
pager = soup.find("div", {"id": re.compile("Pagination", re.I)})
print("pager", pager and pager.get_text(strip=True)[:200])
links = soup.find_all("a", href=re.compile(r"Page\$|deputados\.aspx"))
print("pagination links", len(links))
for a in links:
    print(repr(a.get_text(strip=True)), a.get("href"))

# viewstate / eventvalidation
for name in ["__VIEWSTATE", "__EVENTVALIDATION", "__EVENTTARGET", "__EVENTARGUMENT"]:
    tag = soup.find("input", {"name": name})
    print(name, bool(tag), tag and tag.get("value", "")[:40])

# tabela total
print("total rows found", len(soup.select(".row.margin_h0.margin-Top-15")))
