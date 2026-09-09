"""Ferramentas financeiras para o agente FinanceLLM."""
import json
import re
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional

import numpy as np
import pandas as pd
import requests
import yfinance as yf


ROOT = Path(__file__).resolve().parents[1]
RAW_DIR = ROOT / "data" / "raw"
TICKERS_PATH = ROOT / "data" / "tickers_extended.json"


def _load_tickers() -> List[str]:
    if TICKERS_PATH.exists():
        return json.loads(TICKERS_PATH.read_text(encoding="utf-8"))
    return []


def _save_tickers(tickers: List[str]) -> None:
    TICKERS_PATH.parent.mkdir(parents=True, exist_ok=True)
    TICKERS_PATH.write_text(json.dumps(sorted(set(tickers)), indent=2, ensure_ascii=False), encoding="utf-8")


def add_ticker(symbol: str) -> Dict:
    """Adiciona um ticker à lista local se for válido no Yahoo Finance."""
    ticker = _normalize_ticker(symbol)
    tickers = _load_tickers()
    if ticker in tickers:
        return {"ticker": ticker, "added": False, "message": "Ticker já existe na lista."}
    try:
        info = get_stock_info(ticker)
        if info.get("error") or not info.get("name"):
            return {"ticker": ticker, "added": False, "message": f"Ticker não encontrado no Yahoo Finance: {info.get('error', 'desconhecido')}"}
    except Exception as e:
        return {"ticker": ticker, "added": False, "message": f"Erro ao validar ticker: {e}"}
    tickers.append(ticker)
    _save_tickers(tickers)
    return {"ticker": ticker, "added": True, "message": "Ticker adicionado com sucesso."}


def yahoo_search(query: str, max_results: int = 8) -> List[Dict]:
    """Pesquisa de tickers/empresas via Yahoo Finance (yfinance.Search)."""
    try:
        s = yf.Search(query, max_results=max(20, max_results))
        quotes = s.quotes or []
        results = []
        seen = set()
        for q in quotes:
            symbol = q.get("symbol")
            if not symbol or symbol in seen:
                continue
            seen.add(symbol)
            results.append({
                "symbol": symbol,
                "name": q.get("longname") or q.get("shortname"),
                "exchange": q.get("exchange"),
                "quote_type": q.get("quoteType"),
                "sector": q.get("sector"),
                "industry": q.get("industry"),
            })
            if len(results) >= max_results:
                break
        return results
    except Exception:
        return []


def _normalize_ticker(symbol: str) -> str:
    """Normaliza tickers como EDP.LS, AAPL, etc."""
    symbol = symbol.strip().upper()
    # Mapeamento de empresas portuguesas/europeias comuns
    mapping = {
        "EDP": "EDP.LS",
        "GALP": "GALP.LS",
        "NOS": "NOS.LS",
        "MEO": "NOS.LS",
        "REN": "RENE.LS",
        "JMT": "JMT.LS",
        "BCP": "BCP.LS",
        "BPI": "BPI.LS",
        "SONAE": "SON.LS",
        "CORTICEIRA": "COR.LS",
        "ALTRI": "ALTR.LS",
    }
    if symbol in mapping:
        return mapping[symbol]
    # Se já tem sufixo de bolsa, mantém
    if "." in symbol:
        return symbol
    return symbol


def _fmt_publisher(pub):
    """Normaliza publisher de notícias para string."""
    if not pub:
        return None
    if isinstance(pub, dict):
        return pub.get("displayName") or pub.get("sourceId") or pub.get("name") or str(pub)
    return str(pub)


