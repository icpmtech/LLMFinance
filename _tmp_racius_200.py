import requests, re, time
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")
s = requests.Session()
s.headers.update({"User-Agent": UA, "Accept-Language": "pt-PT,pt;q=0.9"})
urls = [
    "https://www.racius.com/empresas-em-portugal/distrito-porto/?p=200",
    "https://www.racius.com/empresas-em-portugal/distrito-porto/?page=1&p=200",
    "https://www.racius.com/empresas-em-portugal/distrito-porto/?page=201",
    "https://www.racius.com/empresas-em-portugal/distrito-porto/?page=210",
]
for u in urls:
    r = s.get(u, timeout=60, allow_redirects=False)
    n = len(re.findall(r'class="results__col-link"', r.text))
    first = re.search(r'href="([^"]+)" class="results__col-link"', r.text)
    print(u, r.status_code, "loc=", r.headers.get("Location"), "links=", n, "first=", first.group(1) if first else None)
    time.sleep(1)
