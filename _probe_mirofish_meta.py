import json, requests
r = requests.get(
    'http://127.0.0.1:8002/mirofish/meta',
    cookies={'session':'eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiJhZG1pbiIsInVpZCI6InVzZXIxIiwicm9sZSI6ImFkbWluIn0.test'},
    timeout=15,
)
print('status', r.status_code)
try:
    print(json.dumps(r.json(), indent=2, ensure_ascii=False)[:2000])
except Exception as e:
    print('text', r.text[:500])