def extract_tickers(text: str) -> List[str]:
    """Extrai possíveis tickers/empresas do texto do utilizador."""
    # Palavras em maiúsculas com 1-5 letras, excluindo artigos/preposições comuns.
    raw = re.findall(r"\b[A-Z]{1,5}(?:\.LS|\.LB|\.PA|\.DE|\.AS|\.MI|\.MC|\.L)?\b", text)
    stopwords_upper = {
        "A", "O", "AS", "OS", "DE", "DA", "DO", "DAS", "DOS", "EM", "NO", "NA", "NOS", "NAS",
        "PARA", "POR", "COM", "SEM", "QUE", "E", "OU", "SE", "MAS", "SÃO", "FOI", "SER", "ESTAR",
        "UM", "UMA", "QUAL", "QUAIS", "COMO", "MAIS", "MENOS", "MUITO", "MUITA", "PELO", "PELA",
        "THE", "AND", "OF", "IN", "TO", "IS", "FOR", "ON", "AT", "AS", "OR", "IT", "ITS", "AN",
        "DO", "THAT", "THIS", "WITH", "FROM", "BY", "ARE", "WAS", "WERE", "BE", "BEEN", "HAVE",
        "HAS", "HAD", "WILL", "WOULD", "COULD", "SHOULD", "CAN", "MAY", "MIGHT", "SO", "IF", "BUT",
        "NOT", "YES", "PREVISÃO", "PRECO", "PREÇO", "AÇÃO", "ACAO", "MERcADO", "FUTURO", "DIAS",
    }
    candidates = [c for c in raw if c not in stopwords_upper]

    # Mapeamento manual de nomes comuns — exige correspondência de palavra inteira.
    names = {
        "edp": "EDP",
        "galp": "GALP",
        # "nos", "ren", "jmt" removidos — são palavras comuns em português.
        "bcp": "BCP",
        "bpi": "BPI",
        "sonae": "SONAE",
        "corticeira": "COR",
        "altri": "ALTR",
        "microsoft": "MSFT",
        "apple": "AAPL",
        "tesla": "TSLA",
        "google": "GOOGL",
        "alphabet": "GOOGL",
        "amazon": "AMZN",
        "nvidia": "NVDA",
        "meta": "META",
        "facebook": "META",
        "netflix": "NFLX",
        "adobe": "ADBE",
        "salesforce": "CRM",
        "oracle": "ORCL",
        "intel": "INTC",
        "amd": "AMD",
    }
    lower_text = text.lower()
    for word, symbol in names.items():
        if re.search(rf"\b{re.escape(word)}\b", lower_text) and symbol not in candidates:
            candidates.append(symbol)
    return list(dict.fromkeys(candidates))


def _safe_pct(value: Optional[float]) -> Optional[float]:
    """Normaliza percentagens yfinance (0.015 -> 1.5%)."""
    if value is None or not isinstance(value, (int, float)) or pd.isna(value):
        return None
    # yfinance devolve dividendYield e returnOnEquity como fração decimal
    return round(value * 100, 3) if abs(value) < 1 else round(value, 3)


def get_stock_info(symbol: str) -> Dict:
    """Obtém informação rica de uma ação via yfinance."""
    ticker = _normalize_ticker(symbol)
    try:
        t = yf.Ticker(ticker)
        info = t.info or {}
        # Guardar raw
        (RAW_DIR / "yfinance").mkdir(parents=True, exist_ok=True)
        with open(RAW_DIR / "yfinance" / f"{ticker}_info.json", "w", encoding="utf-8") as f:
            json.dump(info, f, indent=2, default=str)

        # KPIs adicionais úteis para decisão
        kpi_float_keys = {
            "beta", "52WeekChange", "SandP52WeekChange", "returnOnAssets",
            "returnOnEquity", "revenueGrowth", "earningsGrowth", "grossMargins",
            "operatingMargins", "profitMargins", "ebitdaMargins", "currentPrice",
            "targetHighPrice", "targetLowPrice", "targetMeanPrice", "targetMedianPrice",
            "recommendationMean", "numberOfAnalystOpinions", "quickRatio", "currentRatio",
            "totalDebtPerShare", "revenuePerShare", "heldPercentInsiders",
            "heldPercentInstitutions", "shortRatio", "shortPercentOfFloat",
            "enterpriseToEbitda", "enterpriseToRevenue", "trailingPE", "forwardPE",
            "priceToBook", "priceToSalesTrailing12Months", "enterpriseValue",
            "totalRevenue", "grossProfits", "ebitda", "netIncomeToCommon",
            "totalCash", "totalDebt", "bookValue", "trailingEps", "forwardEps",
            "impliedSharesOutstanding", "floatShares", "sharesOutstanding",
        }
        kpis = {}
        for k in kpi_float_keys:
            v = info.get(k)
            if isinstance(v, (int, float)) and not pd.isna(v):
                kpis[k] = v

        return {
            "ticker": ticker,
            "name": info.get("longName", info.get("shortName", ticker)),
            "currency": info.get("currency", "N/A"),
            "price": info.get("currentPrice", info.get("regularMarketPrice")),
            "market_cap": info.get("marketCap"),
            "pe": info.get("trailingPE", info.get("forwardPE")),
            "eps": info.get("trailingEps", info.get("forwardEps")),
            "dividend_yield": _safe_pct(info.get("dividendYield")),
            "roe": _safe_pct(info.get("returnOnEquity")),
            "sector": info.get("sector", "N/A"),
            "industry": info.get("industry", "N/A"),
            "website": info.get("website"),
            "country": info.get("country"),
            "employees": info.get("fullTimeEmployees"),
            "summary": info.get("longBusinessSummary"),
            "exchange": info.get("exchange"),
            "quote_type": info.get("quoteType"),
            "beta": info.get("beta"),
            "target_mean_price": info.get("targetMeanPrice"),
            "target_high_price": info.get("targetHighPrice"),
            "target_low_price": info.get("targetLowPrice"),
            "recommendation": info.get("recommendationKey"),
            "recommendation_mean": info.get("recommendationMean"),
            "number_of_analysts": info.get("numberOfAnalystOpinions"),
            "kpis": kpis,
        }
    except Exception as e:
        return {"ticker": ticker, "error": str(e)}


