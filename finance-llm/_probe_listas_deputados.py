"""Inspecionar listas de deputados em RR, Público e CNN Portugal."""
import httpx, re, json
from pathlib import Path

HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/129.0.0.0 Safari/537.36',
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
    'Accept-Language': 'pt-PT,pt;q=0.9',
}

URLS = {
    'rr': 'https://rr.pt/legislativas-2025/deputados/',
    'publico': 'https://www.publico.pt/2025/06/02/infografia/sao-deputados-863',
    'cnn': 'https://cnnportugal.iol.pt/eleicoes/legislativas2025/deputadoseleitos',
}

for name, url in URLS.items():
    print(f'\n=== {name} ===')
    try:
        with httpx.Client(timeout=30, http2=False, follow_redirects=True, headers=HEADERS) as c:
            r = c.get(url)
            print('status', r.status_code, 'len', len(r.text))
            html = r.text
            # tentar encontrar JSON embutido com deputados
            for pattern in [
                r'window\.__INITIAL_STATE__\s*=\s*(\{.*?\});',
                r'window\.__DATA__\s*=\s*(\{.*?\});',
                r'<script[^>]*type="application/json"[^>]*>(.*?)</script>',
            ]:
                for m in re.finditer(pattern, html, re.DOTALL):
                    print('JSON script candidate', pattern[:60])
                    try:
                        txt = m.group(1)
                        data = json.loads(txt)
                        print('parsed keys', list(data.keys())[:10])
                    except Exception as e:
                        print('parse error', e)
            # nomes próprios capitalizados (heurística)
            if name == 'rr':
                # procurar blocos com nome + partido
                for m in re.finditer(r'<div[^>]*class="[^"]*(?:deputado|candidate|person)[^"]*"[^>]*>(.*?)</div>', html, re.DOTALL | re.I):
                    print('block', m.group(1)[:200].replace('\n',' '))
            # procurar estruturas JSON de infografia do Público
            if name == 'publico':
                for m in re.finditer(r'<script[^>]*>(.*?)</script>', html, re.DOTALL):
                    txt = m.group(1)
                    if 'deputad' in txt.lower() or 'legislativas' in txt.lower():
                        print('script snippet', txt[:300])
    except Exception as e:
        print('ERROR', e)
