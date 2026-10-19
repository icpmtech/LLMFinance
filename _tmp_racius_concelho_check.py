import io, re, glob, json
from bs4 import BeautifulSoup
from collections import Counter

for path in glob.glob(r'C:\LLMFinance\_tmp_conc_*.html'):
    conc = path.split('_conc_')[-1].replace('.html','')
    h = io.open(path, encoding='utf-8').read()
    soup = BeautifulSoup(h, 'lxml')
    locs = []
    for link in soup.select('a.results__col-link'):
        local = link.select_one('div.results__col-location')
        locs.append(re.sub(r'^ico-[a-z-]+\s*', '', (local.get_text(' ', strip=True) if local else ''), flags=re.I))
    concs = Counter(locs)
    print(conc, concs.most_common(5))
