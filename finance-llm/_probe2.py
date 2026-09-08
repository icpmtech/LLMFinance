from api.tools import get_holders
import json
h = get_holders('AAPL')
for k,v in h.items():
    if k != 'ticker' and v:
        print('---', k, '---')
        if isinstance(v, list):
            print(json.dumps(v[:1], ensure_ascii=False, indent=2, default=str))
        else:
            print(json.dumps(v, ensure_ascii=False, indent=2, default=str))
