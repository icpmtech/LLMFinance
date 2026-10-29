import json
d = json.load(open('data/cms/cms.json'))
p = [x for x in d['pages'] if x.get('slug') == 'custo-de-vida'][0]
blocks = p['blocks']
print(json.dumps({k: (v if not isinstance(v, str) else v[:200]) for k, v in blocks[0].items() if k != 'data'}, ensure_ascii=False))
print('DATA KEYS', list(blocks[0]['data'].keys()))
for b in blocks[1:]:
    print('---', b['type'])
    print(json.dumps(b['data'], ensure_ascii=False)[:900])
open('/tmp/bloco0.html', 'w').write(blocks[0]['data'].get('html') or blocks[0]['data'].get('texto') or '')
