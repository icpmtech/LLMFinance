import io, json, collections
p = r'C:\LLMFinance\finance-llm\data\racius\racius_cae_nacional.json'
rows = json.load(io.open(p, encoding='utf-8'))
nifs = [r.get('nif') for r in rows if r.get('nif')]
urls = [r.get('url') for r in rows if r.get('url')]
cn = collections.Counter(nifs); cu = collections.Counter(urls)
print('empresas:', len(rows))
print('com NIF:', len(nifs), '| NIF distintos:', len(cn), '| NIF repetidos:', sum(1 for k,v in cn.items() if v>1))
print('URLs distintas:', len(cu), '| URLs repetidas:', sum(1 for k,v in cu.items() if v>1))
print('sem NIF:', len(rows) - len(nifs))
