import urllib.request
req = urllib.request.Request('http://127.0.0.1:8002/contracts-es/analytics')
try:
    r = urllib.request.urlopen(req, timeout=60)
    print('OK', r.status, len(r.read().decode()))
except urllib.error.HTTPError as e:
    print('HTTP', e.code, e.read().decode()[:1500])
except Exception as ex:
    print('ERR', type(ex).__name__, ex)
