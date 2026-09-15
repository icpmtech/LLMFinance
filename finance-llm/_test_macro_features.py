import sys
sys.path.insert(0, r'C:\LLMFinance\finance-llm')
from sentiment.feature_engineering import _load_macro_from_es
from api.elasticsearch_client import get_es_client
import pandas as pd
client = get_es_client()
df = _load_macro_from_es(client)
print(df['name'].unique())
for name in sorted(df['name'].unique()):
    sub = df[df['name']==name]
    print(name, sub['date'].min(), sub['date'].max(), sub.tail(1).to_dict('records'))
