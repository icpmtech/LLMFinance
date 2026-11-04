from playwright.sync_api import sync_playwright
import json
base='http://127.0.0.1:4180'
body=json.dumps({'email':'e2e-empresas-iq@example.com','password':'E2eEmpresasIQ123','remember':True}).encode()
import urllib.request
req=urllib.request.Request(f'{base}/api/auth/login',data=body,headers={'Content-Type':'application/json'})
token=json.loads(urllib.request.urlopen(req).read())['token']
with sync_playwright() as p:
    browser=p.chromium.launch()
    page=browser.new_page(viewport={'width':1280,'height':800})
    console_logs=[]
    page.on('console', lambda msg: console_logs.append(f'{msg.type}: {msg.text}'))
    page.on('pageerror', lambda err: console_logs.append(f'PAGEERROR: {err}'))
    page.on('requestfailed', lambda req: console_logs.append(f'FAILED: {req.url} {req.failure}'))
    page.add_init_script(f"window.localStorage.setItem('finance-llm-token', '{token}');")
    page.goto(f'{base}/execucoes', wait_until='networkidle', timeout=120000)
    page.wait_for_timeout(3000)
    print('URL:', page.url)
    print('TITLE:', page.title())
    for log in console_logs[-50:]:
        print(log)
    html = page.locator('#root').inner_html() if page.locator('#root').count() > 0 else page.content()[:500]
    print('HTML snippet:', html[:500])
    browser.close()
