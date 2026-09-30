import httpx, re
from bs4 import BeautifulSoup
from urllib.parse import urljoin

base = "https://www.parlamento.pt"
bio = "/DeputadoGP/Paginas/Biografia.aspx?BID=7489"
resp = httpx.get(urljoin(base, bio), timeout=30)
print("status", resp.status_code, "len", len(resp.text))

soup = BeautifulSoup(resp.text, "html.parser")
# título
print("TITLE", soup.title.get_text(strip=True) if soup.title else None)
# procurar foto
for img in soup.find_all("img", src=re.compile(r"getimage|fotos?")):
    print("IMG", img.get("src"), img.get("alt"))

# conteúdo biográfico
for sel in ["#ctl00_ctl51_g_b68c74dc_b0c2_4f55_89e7_c66d3495fd00", "div#Biografia", "div.ms-rtestate-field", "article", "#contentBox"]:
    el = soup.select_one(sel)
    if el:
        print("SEL", sel, el.get_text("\n", strip=True)[:800])
        break

# tudo o que contenha "Naturalidade" ou "Nascimento" ou "NIF"
text = soup.get_text("\n", strip=True)
for kw in ["Naturalidade", "Nascimento", "NIF", "Profissão", "Partido", "Mandato", "E-mail", "Telefone"]:
    idx = text.find(kw)
    if idx != -1:
        print("KW", kw, text[idx:idx+200])
