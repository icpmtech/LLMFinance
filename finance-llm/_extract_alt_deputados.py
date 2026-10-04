"""Extrair listas de deputados de fontes alternativas e guardar em JSON."""
import httpx, re, json, unicodedata
from pathlib import Path
from bs4 import BeautifulSoup

HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/129.0.0.0 Safari/537.36',
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
    'Accept-Language': 'pt-PT,pt;q=0.9',
}

def _fix_cnn_encoding(text: str) -> str:
    # A CNN Portugal envia UTF-8 mas com bytes acentuados de ISO-8859-1 colados.
    # Re-encodar como latin1 e depois interpretar como UTF-8 funciona parcialmente.
    try:
        return text.encode('latin1', errors='ignore').decode('utf-8', errors='ignore')
    except Exception:
        return text

def parse_cnn():
    url = 'https://cnnportugal.iol.pt/eleicoes/legislativas2025/deputadoseleitos'
    r = httpx.get(url, headers=HEADERS, timeout=30, follow_redirects=True)
    text = r.content.decode('latin1')  # permite processar sem crash
    text = _fix_cnn_encoding(text)
    soup = BeautifulSoup(text, 'html.parser')
    items = []
    current_party = None
    current_distrito = None
    for el in soup.find_all(['div', 'li', 'h2', 'h3']):
        cls = ' '.join(el.get('class', []))
        txt = el.get_text(' ', strip=True)
        if 'partido-name' in cls or el.get('id', '').startswith('partido'):
            current_party = txt.split('-')[0].strip()
        elif 'distrito-title' in cls:
            current_distrito = txt
        elif 'candidato-entry' in cls:
            nome = ' '.join(txt.split())
            if nome:
                items.append({
                    'nome': nome,
                    'partido': current_party,
                    'distrito': current_distrito,
                    'fonte': url,
                })
    return items

def parse_rr():
    url = 'https://rr.pt/legislativas-2025/deputados/'
    r = httpx.get(url, headers=HEADERS, timeout=30, follow_redirects=True)
    text = r.content.decode('utf-8', errors='replace')
    soup = BeautifulSoup(text, 'html.parser')
    items = []
    current_party = None
    # Estrutura: secções de partido em h3, nomes em divs/parágrafos/elementos seguintes
    for h3 in soup.find_all('h3'):
        party = h3.get_text(' ', strip=True)
        if not party or 'Legislativas' in party:
            continue
        current_party = party
        # percorrer irmãos até ao próximo h3
        for sib in h3.find_next_siblings():
            if sib.name == 'h3':
                break
            txt = sib.get_text(' ', strip=True)
            if txt and len(txt.split()) >= 2 and len(txt) < 80:
                # verificar se parece nome próprio (pode haver li ou div)
                if any(c.isupper() for c in txt) and not any(k in txt.lower() for k in ['volte ao topo', 'continue a explorar', 'mais sobre', 'especial interativo', 'sondagem']):
                    items.append({'nome': txt, 'partido': current_party, 'distrito': None, 'fonte': url})
    return items

def parse_publico_2025():
    url = 'https://www.publico.pt/2025/06/02/infografia/sao-deputados-863'
    r = httpx.get(url, headers=HEADERS, timeout=30, follow_redirects=True)
    text = r.text
    soup = BeautifulSoup(text, 'html.parser')
    items = []
    # TODO: completar parser quando estrutura for conhecida
    return items

def parse_wikipedia_lista():
    url = 'https://pt.wikipedia.org/wiki/Lista_de_deputados_de_Portugal'
    r = httpx.get(url, headers=HEADERS, timeout=30, follow_redirects=True)
    soup = BeautifulSoup(r.text, 'html.parser')
    items = []
    for table in soup.find_all('table', {'class': re.compile(r'wikitable')}):
        rows = table.find_all('tr')
        if not rows:
            continue
        headers = [c.get_text(strip=True).lower() for c in rows[0].find_all(['th','td'])]
        if any(h in headers for h in ['deputado', 'nome', 'círculo', 'partido', 'mandato']):
            for row in rows[1:]:
                cells = [c.get_text(strip=True) for c in row.find_all(['td','th'])]
                if not cells:
                    continue
                # mapeamento simples
                nome = cells[0] if cells else ''
                partido = ''
                circulo = ''
                for c in cells[1:]:
                    cl = c.lower()
                    if any(p in cl for p in ['psd','ps ','cds','chega','il ','be ','pcp','pan','livre','jpp','cdu','ad ']):
                        partido = c
                    elif 'circulo' in cl or 'distrito' in cl or 'região' in cl:
                        circulo = c
                if nome:
                    items.append({'nome': nome, 'partido': partido, 'distrito': circulo, 'fonte': url})
    return items

if __name__ == '__main__':
    out_dir = Path(__file__).parent
    parsers = {
        'cnn': parse_cnn,
        'rr': parse_rr,
        'publico2025': parse_publico_2025,
        'wikipedia_lista': parse_wikipedia_lista,
    }
    for name, fn in parsers.items():
        try:
            data = fn()
            path = out_dir / f'_{name}_deputados.json'
            path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')
            print(name, len(data), '->', path)
        except Exception as e:
            print('ERROR', name, e)
