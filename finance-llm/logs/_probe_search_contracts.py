import httpx
url = 'http://127.0.0.1:8002/contracts/search'
queries = [
    {"q": "EDP", "size": 5},
    {"nif": "503504564", "size": 5},
    {"nif": "503504564", "region": "Porto", "size": 5},
    {"nif": "503504564", "year_from": 2022, "year_to": 2026, "size": 5},
    {"nif": "503504564", "region": "Porto", "year_from": 2022, "year_to": 2026, "size": 5},
    {"nif": "503504564", "cpv_code": "722", "size": 5},
    {"nif": "503504564", "region": "Porto", "year_from": 2022, "year_to": 2026, "cpv_code": "722", "size": 5},
]
for q in queries:
    r = httpx.post(url, json=q, timeout=30)
    j = r.json() if r.status_code == 200 else {}
    total = j.get('total') if isinstance(j, dict) else None
    print(q, 'status', r.status_code, 'total', total)
