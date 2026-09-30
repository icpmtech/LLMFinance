import httpx, re
from bs4 import BeautifulSoup
from urllib.parse import urljoin

base = "https://www.parlamento.pt"
for bid in [7489, 5993, 6937]:
    bio = f"/DeputadoGP/Paginas/Biografia.aspx?BID={bid}"
    resp = httpx.get(urljoin(base, bio), timeout=30)
    soup = BeautifulSoup(resp.text, "html.parser")
    print("\n=== BID", bid, "===")
    # extrair pares label:valor comuns na biografia
    labels = soup.find_all(text=re.compile(r"^(Nome completo|Data de nascimento|Habilitações literárias|Profissão|Partido|Círculo eleitoral|Mandato|Naturalidade|Telefone|E-mail|Grupo Parlamentar|Número de Cartão de Cidadão|NIF)$"))
    for label in labels:
        parent = label.parent
        # tentar próximo irmão
        nxt = parent.find_next_sibling()
        val = ""
        if nxt:
            val = nxt.get_text(" ", strip=True)
        print(repr(label.strip()), "=>", repr(val[:120]))

    # imagem
    for img in soup.find_all("img"):
        src = img.get("src", "")
        if "getimage" in src.lower() or "fotos" in src.lower():
            print("IMG", urljoin(base, src))
