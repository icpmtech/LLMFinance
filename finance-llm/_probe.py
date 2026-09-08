from api.tools import get_holders, get_news
import json
h = get_holders('AAPL')
for k,v in h.items():
    if k != 'ticker' and v:
        print('---', k, '---')
        print(json.dumps(v[:2] if isinstance(v,list) else dict(list(v.items())[:2]), ensure_ascii=False, indent=2, default=str))
n = get_news('AAPL', 2)
print('--- news ---')
print(json.dumps(n, ensure_ascii=False, indent=2, default=str))
