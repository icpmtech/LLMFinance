import json
with open('data/contratos-franca/decp-2026-09.json','r',encoding='utf-8') as f:
    data = json.load(f)
marches = data['marches']
print('sections:', list(marches.keys()))
for section in marches:
    arr = marches[section]
    print(f'{section}: count={len(arr)}, type={type(arr)}')
    if arr:
        sample = arr[0]
        print(f'  sample keys: {list(sample.keys())}')
        print(json.dumps(sample, indent=2, ensure_ascii=False)[:6000])
        break
