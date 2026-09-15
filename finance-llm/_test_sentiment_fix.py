import warnings
warnings.filterwarnings('ignore')
import sys
sys.path.insert(0, '.')
from sentiment.feature_engineering import generate_sentiment_blended_forecast
import json

r = generate_sentiment_blended_forecast('AAPL', future_days=5, period='1y', backend='kronos', include_features=True)
print('status:', 'ok' if not r.get('error') else r.get('error'))
print('signals:', r['signals'])
print('base_forecast[0]:', r['base_forecast'][0] if r['base_forecast'] else None)
print('adjusted_forecast[0]:', r['adjusted_forecast'][0] if r['adjusted_forecast'] else None)
print('json serializable:', end=' ')
try:
    json.dumps(r)
    print('yes')
except Exception as e:
    print('no -', e)