def get_stock_history(symbol: str, period: str = "1y", interval: str = "1d") -> pd.DataFrame:
    """Obtém histórico de preços usando Ticker.history (mais robusto que download)."""
    ticker = _normalize_ticker(symbol)
    ticker_obj = yf.Ticker(ticker)
    df = ticker_obj.history(period=period, interval=interval, auto_adjust=True)
    if df.empty:
        return df
    df = df.reset_index()
    # yfinance pode devolver MultiIndex de colunas (ticker, campo). Achatar.
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = [" ".join(str(c) for c in col if c not in [ticker, ""]).strip() or str(col[-1]) for col in df.columns.values]
    else:
        df.columns = [str(c).split("_")[0].split("'")[0] for c in df.columns]
    # Normalizar nomes comuns para maiúsculas
    rename = {
        "date": "Date",
        "open": "Open",
        "high": "High",
        "low": "Low",
        "close": "Close",
        "adj close": "Adj Close",
        "volume": "Volume",
    }
    df = df.rename(columns={c: rename.get(c.lower(), c) for c in df.columns})
    # Garantir coluna Close
    if "Close" not in df.columns and "Adj Close" in df.columns:
        df = df.rename(columns={"Adj Close": "Close"})
    df["ticker"] = ticker
    return df


def get_dividends(symbol: str) -> Dict:
    """Obtém dividendos históricos."""
    ticker = _normalize_ticker(symbol)
    try:
        t = yf.Ticker(ticker)
        divs = t.dividends
        if divs is None or divs.empty:
            return {"ticker": ticker, "dividends": []}
        if isinstance(divs, pd.Series):
            divs = divs.to_frame(name="dividend")
        divs = divs.reset_index()
        divs["Date"] = pd.to_datetime(divs["Date"]).dt.strftime("%Y-%m-%d")
        return {
            "ticker": ticker,
            "dividends": divs.tail(10).to_dict(orient="records"),
        }
    except Exception as e:
        return {"ticker": ticker, "error": str(e)}


def _df_to_jsonable(df: pd.DataFrame) -> Dict:
    """Converte DataFrame do yfinance num dicionário JSON-safe com datas como strings."""
    if df is None or df.empty:
        return {}
    # yfinance usa Timestamps como índice/colunas; normalizamos para strings ISO.
    df = df.copy()
    if isinstance(df.index, pd.DatetimeIndex):
        df.index = df.index.strftime("%Y-%m-%d")
    for col in df.columns:
        if isinstance(df[col].index, pd.DatetimeIndex):
            df[col].index = df[col].index.strftime("%Y-%m-%d")
    d = df.to_dict()
    # Converter quaisquer Timestamp restantes em chaves para strings
    d = {str(k): v for k, v in d.items()}
    return d


