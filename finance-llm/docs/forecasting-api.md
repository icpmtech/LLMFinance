# API de previsão de preços — FinanceLLM

A API FastAPI expõe endpoints de chat e, agora, um módulo dedicado de previsão de preços baseado num pipeline ARIMA. Este documento descreve o contrato dos endpoints de previsão, os parâmetros disponíveis e exemplos de utilização.

## Base URL

```
http://127.0.0.1:8002
```

A URL pode ser alterada através da variável de ambiente `VITE_API_URL` no frontend ou via `FINANCE_API_PORT` no `start.py`.

> **Nota:** os portos padrão foram alterados para `8002` (API) e `5174` (UI) para evitar conflitos com processos fantasmas no Windows. Podes reverter definindo `FINANCE_API_PORT=8001` e `FINANCE_UI_PORT=5173`.

## Endpoints de previsão

### `GET /tickers`

Devolve a lista de tickers conhecidos pelo projeto, permitindo filtrar por texto.

#### Parâmetros de query

| Nome    | Tipo   | Obrigatório | Descrição                                    |
| ------- | ------ | ----------- | -------------------------------------------- |
| `query` | string | Não         | Texto a procurar no nome do ticker (maiúsculas/minúsculas insensível). |

#### Exemplo

```bash
curl "http://127.0.0.1:8002/tickers?query=EDP"
```

#### Resposta

```json
{
  "query": "EDP",
  "tickers": ["EDP.LS"],
  "yahoo_results": []
}
```

---

### `GET /tickers/search/yahoo`

Procura tickers no Yahoo Finance, útil para descobrir novos símbolos antes de os adicionar ao projeto.

#### Parâmetros de query

| Nome    | Tipo   | Obrigatório | Descrição                                    |
| ------- | ------ | ----------- | -------------------------------------------- |
| `query` | string | Sim         | Texto a procurar (nome, ISIN ou símbolo). |

#### Exemplo

```bash
curl "http://127.0.0.1:8002/tickers/search/yahoo?query=galp"
```

#### Resposta

```json
{
  "query": "galp",
  "tickers": [],
  "yahoo_results": [
    {
      "symbol": "GALP.LS",
      "name": "Galp Energia SGPS S.A.",
      "exchange": "LIS",
      "type": "Equity"
    }
  ]
}
```

---

### `POST /tickers/add`

Adiciona um novo ticker ao ficheiro local `data/tickers_extended.json` após validação no Yahoo Finance.

#### Corpo do pedido (`AddTickerRequest`)

| Campo    | Tipo   | Obrigatório | Descrição                  |
| -------- | ------ | ----------- | -------------------------- |
| `ticker` | string | Sim         | Símbolo bolsista a adicionar. |

#### Exemplo

```bash
curl -X POST "http://127.0.0.1:8002/tickers/add" \
  -H "Content-Type: application/json" \
  -d '{"ticker": "GALP.LS"}'
```

#### Resposta (`AddTickerResponse`)

```json
{
  "ticker": "GALP.LS",
  "added": true,
  "message": "Ticker adicionado com sucesso."
}
```

---

### `GET /tickers/{ticker}/info`

Devolve informações gerais e cotação atual de um ticker.

#### Exemplo

```bash
curl "http://127.0.0.1:8002/tickers/AAPL/info"
```

#### Resposta (`TickerInfoResponse`)

```json
{
  "ticker": "AAPL",
  "name": "Apple Inc.",
  "currency": "USD",
  "price": 225.12,
  "market_cap": 3450000000000,
  "pe": 32.5,
  "eps": 6.91,
  "dividend_yield": 0.0048,
  "sector": "Technology",
  "industry": "Consumer Electronics",
  "website": "https://www.apple.com",
  "country": "United States",
  "employees": 161000,
  "summary": "Apple Inc. designs, manufactures, and markets smartphones..."
}
```

---

### `GET /tickers/{ticker}/history`

Devolve preços históricos diários de um ticker.

