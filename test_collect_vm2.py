import json, urllib.request
base='https://sabemos.studio'
body=json.dumps({'email':'e2e-empresas-iq@example.com','password':'E2eEmpresasIQ123','remember':True}).encode()
req=urllib.request.Request(f'{base}/api/auth/login',data=body,headers={'Content-Type':'application/json'})
resp=urllib.request.urlopen(req, timeout=30)
data=json.loads(resp.read())
token=data['token']
print('user:', data['user']['id'], data['user']['status'], data['user'].get('trial_expires_at'))

headers={'Content-Type':'application/json','Authorization':f'Bearer {token}'}
criteria=json.dumps({'dias':'todos','letras':['A'],'max_pages_per_letra':2,'max_items':20,'min_interval':1.5,'index':False}).encode()
req2=urllib.request.Request(f'{base}/api/execucoes/collect',data=criteria,headers=headers)
try:
    resp2=urllib.request.urlopen(req2, timeout=30)
    print('collect ok', resp2.status)
except urllib.error.HTTPError as e:
    print('collect error', e.code, e.read().decode())
