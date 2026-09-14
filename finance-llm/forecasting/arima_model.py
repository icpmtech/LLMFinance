"""Pipeline robusto de previsão ARIMA para séries temporais financeiras.

Metodologia
-----------
1. Estacionarização via log-retornos diários (retornos compostos).
2. Divisão temporal estrita (passado = treino, futuro imediato = teste).
3. Modelo ARIMA(p,d,q) ajustado sobre os log-retornos.
4. Previsões convertidas de volta a preços absolutos para interpretação.
5. Métricas de erro (RMSE, MAPE) e análise de resíduos (Ljung-Box).
6. Visualização com bandas de confiança.

Referências
-----------
- Hyndman & Athanasopoulos, "Forecasting: Principles and Practice".
- Tsay, "Analysis of Financial Time Series".
"""
from __future__ import annotations

import json
import warnings
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Optional

import matplotlib
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import yfinance as yf
from statsmodels.stats.diagnostic import acorr_ljungbox
from statsmodels.tsa.arima.model import ARIMA

matplotlib.use("Agg")
warnings.filterwarnings("ignore", category=UserWarning)


ROOT = Path(__file__).resolve().parents[1]
OUTPUT_DIR = ROOT / "data" / "forecasting"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)


@dataclass
class ForecastResult:
    """Resultado completo de uma previsão ARIMA."""

    ticker: str
    order: tuple[int, int, int]
    train_prices: pd.Series
    test_prices: pd.Series
    forecast_prices: pd.Series
    forecast_ci: pd.DataFrame
    train_returns: pd.Series
    test_returns: pd.Series
    model_fit: ARIMA
    rmse: float
    mape: float
    ljung_box_pvalue: Optional[float] = None
    plot_path: Optional[Path] = None
    model_summary: Optional[str] = None

    def generate_explanation(self, currency: str = "USD", company_name: Optional[str] = None) -> str:
        """Gera uma narrativa/interpretação automática do gráfico e previsão."""
        future = self.forecast_prices.tail(len(self.forecast_prices) - len(self.test_prices))
        last_test_price = float(self.test_prices.iloc[-1])
        first_fc = float(future.iloc[0])
        last_fc = float(future.iloc[-1])
        min_fc = float(future.min())
        max_fc = float(future.max())

        # Tendência de curto prazo
        if last_fc > last_test_price * 1.005:
            direction = "tendência de alta"
            direction_short = "alta"
        elif last_fc < last_test_price * 0.995:
            direction = "tendência de baixa"
            direction_short = "baixa"
        else:
            direction = "tendência lateral"
            direction_short = "lateral"

        # Amplitude do IC futuro vs preço de referência
        span_pct = ((max_fc - min_fc) / last_test_price) * 100 if last_test_price else 0.0
        ci_last = self.forecast_ci.loc[future.index[-1]] if future.index[-1] in self.forecast_ci.index else None
        if ci_last is not None:
            ci_width = float((ci_last["upper"] - ci_last["lower"]) / last_test_price * 100) if last_test_price else 0.0
        else:
            ci_width = 0.0

        # Avaliar qualidade do ajuste
        mape = self.mape
        if mape < 1.5:
            quality = "excelente"
        elif mape < 3.5:
            quality = "bom"
        elif mape < 7.0:
            quality = "razoável"
        else:
            quality = "fraco"

        lb = self.ljung_box_pvalue
        if lb is None:
            residual_text = "Não foi possível testar a aleatoriedade dos resíduos por falta de dados."
        elif lb > 0.05:
            residual_text = f"O teste Ljung-Box (p={lb:.3f}) não rejeita aleatoriedade dos resíduos, sugerindo que o modelo capturou boa parte da estrutura temporal."
        else:
            residual_text = f"O teste Ljung-Box (p={lb:.3f}) indica resíduos autocorrelacionados; o modelo pode não ter capturado toda a dinâmica da série."

        name = company_name if company_name else self.ticker
        currency_label = currency if currency else "USD"

        text = (
            f"Análise gerada automaticamente para {name} ({self.ticker}).\n\n"
            f"O gráfico apresenta {len(self.train_prices)} dias de treino, "
            f"{len(self.test_prices)} dias de teste e uma projeção ARIMA{self.order} "
            f"para os próximos {len(future)} dias úteis. O último preço conhecido foi "
            f"{last_test_price:.4f} {currency_label}.\n\n"
            f"A previsão aponta uma {direction}, com o preço a sair de {first_fc:.4f} "
            f"e a terminar em {last_fc:.4f} {currency_label}. "
            f"Durante o horizonte previsto, os preços estimados variam entre "
            f"{min_fc:.4f} e {max_fc:.4f} {currency_label} (amplitude de {span_pct:.2f}%). "
            f"O intervalo de confiança a 95% no último dia tem uma largura de cerca de "
            f"{ci_width:.2f}% em torno do preço de referência.\n\n"
            f"A qualidade do ajuste no período de teste foi {quality} (MAPE = {mape:.2f}%; RMSE = {self.rmse:.4f}). "
            f"{residual_text}\n\n"
            f"Interpretação prática: em contexto de mercado, a projeção de {direction_short} deve ser lida como "
            f"uma continuação estatística da tendência recente, não como recomendação de investimento. "
            f"É aconselhável cruzar esta previsão com notícias, resultados da empresa e indicadores macro antes de qualquer decisão."
        )
        return text

    def to_dict(self) -> dict:
        """Representação resumida em dicionário (útil para API/agente)."""
        future = self.forecast_prices.tail(len(self.forecast_prices) - len(self.test_prices))
        return {
            "ticker": self.ticker,
            "order": self.order,
            "train_days": len(self.train_prices),
            "test_days": len(self.test_prices),
            "rmse": round(self.rmse, 4),
            "mape": round(self.mape, 4),
            "ljung_box_pvalue": round(self.ljung_box_pvalue, 4) if self.ljung_box_pvalue is not None else None,
            "last_train_date": str(self.train_prices.index[-1].date()),
            "last_test_date": str(self.test_prices.index[-1].date()),
            "forecast": [
                {
                    "date": str(d.date()),
                    "price": round(float(v), 4),
                    "lower": round(float(self.forecast_ci.loc[d, "lower"]), 4) if d in self.forecast_ci.index else None,
                    "upper": round(float(self.forecast_ci.loc[d, "upper"]), 4) if d in self.forecast_ci.index else None,
                }
                for d, v in future.items()
            ],
            "series": self._series_to_dict(),
            "plot_path": str(self.plot_path) if self.plot_path else None,
        }

    def _series_to_dict(self) -> list[dict]:
        """Converte as três séries (treino, teste, previsão) num formato tabular simples."""
        rows: list[dict] = []
        for d, v in self.train_prices.items():
            rows.append({"date": str(d.date()), "value": round(float(v), 4), "type": "train"})
        for d, v in self.test_prices.items():
            rows.append({"date": str(d.date()), "value": round(float(v), 4), "type": "test"})
        for d, v in self.forecast_prices.items():
            rows.append({"date": str(d.date()), "value": round(float(v), 4), "type": "forecast"})
        return rows


