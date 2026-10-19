import io, json, collections
rows = [json.loads(l) for l in io.open(r'C:\LLMFinance\finance-llm\data\racius\porto.jsonl', encoding='utf-8') if l.strip()]
print('linhas:', len(rows))
nifs = collections.Counter(r.get('nif') or '' for r in rows)
print('nif vazio:', nifs.get('', 0))
dup = {k: v for k, v in nifs.items() if v > 1 and k}
print('nifs repetidos no ficheiro:', len(dup), list(dup.items())[:5])
