import urllib.request, json
req = urllib.request.Request(
    'http://127.0.0.1:8003/contracts/ingest',
    data=json.dumps({"years": [2025], "limit": 500}).encode(),
    headers={'Content-Type': 'application/json'},
    method='POST'
)
r = urllib.request.urlopen(req)
print(r.status, json.dumps(json.loads(r.read()), indent=2, ensure_ascii=False))
