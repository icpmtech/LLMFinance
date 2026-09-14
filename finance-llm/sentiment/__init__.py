"""Módulo de análise de sentimento e engenharia de features para previsão."""
from sentiment.feature_engineering import (
    blend_forecast_with_sentiment,
    build_feature_vector,
    fetch_earnings_features,
    fetch_macro_features,
    fetch_price_history,
    fetch_yahoo_news_features,
    generate_sentiment_blended_forecast,
    get_daily_sentiment,
    get_rss_news_features,
    index_daily_sentiment,
    index_earnings,
    index_macro,
)

__all__ = [
    "get_daily_sentiment",
    "index_daily_sentiment",
    "fetch_yahoo_news_features",
    "get_rss_news_features",
    "fetch_macro_features",
    "index_macro",
    "fetch_earnings_features",
    "index_earnings",
    "build_feature_vector",
    "blend_forecast_with_sentiment",
    "generate_sentiment_blended_forecast",
    "fetch_price_history",
]