#### Parâmetros de query

| Nome     | Tipo   | Padrão | Descrição                          |
| -------- | ------ | ------ | ---------------------------------- |
| `period` | string | `1y`   | Período (`1mo`, `3mo`, `6mo`, `1y`, `2y`, `5y`, `max`). |

#### Exemplo

```bash
curl "http://127.0.0.1:8002/tickers/AAPL/history?period=1y"
```

#### Resposta (`TickerHistoryResponse`)

```json
{
  "ticker": "AAPL",
  "currency": "USD",
  "period": "1y",
  "history": [
    { "date": "2024-09-04", "open": 220.0, "high": 226.5, "low": 219.0, "close": 225.12, "volume": 52000000 }
  ]
}
```

---

### `GET /tickers/{ticker}/financials`

Devolve demonstrações financeiras (income statement, balance sheet, cash flow).

#### Exemplo

```bash
curl "http://127.0.0.1:8002/tickers/AAPL/financials"
```

#### Resposta (`FinancialsResponse`)

```json
{
  "ticker": "AAPL",
  "currency": "USD",
  "income_statement": { "Total Revenue": [ ... ], ... },
  "balance_sheet": { "Total Assets": [ ... ], ... },
  "cash_flow": { "Operating Cash Flow": [ ... ], ... }
}
```

---

### `GET /tickers/{ticker}/sec-filings`

Devolve as submissões SEC mais recentes do Yahoo Finance.

#### Exemplo

```bash
curl "http://127.0.0.1:8002/tickers/AAPL/sec-filings"
```

#### Resposta (`SecFilingsResponse`)

```json
{
  "ticker": "AAPL",
  "filings": [
    {
      "date": "2024-08-02",
      "type": "10-Q",
      "title": "Quarterly report",
      "url": "https://www.sec.gov/..."
    }
  ]
}
```

---

### `POST /forecast`

Executa o pipeline ARIMA completo para um ticker e devolve a previsão, métricas, séries e gráfico.

#### Corpo do pedido (`ForecastRequest`)

| Campo         | Tipo   | Padrão  | Descrição                                                              |
| ------------- | ------ | ------- | ---------------------------------------------------------------------- |
| `ticker`      | string | —       | Símbolo bolsista (ex: `AAPL`, `EDP.LS`, `BCP.LS`).                      |
| `future_days` | int    | `5`     | Número de dias úteis (sessões de negociação) a prever no futuro.        |
| `period`      | string | `"5y"`  | Período histórico a descarregar do Yahoo Finance (`1y`, `2y`, `5y`, `10y`, `max`). |
| `order`       | string | `"2,1,2"` | Ordem ARIMA no formato `"p,d,q"`.                                       |
| `train_ratio` | float  | `0.85`  | Fração da série cronológica a usar para treino (restante é teste).      |

#### Exemplo

```bash
curl -X POST "http://127.0.0.1:8002/forecast" \
  -H "Content-Type: application/json" \
  -d '{
    "ticker": "AAPL",
    "future_days": 5,
    "period": "5y",
    "order": "2,1,2",
    "train_ratio": 0.85
  }'
```

#### Resposta (`ForecastResponse`)

```json
{
  "ticker": "AAPL",
  "order": [2, 1, 2],
  "train_days": 1057,
  "test_days": 187,
  "rmse": 3.4215,
  "mape": 1.8234,
  "ljung_box_pvalue": 0.3456,
  "last_train_date": "2023-08-14",
  "last_test_date": "2024-02-05",
  "currency": "USD",
  "company_name": "Apple Inc.",
  "forecast": [
    { "date": "2024-02-06", "price": 184.23, "lower": 179.12, "upper": 189.34 },
    ...
  ],
  "series": [
    { "date": "2019-02-05", "value": 157.32, "type": "train" },
    { "date": "2023-08-15", "value": 177.45, "type": "test" },
    { "date": "2024-02-06", "value": 184.23, "type": "forecast" },
    ...
  ],
  "plot_url": "/forecast/plot/AAPL_20240102_120030.png",
  "plot_path": "C:/LLMFinance/finance-llm/data/forecasting/AAPL_20240102_120030.png",
  "model_summary": "...",
  "explanation": "Análise gerada automaticamente para Apple Inc. (AAPL)..."
}
```

