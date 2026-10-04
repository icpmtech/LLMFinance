"""Consolidar deputados de múltiplas fontes numa ficha única por pessoa."""
import sys, os
sys.path.insert(0, 'c:/LLMFinance/finance-llm')
os.chdir('c:/LLMFinance/finance-llm')
import json, re, unicodedata
from collections import defaultdict
from pathlib import Path
from api.elasticsearch_client import search_people, index_people

SOURCES = ['parlamento', 'cnnportugal', 'publico']

def normalize_name(name: str) -> str:
    s = unicodedata.normalize('NFKD', name).encode('ascii', 'ignore').decode('ascii').upper()
    s = re.sub(r'[^A-Z0-9]+', '', s)
    return s

def slug(name: str) -> str:
    s = unicodedata.normalize('NFKD', name).encode('ascii', 'ignore').decode('ascii').upper()
    s = re.sub(r'[^A-Z0-9]+', '-', s).strip('-')
    return s

def load_docs():
    docs = []
    for source in SOURCES:
        page = search_people(source=source, size=1000)
        for d in page.get('items', []):
            d['_origin_source'] = source
            docs.append(d)
    return docs

def consolidate(docs):
    groups = defaultdict(list)
    for d in docs:
        name = d.get('name') or d.get('nome') or ''
        key = normalize_name(name)
        groups[key].append(d)

    merged = []
    for key, group in groups.items():
        # escolher nome mais longo (geralmente nome completo) mas preferir Parlamento se existir
        parl = [d for d in group if d['_origin_source'] == 'parlamento']
        publico = [d for d in group if d['_origin_source'] == 'publico']
        cnn = [d for d in group if d['_origin_source'] == 'cnnportugal']
        base = parl[0] if parl else (publico[0] if publico else group[0])
        name = base.get('name') or base.get('nome') or ''
        # preferir nome mais longo entre todos
        for d in group:
            n = d.get('name') or d.get('nome') or ''
            if len(n) > len(name):
                name = n

        # metadados
        partidos = set()
        circulos = set()
        distritos = set()
        bid = None
        photo_url = None
        photo_path = None
        biography = None
        urls = []
        sources = []
        original_nifs = []
        idade = None
        profissao = None
        mandatos = []

        for d in group:
            original_nifs.append(d.get('nif'))
            s = d['_origin_source']
            sources.append(d.get('source'))
            md = d.get('metadata', {})
            if s == 'parlamento':
                bid = md.get('bid') or bid
                photo_url = d.get('photo_url') or photo_url
                photo_path = d.get('photo_path') or photo_path
                biography = d.get('biography') or biography
                circulos.add(md.get('circulo_eleitoral'))
                partidos.add(md.get('partido'))
                urls.extend(filter(None, [md.get('url_biografia'), md.get('url_atividade'), md.get('url_presencas'), md.get('url_interesses')]))
            elif s == 'cnnportugal':
                partidos.add(md.get('partido'))
                distritos.add(md.get('distrito'))
            elif s == 'publico':
                partidos.add(md.get('partido'))
                circulos.add(md.get('circulo_eleitoral'))
                idade = md.get('idade') or idade
                profissao = md.get('profissao') or profissao
                mandatos.extend(md.get('mandatos_anteriores', []))

        partido = next((p for p in partidos if p), None)
        circulo = next((c for c in circulos if c), None) or next((d for d in distritos if d), None)

        s = slug(name)
        nif = f'PT-AR-DEPUTADO:{s}'

        doc = {
            'nif': nif,
            'name': name.title(),
            'nome': name.title(),
            'source': 'assembleia-republica/consolidado',
            'active': True,
            'tags': ['deputados', 'politica', 'assembleia', 'legislatura-xvii'],
            'biography': biography,
            'photo_url': photo_url,
            'photo_path': photo_path,
            'metadata': {
                'original_nifs': original_nifs,
                'sources': list(set(filter(None, sources))),
                'bid': bid,
                'partido': partido,
                'circulo_eleitoral': circulo,
                'idade': idade,
                'profissao': profissao,
                'mandatos_anteriores': list(set(mandatos)),
                'urls_parlamento': list(set(filter(None, urls))),
            }
        }
        merged.append(doc)
    return merged

if __name__ == '__main__':
    docs = load_docs()
    print('loaded', len(docs))
    merged = consolidate(docs)
    print('consolidated', len(merged))
    Path('c:/LLMFinance/finance-llm/_deputados_consolidado.json').write_text(
        json.dumps(merged, ensure_ascii=False, indent=2), encoding='utf-8')
    if merged:
        resp = index_people(merged)
        print('index resp', resp)
    print('source=assembleia-republica/consolidado', search_people(source='assembleia-republica', size=0)['total'])
