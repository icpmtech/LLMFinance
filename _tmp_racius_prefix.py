import requests, re
from bs4 import BeautifulSoup
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")
s = requests.Session()
s.headers.update({"User-Agent": UA, "Accept-Language": "pt-PT,pt;q=0.9"})
for q in ["ab", "1", "galp"]:
    r = s.get(f"https://www.racius.com/empresas-em-portugal/distrito-porto/?q={q}", timeout=40)
    soup = BeautifulSoup(r.text, "lxml")
    nomes = [p.get_text(" ", strip=True) for p in soup.select("p.results__name")][:6]
    total = soup.select_one(".results__found")
    print(q, '|', total.get_text(' ', strip=True) if total else '-', '|', nomes)
