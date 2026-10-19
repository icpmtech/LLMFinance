import requests, re, time
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")
s = requests.Session()
s.headers.update({"User-Agent": UA, "Accept-Language": "pt-PT,pt;q=0.9"})
for u in [
    "https://www.racius.com/empresas-em-portugal/porto/matosinhos/",
    "https://www.racius.com/empresas-em-portugal/porto/vila-nova-de-gaia/?page=200",
    "https://www.racius.com/empresas-em-portugal/porto/matosinhos/?page=200",
    "https://www.racius.com/empresas-em-portugal/porto/matosinhos/?sort=id",
    "https://www.racius.com/empresas-em-portugal/porto/matosinhos/?sort=-id",
]:
    r = s.get(u, timeout=60)
    m = re.search(r'\u003cstrong\u003e([\d\s]+)\u003c/strong\u003e\s*resultados', r.text)
    n = len(re.findall(r'class="results__col-link"', r.text))
    first = re.search(r'href="([^"]+)" class="results__col-link"', r.text)
    print(f"{r.status_code} total={m.group(1).strip() if m else '-':>9} links={n:2} first={first.group(1) if first else '-':40} | {u}")
    time.sleep(0.7)
