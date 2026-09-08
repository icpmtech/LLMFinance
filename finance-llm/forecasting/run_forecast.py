"""Script de exemplo para executar uma previsão ARIMA completa."""
from forecasting.arima_model import run_full_pipeline

if __name__ == "__main__":
    # Exemplo: Apple (AAPL) com dados dos últimos 5 anos.
    result = run_full_pipeline(
        ticker="AAPL",
        period="5y",
        order=(2, 1, 2),
        train_ratio=0.85,
        future_steps=5,
    )
    print(result.to_dict())
    print(f"Gráfico guardado em: {result.plot_path}")
