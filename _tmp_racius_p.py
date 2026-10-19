import requests, re, time
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")
s = requests.Session()
s.headers.update({"User-Agent": UA, "Accept-Language": "pt-PT,pt;q=0.9"})
for url in [
    "https://www.racius.com/empresas-em-portugal/distrito-porto/?page=500&p=200",
    "https://www.racius.com/empresas-em-portugal/distrito-porto/?p=200",
    "https://www.racius.com/empresas-em-portugal/distrito-porto/?page=2&p=200",
    "https://www.racius.com/empresas-em-portugal/distrito-porto/?page=100&p=100",
]:
    r = s.get(url, timeout=60)
    n = len(re.findall(r'class="results__col-link"', r.text))
    first = re.search(r'href="([^"]+)" class="results__col-link"', r.text)
    print(url, r.status_code, "links=", n, "first=", first.group(1) if first else None, "final=", r.url)
    time.sleep(1)
