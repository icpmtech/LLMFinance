"""Backend Kronos para previsão de preços financeiros.

Este módulo integra o modelo fundacional Kronos (decoder-only para séries temporais
financeiras) como alternativa ao ARIMA. Usa os checkpoints NeoQuasar no HuggingFace:

- Kronos-mini (4.1M params, contexto 2048) + tokenizer Kronos-Tokenizer-2k
- Kronos-small (24.7M params, contexto 512) + tokenizer Kronos-Tokenizer-base
- Kronos-base (102.3M params, contexto 512) + tokenizer Kronos-Tokenizer-base

A entrada requer OHLCV diário. Como yfinance fornece Close ajustado e Volume,
sintetizamos Open/High/Low a partir do Close (heurístico) para alimentar o
KronosPredictor. O output é convertido para ForecastResult para reutilizar o
gráfico e a explicação existentes.
"""
from __future__ import annotations

import warnings
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Optional

import matplotlib
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import torch

from forecasting.arima_model import download_close_prices

matplotlib.use("Agg")
warnings.filterwarnings("ignore", category=UserWarning)

ROOT = Path(__file__).resolve().parents[1]
OUTPUT_DIR = ROOT / "data" / "forecasting"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

MODEL_CONFIGS = {
    "kronos-mini": {
        "model_id": "NeoQuasar/Kronos-mini",
        "tokenizer_id": "NeoQuasar/Kronos-Tokenizer-2k",
        "max_context": 2048,
    },
    "kronos-small": {
        "model_id": "NeoQuasar/Kronos-small",
        "tokenizer_id": "NeoQuasar/Kronos-Tokenizer-base",
        "max_context": 512,
    },
    "kronos-base": {
        "model_id": "NeoQuasar/Kronos-base",
        "tokenizer_id": "NeoQuasar/Kronos-Tokenizer-base",
        "max_context": 512,
    },
}


# Cache global lazy para evitar recarregar o modelo a cada pedido.
_MODEL_CACHE: dict[str, dict] = {}


def _get_device() -> str:
    if torch.cuda.is_available():
        return "cuda:0"
    if getattr(torch.backends, "mps", None) and torch.backends.mps.is_available():
        return "mps"
    return "cpu"


def _load_kronos_model(variant: str = "kronos-mini"):
    """Carrega/tokeniza o modelo Kronos com cache global."""
    if variant in _MODEL_CACHE:
        return _MODEL_CACHE[variant]

    cfg = MODEL_CONFIGS.get(variant)
    if cfg is None:
        raise ValueError(f"Variante Kronos desconhecida: {variant}. Use: {list(MODEL_CONFIGS.keys())}")

    from forecasting.kronos_src import Kronos, KronosPredictor, KronosTokenizer

    device = _get_device()
    tokenizer = KronosTokenizer.from_pretrained(cfg["tokenizer_id"])
    model = Kronos.from_pretrained(cfg["model_id"])
    tokenizer.eval()
    model.eval()
    predictor = KronosPredictor(model, tokenizer, device=device, max_context=cfg["max_context"])
    entry = {"predictor": predictor, "tokenizer": tokenizer, "model": model}
    _MODEL_CACHE[variant] = entry
    return entry


def _build_ohlcv(ticker: str, period: str = "5y") -> pd.DataFrame:
    """Descarrega preços diários e constrói DataFrame OHLCV sintetizado.

    O Kronos espera colunas open, high, low, close, volume, amount. Como o Yahoo
    fornece Close ajustado, usamos o retorno intra-dia estimado a partir de
    volatility EWMA do close para gerar O/H/L plausíveis. Volume é real quando
    disponível. 'amount' é estimado como volume * close.
    """
    ticker = ticker.strip().upper()
    close = download_close_prices(ticker, period=period)
    if close.empty:
        raise ValueError(f"Sem dados para {ticker} no período {period}")

    # Estima volatilidade intra-dia simplificada (desvio padrão EWMA dos log-retornos)
    log_ret = np.log(close).diff().dropna()
    daily_vol = log_ret.ewm(span=30).std().iloc[-1]
    if pd.isna(daily_vol) or daily_vol <= 0:
        daily_vol = float(log_ret.std()) or 0.01

    # Simula OHLC a partir do close com range intra-dia estocástico.
    rng = np.random.default_rng(42)
    half_range = close * daily_vol * rng.lognormal(0.0, 0.5, size=len(close))
    half_range = pd.Series(half_range, index=close.index).clip(lower=close * 0.001)

    df = pd.DataFrame({
        "timestamps": close.index,
        "close": close.values,
    })
    # open próximo do close anterior
    df["open"] = close.shift(1).bfill().values
    df["high"] = np.maximum(np.maximum(df["open"], df["close"]) + half_range.values * 0.4, df[["open", "close"]].max(axis=1))
    df["low"] = np.minimum(np.minimum(df["open"], df["close"]) - half_range.values * 0.4, df[["open", "close"]].min(axis=1))

    # Volume: tentar descarregar do Yahoo. Se falhar, usar zeros.
    try:
        import yfinance as yf
        vol_df = yf.download(ticker, period=period, interval="1d", progress=False)
        if not vol_df.empty and "Volume" in vol_df.columns:
            vol = vol_df["Volume"].squeeze()
            vol.index = pd.to_datetime(vol.index)
            vol = vol.reindex(close.index, method="ffill").fillna(0).astype(float)
        else:
            vol = pd.Series(0.0, index=close.index)
    except Exception:
        vol = pd.Series(0.0, index=close.index)

    df["volume"] = vol.values
    df["amount"] = (df["volume"] * df["close"]).values
    df = df[["timestamps", "open", "high", "low", "close", "volume", "amount"]]
    df = df.dropna().reset_index(drop=True)
    df["timestamps"] = pd.to_datetime(df["timestamps"])
    return df


