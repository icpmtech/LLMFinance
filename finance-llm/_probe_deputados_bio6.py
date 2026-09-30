import httpx, re
from bs4 import BeautifulSoup
from urllib.parse import urljoin

base = "https://www.parlamento.pt"
for bid in [7489, 5993]:
    bio = f"/DeputadoGP/Paginas/Biografia.aspx?BID={bid}"
    resp = httpx.get(urljoin(base, bio), timeout=30)
    soup = BeautifulSoup(resp.text, "html.parser")
    print("\n=== BID", bid, "===")
    # Todos os divs com classe TextoRegular-Titulo
    for div in soup.find_all("div", class_="TextoRegular-Titulo"):
        spans = div.find_all("span")
        if len(spans) >= 2:
            label = spans[0].get_text(strip=True)
            value = " | ".join(s.get_text(strip=True) for s in spans[1:])
            print(label, "=>", value[:200])
        else:
            print("TXT", div.get_text(" | ", strip=True)[:200])
    # imagem
    for img in soup.find_all("img"):
        src = img.get("src", "")
        if "getimage" in src.lower():
            print("IMG", urljoin(base, src))
