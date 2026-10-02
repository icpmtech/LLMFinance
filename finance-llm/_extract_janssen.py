import re, json, html
from pathlib import Path

ROOT = Path('c:/LLMFinance/finance-llm')

def extract_schema(txt, typ):
    idx = txt.find(f'"@type": "{typ}"')
    if idx == -1:
        idx = txt.find(f'"@type":"{typ}"')
    if idx == -1:
        return None
    start = txt.rfind('{', 0, idx)
    depth = 0
    end = None
    for i, ch in enumerate(txt[start:], start):
        if ch == '{':
            depth += 1
        elif ch == '}':
            depth -= 1
            if depth == 0:
                end = i + 1
                break
    if end is None:
        return None
    block = txt[start:end]
    # remove trailing commas before }]
    block = re.sub(r',(\s*[}\]])', r'\1', block)
    try:
        return json.loads(block)
    except Exception as e:
        print('schema parse err', e, block[:200])
        return None

results = {}
for name in ['racius','indice','einforma','jnj_contatos','jnj_aviso','justnews']:
    path = ROOT / f'_tmp_janssen_{name}.txt'
    txt = path.read_text(encoding='utf-8')
    print(f'\n=== {name} ({len(txt)} chars) ===')
    d = extract_schema(txt, 'Corporation')
    if d:
        print(json.dumps(d, ensure_ascii=False, indent=2))
        results[name] = d
    else:
        # fallback snippets
        for pat in ['Rua ', 'Avenida ', 'Av. ', 'Edifício ', 'Lote ', 'NIF ', 'NIPC ', 'Capital Social', 'CAE', 'Sócios', 'Gerentes', 'Telefone', 'Telemóvel', 'Email', 'Website']:
            m = re.search(re.escape(pat) + r'.{0,160}', txt, re.IGNORECASE)
            if m:
                print('SNIP', m.group(0).strip())

out = ROOT / '_janssen_extracted.json'
out.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding='utf-8')
print('\nSaved', out)
