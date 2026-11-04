import json, urllib.request, time
base='https://sabemos.studio'
body=json.dumps({'email':'e2e-empresas-iq@example.com','password':'E2eEmpresasIQ123','remember':True}).encode()
req=urllib.request.Request(f'{base}/api/auth/login',data=body,headers={'Content-Type':'application/json'})
resp=urllib.request.urlopen(req, timeout=30)
data=json.loads(resp.read())
print('login ok, status:', data['user']['status'], 'role:', data['user']['role'])
token=data['token']

headers={'Content-Type':'application/json','Authorization':f'Bearer {token}'}
criteria=json.dumps({'dias':'todos','letras':['A'],'max_pages_per_letra':2,'max_items':20,'min_interval':1.5,'index':False}).encode()
req2=urllib.request.Request(f'{base}/api/execucoes/collect',data=criteria,headers=headers)
job=json.loads(urllib.request.urlopen(req2, timeout=30).read())
print('job started:',job['id'],job['state'])

for i in range(60):
    time.sleep(2)
    req3=urllib.request.Request(f'{base}/api/execucoes/jobs/{job["id"]}',headers=headers)
    try:
        st=json.loads(urllib.request.urlopen(req3, timeout=30).read())
    except Exception as e:
        print('poll error',e); continue
    print(f"{i:02d} state={st.get('state')} stage={st.get('stage')} collected={st.get('collected')} letra={st.get('letra')} error={st.get('error') or ''}")
    if st.get('finished') or st.get('state') in ('done','error','empty','stopped'):
        break

print('final state:', st.get('state'))
print('run_id:', st.get('run_id'))
print('collected:', st.get('collected'))
print('errors:', st.get('errors'))
