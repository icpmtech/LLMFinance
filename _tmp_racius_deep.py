import requests, time, re
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")
s = requests.Session()
s.headers.update({"User-Agent": UA, "Accept-Language": "pt-PT,pt;q=0.9"})
base = "https://www.racius.com/empresas-em-portugal/distrito-porto/?page={}"
for p in (120, 150, 180, 200, 220, 250, 300, 400):
    r = s.get(base.format(p), timeout=40, allow_redirects=False)
    loc = r.headers.get("Location")
    first = re.search(r'href="([^"]+)" class="results__col-link"', r.text)
    n = len(re.findall(r'class="results__col-link"', r.text))
    print(p, r.status_code, "loc=", loc, "links=", n, "first=", first.group(1) if first else None)
    time.sleep(0.8)
