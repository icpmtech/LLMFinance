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
divs = bs.select("div.col-xs-12")
for i, div in enumerate(divs):
    print(i, "attrs=", div.attrs, "len=", len(div.get_text(' ', strip=True)))

print("\n--- parents of TextoRegular-Titulo (bio) ---")
for t in bs.select("div.TextoRegular-Titulo"):
    label = t.get_text(strip=True)
    if label in ("Nome completo", "Data de nascimento", "Profissão"):
        p = t.parent
        print(label, "parent:", p.name, p.attrs)
        gp = p.parent
        print("   grandparent:", gp.name, gp.attrs)

print("\n--- xpath-ish: div containing 'Nome completo' ---")
for t in bs.select("div.TextoRegular-Titulo"):
    if t.get_text(strip=True) == "Nome completo":
        col = t.parent
        for up in range(4):
            print("  up", up, col.name, col.attrs, len(col.get_text(' ', strip=True)))
            col = col.parent
