import requests, re
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")
s = requests.Session()
s.headers.update({"User-Agent": UA, "Accept-Language": "pt-PT,pt;q=0.9"})
urls = [
    "https://www.racius.com/empresas-em-portugal/porto/matosinhos/",
    "https://www.racius.com/empresas-em-portugal/porto/vila-nova-de-gaia/",
    "https://www.racius.com/empresas-em-portugal/porto/maia/",
    "https://www.racius.com/empresas-em-portugal/porto/gondomar/",
    "https://www.racius.com/empresas-em-portugal/porto/amarante/",
    "https://www.racius.com/empresas-em-portugal/porto/valongo/",
    "https://www.racius.com/empresas-em-portugal/porto/santo-tirso/",
    "https://www.racius.com/empresas-em-portugal/porto/paredes/",
    "https://www.racius.com/empresas-em-portugal/porto/vila-do-conde/",
    "https://www.racius.com/empresas-em-portugal/porto/povoa-de-varzim/",
    "https://www.racius.com/empresas-em-portugal/porto/felgueiras/",
    "https://www.racius.com/empresas-em-portugal/porto/penafiel/",
    "https://www.racius.com/empresas-em-portugal/porto/marco-de-canaveses/",
    "https://www.racius.com/empresas-em-portugal/porto/trofa/",
    "https://www.racius.com/empresas-em-portugal/porto/pacos-de-ferreira/",
    "https://www.racius.com/empresas-em-portugal/porto/lousada/",
    "https://www.racius.com/empresas-em-portugal/porto/baiao/",
]
for u in urls:
    r = s.get(u, timeout=40)
    links = re.findall(r'href="(/[^"]+/)" class="results__col-link"', r.text)
    print(u, len(set(links)))
    # guarda o HTML para inspecionar localizacao
    open(r'C:\LLMFinance\_tmp_conc_' + u.split('/')[-2] + '.html', 'w', encoding='utf-8').write(r.text)