def get_financials(symbol: str) -> Dict:
    """Obtém demonstrações financeiras anuais e trimestrais via yfinance."""
    ticker = _normalize_ticker(symbol)
    try:
        t = yf.Ticker(ticker)
        inc = t.financials
        bal = t.balance_sheet
        cf = t.cashflow
        inc_q = t.quarterly_financials
        bal_q = t.quarterly_balance_sheet
        cf_q = t.quarterly_cashflow
        return {
            "ticker": ticker,
            "income_statement": _df_to_jsonable(inc),
            "balance_sheet": _df_to_jsonable(bal),
            "cash_flow": _df_to_jsonable(cf),
            "quarterly_income_statement": _df_to_jsonable(inc_q),
            "quarterly_balance_sheet": _df_to_jsonable(bal_q),
            "quarterly_cash_flow": _df_to_jsonable(cf_q),
        }
    except Exception as e:
        return {
            "ticker": ticker,
            "error": str(e),
            "income_statement": {},
            "balance_sheet": {},
            "cash_flow": {},
            "quarterly_income_statement": {},
            "quarterly_balance_sheet": {},
            "quarterly_cash_flow": {},
        }


def get_sec_filings_yahoo(symbol: str, max_age_days: int = 365) -> List[Dict]:
    """Obtém filings SEC publicados no Yahoo Finance para o ticker."""
    ticker = _normalize_ticker(symbol)
    try:
        t = yf.Ticker(ticker)
        filings = t.sec_filings or []
        cutoff = datetime.now() - timedelta(days=max_age_days)
        out = []
        for f in filings:
            d = f.get("date")
            if isinstance(d, datetime) and d < cutoff:
                continue
            out.append({
                "date": str(d) if d else None,
                "type": f.get("type"),
                "title": f.get("title"),
                "url": f.get("edgarUrl") or (f.get("exhibits") or {}).get(f.get("type")),
            })
        return out
    except Exception:
        return []


def get_holders(symbol: str) -> Dict:
    """Obtém principais detentores institucionais e insiders."""
    ticker = _normalize_ticker(symbol)
    try:
        t = yf.Ticker(ticker)
        return {
            "ticker": ticker,
            "institutional": _df_to_jsonable(t.institutional_holders),
            "mutual_fund": _df_to_jsonable(t.mutualfund_holders),
            "major": _df_to_jsonable(t.major_holders),
            "insider_transactions": _df_to_jsonable(t.insider_transactions),
            "insider_purchases": _df_to_jsonable(t.insider_purchases),
        }
    except Exception as e:
        return {"ticker": ticker, "error": str(e)}


def get_sustainability(symbol: str) -> Dict:
    """Obtém score de sustentabilidade ESG do Yahoo Finance."""
    ticker = _normalize_ticker(symbol)
    try:
        t = yf.Ticker(ticker)
        return {"ticker": ticker, "esg": _df_to_jsonable(t.sustainability)}
    except Exception as e:
        return {"ticker": ticker, "error": str(e)}


def get_recommendations(symbol: str) -> Dict:
    """Obtém recomendações e upgrades/downgrades recentes de analistas."""
    ticker = _normalize_ticker(symbol)
    try:
        t = yf.Ticker(ticker)
        return {
            "ticker": ticker,
            "recommendations": _df_to_jsonable(t.recommendations),
            "recommendations_summary": _df_to_jsonable(t.recommendations_summary),
            "upgrades_downgrades": _df_to_jsonable(t.upgrades_downgrades),
        }
    except Exception as e:
        return {"ticker": ticker, "error": str(e)}


def get_calendar(symbol: str) -> Dict:
    """Obtém calendário de earnings e dividendos."""
    ticker = _normalize_ticker(symbol)
    try:
        t = yf.Ticker(ticker)
        return {
            "ticker": ticker,
            "calendar": _df_to_jsonable(t.calendar),
            "earnings_dates": _df_to_jsonable(t.earnings_dates),
        }
    except Exception as e:
        return {"ticker": ticker, "error": str(e)}


def get_news(symbol: str, max_items: int = 10) -> Dict:
    """Obtém notícias recentes do Yahoo Finance."""
    ticker = _normalize_ticker(symbol)
    try:
        t = yf.Ticker(ticker)
        raw = t.news or []
        out = []
        for n in raw[:max_items]:
            content = n.get("content") or n
            out.append({
                "title": content.get("title") or content.get("summary"),
                "publisher": _fmt_publisher(content.get("publisher", content.get("provider"))),
                "published": content.get("pubDate") or content.get("published"),
                "url": content.get("canonicalUrl", {}).get("url") if isinstance(content.get("canonicalUrl"), dict) else content.get("link"),
                "summary": content.get("summary"),
            })
        return {"ticker": ticker, "news": out}
    except Exception as e:
        return {"ticker": ticker, "error": str(e)}


