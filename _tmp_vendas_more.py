import sys, re, time, json
sys.path.insert(0, r"C:\LLMFinance\finance-llm")
exec(open(r"C:\LLMFinance\_tmp_vendas_search.py", encoding="utf-8").read().split('text, inner = search("lisboa_wide")')[0])
h = {"Content-Type": "application/json; charset=utf-8", "X-Requested-With": "XMLHttpRequest", "Referer": URL, "Accept": "application/json, text/javascript, */*; q=0.01"}
for hid in ("9334362", 9334362):
    r3 = s.post(URL + "/GetHtmlDetails", data=json.dumps({"htmlId": hid}), headers=h, timeout=120, verify=verify)
    print("DETAIL", type(hid).__name__, r3.status_code, r3.headers.get("Content-Type"))
    print(r3.text[:2500])
    print("...")
