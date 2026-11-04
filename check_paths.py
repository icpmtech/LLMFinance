from playwright.sync_api import sync_playwright
import json
base='http://127.0.0.1:4180'
body=json.dumps({'email':'e2e-empresas-iq@example.com','password':'E2eEmpresasIQ123','remember':True}).encode()
import urllib.request
req=urllib.request.Request(f'{base}/api/auth/login',data=body,headers={'Content-Type':'application/json'})
token=json.loads(urllib.request.urlopen(req).read())['token']
with sync_playwright() as p:
    browser=p.chromium.launch()
    page=browser.new_page()
    page.add_init_script(f"window.localStorage.setItem('finance-llm-token', '{token}');")
    for path in ['/cire','/vendas','/execucoes','/contribuintes']:
        page.goto(f'{base}{path}', wait_until='networkidle', timeout=120000)
        page.wait_for_timeout(2000)
        print(path, '->', page.url, '|', page.title())
    browser.close()
