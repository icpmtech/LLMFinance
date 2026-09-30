import httpx, re
from bs4 import BeautifulSoup
from urllib.parse import urljoin

url = "https://www.parlamento.pt/deputadogp/paginas/deputados.aspx"
s = httpx.Client(timeout=30, follow_redirects=True)

resp = s.get(url)
soup = BeautifulSoup(resp.text, "html.parser")

rows = soup.select(".row.margin_h0.margin-Top-15")
print("page 1 rows", len(rows))

# Extract viewstate etc.
def get_field(name):
    tag = soup.find("input", {"name": name})
    return tag.get("value", "") if tag else ""

vs = get_field("__VIEWSTATE")
ev = get_field("__EVENTVALIDATION")
gi = get_field("__VIEWSTATEGENERATOR")

# Find next > link target
target = None
for a in soup.find_all("a", href=True):
    if "__doPostBack" in a["href"] and (">" in a.get_text() or "Próx" in a.get_text() or "next" in a.get("title","").lower()):
        m = re.search(r"__doPostBack\('([^']+)'", a["href"])
        if m:
            target = m.group(1)
            print("next target", target)

if target:
    data = {
        "__VIEWSTATE": vs,
        "__VIEWSTATEGENERATOR": gi,
        "__EVENTVALIDATION": ev,
        "__EVENTTARGET": target,
        "__EVENTARGUMENT": "",
    }
    # Need include other possible input fields? Typically only these required for DataPager.
    resp2 = s.post(url, data=data)
    print("page 2 status", resp2.status_code, "len", len(resp2.text))
    soup2 = BeautifulSoup(resp2.text, "html.parser")
    rows2 = soup2.select(".row.margin_h0.margin-Top-15")
    print("page 2 rows", len(rows2))
    for row in rows2[:3]:
        a = row.find("a", href=True)
        if a:
            print("   ", a.get_text(strip=True), a["href"])
