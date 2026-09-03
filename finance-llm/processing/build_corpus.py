"""Gera corpus textual a partir de dados Yahoo Finance para treino do LLM."""
from pathlib import Path
import json
import random
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
RAW_DIR = ROOT / "data" / "raw" / "yfinance"
FINAL_DIR = ROOT / "data" / "final"
FINAL_DIR.mkdir(parents=True, exist_ok=True)

# Garante reprodutibilidade na divisão treino/validação/teste.
random.seed(42)


def _info_text(ticker: str, info: dict) -> list[str]:
    """Gera textos no formato instrução/resposta a partir do info do ticker."""
    texts = []
    sector = info.get("sector", "Unknown")
    industry = info.get("industry", "Unknown")
    country = info.get("country", "Unknown")
    employees = info.get("fullTimeEmployees")
    summary = info.get("longBusinessSummary")
    website = info.get("website")
    name = info.get("longName") or info.get("shortName") or ticker
    currency = info.get("currency", "USD")

    # Perfil da empresa em formato conversacional.
    profile = f"{ticker} is a {sector} company in the {industry} industry, based in {country}."
    if employees:
        profile += f" It employs approximately {employees:,} full-time employees."
    texts.append(profile)

    # Instrução/resposta: identidade e negócio.
    if summary:
        texts.append(f"Instruction: Describe the business of {ticker}.\nResponse: {summary}")
        texts.append(f"Instruction: What does {ticker} do?\nResponse: {summary}")
        texts.append(f"Instruction: Summarize the business of {name} ({ticker}).\nResponse: {summary}")
        texts.append(f"Question: What does {ticker} do? Answer: {summary}")
        texts.append(f"Question: Describe the business of {ticker}. Answer: {summary}")

    if website:
        texts.append(f"Instruction: What is the corporate website of {ticker}?\nResponse: {website}")
        texts.append(f"Question: What is the corporate website of {ticker}? Answer: {website}")

    # Métricas financeiras com contexto factual.
    market_cap = info.get("marketCap")
    if market_cap:
        texts.append(f"{ticker} has a market capitalization of {market_cap:,.0f} {currency}.")
        texts.append(f"Instruction: What is the market capitalization of {ticker}?\nResponse: {name} ({ticker}) has a market capitalization of {market_cap:,.0f} {currency}.")
        texts.append(f"Question: What is the market capitalization of {ticker}? Answer: {market_cap:,.0f} {currency}.")

    pe = info.get("trailingPE") or info.get("forwardPE")
    if pe:
        texts.append(f"{ticker} has a P/E ratio of {pe:.2f}.")
        texts.append(f"Instruction: What is the P/E ratio of {ticker}?\nResponse: {name} ({ticker}) has a P/E ratio of {pe:.2f}.")
        texts.append(f"Question: What is the P/E ratio of {ticker}? Answer: {pe:.2f}.")

    dividend_yield = info.get("dividendYield")
    if dividend_yield:
        # yfinance pode devolver 0.048 (proporção) ou 4.8 (percentagem).
        dy_pct = dividend_yield * 100 if dividend_yield <= 1 else dividend_yield
        texts.append(f"{ticker} dividend yield is {dy_pct:.2f}%.")
        texts.append(f"Instruction: What is the dividend yield of {ticker}?\nResponse: {name} ({ticker}) has a dividend yield of {dy_pct:.2f}%.")
        texts.append(f"Question: What is the dividend yield of {ticker}? Answer: {dy_pct:.2f}%.")

    eps = info.get("trailingEps") or info.get("forwardEps")
    if eps:
        texts.append(f"Instruction: What is the EPS of {ticker}?\nResponse: {name} ({ticker}) has an EPS of {eps:.2f} {currency}.")
        texts.append(f"Question: What is the EPS of {ticker}? Answer: {eps:.2f} {currency}.")

    beta = info.get("beta")
    if beta is not None:
        texts.append(f"Instruction: What is the beta of {ticker}?\nResponse: {name} ({ticker}) has a beta of {beta:.2f}.")
        texts.append(f"Question: What is the beta of {ticker}? Answer: {beta:.2f}.")

    price = info.get("currentPrice") or info.get("previousClose") or info.get("regularMarketPrice")
    if price:
        texts.append(f"Instruction: What is the current price of {ticker}?\nResponse: {name} ({ticker}) is trading at {price:.2f} {currency}.")
        texts.append(f"Question: What is the current price of {ticker}? Answer: {price:.2f} {currency}.")

    texts.append(
        f"Instruction: Where is {ticker} based and what industry is it in?\n"
        f"Response: {name} ({ticker}) is a {sector} company in the {industry} industry, based in {country}."
    )
    texts.append(
        f"Question: Where is {ticker} based and what industry is it in? "
        f"Answer: {ticker} is a {sector} company in the {industry} industry, based in {country}."
    )
    return texts


