import requests
import json
import sys

url = 'http://127.0.0.1:8002/researcher/investigate'
question = 'Investiga os contratos de software (CPV 722) da EDP no distrito do Porto entre 2022 e 2026'
resp = requests.post(url, json={'question': question}, timeout=120)
print('status_code', resp.status_code)
data = resp.json()
print(json.dumps({k: data[k] for k in ['status', 'iterations', 'tool_calls', 'warnings']}, ensure_ascii=False, indent=2))
print('---REPORT---')
print(data['report'])