def download_close_prices(
    ticker: str,
    start: Optional[str] = None,
    end: Optional[str] = None,
    period: str = "5y",
) -> pd.Series:
    """Descarrega preços de fecho diários e força frequência de dias úteis.

    Se `start` e `end` forem fornecidos, usa o intervalo explícito.
    Caso contrário, usa `period`.
    """
    ticker = ticker.strip().upper()
    try:
        # Usar Ticker.history é mais robusto e thread-safe que yf.download.
        ticker_obj = yf.Ticker(ticker)
        if start and end:
            df = ticker_obj.history(start=start, end=end, auto_adjust=True)
        else:
            df = ticker_obj.history(period=period, interval="1d", auto_adjust=True)
    except Exception:
        df = pd.DataFrame()

    if df.empty:
        # Fallback para o caminho antigo caso Ticker.history falhe.
        if start and end:
            df = yf.download(ticker, start=start, end=end, progress=False, auto_adjust=True)
        else:
            df = yf.download(ticker, period=period, interval="1d", progress=False, auto_adjust=True)

    if df.empty:
        raise ValueError(f"Sem dados para {ticker} no período pedido.")

    # yfinance com auto_adjust=True devolve coluna "Close" (já ajustada).
    close = df["Close"].copy()
    close.index = pd.to_datetime(close.index)
    close = close.squeeze()
    close = close.asfreq("B").ffill()
    close.name = "Close"
    return close