def _future_business_days(last_date: pd.Timestamp, n: int) -> pd.DatetimeIndex:
    return pd.date_range(start=last_date + pd.tseries.offsets.BusinessDay(), periods=n, freq="B")


def run_kronos_pipeline(
    ticker: str,
    period: str = "5y",
    future_steps: int = 5,
    variant: str = "kronos-mini",
    top_p: float = 0.9,
    temperature: float = 1.0,
    sample_count: int = 1,
    save_plot: bool = True,
) -> dict:
    """Executa previsão Kronos e devolve dicionário compatível com ForecastResponse.

    O dicionário devolvido contém os campos: ticker, order, train_days, test_days,
    rmse, mape, ljung_box_pvalue, last_train_date, last_test_date, forecast[],
    series[], plot_path, explanation, model_summary.
    """
    cfg = MODEL_CONFIGS[variant]
    max_ctx = cfg["max_context"]

    df = _build_ohlcv(ticker, period=period)
    if len(df) < 60:
        raise ValueError(f"Dados insuficientes para {ticker}: {len(df)} dias")

    # Lookback: usa o máximo permitido pelo contexto, deixando margem para predição.
    # Guardamos uma fatia de teste do tamanho de future_steps para calcular métricas.
    available = len(df)
    min_history = max(60, future_steps * 3)
    if available < min_history + future_steps:
        raise ValueError(f"Dados insuficientes para validação com horizonte {future_steps}")

    lookback = min(max_ctx, available - future_steps)
    train_df = df.iloc[:lookback].copy()
    test_df = df.iloc[lookback: lookback + future_steps].copy()

    x_df = train_df[["open", "high", "low", "close", "volume", "amount"]].reset_index(drop=True)
    x_timestamp = pd.Series(train_df["timestamps"].values, name="timestamps")
    y_timestamp = pd.Series(test_df["timestamps"].values, name="timestamps")

    model_entry = _load_kronos_model(variant)
    predictor = model_entry["predictor"]

    pred_df = predictor.predict(
        df=x_df,
        x_timestamp=x_timestamp,
        y_timestamp=y_timestamp,
        pred_len=len(y_timestamp),
        T=temperature,
        top_p=top_p,
        sample_count=sample_count,
        verbose=False,
    )

    # pred_df tem índice y_timestamp e colunas OHLCV+amount.
    pred_close = pred_df["close"].squeeze()
    if hasattr(pred_close, "to_numpy"):
        pred_close = pred_close.to_numpy()
    pred_close = pd.Series(pred_close, index=pd.to_datetime(y_timestamp.values))
    actual_close = test_df.set_index("timestamps")["close"].reindex(pred_close.index)

    # Métricas simples contra a fatia de teste.
    rmse, mape = _evaluate(actual_close, pred_close)

    # Séries para o gráfico.
    train_series = pd.Series(train_df["close"].values, index=pd.to_datetime(train_df["timestamps"].values), name="close")
    test_series = actual_close
    forecast_series = pred_close

    plot_path = None
    if save_plot:
        plot_path = _plot_forecast(ticker, variant, train_series, test_series, forecast_series)

    last_train_date = train_series.index[-1]
    last_test_date = test_series.index[-1]

    # Intervalo de confiança empírico com base no erro absoluto.
    abs_err = np.abs(actual_close.values - pred_close.values)
    std_err = float(np.std(abs_err)) if len(abs_err) > 1 else float(np.mean(abs_err)) if len(abs_err) else 0.0
    forecast_points = []
    for i, (d, price) in enumerate(forecast_series.items()):
        lower = round(float(price - 1.96 * std_err), 4)
        upper = round(float(price + 1.96 * std_err), 4)
        forecast_points.append({"date": str(d.date()), "price": round(float(price), 4), "lower": lower, "upper": upper})

    series_rows: list[dict] = []
    for d, v in train_series.items():
        series_rows.append({"date": str(d.date()), "value": round(float(v), 4), "type": "train"})
    for d, v in test_series.items():
        series_rows.append({"date": str(d.date()), "value": round(float(v), 4), "type": "test"})
    for d, v in forecast_series.items():
        series_rows.append({"date": str(d.date()), "value": round(float(v), 4), "type": "forecast"})

    explanation = _generate_explanation(ticker, variant, train_series, test_series, forecast_series, rmse, mape)

    return {
        "ticker": ticker,
        "order": (0, 0, 0),
        "train_days": len(train_series),
        "test_days": len(test_series),
        "rmse": round(rmse, 4),
        "mape": round(mape, 4),
        "ljung_box_pvalue": None,
        "last_train_date": str(last_train_date.date()),
        "last_test_date": str(last_test_date.date()),
        "forecast": forecast_points,
        "series": series_rows,
        "plot_path": str(plot_path) if plot_path else None,
        "model_summary": f"Kronos {variant} ({cfg['model_id']})",
        "explanation": explanation,
    }


