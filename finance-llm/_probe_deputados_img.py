import httpx, re
from bs4 import BeautifulSoup
from urllib.parse import urljoin

base = "https://www.parlamento.pt"
bid = 7489
resp = httpx.get(urljoin(base, f"/DeputadoGP/Paginas/Biografia.aspx?BID={bid}"), timeout=30)
soup = BeautifulSoup(resp.text, "html.parser")

print("--- todas as imagens")
for img in soup.find_all("img"):
    print(repr(img.get("src")), repr(img.get("alt")), repr(img.get("class")))

print("--- links de email")
for a in soup.find_all("a", href=re.compile(r"mailto|email", re.I)):
    print(repr(a.get_text(strip=True)), a["href"])
for a in soup.find_all("a", href=True):
    if "mailto" in a["href"].lower():
        print("MAILTO", a["href"])

print("--- links com 'Email' no texto")
for a in soup.find_all(["a", "input"], href=True):
    if "mail" in a.get_text(strip=True).lower() or "mail" in (a.get("title") or "").lower():
        print(repr(a.get_text(strip=True)), a["href"])

print("--- onmouseover / data-* com imagem")
for tag in soup.find_all(attrs={"onmouseover": True}):
    print(tag.get("onmouseover")[:200])

print("--- elementos com getimage no html")
for m in re.finditer(r"[^\"']*getimage[^\"']*", resp.text):
    print(m.group(0))
