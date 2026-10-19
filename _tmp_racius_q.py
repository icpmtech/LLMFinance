import requests, re, time
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")
s = requests.Session()
s.headers.update({"User-Agent": UA, "Accept-Language": "pt-PT,pt;q=0.9"})

def total(url):
    r = s.get(url, timeout=40, allow_redirects=True)
    m = re.search(r'<strong>([\d\s]+)</strong>\s*resultados', r.text)
    n = len(re.findall(r'class="results__col-link"', r.text))
    return r.status_code, (m.group(1).strip() if m else '-'), n

urls = [
    "https://www.racius.com/empresas-em-portugal/porto/porto/?q=a",
    "https://www.racius.com/empresas-em-portugal/porto/porto/?q=ab",
    "https://www.racius.com/empresas-em-portugal/porto/porto/?q=aba",
    "https://www.racius.com/empresas-em-portugal/porto/porto/?q=b",
    "https://www.racius.com/empresas-em-portugal/porto/matosinhos/",
    "https://www.racius.com/empresas-em-portugal/porto/vila-nova-de-gaia/",
    "https://www.racius.com/empresas-em-portugal/porto/gaia/",
    "https://www.racius.com/empresas-em-portugal/porto/amarante/",
]
for u in urls:
    print(f"{total(u)} | {u}")
    time.sleep(0.8)
