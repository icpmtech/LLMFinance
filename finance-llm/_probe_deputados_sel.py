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


for bid in (7489, 5993, 9194):
    b = get(base + f"/DeputadoGP/Paginas/Biografia.aspx?BID={bid}")
    bs = BeautifulSoup(b.text, "html.parser")
    print("=== BID", bid)
    cands = bs.select("div.ms-WPBody div.col-xs-12")
    print("  ms-WPBody .col-xs-12:", [(len(d.get_text(' ', strip=True)), d.get_text(' ', strip=True)[:50]) for d in cands])
    cands2 = bs.select("div.col-xs-12 > div.TextoRegular-Titulo")
    print("  col-xs-12 > Titulo:", len(cands2))
    for c in cands2:
        print("     parent len", len(c.parent.get_text(" ", strip=True)), c.get_text(strip=True))
        break
