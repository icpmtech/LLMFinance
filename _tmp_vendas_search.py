import sys, re, time
sys.path.insert(0, r"C:\LLMFinance\finance-llm")
import requests
from collectors import tls_chain

URL = "https://www.citius.mj.pt/portal/consultas/ConsultasVenda.aspx"
s = requests.Session()
s.headers.update({
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/129.0.0.0 Safari/537.36",
    "Accept-Language": "pt-PT,pt;q=0.9,en;q=0.8",
})
verify = True
resp = None
for attempt in range(5):
    try:
        resp = s.get(URL, timeout=60, verify=verify)
        break
    except requests.exceptions.SSLError:
        with tls_chain._lock:
            tls_chain._cache.clear()
        verify = tls_chain.verify_for(URL, proxy=None)
        time.sleep(2)

def val(html, name):
    m = re.search(r'id="' + re.escape(name) + r'"[^>]*value="([^"]*)"', html)
    return m.group(1) if m else ""

html = resp.content.decode("utf-8", errors="replace")
base = "ctl00$ContentPlaceHolder1$"
state0 = {n: val(html, n) for n in ("__VIEWSTATE","__VIEWSTATEGENERATOR","__EVENTVALIDATION")}

def search(label, tribunal="2871017", desde="21-09-2026", ate="21-12-2026", chk=False, tipo="0", modal="0", estado="0", state=None):
    st = state or state0
    data = dict(st)
    data.update({
        "__EVENTTARGET": "", "__EVENTARGUMENT": "", "__LASTFOCUS": "", "__VIEWSTATEENCRYPTED": "",
        "__ASYNCPOST": "true",
        "ctl00$ContentPlaceHolder1$ScriptManager1": "ctl00$ContentPlaceHolder1$ScriptManager1|" + base + "btnSearch",
        base+"ddlTribunais": tribunal,
        base+"txtCalendarDesde": desde,
        base+"txtCalendarAte": ate,
        base+"ddlTiposBem": tipo,
        base+"ddlModalidades": modal,
        base+"ddlEstados": estado,
        base+"btnSearch": "Pesquisar",
    })
    if chk:
        data[base+"chkDatas"] = "on"
    headers = {"X-MicrosoftAjax": "Delta=true", "X-Requested-With": "XMLHttpRequest",
               "Cache-Control": "no-cache", "Referer": URL, "Origin": "https://www.citius.mj.pt"}
    r2 = s.post(URL, data=data, timeout=180, verify=verify, headers=headers)
    text = r2.content.decode("utf-8", errors="replace")
    m = re.search(r'updatePanel\|ctl00_ContentPlaceHolder1_pnlUpdResults\|(.*?)\|0\|hiddenField', text, re.S)
    inner = m.group(1) if m else ""
    open(r"C:\LLMFinance\_tmp_vendas_%s.txt" % label, "w", encoding="utf-8").write(text)
    print("====", label, r2.status_code, "panel", len(inner))
    cnt = re.search(r"Numero de Registos:\s*(\d+)", inner)
    print("COUNT", cnt.group(1) if cnt else None)
    return text, inner

text, inner = search("lisboa_wide")
print(inner[:8000])
