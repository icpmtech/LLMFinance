from bs4 import BeautifulSoup

html = open(r"C:\LLMFinance\_tmp_vendas_page.html", encoding="utf-8").read()
soup = BeautifulSoup(html, "html.parser")
print("TITLE", soup.title.get_text(strip=True))
for f in soup.find_all("form"):
    print("FORM", f.get("id"), f.get("name"), f.get("action"))
    for el in f.find_all(["input", "select", "textarea"]):
        opts = [(o.get("value"), o.get_text(strip=True)) for o in el.find_all("option")]
        print("  ", el.name, el.get("type"), el.get("name"), el.get("id"), "VAL=", (el.get("value") or "")[:80], ("OPTS=%d %s" % (len(opts), str(opts[:20]))) if opts else "")
print("---- DIVS with id ----")
for d in soup.find_all(["div", "table"], id=True):
    print(d.name, d.get("id"), len(d.get_text(strip=True)))
