import requests
r = requests.post(
    'http://127.0.0.1:8002/auth/login',
    headers={'Content-Type':'application/json'},
    json={'email':'qa.office.debug@iqos.dev','password':'Password1'},
    timeout=20
)
print('STATUS', r.status_code)
print(r.text)
print('COOKIES', r.cookies.keys())
