import httpx, re
from bs4 import BeautifulSoup
from urllib.parse import urljoin

base = "https://www.parlamento.pt"
for bid in [7489, 5993]:
    bio = f"/DeputadoGP/Paginas/Biografia.aspx?BID={bid}"
    resp = httpx.get(urljoin(base, bio), timeout=30)
    soup = BeautifulSoup(resp.text, "html.parser")
    print("\n=== BID", bid, "===")
    for tag in soup.find_all("span", string=re.compile(r"^(Nome completo|Data de nascimento|Habilitações literárias|Profissão|Partido|Círculo eleitoral|Mandato|Naturalidade|Telefone|E-mail)$")):
        print("\nSPAN label", repr(tag.get_text(strip=True)))
        # climb a few levels
        for up in [1,2,3,4,5]:
            parent = tag
            for _ in range(up):
                parent = parent.find_parent()
            print(" up", up, parent.name, parent.get("class"), "text=", parent.get_text(" | ", strip=True)[:300])
