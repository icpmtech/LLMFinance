import httpx, re
from bs4 import BeautifulSoup
from urllib.parse import urljoin

base = "https://www.parlamento.pt"
for bid in [7489, 5993]:
    bio = f"/DeputadoGP/Paginas/Biografia.aspx?BID={bid}"
    resp = httpx.get(urljoin(base, bio), timeout=30)
    soup = BeautifulSoup(resp.text, "html.parser")
    print("\n=== BID", bid, "===")
    # Procurar tabelas e divs que contenham as etiquetas
    for kw in ["Nome completo", "Data de nascimento", "Habilitações literárias", "Profissão"]:
        for tag in soup.find_all(string=re.compile(re.escape(kw))):
            print("KW", kw)
            parent = tag.find_parent()
            print("  parent", parent.name, parent.get("class"))
            # text around
            txt = parent.get_text(" | ", strip=True)
            print("  text", txt[:300])
            # próximo irmão
            nxt = parent.find_next_sibling()
            if nxt:
                print("  next", nxt.name, nxt.get_text(" | ", strip=True)[:200])
            print()
            break
