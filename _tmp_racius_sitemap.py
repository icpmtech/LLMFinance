import requests, re
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")
s = requests.Session()
s.headers.update({"User-Agent": UA, "Accept-Language": "pt-PT,pt;q=0.9"})
for u in ["https://www.racius.com/sitemap.xml", "https://www.racius.com/robots.txt"]:
    r = s.get(u, timeout=40)
    print('==', u, r.status_code, len(r.text))
    print(r.text[:1200])
