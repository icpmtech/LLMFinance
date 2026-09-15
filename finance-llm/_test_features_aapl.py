import sys
sys.path.insert(0, r'C:\LLMFinance\finance-llm')
from sentiment.feature_engineering import build_feature_vector
import pandas as pd
prices = build_feature_vector('AAPL', days=5, period='1y')
print(prices[['date','US10Y','USFFR','USCPI','US02Y']].tail(20))
print('last row:', prices.iloc[-1][['US10Y','USFFR','USCPI','US02Y']].to_dict())