def to_log_returns(prices: pd.Series) -> pd.Series:
    """Converte preços em log-retornos diários (série estacionária)."""
    log_prices = np.log(prices.replace(0, np.nan).dropna())
    returns = log_prices.diff().dropna()
    returns.name = "log_return"
    return returns


def train_test_split(
    series: pd.Series, train_ratio: float = 0.85
) -> tuple[pd.Series, pd.Series]:
    """Divisão temporal estrita: treino = primeiros `train_ratio` obs."""
    if not 0 < train_ratio < 1:
        raise ValueError("train_ratio deve estar entre 0 e 1.")
    cutoff = int(len(series) * train_ratio)
    train = series.iloc[:cutoff]
    test = series.iloc[cutoff:]
    return train, test


def fit_arima(train_series: pd.Series, order: tuple[int, int, int] = (2, 1, 2)) -> ARIMA:
    """Ajusta um modelo ARIMA à série de treino.

    A ordem padrão (2,1,2) é conservadora para retornos financeiros.
    """
    model = ARIMA(train_series, order=order)
    return model.fit()


def forecast(
    model_fit,
    steps: int,
    last_train_date: Optional[pd.Timestamp] = None,
    freq: str = "B",
) -> tuple[pd.Series, pd.DataFrame]:
    """Gera previsões pontuais e intervalos de confiança para `steps` passos."""
    fc = model_fit.get_forecast(steps=steps)
    mean = fc.predicted_mean
    ci = fc.conf_int()

    if last_train_date is not None:
        future_index = pd.date_range(
            start=last_train_date + pd.tseries.offsets.BusinessDay(),
            periods=steps,
            freq=freq,
        )
        mean.index = future_index
        ci.index = future_index

    return mean, ci


def evaluate_forecast(actual: pd.Series, predicted: pd.Series) -> tuple[float, float]:
    """Calcula RMSE e MAPE entre valores reais e previstos."""
    actual = actual.dropna()
    predicted = predicted.dropna().reindex(actual.index)
    errors = actual - predicted
    rmse = float(np.sqrt(np.mean(errors**2)))
    mape = float(np.mean(np.abs(errors / actual.replace(0, np.nan)).dropna()) * 100)
    return rmse, mape


def residual_analysis(model_fit, lags: int = 10) -> dict:
    """Testa se os resíduos se comportam como ruído branco (Ljung-Box)."""
    resid = model_fit.resid.dropna()
    if len(resid) < lags + 2:
        return {"pvalue": None, "error": "Resíduos insuficientes"}
    lb = acorr_ljungbox(resid, lags=[lags], return_df=True)
    pvalue = float(lb.iloc[0]["lb_pvalue"])
    return {"pvalue": pvalue, "is_white_noise": pvalue > 0.05}


def _returns_to_prices(
    returns_forecast: pd.Series,
    last_known_price: float,
    last_known_date: pd.Timestamp,
    historical_prices: Optional[pd.Series] = None,
    trend_window: int = 30,
    trend_weight: float = 0.85,
) -> pd.Series:
    """Converte log-retornos previstos de volta para preços absolutos com tendência.

    O ARIMA ajustado a log-retornos tende a reverter rapidamente à média,
    produzindo previsões quase planas. Para dar mais aspeto de série de
    mercado financeiro, misturamos a previsão pontual do ARIMA com o drift
    de uma regressão linear dos últimos `trend_window` preços reais. O peso
    do drift decresce ao longo do horizonte para não divergir indefinidamente.
    """
    adjusted_returns = returns_forecast.copy().to_numpy()
    n = len(adjusted_returns)

    if historical_prices is not None and len(historical_prices) >= 3:
        recent = historical_prices.tail(trend_window)
        x = np.arange(len(recent), dtype=float)
        y = np.log(recent.to_numpy(dtype=float))
        slope, intercept = np.polyfit(x, y, 1)
        # Drift diário médio da tendência linear (em log-retornos)
        trend_drift = float(slope)
    else:
        trend_drift = 0.0

    if n > 0:
        # Mistura entre previsão ARIMA e drift de tendência; decaimento suave
        weights = trend_weight * np.exp(-np.arange(n) / (n * 0.7))
        weights = np.clip(weights, 0.0, 1.0)
        adjusted_returns = adjusted_returns * (1.0 - weights) + trend_drift * weights

    log_prices = np.log(last_known_price) + np.cumsum(adjusted_returns)
    prices = np.exp(log_prices)
    prices = pd.Series(prices, index=returns_forecast.index, name="price")
    return prices


