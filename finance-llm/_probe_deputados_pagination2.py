import httpx, re
from bs4 import BeautifulSoup

url = "https://www.parlamento.pt/deputadogp/paginas/deputados.aspx"
resp = httpx.get(url, timeout=30, follow_redirects=True)
text = resp.text
soup = BeautifulSoup(text, "html.parser")

# Procurar todos os inputs type submit / image
btns = soup.find_all(["input", "a", "button"])
for b in btns:
    name = b.get("name") or b.get("id") or b.get_text(strip=True)
    val = b.get("value") or b.get("title") or b.get("alt") or ""
    if any(k in (name + " " + val).lower() for k in ["page", "next", "próx", ">", "$p"]):
        print("BTN", name, repr(val), b.get("href"), b.name)

# encontrar data pager
for tag in soup.find_all(id=re.compile(r"DataPager|Paging|Pager|Pagin", re.I)):
    print("PAGER ID", tag.get("id"), "text", tag.get_text(strip=True)[:200])

# procurar todos os __EVENTTARGET presentes no script do aspnet
print("--- eventtarget candidates in HTML")
for m in re.finditer(r'__doPostBack\("([^"]+)"', text):
    print(m.group(1))
