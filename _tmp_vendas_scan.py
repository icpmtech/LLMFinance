import sys, re, time, json
sys.path.insert(0, r"C:\LLMFinance\finance-llm")
import requests
from bs4 import BeautifulSoup
from collectors import tls_chain

URL = "https://www.citius.mj.pt/portal/consultas/ConsultasVenda.aspx"
s = requests.Session()
s.headers.update({"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/129.0.0.0 Safari/537.36", "Accept-Language": "pt-PT,pt;q=0.9,en;q=0.8"})
verify = True
for attempt in range(5):
    try:
        resp = s.get(URL, timeout=60, verify=verify); break
    except requests.exceptions.SSLError:
        with tls_chain._lock: tls_chain._cache.clear()
        verify = tls_chain.verify_for(URL, proxy=None); time.sleep(2)

def val(html, name):
    m = re.search(r'id="' + re.escape(name) + r'"[^>]*value="([^"]*)"', html)
    return m.group(1) if m else ""

html = resp.content.decode("utf-8", errors="replace")
soup = BeautifulSoup(html, "html.parser")
opts = [(o.get("value"), o.get_text(strip=True)) for o in soup.select("#ctl00_ContentPlaceHolder1_ddlTribunais option")]
print("tribunais:", len(opts))
base = "ctl00$ContentPlaceHolder1$"
state = {n: val(html, n) for n in ("__VIEWSTATE","__VIEWSTATEGENERATOR","__EVENTVALIDATION")}

def absorb(text):
    for name in ("__VIEWSTATE","__VIEWSTATEGENERATOR","__EVENTVALIDATION","__VIEWSTATEENCRYPTED"):
        m = re.search(r'hiddenField\|' + re.escape(name) + r'\|([^|]*)\|', text)
        if m and m.group(1): state[name] = m.group(1)

def search(tribunal, desde="21-09-2026", ate="21-12-2026", estado="0"):
    data = dict(state)
    data.update({"__EVENTTARGET": "", "__EVENTARGUMENT": "", "__LASTFOCUS": "", "__VIEWSTATEENCRYPTED": "", "__ASYNCPOST": "true",
        "ctl00$ContentPlaceHolder1$ScriptManager1": "ctl00$ContentPlaceHolder1$ScriptManager1|" + base + "btnSearch",
        base+"ddlTribunais": tribunal, base+"txtCalendarDesde": desde, base+"txtCalendarAte": ate,
        base+"ddlTiposBem": "0", base+"ddlModalidades": "0", base+"ddlEstados": estado, base+"btnSearch": "Pesquisar"})
    h = {"X-MicrosoftAjax": "Delta=true", "X-Requested-With": "XMLHttpRequest", "Cache-Control": "no-cache", "Referer": URL, "Origin": "https://www.citius.mj.pt"}
    r = s.post(URL, data=data, timeout=180, verify=verify, headers=h)
    text = r.content.decode("utf-8", errors="replace")
    absorb(text)
    m = re.search(r'updatePanel\|ctl00_ContentPlaceHolder1_pnlUpdResults\|(.*?)\|0\|hiddenField', text, re.S)
    return m.group(1) if m else "", text

found = []
for i, (value, label) in enumerate(opts[1:], 1):
    try:
        inner, text = search(value)
        m = re.search(r"Numero de Registos:\s*(\d+)", inner)
        n = int(m.group(1)) if m else 0
        if n:
            print(i, value, label, "->", n, flush=True)
            found.append({"value": value, "label": label, "count": n})
            if n > 10:
                open(r"C:\LLMFinance\_tmp_vendas_big.txt","w",encoding="utf-8").write(text)
                break
    except Exception as exc:
        print(i, label, "ERR", exc, flush=True)
    time.sleep(0.3)
print("TOTAL tribunais com registos:", len(found))
json.dump(found, open(r"C:\LLMFinance\_tmp_vendas_counts.json","w",encoding="utf-8"), ensure_ascii=False, indent=1)