def _evaluate(actual: pd.Series, predicted: pd.Series) -> tuple[float, float]:
    merged = pd.concat([actual.rename("actual"), predicted.rename("predicted")], axis=1).dropna()
    if merged.empty:
        return 0.0, 0.0
    errors = merged["actual"] - merged["predicted"]
    rmse = float(np.sqrt(np.mean(errors ** 2)))
    mape = float(np.mean(np.abs(errors / merged["actual"].replace(0, np.nan)).dropna()) * 100)
    return rmse, mape


def _generate_explanation(
    ticker: str,
    variant: str,
    train: pd.Series,
    test: pd.Series,
    forecast: pd.Series,
    rmse: float,
    mape: float,
) -> str:
    last_test_price = float(test.iloc[-1])
    first_fc = float(forecast.iloc[0])
    last_fc = float(forecast.iloc[-1])
    min_fc = float(forecast.min())
    max_fc = float(forecast.max())

    if last_fc > last_test_price * 1.005:
        direction = "tendência de alta"
    elif last_fc < last_test_price * 0.995:
        direction = "tendência de baixa"
    else:
        direction = "tendência lateral"

    span_pct = ((max_fc - min_fc) / last_test_price) * 100 if last_test_price else 0.0

    if mape < 1.5:
        quality = "excelente"
    elif mape < 3.5:
        quality = "bom"
    elif mape < 7.0:
        quality = "razoável"
    else:
        quality = "fraco"

    return (
        f"Análise gerada automaticamente para {ticker}.\n\n"
        f"O gráfico apresenta {len(train)} dias de contexto histórico, "
        f"{len(test)} dias de validação e uma projeção com o modelo {variant} "
        f"para os próximos {len(forecast)} dias úteis. O último preço conhecido foi "
        f"{last_test_price:.4f}.\n\n"
        f"A previsão aponta uma {direction}, com o preço a sair de {first_fc:.4f} "
        f"e a terminar em {last_fc:.4f}. Durante o horizonte previsto, os preços "
        f"estimados variam entre {min_fc:.4f} e {max_fc:.4f} (amplitude de {span_pct:.2f}%).\n\n"
        f"A qualidade da validação no período de teste foi {quality} (MAPE = {mape:.2f}%; RMSE = {rmse:.4f}). "
        f"Interpretação prática: trata-se de uma projeção fundacional baseada em padrões históricos de K-line, "
        f"não uma recomendação de investimento. Cruzar com notícias, resultados da empresa e indicadores macro "
        f"antes de qualquer decisão."
    )


def _plot_forecast(
    ticker: str,
    variant: str,
    train: pd.Series,
    test: pd.Series,
    forecast: pd.Series,
) -> Path:
    fig, ax = plt.subplots(figsize=(12, 6))
    ax.set_facecolor("#f8f9fa")
    ax.grid(True, color="#dee2e6", linestyle="-", linewidth=0.5, alpha=0.8)
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)

    ax.fill_between(forecast.index, forecast, alpha=0.10, color="crimson", label="Projeção futura")
    ax.plot(train.index, train, label="Contexto histórico", color="#2c3e50", linewidth=1.2)
    ax.plot(test.index, test, label="Validação (real)", color="#27ae60", linewidth=1.4)
    ax.plot(forecast.index, forecast, label="Previsão", color="crimson", linewidth=1.6)

    today_date = test.index[-1]
    ax.axvline(today_date, color="#7f8c8d", linestyle="--", linewidth=1.0, alpha=0.7, label="Hoje")
    ax.set_title(f"Previsão Kronos ({variant}) — {ticker}", fontsize=14, fontweight="bold")
    ax.set_xlabel("Data", fontsize=11)
    ax.set_ylabel("Preço", fontsize=11)
    ax.legend(loc="upper left", framealpha=0.95)
    fig.tight_layout()

    today = date.today().isoformat()
    save_path = OUTPUT_DIR / f"{ticker}_kronos_{variant}_{today}.png"
    fig.savefig(save_path, dpi=150)
    plt.close(fig)
    return save_path
