import requests, re, time
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")
s = requests.Session()
s.headers.update({"User-Agent": UA, "Accept-Language": "pt-PT,pt;q=0.9"})
urls = [
    "https://www.racius.com/empresas-em-portugal/distrito-porto/concelho-porto/",
    "https://www.racius.com/empresas-em-portugal/concelho-porto/",
    "https://www.racius.com/empresas-em-portugal/porto/porto/",
    "https://www.racius.com/empresas-em-portugal/distrito-porto/porto/",
    "https://www.racius.com/empresas-em-portugal/distrito-porto/?concelho=porto",
    "https://www.racius.com/empresas-em-portugal/distrito-porto/?q=padaria",
]
for u in urls:
    r = s.get(u, timeout=40, allow_redirects=False)
    txt = r.text
    found = re.search(r'<strong>([\d\s]+)</strong>\s*resultados', txt)
    n = len(re.findall(r'class="results__col-link"', txt))
    title = re.search(r'<title>([^<]*)</title>', txt)
    print(f"{r.status_code} links={n:2} total={found.group(1).strip() if found else '-':>9} | {u} | {title.group(1)[:60] if title else ''}")
    time.sleep(0.8)
