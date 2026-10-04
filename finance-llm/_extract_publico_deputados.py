"""Extrair deputados das infografias Público (2024 e 2025) e indexar no finance_people."""
import httpx, re, json, unicodedata
from pathlib import Path
from typing import List, Dict

HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/129.0.0.0 Safari/537.36',
}

def _fix_encoding(text: str) -> str:
    # A Público serve UTF-8 corretamente; o roundtrip latin1->utf8 era
    # destrutivo para caracteres acentuados. Devolver o texto original.
    return text

def _slug(nome: str) -> str:
    s = unicodedata.normalize('NFKD', nome).encode('ascii', 'ignore').decode('ascii').upper()
    s = re.sub(r'[^A-Z0-9]+', '-', s).strip('-')
    return s

def _extract_publico_arrays(url: str) -> List[List[str]]:
    r = httpx.get(url, headers=HEADERS, timeout=30, follow_redirects=True)
    text = r.text
    idx = text.find('function initInfographic')
    body = text[idx:idx + 200000] if idx != -1 else text
    rows: List[List[str]] = []
    for m in re.finditer(r'var\s+deputados(\w+)\s*=\s*(\[.*?\]);', body, re.DOTALL):
        partido_var = m.group(1)
        raw = m.group(2)
        raw = _fix_encoding(raw)
        try:
            arr = json.loads(raw)
        except Exception:
            # tentar corrigir trailing commas / quotes simples
            raw2 = raw.replace("'", '"')
            raw2 = re.sub(r',\s*([\}\]])', r'\1', raw2)
            try:
                arr = json.loads(raw2)
            except Exception as e:
                print('parse error', partido_var, e)
                continue
        for dep in arr:
            if isinstance(dep, list) and len(dep) >= 5:
                rows.append(dep)
    return rows

def _publico_doc(row: List[str], url: str, year: int) -> Dict:
    # 2024: [num, nome, circulo, partido, idade, profissao, ?, mandatos...]
    # 2025: [num, nome, circulo, partido, data_nasc, idade, profissao, ?, mandatos...]
    numero = row[0]
    nome = row[1]
    circulo = row[2]
    partido = row[3]
    if year >= 2025 and len(row) > 5:
        data_nasc = row[4]
        idade = row[5]
        profissao = row[6] if len(row) > 6 else ''
        mandatos = [x for x in row[9:] if x] if len(row) > 9 else []
    else:
        data_nasc = ''
        idade = row[4] if len(row) > 4 else ''
        profissao = row[5] if len(row) > 5 else ''
        mandatos = [x for x in row[8:] if x] if len(row) > 8 else []
    slug = _slug(nome)
    nif = f'PT-PUBLICO-{year}-{slug}'
    return {
        'nif': nif,
        'name': nome.title(),
        'nome': nome.title(),
        'source': url.replace('https://', ''),
        'active': True,
        'tags': ['deputados', 'politica', 'assembleia', f'publico{year}'],
        'metadata': {
            'fonte': f'Público Infografia {year}',
            'partido': partido,
            'circulo_eleitoral': circulo,
            'data_nascimento': data_nasc,
            'idade': idade,
            'profissao': profissao,
            'numero': numero,
            'mandatos_anteriores': mandatos,
        }
    }

def run_publico_2024():
    url = 'https://www.publico.pt/2024/03/26/infografia/nova-assembleia-republica-808'
    rows = _extract_publico_arrays(url)
    print('publico 2024 rows', len(rows))
    docs = [_publico_doc(r, url, 2024) for r in rows]
    return docs

def run_publico_2025():
    url = 'https://www.publico.pt/2025/06/02/infografia/sao-deputados-863'
    r = httpx.get(url, headers=HEADERS, timeout=45, follow_redirects=True)
    text = r.text
    # O HTML 2025 não contém initInfographic; os arrays estão inline noutro script.
    rows = []
    for m in re.finditer(r'var\s+deputados(\w+)\s*=\s*(\[.*?\]);', text, re.DOTALL):
        raw = _fix_encoding(m.group(2))
        # tentar parse JSON; se falhar, converter aspas simples e remover trailing commas
        try:
            arr = json.loads(raw)
        except Exception:
            raw2 = raw.replace("'", '"')
            raw2 = re.sub(r',\s*([\}\]])', r'\1', raw2)
            try:
                arr = json.loads(raw2)
            except Exception:
                continue
        rows.extend([r for r in arr if isinstance(r, list)])
    print('publico 2025 rows', len(rows))
    return [_publico_doc(r, url, 2025) for r in rows]

if __name__ == '__main__':
    import sys, os
    sys.path.insert(0, 'c:/LLMFinance/finance-llm')
    os.chdir('c:/LLMFinance/finance-llm')
    from api.elasticsearch_client import index_people, search_people

    docs24 = run_publico_2024()
    docs25 = run_publico_2025()
    docs = docs24 + docs25
    print('total docs', len(docs))
    if docs:
        resp = index_people(docs)
        print('index resp', resp)
    print('source=publico', search_people(source='publico', size=0)['total'])
    # guardar json
    Path('c:/LLMFinance/finance-llm/_publico_deputados.json').write_text(
        json.dumps(docs, ensure_ascii=False, indent=2), encoding='utf-8')
