"""Engenharia de features sentimento + macro + earnings para previsão financeira.

Este módulo:
1. Recolhe notícias do Yahoo + RSS.
2. Analisa/analisa-as em batch com api.news_nlp (sentimento, entidades, tópicos, PT).
3. Indexa notícias enriquecidas em finance_news.
4. Agrega sentimento por dia (finance_sentiment_daily).
5. Indexa earnings (finance_earnings) e macro (finance_macro).
6. Alinha tudo com preços históricos para criar vetores de features.
7. Combina com previsões ARIMA/Kronos para gerar blended forecast/signal.
"""
import json
import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

from api.elasticsearch_client import (
    ensure_indices,
    get_es_client,
    index_analyzed_news_items,
    search_news,
    search_prices,
)
from api.news_nlp import analyze_news_batch
from api.tools import (
    get_earnings_and_calendar,
    get_macro_snapshot,
    get_news,
    get_stock_history,
)
from collectors.rss import collect_finance_rss

logger = logging.getLogger(__name__)

# Série macro-chave para risco e yield curve
MACRO_NAMES = ["US10Y", "US02Y", "USFFR", "USCPI", "USCOREPCE", "USUNEMP"]

SENTIMENT_SCORE = {
    "positivo": 1.0,
    "neutro": 0.0,
    "negativo": -1.0,
}


