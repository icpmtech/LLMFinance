import json, base64
d = json.load(open('data/cms/cms.json'))
p = [x for x in d['pages'] if x.get('slug') == 'custo-de-vida'][0]
md = p['blocks'][0]['data']['markdown']
print(base64.b64encode(md.encode('utf-8')).decode())