#### Campos da resposta

| Campo                | Descrição                                                                 |
| -------------------- | ------------------------------------------------------------------------- |
| `ticker`             | Ticker normalizado usado no modelo.                                       |
| `order`              | Ordem ARIMA aplicada `(p,d,q)`.                                           |
| `train_days`         | Número de observações de treino.                                          |
| `test_days`          | Número de observações de teste.                                             |
| `rmse`               | Root Mean Squared Error no conjunto de teste.                             |
| `mape`               | Mean Absolute Percentage Error no conjunto de teste.                      |
| `ljung_box_pvalue`   | p-value do teste Ljung-Box sobre resíduos; `null` se não for calculável.  |
| `last_train_date`    | Última data do conjunto de treino.                                          |
| `last_test_date`     | Última data histórica disponível (fim do teste).                          |
| `currency`           | Moeda do ticker (ex: `USD`, `EUR`).                                       |
| `company_name`       | Nome da empresa, quando disponível.                                         |
| `forecast`           | Lista de pontos futuros com preço pontual e intervalo de confiança 95%.   |
| `series`             | Série unificada `train` / `test` / `forecast` para desenho de gráficos.   |
| `plot_url`           | Caminho relativo para obter o PNG gerado.                                 |
| `plot_path`          | Caminho absoluto do ficheiro PNG no servidor.                               |
| `model_summary`      | Resumo textual do modelo ARIMA ajustado (`statsmodels`).                  |
| `explanation`        | Narrativa gerada automaticamente com a interpretação do gráfico/previsão. |

---

### `GET /forecast/plot/{filename}`

Serve a imagem PNG gerada pelo pipeline ARIMA.

#### Exemplo

```bash
curl -O "http://127.0.0.1:8002/forecast/plot/AAPL_20240102_120030.png"
```

---

## Metodologia ARIMA

O pipeline (`forecasting/arima_model.py`) segue os seguintes passos:

1. **Obtenção de dados**: preços diários de fecho ajustados via `yfinance`.
2. **Transformação**: aplica logaritmo natural e diferenciação para tornar a série estacionária.
3. **Divisão treino/teste**: estritamente cronológica (por omissão 85% treino, 15% teste).
4. **Ajuste ARIMA**: modelo `statsmodels.tsa.arima.model.ARIMA` com a ordem pedida.
5. **Previsão**: previsão passo-a-passo sobre o teste e `future_days` dias futuros.
6. **Métricas**: RMSE e MAPE calculados no conjunto de teste.
7. **Diagnóstico**: teste Ljung-Box aos resíduos para detetar autocorrelação residual.
8. **Visualização**: gráfico com séries de treino, teste, previsão e intervalo de confiança a 95%.

> **Nota sobre intervalos de confiança**
> Os IC 95% são calculados apenas para o horizonte futuro. Em vez de acumular os
> limites diários devolvidos pelo ARIMA (o que produz bandas economicamente
> absurdas para horizontes longos), o modelo usa a volatilidade incondicional dos
> resíduos e a aproximação de random-walk: `P_h * exp(±1,96 * σ * sqrt(h))`.
> Isto garante bandas realistas e impede que o eixo Y do gráfico seja
> distorcido por valores extremos.

## Erros comuns

| Código | Causa típica                                           |
| ------ | ------------------------------------------------------ |
| `400`  | Ordem ARIMA inválida (formato deve ser `p,d,q`).       |
| `404`  | Gráfico pedido não existe.                             |
| `500`  | Erro no pipeline (ticker inválido, dados insuficientes, ou falha numérica no ajuste ARIMA). |
