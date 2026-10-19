import io, json
for line in io.open(r'C:\LLMFinance\finance-llm\data\racius\racius_empresas.jsonl', encoding='utf-8'):
    d = json.loads(line)
    if 'clivita' in (d.get('url') or '') or 'serracao' in (d.get('url') or ''):
        print(d.get('url'))
        print(json.dumps(d.get('ficha'), ensure_ascii=False, indent=2))
        print('concelho=', d.get('concelho'), 'distrito=', d.get('distrito'))
