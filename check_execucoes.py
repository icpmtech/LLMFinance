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
    page.goto(f'{base}/execucoes', wait_until='networkidle', timeout=120000)
    page.evaluate("() => { document.querySelectorAll('[class*=\"iubenda\"], [id*=\"iubenda\"]').forEach(n => n.remove()); }")
    page.screenshot(path='c:/LLMFinance/execucoes_loggedin.png', full_page=False)
    logs = page.evaluate('() => { const l=[]; for (const e of window.__errors||[]) l.push(e); return l; }') or []
    print('title:', page.title())
    print('url:', page.url)
    print('body snippet:', page.locator('body').inner_text()[:400])
    print('console errors:', logs)
    browser.close()
