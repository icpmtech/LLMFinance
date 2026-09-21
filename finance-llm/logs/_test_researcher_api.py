import httpx, json, time

url = 'http://127.0.0.1:8002/researcher/investigate'
body = {"question": "Investiga a relação entre a EDP e contratos de software no distrito do Porto entre 2022 e 2026"}
start = time.time()
resp = httpx.post(url, json=body, timeout=180)
print('status', resp.status_code)
print('elapsed', round(time.time()-start, 2))
if resp.status_code == 200:
    r = resp.json()
    print('iterations', r.get('iterations'), 'tool_calls', r.get('tool_calls'), 'elapsed_seconds', r.get('elapsed_seconds'))
    print('entities', len(r.get('entities', [])))
    print('contracts', len(r.get('contracts', [])))
    print('relationships', len(r.get('relationships', [])))
    print('report first lines:')
    print('\n'.join(r.get('report','').split('\n')[:30]))
    with open('C:\\LLMFinance\\finance-llm\\logs\\_test_researcher_edp2.json', 'w', encoding='utf-8') as f:
        json.dump(r, f, ensure_ascii=False, indent=2)
    print('saved to logs/_test_researcher_edp2.json')
else:
    print('text:', resp.text[:500])
