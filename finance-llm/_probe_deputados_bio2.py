import httpx, re
from bs4 import BeautifulSoup
from urllib.parse import urljoin

base = "https://www.parlamento.pt"
for bid in [7489, 5993, 6937]:
    bio = f"/DeputadoGP/Paginas/Biografia.aspx?BID={bid}"
    resp = httpx.get(urljoin(base, bio), timeout=30)
    soup = BeautifulSoup(resp.text, "html.parser")
    text = soup.get_text("\n", strip=True)
    print("\n=== BID", bid, "===")
    for kw in ["Nome", "Partido", "Naturalidade", "Nascimento", "NIF", "Profissão", "Circulo eleitoral", "Mandato", "Telefone", "E-mail"]:
        idx = text.find(kw)
        if idx != -1:
            print(kw + ":", text[idx:idx+240].replace("\n", " | "))
    # procurar imagem principal
    for img in soup.find_all("img"):
        src = img.get("src", "")
        if "getimage" in src.lower() or "fotos" in src.lower():
            print("IMG", urljoin(base, src))
