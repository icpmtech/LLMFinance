"""Ferramentas financeiras para o agente FinanceLLM."""
import json
import re
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional

import pandas as pd
import requests
import yfinance as yf


ROOT = Path(__file__).resolve().parents[1]
RAW_DIR = ROOT / "data" / "raw"


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
        "BCP": "BCP.LB",
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


def extract_tickers(text: str) -> List[str]:
    """Extrai possíveis tickers/empresas do texto do utilizador."""
    # Palavras em maiúsculas com 1-5 letras
    candidates = re.findall(r"\b[A-Z]{1,5}(?:\.LS|\.LB|\.PA|\.DE|\.AS|\.MI|\.MC|\.L)?\b", text)
    # Mapeamento manual de nomes comuns
    names = {
        "edp": "EDP",
        "galp": "GALP",
        "nos": "NOS",
        "ren": "REN",
        "jmt": "JMT",
        "bcp": "BCP",
        "bpi": "BPI",
        "sonae": "SONAE",
        "microsoft": "MSFT",
        "apple": "AAPL",
        "tesla": "TSLA",
        "google": "GOOGL",
        "alphabet": "GOOGL",
        "amazon": "AMZN",
        "nvidia": "NVDA",
    }
    for word, symbol in names.items():
        if word in text.lower() and symbol not in candidates:
            candidates.append(symbol)
    return list(dict.fromkeys(candidates))


def get_stock_info(symbol: str) -> Dict:
    """Obtém informação básica de uma ação via yfinance."""
    ticker = _normalize_ticker(symbol)
    try:
        t = yf.Ticker(ticker)
        info = t.info or {}
        # Guardar raw
        (RAW_DIR / "yfinance").mkdir(parents=True, exist_ok=True)
        with open(RAW_DIR / "yfinance" / f"{ticker}_info.json", "w", encoding="utf-8") as f:
            json.dump(info, f, indent=2, default=str)
        return {
            "ticker": ticker,
            "name": info.get("longName", info.get("shortName", ticker)),
            "currency": info.get("currency", "N/A"),
            "price": info.get("currentPrice", info.get("regularMarketPrice", "N/A")),
            "dividend_yield": info.get("dividendYield", "N/A"),
            "pe": info.get("trailingPE", info.get("forwardPE", "N/A")),
            "roe": info.get("returnOnEquity", "N/A"),
            "sector": info.get("sector", "N/A"),
            "website": info.get("website"),
        }
    except Exception as e:
        return {"ticker": ticker, "error": str(e)}


def get_stock_history(symbol: str, period: str = "1y") -> pd.DataFrame:
    """Obtém histórico de preços."""
    ticker = _normalize_ticker(symbol)
    df = yf.download(ticker, period=period, interval="1d", progress=False, auto_adjust=True)
    if df.empty:
        return df
    df = df.reset_index()
    # Normalizar colunas para nomes simples
    df.columns = [str(c).split("_")[0].split("'")[0] for c in df.columns]
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


# Registo de ferramentas disponíveis para o agente
TOOLS = {
    "get_stock_info": get_stock_info,
    "get_stock_history": get_stock_history,
    "get_dividends": get_dividends,
    "get_macro_indicator": get_macro_indicator,
}
