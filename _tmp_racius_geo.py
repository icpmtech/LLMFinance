import io, time
import requests
from bs4 import BeautifulSoup

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")
urls = [
    "https://www.racius.com/clivita-saude-e-vida-natural-lda/",
    "https://www.racius.com/serracao-alcoa-lda/",
    "https://www.racius.com/auto-radiadores-ninho-de-oeiras-lda/",
    "https://www.racius.com/transportes-guilherme-baptista-carvalho-limitada/",
]
s = requests.Session()
s.headers.update({"User-Agent": UA, "Accept-Language": "pt-PT,pt;q=0.9"})
for u in urls:
    html = s.get(u, timeout=40).text
    soup = BeautifulSoup(html, "lxml")
    lines = []
    for li in soup.select("li.detail__detail"):
        keys = [p.get_text(" ", strip=True) for p in li.select("p.detail__key-info")]
        vals = [p.get_text(" ", strip=True) for p in li.select("p.t--d-blue")]
        if keys and keys[0] == "Morada":
            lines.append(list(zip(keys, vals)))
    print(u)
    for group in lines:
        print("   ", group)
    time.sleep(1.5)
