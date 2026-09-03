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
    """Gera textos descritivos a partir do info do ticker."""
    texts = []
    sector = info.get("sector", "Unknown")
    industry = info.get("industry", "Unknown")
    country = info.get("country", "Unknown")
    employees = info.get("fullTimeEmployees")
    summary = info.get("longBusinessSummary")
    website = info.get("website")

    # Perfil da empresa.
    profile = f"{ticker} is a {sector} company in the {industry} industry, based in {country}."
    if employees:
        profile += f" It employs approximately {employees:,} full-time employees."
    texts.append(profile)

    if summary:
        # Gera algumas variações de instrução/continuação com o sumário.
        texts.append(f"Describe the business of {ticker}. {summary}")
        texts.append(f"What does {ticker} do? {summary}")

    if website:
        texts.append(f"The corporate website of {ticker} is {website}.")

    # Métricas financeiras simples.
    market_cap = info.get("marketCap")
    if market_cap:
        texts.append(f"{ticker} has a market capitalization of {market_cap:,.0f} USD.")
    pe = info.get("trailingPE") or info.get("forwardPE")
    if pe:
        texts.append(f"{ticker} has a P/E ratio of {pe:.2f}.")
    dividend_yield = info.get("dividendYield")
    if dividend_yield:
        texts.append(f"{ticker} dividend yield is {dividend_yield*100:.2f}%.")
    return texts


def _history_texts(ticker: str, df: pd.DataFrame) -> list[str]:
    """Gera textos de análise de preços a partir de dados históricos."""
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

    # Pergunta/resposta simples baseada nos dados mais recentes.
    texts.append(
        f"What was the closing price of {ticker} on {date}? The closing price was {close:.2f}."
    )
    texts.append(
        f"What was the trading volume of {ticker} on {date}? The trading volume was {volume:,} shares."
    )

    # Janelas deslizantes de 5 dias para criar contexto.
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