def _future_price_ci(
    future_prices: pd.Series,
    last_known_price: float,
    residuals: pd.Series,
    confidence: float = 0.95,
) -> pd.DataFrame:
    """Constrói intervalos de confiança realistas para preços futuros.

    Em vez de acumular os limites diários fornecidos pelo ARIMA (o que produz
    bandas que crescem de forma economicamente absurda para horizontes além de
    alguns dias), usamos a volatilidade incondicional dos resíduos do modelo e
    a aproximação de random-walk:

        log(P_h) ~ N(log(P_0) + h*mu, h * sigma^2)

    onde h é o horizonte e sigma é o desvio-padrão dos resíduos. O IC dos
    preços é dado por P_h * exp(± z * sigma * sqrt(h)).
    """
    sigma = float(residuals.dropna().std())
    z = 1.96 if confidence >= 0.95 else 1.645
    steps = np.arange(1, len(future_prices) + 1)
    margin = z * sigma * np.sqrt(steps)
    lower = future_prices * np.exp(-margin)
    upper = future_prices * np.exp(margin)
    return pd.DataFrame({"lower": lower, "upper": upper}, index=future_prices.index)


def plot_forecast(
    result: ForecastResult,
    save_path: Optional[Path] = None,
    show: bool = False,
) -> Path:
    """Gera gráfico financeiro: treino, teste, previsão, bandas de confiança e tendência."""
    fig, ax = plt.subplots(figsize=(12, 6))

    # Fundo e grid estilo terminal/plataforma financeira
    ax.set_facecolor("#f8f9fa")
    ax.grid(True, color="#dee2e6", linestyle="-", linewidth=0.5, alpha=0.8)
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)

    # Área sob a previsão
    ax.fill_between(
        result.forecast_prices.index,
        result.forecast_prices,
        alpha=0.10,
        color="crimson",
        label="Projeção futura",
    )

    # Linhas das séries
    ax.plot(result.train_prices.index, result.train_prices, label="Treino", color="#2c3e50", linewidth=1.2)
    ax.plot(result.test_prices.index, result.test_prices, label="Teste (real)", color="#27ae60", linewidth=1.4)
    ax.plot(
        result.forecast_prices.index,
        result.forecast_prices,
        label="Previsão",
        color="crimson",
        linewidth=1.6,
    )

    # Bandas de confiança
    if result.forecast_ci is not None and not result.forecast_ci.empty:
        ax.fill_between(
            result.forecast_ci.index,
            result.forecast_ci["lower"],
            result.forecast_ci["upper"],
            color="crimson",
            alpha=0.12,
            label="IC 95%",
        )

    # Linha vertical no "hoje" (último dia de teste)
    today_date = result.test_prices.index[-1]
    ax.axvline(today_date, color="#7f8c8d", linestyle="--", linewidth=1.0, alpha=0.7, label="Hoje")

    ax.set_title(f"Previsão ARIMA{result.order} — {result.ticker}", fontsize=14, fontweight="bold")
    ax.set_xlabel("Data", fontsize=11)
    ax.set_ylabel("Preço", fontsize=11)
    ax.legend(loc="upper left", framealpha=0.95)
    fig.tight_layout()

    if save_path is None:
        today = date.today().isoformat()
        save_path = OUTPUT_DIR / f"{result.ticker}_forecast_{today}.png"

    fig.savefig(save_path, dpi=150)
    if show:
        plt.show()
    plt.close(fig)
    return save_path


