import sys
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
try:
    r = s.get(URL, timeout=60, verify=verify)
except requests.exceptions.SSLError as exc:
    bundle = tls_chain.verify_for(URL, proxy=None)
    print("TLS bundle:", bundle)
    verify = bundle
    r = s.get(URL, timeout=60, verify=verify)
print("STATUS", r.status_code, len(r.content), r.encoding)
html = r.content.decode("utf-8", errors="replace")
open(r"C:\LLMFinance\_tmp_vendas_page.html", "w", encoding="utf-8").write(html)
print(html[:1500])
