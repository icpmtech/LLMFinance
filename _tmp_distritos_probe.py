import json
j = json.load(open(r'C:\LLMFinance\finance-llm\data\municipios\municipios.json', encoding='utf-8'))
for f in j['fichas']:
    if not f.get('distrito'):
        print(f['nome'], '|', f.get('nuts_nome'), '|', f.get('nuts'))
