from api.tools import get_technical_indicators
r = get_technical_indicators('EDP.LS', period='6mo')
print('error' in r, len(r.get('dates', [])), list(r.keys()))
if 'error' in r:
    print(r['error'])
else:
    print('first rsi', r['rsi14'][:3])
    print('last macd', r['macd'][-3:])
