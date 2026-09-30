import time
import httpx
from bs4 import BeautifulSoup

base = "https://www.parlamento.pt"
s = httpx.Client(timeout=60, follow_redirects=True, headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"})


def get(url, tries=4):
    last = None
    for i in range(tries):
        try:
            return s.get(url)
        except Exception as exc:
            last = exc
            time.sleep(2 + i * 2)
    raise last


b = get(base + "/DeputadoGP/Paginas/Biografia.aspx?BID=7489")
bs = BeautifulSoup(b.text, "html.parser")

# encontrar o span do label e subir mostrando ids/classes
target = None
for sp in bs.find_all("span"):
    if sp.get_text(strip=True) == "Nome completo":
        target = sp
        break
print("target found:", bool(target))
node = target
for up in range(10):
    node = node.parent
    if node is None:
        break
    print(up + 1, node.name, node.attrs)
    txt = node.get_text(" ", strip=True)
    print("    len", len(txt), repr(txt[:120]))
