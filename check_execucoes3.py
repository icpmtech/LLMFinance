from playwright.sync_api import sync_playwright
import json
base='http://127.0.0.1:4180'
body=json.dumps({'email':'e2e-empresas-iq@example.com','password':'E2eEmpresasIQ123','remember':True}).encode()
import urllib.request
req=urllib.request.Request(f'{base}/api/auth/login',data=body,headers={'Content-Type':'application/json'})
token=json.loads(urllib.request.urlopen(req).read())['token']
with sync_playwright() as p:
    browser=p.chromium.launch(headless=False)
    page=browser.new_page(viewport={'width':1280,'height':800})
    page.goto(f'{base}/execucoes', wait_until='domcontentloaded', timeout=30000)
    page.evaluate(f"window.localStorage.setItem('finance-llm-token', '{token}');")
    page.reload(wait_until='networkidle', timeout=120000)
    page.wait_for_timeout(2000)
    print('URL:', page.url)
    print('TITLE:', page.title())
    # remove consent banner
    page.evaluate("() => { document.querySelectorAll('[class*=\"iubenda\"], [id*=\"iubenda\"]').forEach(n => n.remove()); }")
    print('BODY:', page.locator('body').inner_text()[:400])
    browser.close()
