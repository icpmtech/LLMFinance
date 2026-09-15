import urllib.request, json, urllib.error
url = 'http://127.0.0.1:8003/sentiment/analyze/AAPL?backend=kronos&future_days=5&period=1y&include_features=true'
req = urllib.request.Request(url, data=b'', method='POST', headers={'Accept':'application/json'})
try:
    with urllib.request.urlopen(req, timeout=180) as r:
        print('status', r.status)
        data = json.loads(r.read())
        print(json.dumps(data, indent=2, default=str))
except urllib.error.HTTPError as e:
    print('status', e.code, e.read().decode())
except Exception as e:
    print('error', type(e).__name__, e)