def _today() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def _parse_date(d: Any) -> Optional[datetime]:
    if d is None:
        return None
    if isinstance(d, datetime):
        return d
    if isinstance(d, str):
        for fmt in ("%Y-%m-%dT%H:%M:%S.%f", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d"):
            try:
                return datetime.strptime(d[: len(fmt)], fmt)
            except ValueError:
                continue
        try:
            return datetime.fromisoformat(d.replace("Z", "+00:00"))
        except ValueError:
            pass
    return None


def _date_str(d: Any) -> Optional[str]:
    dt = _parse_date(d)
    return dt.strftime("%Y-%m-%d") if dt else None


# -----------------------------------------------------------------------------
# 1. Coleta e NLP
# -----------------------------------------------------------------------------

def get_rss_news_features(
    ticker: str,
    max_items: int = 200,
    since_days: int = 30,
    fetch_full_text: bool = False,
) -> List[Dict[str, Any]]:
    """Recolhe notícias RSS para o ticker."""
    return collect_finance_rss(
        ticker=ticker,
        max_items=max_items,
        since_days=since_days,
        fetch_full_text=fetch_full_text,
    )


def fetch_yahoo_news_features(ticker: str, max_items: int = 50) -> List[Dict[str, Any]]:
    """Recolhe notícias Yahoo Finance para o ticker."""
    result = get_news(ticker, max_items=max_items)
    if result.get("error"):
        logger.warning("Yahoo news error %s: %s", ticker, result["error"])
        return []
    out = []
    for n in result.get("news", []):
        published = n.get("published") or n.get("pubDate")
        out.append(
            {
                "id": "",
                "title": n.get("title") or "",
                "summary": n.get("summary") or "",
                "url": n.get("url") or "",
                "publisher": n.get("publisher") or "yahoo_finance",
                "published": published,
                "source": "yahoo_finance",
                "tags": [],
            }
        )
    return out


def analyze_and_index_news(
    ticker: str,
    items: List[Dict[str, Any]],
    es: Optional[Any] = None,
) -> Dict[str, Any]:
    """Analisa notícias com NLP e indexa-as no ES."""
    if not items:
        return {"ticker": ticker, "analyzed": 0, "indexed": 0}

    client = es or get_es_client()
    if client:
        ensure_indices(client)

    analyses = analyze_news_batch(items, ticker=ticker)
    indexed = {"indexed_count": 0}
    if client:
        indexed = index_analyzed_news_items(ticker, items, analyses, es=client)

    # Devolve também lista enriquecida para downstream
    enriched = []
    for item, analysis in zip(items, analyses):
        enriched.append(
            {
                "title": item.get("title"),
                "summary": item.get("summary"),
                "published": item.get("published"),
                "publisher": item.get("publisher"),
                "url": item.get("url"),
                "source": item.get("source"),
                "sentiment": analysis.sentiment,
                "score": SENTIMENT_SCORE.get(analysis.sentiment, 0.0),
                "entities": analysis.entities,
                "topics": analysis.topics,
                "summary_pt": analysis.summary_pt,
            }
        )

    return {
        "ticker": ticker,
        "analyzed": len(analyses),
        "indexed": indexed.get("indexed_count", 0),
        "items": enriched,
    }


# -----------------------------------------------------------------------------
# 2. Agregação diária de sentimento
# -----------------------------------------------------------------------------

def get_daily_sentiment(
    ticker: str,
    days: int = 90,
    es: Optional[Any] = None,
) -> pd.DataFrame:
    """Lê notícias indexadas e devolve DataFrame com sentimento agregado por dia."""
    client = es or get_es_client()
    if not client:
        return pd.DataFrame()

    end = datetime.now(timezone.utc)
    start = end - timedelta(days=days)
    items = search_news(
        ticker,
        start_date=start.strftime("%Y-%m-%d"),
        end_date=end.strftime("%Y-%m-%d"),
        size=5000,
        es=client,
    ).get("items", [])

    if not items:
        return pd.DataFrame()

    rows = []
    for it in items:
        d = _date_str(it.get("published"))
        if not d:
            continue
        sent = it.get("sentiment", "neutro")
        score = SENTIMENT_SCORE.get(sent, 0.0)
        rows.append({"date": d, "score": score, "sentiment": sent})

    df = pd.DataFrame(rows)
    if df.empty:
        return pd.DataFrame()

    agg = df.groupby("date").agg(
        news_count=("score", "count"),
        sentiment_mean=("score", "mean"),
        sentiment_std=("score", "std"),
        positive_count=("score", lambda x: (x > 0).sum()),
        negative_count=("score", lambda x: (x < 0).sum()),
    ).reset_index()
    agg["sentiment_std"] = agg["sentiment_std"].fillna(0.0)
    agg["positive_ratio"] = (agg["positive_count"] / agg["news_count"]).round(4)
    agg["negative_ratio"] = (agg["negative_count"] / agg["news_count"]).round(4)
    agg["ticker"] = ticker.upper()
    return agg.sort_values("date")


def index_daily_sentiment(
    ticker: str,
    df: pd.DataFrame,
    es: Optional[Any] = None,
) -> Dict[str, Any]:
    """Indexa agregação diária de sentimento no índice finance_sentiment_daily."""
    client = es or get_es_client()
    if not client or df.empty:
        return {"ticker": ticker, "indexed": 0}

    _ensure_sentiment_index(client)
    ticker = ticker.upper()
    actions = []
    for _, row in df.iterrows():
        date = str(row["date"])[:10]
        doc_id = f"{ticker}-{date}"
        actions.append(
            {
                "_op_type": "index",
                "_index": "finance_sentiment_daily",
                "_id": doc_id,
                "ticker": ticker,
                "date": date,
                "news_count": int(row["news_count"]),
                "sentiment_mean": float(row["sentiment_mean"]),
                "sentiment_std": float(row["sentiment_std"]),
                "positive_count": int(row["positive_count"]),
                "negative_count": int(row["negative_count"]),
                "positive_ratio": float(row["positive_ratio"]),
                "negative_ratio": float(row["negative_ratio"]),
                "updated_at": _today(),
            }
        )

    from elasticsearch.helpers import bulk

    try:
        success, errors = bulk(client, actions, raise_on_error=False, refresh=True)
        return {"ticker": ticker, "indexed": success, "errors": len(errors)}
    except Exception as e:
        return {"ticker": ticker, "error": str(e), "indexed": 0}


# -----------------------------------------------------------------------------
# 3. Macro e Earnings
# -----------------------------------------------------------------------------

def fetch_macro_features() -> pd.DataFrame:
    """Recolhe snapshot macro e devolve DataFrame com colunas name/date/value."""
    snapshot = get_macro_snapshot()
    rows = []
    for name, data in snapshot.items():
        if data.get("error"):
            continue
        series = data.get("series", [])
        for point in series:
            rows.append(
                {
                    "name": name,
                    "date": point.get("date"),
                    "value": point.get("value"),
                    "updated_at": _today(),
                }
            )
    df = pd.DataFrame(rows)
    if df.empty:
        return pd.DataFrame(columns=["name", "date", "value", "updated_at"])
    df["date"] = pd.to_datetime(df["date"]).dt.strftime("%Y-%m-%d")
    return df.sort_values(["name", "date"])


def index_macro(df: pd.DataFrame, es: Optional[Any] = None) -> Dict[str, Any]:
    """Indexa série macro em finance_macro."""
    client = es or get_es_client()
    if not client or df.empty:
        return {"indexed": 0}

    _ensure_macro_index(client)
    from elasticsearch.helpers import bulk

    actions = []
    for _, row in df.iterrows():
        doc_id = f"{row['name']}-{row['date']}"
        actions.append(
            {
                "_op_type": "index",
                "_index": "finance_macro",
                "_id": doc_id,
                "name": row["name"],
                "date": row["date"],
                "value": float(row["value"]) if pd.notna(row["value"]) else None,
                "updated_at": row.get("updated_at") or _today(),
            }
        )

    try:
        success, errors = bulk(client, actions, raise_on_error=False, refresh=True)
        return {"indexed": success, "errors": len(errors)}
    except Exception as e:
        return {"error": str(e), "indexed": 0}


def fetch_earnings_features(ticker: str) -> pd.DataFrame:
    """Recolhe calendário de earnings e devolve DataFrame de eventos."""
    data = get_earnings_and_calendar(ticker)
    if data.get("error"):
        logger.warning("Earnings error %s: %s", ticker, data["error"])
        return pd.DataFrame()

    rows = []
    for row in data.get("earnings_dates", []):
        if not row.get("date"):
            continue
        eps_est = row.get("eps_estimate")
        reported = row.get("reported_eps")
        surprise = None
        if eps_est and reported and eps_est != 0:
            surprise = round((reported - eps_est) / abs(eps_est), 4)
        rows.append(
            {
                "ticker": ticker.upper(),
                "date": str(row["date"])[:10],
                "eps_estimate": eps_est,
                "reported_eps": reported,
                "surprise_pct": surprise,
                "updated_at": _today(),
            }
        )

    # Adicionar próximo earnings futuro (sem reported)
    next_e = data.get("next_earnings")
    if next_e and next_e.get("date"):
        rows.append(
            {
                "ticker": ticker.upper(),
                "date": str(next_e["date"])[:10],
                "eps_estimate": next_e.get("eps_estimate"),
                "reported_eps": None,
                "surprise_pct": None,
                "updated_at": _today(),
            }
        )

    df = pd.DataFrame(rows)
    if df.empty:
        return df
    df["date"] = pd.to_datetime(df["date"]).dt.strftime("%Y-%m-%d")
    return df.drop_duplicates(subset=["ticker", "date"]).sort_values("date")


def index_earnings(
    ticker: str,
    df: pd.DataFrame,
    es: Optional[Any] = None,
) -> Dict[str, Any]:
    """Indexa earnings em finance_earnings."""
    client = es or get_es_client()
    if not client or df.empty:
        return {"ticker": ticker, "indexed": 0}

    _ensure_earnings_index(client)
    from elasticsearch.helpers import bulk

    actions = []
    for _, row in df.iterrows():
        doc_id = f"{row['ticker']}-{row['date']}"
        actions.append(
            {
                "_op_type": "index",
                "_index": "finance_earnings",
                "_id": doc_id,
                "ticker": row["ticker"],
                "date": row["date"],
                "eps_estimate": float(row["eps_estimate"]) if pd.notna(row.get("eps_estimate")) else None,
                "reported_eps": float(row["reported_eps"]) if pd.notna(row.get("reported_eps")) else None,
                "surprise_pct": float(row["surprise_pct"]) if pd.notna(row.get("surprise_pct")) else None,
                "updated_at": row.get("updated_at") or _today(),
            }
        )

    try:
        success, errors = bulk(client, actions, raise_on_error=False, refresh=True)
        return {"ticker": ticker, "indexed": success, "errors": len(errors)}
    except Exception as e:
        return {"ticker": ticker, "error": str(e), "indexed": 0}


# -----------------------------------------------------------------------------
# 4. Alinhamento com preços e vetor de features
# -----------------------------------------------------------------------------

def fetch_price_history(
    ticker: str,
    period: str = "1y",
    es: Optional[Any] = None,
) -> pd.DataFrame:
    """Obtém preços históricos do ES ou yfinance e devolve DataFrame OHLCV."""
    client = es
    if client is None:
        client = get_es_client()
    if client:
        try:
            end = datetime.now(timezone.utc)
            start = end - pd.Timedelta(period)
            resp = search_prices(
                ticker,
                start_date=start.strftime("%Y-%m-%d"),
                end_date=end.strftime("%Y-%m-%d"),
                size=5000,
                es=client,
            )
            pts = resp.get("points", [])
            if pts:
                df = pd.DataFrame(pts)
                df["date"] = pd.to_datetime(df["date"]).dt.strftime("%Y-%m-%d")
                return df.sort_values("date").reset_index(drop=True)
        except Exception as e:
            logger.warning("ES prices error %s: %s", ticker, e)

    try:
        df = get_stock_history(ticker, period=period)
        if df.empty:
            return pd.DataFrame()
        df["date"] = pd.to_datetime(df["Date"]).dt.strftime("%Y-%m-%d")
        # Garantir colunas padronizadas
        for col in ["Open", "High", "Low", "Close", "Volume"]:
            if col not in df.columns:
                df[col] = np.nan
        return df[["date", "Open", "High", "Low", "Close", "Volume", "ticker"]].sort_values("date").reset_index(drop=True)
    except Exception as e:
        logger.error("Price history error %s: %s", ticker, e)
        return pd.DataFrame()


def build_feature_vector(
    ticker: str,
    days: int = 90,
    period: str = "1y",
    es: Optional[Any] = None,
) -> pd.DataFrame:
    """Constrói DataFrame unificado: preços + sentimento + earnings + macro."""
    prices = fetch_price_history(ticker, period=period, es=es)
    if prices.empty:
        return pd.DataFrame()

    # Sentimento diário
    sent = get_daily_sentiment(ticker, days=days, es=es)
    if not sent.empty:
        prices = prices.merge(sent, on="date", how="left")
    else:
        for c in ["news_count", "sentiment_mean", "sentiment_std", "positive_ratio", "negative_ratio"]:
            prices[c] = np.nan

    # Earnings
    earnings = fetch_earnings_features(ticker)
    if not earnings.empty:
        prices = prices.merge(
            earnings[["date", "eps_estimate", "reported_eps", "surprise_pct"]],
            on="date",
            how="left",
        )
    else:
        for c in ["eps_estimate", "reported_eps", "surprise_pct"]:
            prices[c] = np.nan

    # Preencher forward earnings estimate (EPS futuro) até à data de reporte
    prices["eps_estimate"] = prices["eps_estimate"].ffill()

    # Macro (pivot)
    client = es or get_es_client()
    macro_df = pd.DataFrame()
    if client:
        try:
            macro_df = _load_macro_from_es(client)
        except Exception as e:
            logger.warning("Macro load error: %s", e)
    if macro_df.empty:
        macro_df = fetch_macro_features()

    if not macro_df.empty:
        macro_pivot = macro_df.pivot(index="date", columns="name", values="value").reset_index()
        macro_cols = [c for c in macro_pivot.columns if c != "date"]
        prices = prices.merge(macro_pivot, on="date", how="left")
        # Forward fill limitado a 30 dias para macro de baixa frequência
        for c in macro_cols:
            prices[c] = prices[c].ffill(limit=30)
    else:
        macro_cols = []

    # Features derivadas
    prices["return_1d"] = prices["Close"].pct_change(1)
    prices["return_5d"] = prices["Close"].pct_change(5)
    prices["volatility_20d"] = prices["return_1d"].rolling(20).std()
    prices["sma_20"] = prices["Close"].rolling(20).mean()
    prices["sma_50"] = prices["Close"].rolling(50).mean()

    # Próximo earnings em dias
    if not earnings.empty:
        earnings_dates = pd.to_datetime(earnings["date"]).tolist()
        prices["days_to_earnings"] = prices["date"].apply(
            lambda d: _days_to_next(pd.to_datetime(d), earnings_dates)
        )
    else:
        prices["days_to_earnings"] = np.nan

    # Preenche NaNs restantes com 0 (sentimento) ou forward fill
    for c in ["news_count", "sentiment_mean", "sentiment_std", "positive_ratio", "negative_ratio"]:
        if c in prices.columns:
            prices[c] = prices[c].fillna(0.0)

    return prices.sort_values("date").reset_index(drop=True)


def _days_to_next(d: datetime, dates: List[datetime]) -> Optional[int]:
    future = [x for x in dates if x >= d]
    if not future:
        return None
    return (min(future) - d).days


# -----------------------------------------------------------------------------
# 5. Blending com previsão
# -----------------------------------------------------------------------------

def blend_forecast_with_sentiment(
    ticker: str,
    base_forecast: List[Dict[str, Any]],
    days: int = 90,
    period: str = "1y",
    es: Optional[Any] = None,
) -> Dict[str, Any]:
    """Ajusta uma previsão base com sinal de sentimento/macro/earnings.

    Devolve:
        - adjusted_forecast: lista de {date, price, upper, lower}
        - sentiment_signal: score -1..1
        - macro_signal: score -1..1
        - earnings_signal: score -1..1
        - blended_signal: score -1..1
        - weights: dict com pesos usados
    """
    features = build_feature_vector(ticker, days=days, period=period, es=es)
    if features.empty:
        return {
            "ticker": ticker,
            "error": "Sem dados de preço/sentimento para blending",
            "base_forecast": base_forecast,
        }

    last = features.iloc[-1]
    sentiment_signal = _sentiment_signal(last)
    macro_signal = _macro_signal(last, features)
    earnings_signal = _earnings_signal(last, features)

    # Pesos: sentimento 40%, macro 30%, earnings 30%
    weights = {"sentiment": 0.40, "macro": 0.30, "earnings": 0.30}
    blended = (
        weights["sentiment"] * sentiment_signal
        + weights["macro"] * macro_signal
        + weights["earnings"] * earnings_signal
    )

    # Ajustar previsão base: +0.1% por ponto de blended signal por dia previsto
    adjusted = []
    for i, p in enumerate(base_forecast):
        bias = blended * (i + 1) * 0.001  # 0.1% por dia * signal
        price = p.get("price")
        if price is None:
            continue
        adj_price = price * (1 + bias)
        upper = p.get("upper", adj_price * 1.02) if p.get("upper") else adj_price * 1.02
        lower = p.get("lower", adj_price * 0.98) if p.get("lower") else adj_price * 0.98
        adjusted.append(
            {
                "date": p.get("date"),
                "price": round(adj_price, 4),
                "upper": round(upper * (1 + abs(bias) * 0.5), 4),
                "lower": round(lower * (1 - abs(bias) * 0.5), 4),
                "bias": round(bias, 6),
            }
        )

    return {
        "ticker": ticker.upper(),
        "base_forecast": base_forecast,
        "adjusted_forecast": adjusted,
        "sentiment_signal": round(sentiment_signal, 4),
        "macro_signal": round(macro_signal, 4),
        "earnings_signal": round(earnings_signal, 4),
        "blended_signal": round(blended, 4),
        "weights": weights,
        "features": {
            "sentiment_mean": float(last.get("sentiment_mean", 0)),
            "news_count": int(last.get("news_count", 0)),
            "days_to_earnings": last.get("days_to_earnings"),
            "eps_estimate": float(last.get("eps_estimate")) if pd.notna(last.get("eps_estimate")) else None,
            "surprise_pct": float(last.get("surprise_pct")) if pd.notna(last.get("surprise_pct")) else None,
            "US10Y": float(last.get("US10Y")) if pd.notna(last.get("US10Y")) else None,
            "USFFR": float(last.get("USFFR")) if pd.notna(last.get("USFFR")) else None,
            "USCPI": float(last.get("USCPI")) if pd.notna(last.get("USCPI")) else None,
        },
    }


def _sentiment_signal(last: pd.Series) -> float:
    score = float(last.get("sentiment_mean", 0) or 0)
    pos = float(last.get("positive_ratio", 0) or 0)
    neg = float(last.get("negative_ratio", 0) or 0)
    if last.get("news_count", 0) < 3:
        # Pouca amostra: atenua
        return score * 0.3
    return max(-1.0, min(1.0, score + (pos - neg) * 0.3))


def _macro_signal(last: pd.Series, features: pd.DataFrame) -> float:
    signal = 0.0
    n = 0
    us10y = last.get("US10Y")
    usffr = last.get("USFFR")
    cpi = last.get("USCPI")
    if pd.notna(us10y) and pd.notna(usffr):
        spread = us10y - usffr
        # Inverted yield curve = negativo
        if spread < 0:
            signal -= 0.3
        else:
            signal += 0.2
        n += 1
    if pd.notna(cpi):
        # Avalia variação recente do CPI (mês a mês, proxy)
        cpi_series = features["USCPI"].dropna().tail(2)
        if len(cpi_series) >= 2:
            change = (cpi_series.iloc[-1] - cpi_series.iloc[0]) / cpi_series.iloc[0]
            if change > 0.005:
                signal -= 0.3
            elif change < -0.005:
                signal += 0.2
        n += 1
    return max(-1.0, min(1.0, signal)) if n else 0.0


def _earnings_signal(last: pd.Series, features: pd.DataFrame) -> float:
    signal = 0.0
    days_to = last.get("days_to_earnings")
    if pd.notna(days_to):
        if days_to <= 5:
            # Volatilidade típica pre-earnings -> neutro ligeiramente negativo (risco)
            signal -= 0.1
        elif days_to <= 30:
            signal += 0.05
    surprise = last.get("surprise_pct")
    if pd.notna(surprise):
        # Surprise positivo recente = bullish
        signal += max(-0.5, min(0.5, surprise))
    return max(-1.0, min(1.0, signal))


# -----------------------------------------------------------------------------
# 6. Pipeline de alto nível
# -----------------------------------------------------------------------------

def generate_sentiment_blended_forecast(
    ticker: str,
    future_days: int = 5,
    period: str = "1y",
    backend: str = "kronos",
    include_features: bool = True,
) -> Dict[str, Any]:
    """Pipeline completo: recolhe dados, gera previsão base e aplica blending.

    A previsão base é gerada com Kronos, que é mais robusto a tickers globais como
    AAPL e evita o caminho yfinance.download usado pelo pipeline ARIMA antigo.
    O parâmetro backend é registado para informação; o blending é independente.
    """
    # 1. Coletar e indexar notícias (Yahoo + RSS)
    yahoo_items = fetch_yahoo_news_features(ticker)
    rss_items = get_rss_news_features(ticker, max_items=100)
    all_items = yahoo_items + rss_items
    if all_items:
        analyze_and_index_news(ticker, all_items)

    # 2. Indexar macro e earnings
    macro_df = fetch_macro_features()
    if not macro_df.empty:
        index_macro(macro_df)
    earnings_df = fetch_earnings_features(ticker)
    if not earnings_df.empty:
        index_earnings(ticker, earnings_df)

    # 3. Gerar previsão base (sempre via Kronos para fiabilidade)
    from forecasting.kronos_model import run_kronos_pipeline

    try:
        base_result = run_kronos_pipeline(
            ticker=ticker,
            period=period,
            future_steps=future_days,
            variant="kronos-mini",
        )
        base_forecast = base_result.get("forecast", [])
    except Exception as exc:
        logger.warning("Kronos base forecast failed for %s: %s", ticker, exc)
        base_forecast = []

    # 4. Blending
    blended = blend_forecast_with_sentiment(ticker, base_forecast, period=period)
    blended["base_model"] = backend
    blended["period"] = period
    blended["future_days"] = future_days

    if not include_features:
        blended.pop("features", None)
    return blended


# -----------------------------------------------------------------------------
# 7. Helpers ES mappings
# -----------------------------------------------------------------------------

def _ensure_sentiment_index(client: Any) -> None:
    mappings = {
        "properties": {
            "ticker": {"type": "keyword"},
            "date": {"type": "date"},
            "news_count": {"type": "integer"},
            "sentiment_mean": {"type": "float"},
            "sentiment_std": {"type": "float"},
            "positive_count": {"type": "integer"},
            "negative_count": {"type": "integer"},
            "positive_ratio": {"type": "float"},
            "negative_ratio": {"type": "float"},
            "updated_at": {"type": "date"},
        }
    }
    if not client.indices.exists(index="finance_sentiment_daily"):
        client.indices.create(
            index="finance_sentiment_daily",
            body={"mappings": mappings, "settings": {"number_of_shards": 1, "number_of_replicas": 0}},
        )


def _ensure_macro_index(client: Any) -> None:
    mappings = {
        "properties": {
            "name": {"type": "keyword"},
            "date": {"type": "date"},
            "value": {"type": "float"},
            "updated_at": {"type": "date"},
        }
    }
    if not client.indices.exists(index="finance_macro"):
        client.indices.create(
            index="finance_macro",
            body={"mappings": mappings, "settings": {"number_of_shards": 1, "number_of_replicas": 0}},
        )


def _ensure_earnings_index(client: Any) -> None:
    mappings = {
        "properties": {
            "ticker": {"type": "keyword"},
            "date": {"type": "date"},
            "eps_estimate": {"type": "float"},
            "reported_eps": {"type": "float"},
            "surprise_pct": {"type": "float"},
            "updated_at": {"type": "date"},
        }
    }
    if not client.indices.exists(index="finance_earnings"):
        client.indices.create(
            index="finance_earnings",
            body={"mappings": mappings, "settings": {"number_of_shards": 1, "number_of_replicas": 0}},
        )


def _load_macro_from_es(client: Any) -> pd.DataFrame:
    end = datetime.now(timezone.utc)
    start = end - timedelta(days=365 * 2)
    query = {
        "bool": {
            "filter": [{"range": {"date": {"gte": start.strftime("%Y-%m-%d"), "lte": end.strftime("%Y-%m-%d")}}}]
        }
    }
    resp = client.search(
        index="finance_macro",
        body={"query": query, "sort": [{"date": {"order": "asc"}}], "size": 5000},
    )
    rows = [hit["_source"] for hit in resp["hits"]["hits"]]
    if not rows:
        return pd.DataFrame()
    df = pd.DataFrame(rows)
    df["date"] = pd.to_datetime(df["date"]).dt.strftime("%Y-%m-%d")
    return df.sort_values(["name", "date"])