def get_options(symbol: str) -> Dict:
    """Obtém datas de expiração e cadeias de opções disponíveis."""
    ticker = _normalize_ticker(symbol)
    try:
        t = yf.Ticker(ticker)
        dates = list(t.options) if t.options else []
        chains = []
        for d in dates[:2]:
            try:
                chain = t.option_chain(d)
                chains.append({
                    "date": d,
                    "calls": _df_to_jsonable(chain.calls),
                    "puts": _df_to_jsonable(chain.puts),
                })
            except Exception:
                continue
        return {"ticker": ticker, "expiration_dates": dates, "chains": chains}
    except Exception as e:
        return {"ticker": ticker, "error": str(e)}


def get_actions(symbol: str) -> Dict:
    """Obtém splits, dividendos e capital actions históricas."""
    ticker = _normalize_ticker(symbol)
    try:
        t = yf.Ticker(ticker)
        actions = t.actions
        splits = t.splits
        dividends = t.dividends
        return {
            "ticker": ticker,
            "actions": _df_to_jsonable(actions),
            "splits": _df_to_jsonable(splits.to_frame(name="split") if isinstance(splits, pd.Series) else splits),
            "dividends": _df_to_jsonable(dividends.to_frame(name="dividend") if isinstance(dividends, pd.Series) else dividends),
        }
    except Exception as e:
        return {"ticker": ticker, "error": str(e)}


def get_technical_indicators(symbol: str, period: str = "1y") -> Dict:
    """Calcula indicadores técnicos clássicos a partir do histórico de preços."""
    ticker = _normalize_ticker(symbol)
    try:
        df = get_stock_history(ticker, period=period)
        if df.empty or "Close" not in df.columns:
            return {"ticker": ticker, "error": "Histórico de preços vazio ou sem coluna Close"}

        close = pd.Series(df["Close"].values.ravel() if isinstance(df["Close"].values, np.ndarray) else df["Close"])
        high = pd.Series(df["High"].values.ravel() if isinstance(df["High"].values, np.ndarray) else df["High"]) if "High" in df.columns else close
        low = pd.Series(df["Low"].values.ravel() if isinstance(df["Low"].values, np.ndarray) else df["Low"]) if "Low" in df.columns else close
        volume = pd.Series(df["Volume"].values.ravel() if isinstance(df["Volume"].values, np.ndarray) else df["Volume"]) if "Volume" in df.columns else pd.Series([0] * len(close))

        def _ema(series: pd.Series, span: int) -> pd.Series:
            return series.ewm(span=span, adjust=False).mean()

        def _sma(series: pd.Series, window: int) -> pd.Series:
            return series.rolling(window=window).mean()

        def _rsi(series: pd.Series, window: int = 14) -> pd.Series:
            delta = series.diff()
            gain = delta.where(delta > 0, 0.0)
            loss = -delta.where(delta < 0, 0.0)
            avg_gain = gain.rolling(window=window).mean()
            avg_loss = loss.rolling(window=window).mean()
            rs = avg_gain / avg_loss.replace(0, np.nan)
            rsi = 100 - (100 / (1 + rs))
            return rsi.fillna(50)

        def _macd(series: pd.Series) -> tuple:
            ema12 = _ema(series, 12)
            ema26 = _ema(series, 26)
            macd = ema12 - ema26
            signal = _ema(macd, 9)
            hist = macd - signal
            return macd, signal, hist

        def _bb(series: pd.Series, window: int = 20) -> tuple:
            sma = _sma(series, window)
            std = series.rolling(window=window).std()
            upper = sma + 2 * std
            lower = sma - 2 * std
            return upper, sma, lower

        def _atr(h: pd.Series, l: pd.Series, c: pd.Series, window: int = 14) -> pd.Series:
            prev_close = c.shift(1)
            tr1 = h - l
            tr2 = (h - prev_close).abs()
            tr3 = (l - prev_close).abs()
            tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
            return tr.rolling(window=window).mean()

        def _obv(c: pd.Series, vol: pd.Series) -> pd.Series:
            obv = [0.0]
            for i in range(1, len(c)):
                if c.iloc[i] > c.iloc[i - 1]:
                    obv.append(obv[-1] + vol.iloc[i])
                elif c.iloc[i] < c.iloc[i - 1]:
                    obv.append(obv[-1] - vol.iloc[i])
                else:
                    obv.append(obv[-1])
            return pd.Series(obv, index=c.index)

        sma20 = _sma(close, 20)
        sma50 = _sma(close, 50)
        sma200 = _sma(close, 200)
        ema12 = _ema(close, 12)
        ema26 = _ema(close, 26)
        rsi14 = _rsi(close, 14)
        macd_line, macd_signal, macd_hist = _macd(close)
        bb_upper, bb_middle, bb_lower = _bb(close)
        atr14 = _atr(high, low, close)
        obv_series = _obv(close, volume)

        # Índice de datas (strings) alinhado com as séries
        dates = df["Date"].astype(str).tolist()

        def _points(series: pd.Series) -> List[Optional[float]]:
            vals = series.where(pd.notna(series), None).tolist()
            # json-safe: converter numpy floats para float nativo
            return [(float(v) if v is not None and not isinstance(v, (str, type(None))) else v) for v in vals]

        return {
            "ticker": ticker,
            "period": period,
            "dates": dates,
            "price": _points(close),
            "volume": _points(volume),
            "sma20": _points(sma20),
            "sma50": _points(sma50),
            "sma200": _points(sma200),
            "ema12": _points(ema12),
            "ema26": _points(ema26),
            "rsi14": _points(rsi14),
            "macd": _points(macd_line),
            "macd_signal": _points(macd_signal),
            "macd_histogram": _points(macd_hist),
            "bb_upper": _points(bb_upper),
            "bb_middle": _points(bb_middle),
            "bb_lower": _points(bb_lower),
            "atr14": _points(atr14),
            "obv": _points(obv_series),
        }
    except Exception as e:
        return {"ticker": ticker, "error": str(e)}


