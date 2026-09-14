import json, os
path = r'C:\temp\contratos_probe\Contratos2025.json'
print('Size bytes:', os.path.getsize(path))
with open(path, 'r', encoding='utf-8') as f:
    data = json.load(f)
print('Type:', type(data))
if isinstance(data, list):
    print('Records:', len(data))
    print('First record keys:', list(data[0].keys()))
    print('First record sample:')
    print(json.dumps(data[0], indent=2, ensure_ascii=False))
else:
    print('Keys:', list(data.keys()))
    first = list(data.values())[0] if data else None
    print('First value sample:', json.dumps(first, indent=2, ensure_ascii=False)[:2000])
