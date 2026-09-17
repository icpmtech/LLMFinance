# Interface de previsão de preços — IQ OS

O frontend React inclui agora uma página dedicada de previsão de preços. Esta página permite escolher um ticker, configurar o modelo ARIMA e visualizar resultados em gráficos e tabelas.

## Aceder à página

1. Inicie tudo de uma só vez: `python start.py` (ou manualmente: backend em `uvicorn api.main:app --port 8002` e frontend em `cd chat-ui && npm run preview -- --port 5174`).
2. Na barra lateral do chat clique em **Previsões** para alternar para a página de forecast, ou **Tickers** para explorar detalhes de um ticker.

> **Portos:** por defeito a API usa `8002` e o UI `5174`. Podes alterar com as variáveis de ambiente `FINANCE_API_PORT` e `FINANCE_UI_PORT`, ou passar `--port` manualmente.

## Funcionalidades

### Pesquisa de tickers

- O campo **Procurar** possui uma caixa de pesquisa com sugestões automáticas do endpoint local `GET /tickers`.
- Escreva pelo menos duas letras (ex: `EDP`, `AAPL`) para obter resultados.
- Clique numa sugestão para preencher o ticker selecionado.
- Também pode escrever diretamente no campo **Ticker selecionado** (ex: `BCP.LS`, `MSFT`).
- Tickers ainda não registados localmente podem ser executados na mesma: a previsão usa os dados do Yahoo Finance em tempo real.

### Filtros e parâmetros

| Controlo          | Descrição                                                                  |
| ----------------- | -------------------------------------------------------------------------- |
| **Dias futuros**  | Quantos dias úteis prever (1–90).                                          |
| **Período histórico** | Janela de dados históricos descarregados (`1y`, `2y`, `5y`, `10y`, `max`). |
| **Ordem ARIMA**   | Parâmetros `p,d,q` do modelo (ex: `2,1,2`).                                |
| **Rácio treino**  | Fração da série usada para treino (0.50–0.95).                             |

### Gráficos

- **Série histórica e previsão** (Recharts): mostra três segmentos:
  - `Treino` — série até ao corte definido por `train_ratio`;
  - `Teste` — valores reais após o corte;
  - `Previsão` — valores projetados para o futuro;
  - `Limite inferior/superior (IC 95%)` — banda de confiança calculada com base
  na volatilidade dos resíduos do modelo, garantindo valores economicamente
  realistas e sem distorcer a escala do gráfico.
- Uma linha vertical assinala a transição entre teste e previsão futura.
- Passe o rato sobre o gráfico para ver datas e preços formatados.
- O eixo Y ajusta-se automaticamente ao intervalo de preços visíveis.
- Botões **Reset datas** e **Mostrar tudo** permitem controlar o zoom e a visibilidade das séries.

### Tabela de preços previstos

- Apresenta data, preço pontual e intervalo de confiança a 95% para cada dia futuro.
- A tabela tem cabeçalho fixo e pode ser lida mesmo quando há muitos dias previstos.

### Métricas

Quatro cartões resumo:

| Métrica            | Significado                                              |
| ------------------ | -------------------------------------------------------- |
| **RMSE**           | Erro médio quadrático entre valores reais e previstos.   |
| **MAPE**           | Erro percentual médio absoluto.                          |
| **Ljung-Box p-value** | Testa se os resíduos ainda têm autocorrelação.           |
| **Ordem ARIMA**    | Parâmetros usados e tamanhos dos conjuntos treino/teste. |

### Gráfico gerado pelo modelo

O backend gera um PNG estático com `matplotlib`. A página mostra essa imagem abaixo do gráfico interativo.

### Leitura do gráfico (IA)

Abaixo do gráfico interativo, o painel **Leitura do gráfico (IA)** apresenta uma
narrativa automática em português que resume:

- número de dias de treino/teste e horizonte futuro;
- tendência projetada (alta, baixa ou lateral);
- amplitude de preços esperada e largura do intervalo de confiança a 95%;
- qualidade do ajuste (MAPE/RMSE) e resultado do teste Ljung-Box;
- interpretação prática e aviso de que não constitui recomendação de investimento.

Esta explicação é construída no backend a partir das métricas e da série
prevista, mantendo coerência com o que é mostrado no gráfico.

### Resumo do modelo

Se o backend devolver o resumo do modelo ARIMA, é possível mostrá-lo/ocultá-lo num bloco de texto monoespaçado. Útil para depuração avançada.

## Página de detalhe de tickers

A página **Tickers** (`chat-ui/src/pages/TickerPage.tsx`) permite:

- Pesquisar tickers no Yahoo Finance e na lista local (`GET /tickers/search/yahoo`).
- Adicionar um novo ticker ao projeto (`POST /tickers/add`).
- Ver informação geral do ticker: nome, preço atual, capitalização, P/E, EPS, dividend yield, setor, país, empregados e resumo (`GET /tickers/{ticker}/info`).
- Visualizar gráfico histórico de preços com seletor de período (1M–5Y) e tabela dos últimos 30 dias (`GET /tickers/{ticker}/history`).
- Consultar demonstrações financeiras (income statement, balance sheet, cash flow) em tabelas (`GET /tickers/{ticker}/financials`).
- Ver submissões SEC/XBRL com links diretos (`GET /tickers/{ticker}/sec-filings`).

A partir da página de detalhe pode também saltar para a previsão ARIMA do ticker selecionado.

## Estrutura de ficheiros

- `chat-ui/src/pages/ForecastPage.tsx` — componente principal da página de previsão.
- `chat-ui/src/pages/TickerPage.tsx` — componente principal da página de detalhe de tickers.
- `chat-ui/src/api.ts` — funções `searchLocalTickers`, `searchYahooTickers`, `addTicker`, `getTickerInfo`, `getTickerHistory`, `getTickerFinancials`, `getTickerSecFilings`, `runForecast` e `getPlotUrl`.
- `chat-ui/src/types.ts` — interfaces TypeScript das respostas da API.
- `chat-ui/src/App.tsx` — alternador entre vistas `chat`, `forecast` e `tickers`.
- `chat-ui/src/components/Sidebar.tsx` — botões **Previsões** e **Tickers** na barra lateral.

## Dependências

A página utiliza:

- `recharts` para os gráficos interativos (já incluído em `package.json`).
- `lucide-react` para ícones.
- Tailwind CSS v4 para estilos.

## Notas de utilização

- A previsão pode demorar alguns segundos porque o modelo é ajustado em tempo real.
- Se o ticker não tiver dados suficientes ou a ordem ARIMA for instável, a API devolve um erro 500 e a página mostra a mensagem.
- A ordem ARIMA deve seguir sempre o formato `p,d,q` (três inteiros separados por vírgulas).
- Tickers que ainda não existam em `data/tickers_extended.json` podem ser adicionados na página **Tickers** ou executados diretamente na página **Previsões** (desde que existam no Yahoo Finance).