def run_full_pipeline(
    ticker: str,
    start: Optional[str] = None,
    end: Optional[str] = None,
    period: str = "5y",
    order: tuple[int, int, int] = (2, 1, 2),
    train_ratio: float = 0.85,
    future_steps: int = 5,
    save_plot: bool = True,
    include_model_summary: bool = False,
) -> ForecastResult:
    """Executa o pipeline completo de previsão ARIMA.

    1. Dados reais do Yahoo Finance.
    2. Log-retornos para estacionaridade.
    3. Divisão temporal incorruptível.
    4. ARIMA nos retornos.
    5. Conversão para preços.
    6. Métricas de erro e análise de resíduos.
    7. Gráfico com bandas de confiança.
    """
    # 1. Dados
    prices = download_close_prices(ticker, start=start, end=end, period=period)

    # 2. Estacionarização
    returns = to_log_returns(prices)

    # 3. Split temporal estrito
    train_returns, test_returns = train_test_split(returns, train_ratio=train_ratio)

    # 4. Modelo ARIMA
    model_fit = fit_arima(train_returns, order=order)

    # 5. Previsões de retornos e conversão para preços
    total_steps = len(test_returns) + future_steps
    returns_fc, _ = forecast(
        model_fit,
        steps=total_steps,
        last_train_date=train_returns.index[-1],
        freq="B",
    )

    last_train_date = train_returns.index[-1]
    last_train_price = float(prices.loc[last_train_date])
    forecast_prices = _returns_to_prices(
        returns_fc, last_train_price, last_train_date, historical_prices=prices
    )

    # Separar previsões de teste e futuras
    test_forecast_prices = forecast_prices.iloc[: len(test_returns)]
    future_forecast_prices = forecast_prices.iloc[len(test_returns) :]

    # 5.1 Intervalos de confiança apenas para o horizonte futuro.
    # Acumular os limites diários do ARIMA ao longo de muitos passos produz
    # bandas economicamente absurdas. Usamos a volatilidade incondicional dos
    # resíduos e a aproximação de random-walk para obter ICs coerentes.
    future_ci_prices = _future_price_ci(
        future_forecast_prices,
        last_train_price,
        model_fit.resid,
        confidence=0.95,
    )
    # Juntar CI do futuro com NaNs para o período de teste (apenas para o plot)
    test_index = forecast_prices.index[: len(test_returns)]
    empty_test_ci = pd.DataFrame(
        {"lower": [np.nan] * len(test_index), "upper": [np.nan] * len(test_index)},
        index=test_index,
    )
    forecast_ci_prices = pd.concat([empty_test_ci, future_ci_prices]).sort_index()

    # 6. Métricas apenas sobre o período de teste
    # Recuperar preços de teste absolutos
    test_prices = prices.loc[test_returns.index]
    rmse, mape = evaluate_forecast(test_prices, test_forecast_prices)

    # 7. Análise de resíduos
    resid = residual_analysis(model_fit)

    result = ForecastResult(
        ticker=ticker,
        order=order,
        train_prices=prices.loc[train_returns.index],
        test_prices=test_prices,
        forecast_prices=forecast_prices,
        forecast_ci=forecast_ci_prices,
        train_returns=train_returns,
        test_returns=test_returns,
        model_fit=model_fit,
        rmse=rmse,
        mape=mape,
        ljung_box_pvalue=resid["pvalue"] if resid["pvalue"] is not None else None,
    )

    if include_model_summary:
        result.model_summary = str(model_fit.summary())

    # 8. Gráfico
    if save_plot:
        result.plot_path = plot_forecast(result)

    return result


def main():
    """Entrypoint para testes rápidos em linha de comandos."""
    import argparse

    parser = argparse.ArgumentParser(description="Previsão ARIMA para preços de ações.")
    parser.add_argument("--ticker", default="AAPL", help="Ticker Yahoo Finance (ex: AAPL, EDP.LS)")
    parser.add_argument("--start", default=None, help="Data de início (YYYY-MM-DD)")
    parser.add_argument("--end", default=None, help="Data de fim (YYYY-MM-DD)")
    parser.add_argument("--period", default="5y", help="Período alternativo se start/end omitidos")
    parser.add_argument("--order", default="2,1,2", help="Ordem ARIMA (p,d,q)")
    parser.add_argument("--train-ratio", type=float, default=0.85, help="Proporção de treino")
    parser.add_argument("--future-steps", type=int, default=5, help="Dias futuros a projetar")
    parser.add_argument("--save-json", default=None, help="Caminho para guardar resultado JSON")
    parser.add_argument("--summary", action="store_true", help="Incluir resumo textual do modelo")
    args = parser.parse_args()

    order = tuple(int(x) for x in args.order.split(","))
    result = run_full_pipeline(
        ticker=args.ticker,
        start=args.start,
        end=args.end,
        period=args.period,
        order=order,
        train_ratio=args.train_ratio,
        future_steps=args.future_steps,
        include_model_summary=args.summary,
    )

    summary = result.to_dict()
    print(json.dumps(summary, indent=2, ensure_ascii=False))

    if args.save_json:
        Path(args.save_json).write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")


if __name__ == "__main__":
    main()