def _history_texts(ticker: str, df: pd.DataFrame) -> list[str]:
    """Gera textos de análise de preços no formato instrução/resposta."""
    texts = []
    if df.empty:
        return texts
    df = df.reset_index()
    # Garante nomes de colunas simples, sem MultiIndex.
    df.columns = [c[0] if isinstance(c, tuple) else c for c in df.columns]

    required = ["Date", "Open", "High", "Low", "Close", "Volume"]
    if not all(c in df.columns for c in required):
        return texts

    df = df.sort_values("Date").reset_index(drop=True)
    latest = df.iloc[-1]
    prev = df.iloc[-2] if len(df) > 1 else latest

    date = str(latest["Date"])[:10]
    close = float(latest["Close"])
    open_ = float(latest["Open"])
    high = float(latest["High"])
    low = float(latest["Low"])
    volume = int(latest["Volume"])

    # Resumo diário.
    daily = (
        f"On {date}, {ticker} opened at {open_:.2f}, reached a high of {high:.2f}, "
        f"a low of {low:.2f}, and closed at {close:.2f}, with a volume of {volume:,} shares."
    )
    texts.append(daily)

    # Variação percentual.
    prev_close = float(prev["Close"])
    change = close - prev_close
    pct = (change / prev_close * 100) if prev_close else 0.0
    direction = "up" if change >= 0 else "down"
    texts.append(
        f"{ticker} closed {direction} {abs(pct):.2f}% from the previous close of {prev_close:.2f} to {close:.2f}."
    )

    # Instrução/resposta com cotação diária.
    texts.append(
        f"Instruction: What was the closing price of {ticker} on {date}?\n"
        f"Response: The closing price of {ticker} on {date} was {close:.2f}."
    )
    texts.append(
        f"Question: What was the closing price of {ticker} on {date}? Answer: The closing price was {close:.2f}."
    )
    texts.append(
        f"Instruction: What was the trading volume of {ticker} on {date}?\n"
        f"Response: The trading volume of {ticker} on {date} was {volume:,} shares."
    )
    texts.append(
        f"Question: What was the trading volume of {ticker} on {date}? Answer: The trading volume was {volume:,} shares."
    )
    texts.append(
        f"Instruction: What was the daily high of {ticker} on {date}?\nResponse: The daily high of {ticker} on {date} was {high:.2f}."
    )
    texts.append(
        f"Question: What was the daily high of {ticker} on {date}? Answer: The daily high was {high:.2f}."
    )
    texts.append(
        f"Instruction: What was the daily low of {ticker} on {date}?\nResponse: The daily low of {ticker} on {date} was {low:.2f}."
    )
    texts.append(
        f"Question: What was the daily low of {ticker} on {date}? Answer: The daily low was {low:.2f}."
    )
    texts.append(
        f"Instruction: Summarize the recent price trend of {ticker}.\n"
        f"Response: On {date}, {ticker} opened at {open_:.2f}, reached a high of {high:.2f}, "
        f"a low of {low:.2f}, and closed at {close:.2f}, with a volume of {volume:,} shares. "
        f"The stock closed {direction} {abs(pct):.2f}% from the previous close of {prev_close:.2f}."
    )
    texts.append(
        f"Question: Summarize the recent price trend of {ticker}. "
        f"Answer: On {date}, {ticker} opened at {open_:.2f}, reached a high of {high:.2f}, "
        f"a low of {low:.2f}, and closed at {close:.2f}, with a volume of {volume:,} shares. "
        f"The stock closed {direction} {abs(pct):.2f}% from the previous close of {prev_close:.2f}."
    )

    # Médias móveis e tendências de curto prazo.
    for window_days in [5, 10, 20, 50]:
        if len(df) >= window_days:
            recent = df.tail(window_days)
            closes = [float(c) for c in recent["Close"].tolist()]
            avg = sum(closes) / len(closes)
            start = float(recent["Close"].iloc[0])
            end = float(recent["Close"].iloc[-1])
            trend = "upward" if end >= start else "downward"
            texts.append(
                f"Instruction: What is the {window_days}-day moving average of {ticker}?\n"
                f"Response: The {window_days}-day moving average of {ticker} is approximately {avg:.2f}, "
                f"with the price moving in a {trend} trend."
            )
            texts.append(
                f"Question: What is the {window_days}-day moving average of {ticker}? "
                f"Answer: The {window_days}-day moving average of {ticker} is approximately {avg:.2f}, "
                f"with the price moving in a {trend} trend."
            )

    # Janelas deslizantes de 5 dias.
    for i in range(5, len(df)):
        window = df.iloc[i - 5 : i + 1]
        dates = [str(d)[:10] for d in window["Date"].tolist()]
        closes = [float(c) for c in window["Close"].tolist()]
        text = (
            f"{ticker} 5-day price trend from {dates[0]} to {dates[-1]}: "
            + ", ".join(f"{d} {c:.2f}" for d, c in zip(dates, closes))
            + "."
        )
        texts.append(text)
    return texts


def build_corpus() -> None:
    """Gera ficheiros JSONL finais a partir dos dados raw do Yahoo Finance."""
    all_texts: list[str] = []
    for info_path in sorted(RAW_DIR.glob("*_info.json")):
        ticker = info_path.stem.replace("_info", "")
        price_path = RAW_DIR / f"{ticker}_1d.parquet"
        if not price_path.exists():
            continue
        with info_path.open("r", encoding="utf-8") as f:
            info = json.load(f)
        df = pd.read_parquet(price_path)

        all_texts.extend(_info_text(ticker, info))
        all_texts.extend(_history_texts(ticker, df))

    random.shuffle(all_texts)

    n = len(all_texts)
    if n == 0:
        raise ValueError("Não foram encontrados textos para treino.")

    n_test = max(1, int(n * 0.1))
    n_val = max(1, int(n * 0.1))
    n_train = n - n_test - n_val

    splits = {
        "train": all_texts[:n_train],
        "validation": all_texts[n_train : n_train + n_val],
        "test": all_texts[n_train + n_val :],
    }

    for split, texts in splits.items():
        path = FINAL_DIR / f"{split}.jsonl"
        with path.open("w", encoding="utf-8") as f:
            for text in texts:
                f.write(json.dumps({"text": text}, ensure_ascii=False) + "\n")
        print(f"{path}: {len(texts)} examples")


if __name__ == "__main__":
    build_corpus()