def get_macro_indicator(series_id: str = "DGS10") -> Dict:
    """Obtém um indicador macro via FRED (requer chave de API no .env)."""
    from fredapi import Fred
    import os

    key = os.getenv("FRED_API_KEY")
    if not key:
        return {"series_id": series_id, "error": "FRED_API_KEY não configurada"}
    try:
        fred = Fred(api_key=key)
        s = fred.get_series(series_id)
        last = s.dropna().iloc[-1]
        return {
            "series_id": series_id,
            "value": float(last),
            "date": str(s.dropna().index[-1].date()),
        }
    except Exception as e:
        return {"series_id": series_id, "error": str(e)}


def forecast_prices(symbol: str, future_days: int = 5, period: str = "5y") -> Dict:
    """Gera previsão ARIMA de preços para um ticker.

    Usa log-retornos, divisão temporal estrita, métricas de erro e
    bandas de confiança. Guarda o gráfico em data/forecasting/.
    """
    from forecasting.arima_model import run_full_pipeline

    ticker = _normalize_ticker(symbol)
    try:
        result = run_full_pipeline(
            ticker=ticker,
            period=period,
            order=(2, 1, 2),
            train_ratio=0.85,
            future_steps=future_days,
        )
        return result.to_dict()
    except Exception as e:
        return {"ticker": ticker, "error": str(e)}


from api.explain_technical import explain_technical_indicators

# Registo de ferramentas disponíveis para o agente
TOOLS = {
    "get_stock_info": get_stock_info,
    "get_stock_history": get_stock_history,
    "get_dividends": get_dividends,
    "get_macro_indicator": get_macro_indicator,
    "forecast_prices": forecast_prices,
    "yahoo_search": yahoo_search,
    "add_ticker": add_ticker,
    "get_financials": get_financials,
    "get_sec_filings_yahoo": get_sec_filings_yahoo,
    "get_holders": get_holders,
    "get_sustainability": get_sustainability,
    "get_recommendations": get_recommendations,
    "get_calendar": get_calendar,
    "get_news": get_news,
    "get_options": get_options,
    "get_actions": get_actions,
}
