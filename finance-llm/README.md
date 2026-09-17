# IQ OS

**IQ OS** é a plataforma de inteligência financeira: contratos públicos, empresas, mercados,
previsões e chat com três modelos de linguagem — GPT-2, Mistral e um **BloombergGPT-style (RAG)** —
treinados sobre dados do Yahoo Finance, acessíveis via API FastAPI e interface React com ambiente
de trabalho em janelas (estilo macOS). O backend permite escolher o modelo em cada pedido (`gpt2`,
`mistral` ou `bloomberg`). O modelo BloombergGPT-style lê documentos PDF convertidos para Markdown
e responde com base no conhecimento indexado.

> **Nota sobre nomes:** a marca visível na aplicação é **IQ OS**. Os identificadores técnicos
> mantêm o nome antigo por compatibilidade — a pasta `finance-llm/`, os comandos `finance-llm.cmd` /
> `finance-llm.ps1`, os índices do Elasticsearch (`finance_*`), as chaves do `localStorage`
> (`finance-llm-*`) e o ficheiro de configuração do CLI (`~/.finance-llm/config.json`).

> **Arquitetura completa do RAG:** ver [`docs/bloomberggpt_rag_architecture.md`](docs/bloomberggpt_rag_architecture.md).

## Estrutura

```
finance-llm/
├── api/                 # Backend FastAPI + agente financeiro + RAG
│   ├── main.py          # Entrypoint FastAPI
│   ├── rag_routes.py    # Endpoints RAG
│   ├── rag_service.py   # Serviço RAG singleton + cache de modelos
│   ├── ontology_registry.py  # Ontologia (tipos de objeto, ligações, ações)
│   ├── ontology_service.py   # Motor da ontologia (consulta, ligações, grounding, validação)
│   ├── ontology_routes.py    # Endpoints /ontology/*
│   └── agent.py         # Agente financeiro (GPT-2 / Mistral / ARIMA)
├── chat-ui/             # Frontend React + Vite + Tailwind CSS v4
│   ├── src/
│   │   ├── pages/RagPage.tsx
│   │   ├── components/RagChat.tsx
│   │   └── components/PdfUploader.tsx
│   └── dist/            # Build de produção
├── collectors/          # Recolha de dados (Yahoo Finance, FRED, ECB, ...)
├── forecasting/         # Previsão ARIMA de séries temporais financeiras
│   ├── arima_model.py
│   └── run_forecast.py
├── rag/                 # Motor RAG (PDF → Markdown → chunks → FAISS)
│   ├── chat/rag_engine.py
│   ├── ingestion/chunker.py
│   ├── ingestion/ingest_pdf.py
│   ├── ingestion/markdown_store.py
│   └── ingestion/vector_store.py
├── processing/          # Normalização e construção do corpus
├── model/               # GPT-2, Mistral e BloombergGPT-style financeiros
│   ├── gpt2_finance.py
│   ├── mistral_finance.py
│   ├── bloomberg_gpt.py
│   ├── gpt2-finance/
│   ├── mistral-finance/
│   └── bloomberg-finance/
├── training/            # Fine-tuning manual em PyTorch
│   ├── train.py
│   └── train_mistral.py
├── inference/           # Geração de texto
│   ├── generate.py
│   └── generate_mistral.py
└── data/                # Dados brutos, processados e finais
```

## Requisitos

- Python 3.11+
- uv (ou `pip` com `.venv`)
- Node.js 20+ (para o UI)

## Instalação

```bash
# Ambiente Python
uv venv --python 3.11 .venv
.venv\Scripts\pip install -r requirements.txt
.venv\Scripts\pip install markitdown[pdf]

# Frontend
cd chat-ui
npm install
```

### Arranque rápido

Após a instalação, usa os scripts helper para iniciar tudo:

```powershell
# Backend + frontend (ports 8003 / 4180)
.\start_solution.ps1
```

Ou em passos separados:

```bash
# Backend na porta 8003 (evita processos fantasmas na 8002)
start_backend_8003.bat

# Frontend (build de produção + preview na porta 4173)
cd chat-ui
npm run build
npm run preview
```

Abre http://127.0.0.1:4180 no browser.

Para parar a solução completa:

```powershell
.\stop_solution.ps1
```

### Docker Compose

Para correr a solução completa (Elasticsearch + backend + frontend) em containers, garante que tens Docker Desktop/Engine instalado e corre:

```bash
docker compose up --build -d
```

- Frontend: http://127.0.0.1:4180
- API docs (Swagger): http://127.0.0.1:8003/docs
- Elasticsearch: http://127.0.0.1:9200

Para parar:

```bash
docker compose down
```

Os volumes `./data`, `./model`, `./rag` e `./logs` são montados no backend (os mesmos dados da execução local), e o índice do Elasticsearch persiste no volume `es-data`. Mais detalhes em [`docs/docker-setup.md`](docs/docker-setup.md).

## Recolha de dados

```bash
.venv\Scripts\python collectors/yahoo.py
```

## Previsão de séries temporais (ARIMA)

O projecto inclui um módulo de previsão de preços baseado em ARIMA, acessível pela linha de comandos ou através do agente de chat. O modelo segue quatro passos rigorosos:

1. **Estabilização** — preços de fecho transformados em log-retornos.
2. **Validação temporal** — divisão cronológica 85 % treino / 15 % teste, sem baralhamento.
3. **Métricas** — RMSE e MAPE calculados no conjunto de teste.
4. **Análise de resíduos** — teste Ljung-Box para verificar se os resíduos são ruído branco.

### Linha de comandos

Previsão por defeito para a Apple (AAPL) a 5 dias úteis:

```bash
.venv\Scripts\python -m forecasting.run_forecast
```

Definir outro ticker e horizonte:

```bash
.venv\Scripts\python forecasting/arima_model.py --ticker MSFT --future_days 10 --period 5y
```

A saída inclui preços projectados, RMSE, MAPE e p-value de Ljung-Box.

### Pelo agente de chat

Basta perguntar ao chat, por exemplo:

> *Qual a previsão para a Apple nos próximos 5 dias?*

O agente detecta automaticamente perguntas de previsão, extrai o ticker e responde com os valores projectados pelos modelos ARIMA(2,1,2). Enquanto os modelos de linguagem (GPT-2/Mistral) estiverem em treino, a resposta é baseada nos dados do Yahoo Finance e nas métricas de erro do modelo ARIMA.

## Construir corpus e inicializar modelos

```bash
.venv\Scripts\python processing/build_corpus.py
.venv\Scripts\python model/gpt2_finance.py
.venv\Scripts\python model/mistral_finance.py
```

## Treinar

### GPT-2

```bash
.venv\Scripts\python training/train.py
```

### Mistral

```bash
.venv\Scripts\python training/train_mistral.py
```

Por defeito os treinos usam todo o corpus (`8070` exemplos de treino), o que pode demorar várias horas em CPU. Para testes rápidos:

```bash
# GPT-2
.venv\Scripts\python -c "from training.train import train_model; train_model(max_samples=500, save_checkpoints=False)"

# Mistral
.venv\Scripts\python training/train_mistral.py --max_samples 500 --epochs 2 --batch_size 4
```

## Executar

### Backend

Terminal 1 — backend FastAPI na porta **8003** (a 8002 ficou reservada a processos fantasmas no Windows):

```bash
cd finance-llm
start_backend_8003.bat
```

ou manualmente:

```bash
cd finance-llm
.venv\Scripts\python -m uvicorn api.main:app --host 127.0.0.1 --port 8003
```

### Frontend

Terminal 2 — frontend Vite preview na porta **4173**:

```bash
cd finance-llm/chat-ui
npm run build
npm run preview
```

Abre http://127.0.0.1:4173 no browser.

Também pode servir o *build* com o servidor estático do repositório (é o que serve a PWA com os
tipos MIME certos para `manifest.webmanifest`/`sw.js`, em <http://localhost:5174>):

```bash
python _serve_spa.py --root chat-ui/dist --port 5174
```

A instalação da aplicação e o modo offline só funcionam em `localhost` ou HTTPS (contexto seguro).

Endereços da interface (ex.: `/tickers/EDP/grafico`, `/companies/503140600`, `/browser`) podem ser
abertos diretamente: a API serve o `index.html` para **navegações de browser** (`Accept: text/html`)
que não correspondam a um endpoint, e continua a devolver JSON/404 para os pedidos de API e para
caminhos com extensão de ficheiro. Em desenvolvimento com o servidor do Vite, o proxy interno
encaminha `/tickers`, `/companies`, `/contracts`, … para a API — sem este fallback, recarregar a
página numa dessas rotas devolvia `{"detail":"Not Found"}`.

> Nota: a API está configurada para `http://127.0.0.1:8003` em `chat-ui/src/api.ts`. Se alterares a porta, atualiza também o frontend e reconstrói o UI.

### Interface

- **Dock estilo macOS** (em baixo, à esquerda ou à direita) com ampliação ao passar o rato, etiquetas,
  indicadores de aplicações abertas, arrumação por arrastar e painel de preferências.
- **Barra lateral = menu de aplicações** (estilo macOS) em três modos — *expandida*, *só ícones*
  (rail de 68 px) e *escondida* — com material translúcido («vibrancy»), pesquisa rápida
  (`/` ou `Ctrl+K`), secção de recentes, secções *Aplicações* / *Ferramentas* com triângulo de
  divulgação e ponto nas aplicações com janela aberta. Cada linha abre (ou foca) a aplicação;
  a **largura é redimensionável** arrastando a divisória (`196`–`384` px, duplo clique repõe `268` px).
  `Ctrl+B` esconde/mostra. As páginas internas de cada aplicação vivem dentro da própria
  aplicação — por exemplo, o EmpresasIQ usa **separadores (segmented control) no topo**, em vez de
  uma barra lateral própria, e nenhuma janela duplica a barra da plataforma.
- **Ecrã inteiro** e **PWA** (instalável, funciona sem ligação): `manifest.webmanifest` + `sw.js`;
  a instalação (e o pacote de atalhos para Windows) está em **Definições → Aplicação IQ OS**.
- **Contas** em Elasticsearch (`finance_users` / `finance_sessions`), com login, registo,
  definições de perfil, sessões ativas e terminação remota.
- **Terminal** (`/cli`) — o CLI da plataforma dentro da aplicação, com histórico (↑/↓),
  completamento com Tab, sugestões clicáveis e saída `--json`.
- **Finder** (`/finder`) — explorador dos dados no estilo do Finder do macOS (locais, ícones,
  colunas, lista, galeria, Quick Look, inspetor, etiquetas, barra de caminho e exportação CSV).
- **Comparação** (`/compare`) — janela própria para pôr lado a lado entidades
  (adjudicantes/adjudicatários) ou contratos, com valores, analítica por ano e CPV em comum.
- **Gráfico Tempo Real** (`/chart`, `/tickers/<T>/grafico`) — cotações em tempo real com o
  *Advanced Real-Time Chart* da TradingView (ver abaixo).
- **Browser** (`/browser`) — navegador dentro da plataforma: separadores, favoritos, histórico,
  atalhos para páginas do IQ OS e fontes de mercado e integração com a pesquisa global (ver abaixo).
- **Administração** (`/admin`) — sistema, utilizadores, eventos e logs; visível apenas a contas
  com papel `admin` (ver abaixo).

### Administração da solução

Aplicação **Administração** (`/admin`), reservada a contas com papel `admin` (a barra lateral e o
dock escondem-na aos restantes), com quatro separadores:

- **Visão geral** — versão da API, *host*, plataforma, Python, tempo de atividade, estado do
  Elasticsearch (versão, *cluster*, saúde, nós), **índices** com nº de documentos e tamanho
  (`finance_users`, `finance_sessions`, `finance_events`, `contratos`, `finance_entities`, …),
  contas por papel/estado, sessões ativas e eventos das últimas 24 h por nível, origem e caminho.
- **Utilizadores** — pesquisa por nome/email, filtros por papel (`admin`/`member`) e estado
  (`active`/`suspended`), sessões ativas e nº de logins por conta; alterar papel/estado, terminar
  sessões de um utilizador e apagar contas (as ações ficam registadas como eventos de auditoria).
- **Eventos** — o *event logger viewer* descrito abaixo.
- **Ficheiros de log** — lista de `logs/*.log|.err|.out|.jsonl` com tamanho e data, pré-visualização
  das últimas linhas (100–3000), modo «Direto» (atualiza a cada 5 s) e quebra de linhas.

#### Registo de eventos (event logger)

`api/events_service.py` escreve cada evento em **três destinos** complementares:

1. **Memória** — `deque` circular das últimas 2000 entradas, sempre disponível (é a fonte do modo
   «tempo real», onde aparecem *todos* os pedidos, incluindo os de nível `debug`/`info`);
2. **Ficheiro** — `logs/events.jsonl` (uma linha JSON por evento, com rotação a ~5 MB);
3. **Elasticsearch** — índice `finance_events`, pesquisável e agregável (só recebe
   autenticação/administração e nível ≥ `warning`, para não duplicar o tráfego).

- Um *middleware* em `api/main.py` regista cada pedido à API (método, caminho, status, duração,
  utilizador e IP), com o nível derivado do código de resposta (2xx → `debug`, 4xx → `warning`,
  5xx → `error`); a identidade vem do token (com cache de 5 min para não bater no Elasticsearch).
- `auth_routes.py` regista ainda os eventos de segurança: registo, início de sessão (sucesso e
  falha), fim de sessão, alteração de palavra-passe, revogação de sessões e apagamento de conta.
- O visualizador permite filtrar por **nível** (chips), **origem** (`api`, `auth`, `admin`),
  **utilizador**, **texto** e **janela temporal**, alternar entre **tempo real (memória)** e
  **arquivo (Elasticsearch)** (ou fonte automática), ligar o **modo direto**, ver as contagens por
  nível/origem/caminho e por hora, abrir o JSON completo de cada evento e **registar eventos
  manuais** para teste (`POST /admin/events`).
- Para dar acesso a uma conta (a primeira conta do sistema é `admin`):
  `python scripts/promote_admin.py --email alguem@exemplo.pt` (ou `--list`, `--demote`).

### Janelas (estilo macOS)

Com o **modo janelas** ligado (predefinição em ecrãs ≥ 1024 px), cada página abre numa janela
flutuante dentro de uma área de trabalho, em vez de ocupar o ecrã inteiro:

- **Arrastar** pela barra de título; **redimensionar** pelas 8 margens.
- **Encaixe**: arrastar para o topo maximiza; para as margens esquerda/direita ocupa meio ecrã
  (com pré-visualização antes de largar).
- **Duplo clique** na barra de título maximiza/reposiciona; arrastar uma janela maximizada
  repõe o tamanho anterior.
- **Semáforos** macOS: fechar, minimizar, maximizar. As janelas minimizadas continuam
  indicadas no dock (ponto) e voltam com um clique no ícone.
- **Barra de menus** com o número de janelas, o título da janela ativa, o menu **Janelas**
  (lista todas, incluindo minimizadas, para focar/restaurar) e a disposição
  (`Cascata`, `Lado a lado`, `Minimizar todas`, `Fechar todas`) e relógio.
- **Atalhos**: `Ctrl/Cmd + \`` cicla janelas, `Ctrl/Cmd + W` fecha, `Ctrl/Cmd + M` minimiza,
  `Ctrl/Cmd + Shift + M` maximiza/reposiciona.
- **Área de trabalho vazia** tem um lançador rápido (EmpresasIQ, Contratos, Dashboard, Terminal).
- A geometria, o empilhamento e o estado (minimizada/maximizada) ficam guardados em
  `localStorage` (`finance-llm-windows:v1`) e são repostos ao recarregar.
- O modo liga-se/desliga nas **Definições → Preferências → Modo janelas** (guardado na conta)
  ou no painel de preferências do dock. Num telemóvel a plataforma abre em modo página.

**As modais também são janelas.** As fichas de entidade e de contrato (EmpresasIQ) e o
**Quick Look** do Finder deixam de ser sobreposições modais e passam a abrir como **janelas**
(uma por item, `company-detail:<NIF>`, `contract-detail:<id>`, `quicklook:<tipo>:<id>`):
arrastáveis, redimensionáveis, minimizáveis, com título próprio, restauráveis pelo menu
**Janelas** e repostas ao recarregar. Abrir a ficha de uma entidade a partir de um contrato
empilha uma segunda janela, como no macOS. Em **modo página** (sem gestor de janelas) mantém-se
a ficha/quick look sobrepostos, como antes.

### Finder (explorador de dados)

Aplicação **Finder** (`/finder`), no dock e no menu de aplicações: os dados da plataforma
(entidades, contratos, documentos RAG, tickers e índices do Elasticsearch) são tratados como
«ficheiros», com a linguagem do Finder do macOS.

- **Locais** (menu *Locais* na barra de ferramentas ou 1.ª coluna da vista de colunas):
  Recentes, Favoritos (lê e escreve os favoritos reais em Elasticsearch), Entidades, Contratos,
  Documentos, Mercados e Índices (com contagens reais: 2 250 969 contratos, 214 123 entidades, …).
- **Quatro vistas**: ícones, colunas (Miller: locais → itens → relacionados), lista com ordenação
  por coluna (Nome/Tipo/Data/Tamanho) e galeria com película.
- **Quick Look** (barra de espaço, duplo clique ou Enter): ficha do item. Para **entidades** traz o
  dossier completo — valores (contratado, médio, maior, como adjudicante e adjudicatário), **análítica**
  (por ano, top CPV, tipo de procedimento e de contrato, com barras), **contratos associados**
  (nº clicável abre a ficha do contrato, papel, data e valor) e **concorrentes**
  (co-ocorrência nos mesmos procedimentos, clicável para abrir a entidade; se o portal não
  publicar concorrentes nesses contratos, explica-o em vez de ficar vazio).
- **Obter informação** (⌘/Ctrl+I): inspetor lateral com metadados, etiquetas e ação de favorito.
- **Menu de contexto** (botão direito): Quick Look, obter informação, favoritos, copiar
  identificador e abrir na aplicação (deep link para `/companies/<NIF>`, `/tickers/<símbolo>`, …).
- **Barra de caminho e de estado** com contagem de itens, registos e valor total; **exportar CSV**
  da lista atual; pesquisa por local (usa a API: contratos, entidades, documentos, tickers).
- Atalhos: `/` pesquisa, setas navegam, Espaço Quick Look, Esc fecha, Retrocesso volta atrás.

### Gráfico Tempo Real (TradingView)

Aplicação **Gráfico Tempo Real** (`/chart` ou `/tickers/<TICKER>/grafico`), própria e no menu de
aplicações: embebe o **Advanced Real-Time Chart** da TradingView — velas, intervalos (1 min a
mensal), estilos (velas, velas ocas, Heikin Ashi, área, linha, barras), indicadores rápidos
(volume, RSI, MACD, Bollinger, EMA), ferramentas de desenho, tema escuro/claro, ecrã inteiro e
ligação direta para a página do ativo na TradingView.

- O ticker da plataforma (`EDP`, `AAPL`) é traduzido no **símbolo da TradingView** a partir da
  bolsa devolvida pela API (`LIS` → `EURONEXT:EDP`, `NMS` → `NASDAQ:AAPL`); também aceita
  sufixos (`EDP.LS`) e símbolos completos (`BME:SAN`).
- A resolução pode ser **substituída à mão** («Símbolo manual»), com o valor guardado por ticker
  em `finance-llm-tv-symbols:v1`; «Repor automático» volta à resolução pela bolsa.
- Pesquisa de tickers na própria janela (lista local com recurso ao Yahoo Finance) e nota de
  rodapé sobre dados em tempo real/diferidos conforme a bolsa.
- O mesmo widget aparece no separador **Gráfico em tempo real** da ficha do ticker
  (Mercados → ticker), com o botão **Abrir em janela** para a aplicação dedicada.
- **Nota de implementação**: o `embed-widget-advanced-chart.js` exige duas coisas ao contentor que o
  envolve, e ambas já provocaram erros visíveis na consola:
  1. o `<script>` tem de ser **filho direto de um elemento com a classe
     `tradingview-widget-container`** (o widget procura-o por
     `document.currentScript.parentNode`); sem isso avisa
     `Cannot listen to the event from the provided iframe, contentWindow is not available`;
  2. esse elemento tem de estar **ligado ao documento** quando o script executa (o script vem de
     cache e corre em milissegundos) e **nunca pode ser removido enquanto o script estiver a
     carregar** — caso contrário o script executa sem pai e rebenta com
     `Uncaught TypeError: Cannot read properties of null (reading 'querySelector')`.

  Por isso o widget é construído em «gerações»: cada mudança de opção cria um contentor novo (já
  ligado ao documento) e a geração anterior é **afastada para `#iqos-tv-retired`** — um contentor
  oculto mas ligado ao documento — sendo apagada logo que o script executa, ou 30 s depois. Isto
  cobre também o duplo `mount`/`unmount` do `StrictMode` em desenvolvimento.
- **Snippet oficial, sem proxy**: a árvore é a do snippet publicado pela TradingView
  (`div.tradingview-widget-container` > `div.tradingview-widget-container__widget` com
  `calc(100% - 32px)` de altura, `div.tradingview-widget-copyright` com a ligação de atribuição e o
  `<script src="https://s3.tradingview.com/external-embedding/embed-widget-advanced-chart.js">` com
  a configuração em JSON — `autosize`, `hide_side_toolbar: true`, `support_host`, `studies`,
  `backgroundColor`/`gridColor` conforme o tema). O script é pedido **diretamente à TradingView**;
  o `/proxy` do Browser **não** é usado por este widget (servir a página da TradingView fora do
  domínio dela faz o motor de gráficos arrancar sem dados e rebentar em `widget-sidetoolbar` com
  `Value is null`).
- **Reserva quando a incorporação é bloqueada**: o script carrega mas o `iframe` para
  `www.tradingview-widget.com` pode ser abortado pelo browser (`ERR_ABORTED`, políticas de
  enquadramento, extensões, redes restritas). Um vigia deteta o quadro vazio em ~5 s e mostra, no
  lugar dele, o **gráfico nativo do IQ OS** (`NativePriceChart`: velas + volume com cotações da
  própria API), com uma nota âmbar, o botão **Tentar a TradingView** e a ligação direta para o
  ativo na TradingView. Os marcadores `hide_side_toolbar`, `hide_top_toolbar`, `estudos` e tema
  continuam a ser aplicados ao widget quando este carrega.

### Indicadores do ticker em cartões

O `TickerInfo.kpis` (Yahoo Finance) é mostrado em **cartões temáticos** — *Valorização*,
*Margens & crescimento*, *Resultados (12 meses)*, *Balanço & liquidez*, *Analistas & preços-alvo*
e *Mercado & capital* (mais *Outros indicadores* para chaves não mapeadas) — tanto na aplicação
**Mercados** como na aba *Visão Geral* da ficha do ticker.

- Cada indicador tem **formato declarado** (`percent`, `ratio`, `scale`, `currency`,
  `compactCurrency`, `count`, `compactCount`): a heurística antiga («se for pequeno é
  percentagem») transformava o nº de analistas `19` em `1900%` e o valor contabilístico `9,66`
  em `965,60%`.
- Números em `pt-PT` (vírgula decimal, milhares com espaço) e valores grandes abreviados
  (`45,34 mM EUR`); as variações levam sinal (`+24,48%`) e cor, margens e rácios não levam `+`.
- Cada linha tem *tooltip* com a chave original e o valor cru (ex.: `trailingPE = 16.73`), para
  não haver dúvidas sobre a proveniência do número.

### Contratos de uma entidade (ver todos)

As listas de **Contratos Recentes** da ficha de entidade (EmpresasIQ e página da empresa) e de
**Contratos associados** do Quick Look têm o botão **Ver todos (N)**, que abre a janela
`entity-contracts:<NIF>` — **Contratos · <entidade>** — com a lista completa:

- **Pesquisa** no objeto (relevância) e filtros por **ano**; ordenação por data de publicação,
  data de celebração, **valor**, objeto ou adjudicatário, com sentido ascendente/descendente.
- Carregamento por páginas de 50 com **scroll infinito** e botão **Carregar mais**, contador
  «X de N contratos», valor dos contratos carregados e **exportação CSV**.
- Colunas Nº, Objeto, **Papel** (adjudicante/adjudicatário), Adjudicatários, Data e Valor;
  clicar numa linha abre a **ficha do contrato** e o botão da última coluna acrescenta o contrato
  à **comparação**.
- Em modo página (telemóvel, sem gestor de janelas) a mesma lista abre na modal do EmpresasIQ.

### Comparação (entidades e contratos)

Aplicação **Comparar** (`/compare`), no menu de aplicações: compara até **4 itens** da mesma
espécie (entidades entre si, contratos entre si) numa **janela** arrastável como as restantes.

- **Entidades**: contratos, valor contratado, valor médio, maior contrato, valor e nº de contratos
  como adjudicante e como adjudicatário, marcas INPI e firmas RNPC — o **melhor valor de cada
  linha** fica destacado (verde) com barra proporcional; matriz de **valor contratado por ano**,
  **CPV em comum** entre as entidades e os **maiores CPV** de cada uma.
- **Contratos**: valor contratual (comparado), objeto, nº, data, tipo de contrato, procedimento,
  adjudicantes, adjudicatários, CPV, local de execução, preço base e partes (NIF), com botão
  **Abrir ficha** por contrato. Linhas sem informação em nenhuma coluna desaparecem.
- **Como chegar lá**: multi-seleção no **Finder** (Ctrl/⌘+clique em 2–4 linhas → **Comparar (n)**),
  menu de contexto do Finder (**Comparar com…**), botão **Comparar** nas fichas de entidade e de
  contrato (passa a **Na comparação**, com **Ver comparação**), Quick Look, ou o seletor
  **+ Adicionar entidade/contrato** dentro da própria janela (pesquisa por nome/NIF/objeto).
- A seleção vive em `localStorage` (`finance-llm-compare:v1`), sobrevive ao recarregar e é
  partilhada por todas as entradas; mudar de espécie substitui a seleção anterior.

### Browser (navegador dentro do IQ OS)

Aplicação **Browser** (`/browser`), no dock e no menu de aplicações: um navegador dentro da
plataforma, para consultar fontes externas sem sair do IQ OS.

- **Separadores** (até 12) com título, ícone e fecho individual; **barra de endereço** que aceita
  URL completo, domínio (`edp.pt`), rota interna (`/tickers`) ou texto livre (pesquisa no motor
  escolhido: DuckDuckGo por omissão, Google, Bing ou Brave, guardado em `finance-llm-browser:v1`).
- **Voltar/avançar** com pilha própria por separador, **recarregar**, **página inicial**,
  **favoritos** (estrela; `Ctrl+D`), **histórico** (300 entradas, com remoção e limpeza) e painel
  lateral com ambos.
- **Página inicial** com atalhos em três grupos: *Plataforma* (páginas do IQ OS), *Mercados*
  (TradingView, Yahoo Finance, Google Finance, Euronext, Investing, CoinMarketCap) e *Fontes
  oficiais* (BASE.gov, CMVM, INE, Banco de Portugal, Eurostat, INPI), mais os favoritos e os
  endereços visitados recentemente.
- **Integração com o IQ OS**: rotas internas conhecidas abrem a aplicação correspondente (ex.:
  `/dashboard`, `/contracts/search`) em vez de serem incorporadas; se um endereço interno for
  escrito à mão aparece a escolha **Abrir na aplicação** / **Ver aqui dentro** / **Abrir em nova
  aba** (evita janelas dentro de janelas, mas permite incorporar quando faz sentido). O botão
  **Procurar no IQ OS** leva a pesquisa para a aplicação *Pesquisa Global*.
- **Sites que recusam incorporação** (`X-Frame-Options`/CSP) são detetados por lista conhecida e
  apresentam um aviso com **Abrir em nova aba** e **Tentar mesmo assim**; quando um endereço não
  responde em 8 s (site offline, rede bloqueada) aparece uma faixa com as mesmas saídas. O botão
  **Abrir numa aba do sistema** está sempre disponível na barra.
- Atalhos dentro da janela: `Ctrl+T` (nova aba), `Ctrl+L` (barra de endereço), `Ctrl+D`
  (favorito), `Ctrl+R` (recarregar), `Alt+←`/`Alt+→` (voltar/avançar). O rodapé permite desligar
  o restauro de separadores ao abrir e **reiniciar a sessão** (mantém favoritos e histórico).

#### Ler páginas que bloqueiam incorporação (proxy do servidor)

A maioria dos sites envia `X-Frame-Options`/`Content-Security-Policy: frame-ancestors` e recusa
ser mostrada num `iframe` (base.gov.pt, euronext.com, finance.yahoo.com, Google, DuckDuckGo,
CMVM, …) — o browser não pode contornar isso, mas o **servidor** pode ler essas páginas.

- `GET|POST /proxy?url=<endereço>` (`api/proxy_routes.py`) busca a página com `httpx`, **remove os
  cabeçalhos que impedem a incorporação** (`X-Frame-Options`, CSP, COOP/COEP/CORP, `Set-Cookie`,
  `Content-Encoding`), reconverte o HTML em UTF-8 e injeta:
  - um `<base href="…">` com o endereço final, para que CSS/JS/imagens continuem a ser pedidos ao
    site original (esses não são bloqueados por políticas de enquadramento);
  - um script que **reencaminha `fetch`/`XMLHttpRequest` para o site original através do próprio
    proxy** (endereços absolutos para o nosso servidor — a página tem `<base>` apontado ao site
    original, pelo que um caminho relativo resolveria para lá e o browser recusava por CORS), que
    **interceta cliques e formulários**: pede ao Browser do IQ OS para navegar (barra de endereço,
    separadores e histórico ficam em sintonia) e faz os POST de formulários dentro do quadro,
    reescrevendo o documento com a resposta (postbacks ASP.NET);
  - um `WebSocket` reencaminhado para `wss://<este servidor>/proxy/ws?url=<destino>&origin=<site>`
    (`api/proxy_routes.py`, `websocket_route`): muitos servidores de tempo real validam o `Origin`
    do *handshake* e recusam o nosso com 403 — o servidor abre então a ligação com o `Origin` do
    próprio site e copia as mensagens nos dois sentidos.
- O proxy é **usado apenas pelo Browser** (e pelas leituras que ele faz); o gráfico da TradingView
  carrega o widget pelo snippet oficial (ver «Gráfico Tempo Real»).
- No Browser, o rodapé tem **«ler bloqueadas pelo servidor»** (ligado por omissão: os sites da
  lista de bloqueio são lidos pelo proxy em vez de mostrar um aviso) e **«ler tudo pelo servidor»**
  (força o proxy em todos os endereços); o indicador **proxy** na barra de endereço mostra quando
  está a ser usado.
- Pesquisa: o motor predefinido é o `lite.duckduckgo.com/lite/?q=`, HTML simples que funciona bem
  pelo proxy (os resultados aparecem dentro do IQ OS; o Google/Bing/Brave devolvem apps de
  JavaScript e ficam incompletos).
- **Limitações assumidas**: não há sessões (cookies não são reenviados, por isso banca/e-mail/redes
  sociais continuam a abrir numa aba do sistema), SPAs muito dependentes de JavaScript podem
  aparecer incompletas e alguns servidores exigem HTTP/2 ou TLS específico.
- **Segurança**: só `http`/`https`, destinos privados/loopback/metadata recusados (SSRF), limite de
  12 MB e tempo limite de 25 s, sem reenvio de cookies nem credenciais. As requisições do proxy
  ficam registadas como eventos de origem `proxy`.

#### Porquê não WASM (e que alternativas existem)

O bloqueio é uma **decisão do servidor** (cabeçalhos HTTP), não uma limitação do motor de
renderização: qualquer mecanismo que carregue a página como documento embutido é bloqueado, mesmo
um browser compilado para WASM. O que resolve é mudar **quem pede** a página ou **onde ela é
renderizada**:

| Abordagem | Custo | Veredicto |
|---|---|---|
| Proxy no servidor (implementado) | horas, `httpx` | ✅ resolve sites estáticos/news/gov e pesquisa; sem sessões |
| Chromium *headless* no servidor (Playwright/CDP + `screencast`) | ~150 MB de binário | ✅ carregaria **qualquer** site (SPAs, login) com input reencaminhado |
| Webview nativo no pacote desktop (Electron/Tauri `WebContentsView`) | empacotamento da app | ✅ o caminho correto a longo prazo para um browser embutido |
| Máquina virtual em WASM (v86/CheerpX) com um browser lá dentro | dezenas de MB, arranque lento, rede por WebSocket, sem integração | ❌ desproporcionado e frágil |
| Motor de render em WASM (Servo, SerenityOS LibWeb) | experimental | ❌ sem paridade de DOM/rede |
| QuickJS em WASM (executar o JS da página num sandbox nosso) | não traz layout/CSS | ⚠️ complemento futuro, hoje desnecessário (o Chromium já corre o JS da página lida) |


### Fornecedores de IA (chat)

O chat aceita, além dos modelos locais, **fornecedores externos** com chave própria ou do
servidor, configuráveis em **Definições → Fornecedores de IA**.

- **Catálogo** (`api/providers_service.py`): OpenAI, DeepSeek, xAI (Grok), Anthropic (Claude),
  Google (Gemini), Groq, Mistral AI (cloud), OpenRouter e **Ollama** (local, sem chave), além dos
  modelos locais da plataforma (GPT-2, Mistral Finance, BloombergGPT-style).
- **Chaves por utilizador** no índice `finance_provider_keys` (`_id` = id do utilizador), com
  máscara na interface (`sk-…abcd`, nunca a chave completa); sem chave própria é usada a
  variável de ambiente do servidor (`OPENAI_API_KEY`, `DEEPSEEK_API_KEY`, `XAI_API_KEY`,
  `ANTHROPIC_API_KEY`, `GEMINI_API_KEY`, `GROQ_API_KEY`, `MISTRAL_API_KEY`, `OPENROUTER_API_KEY`,
  `OLLAMA_API_KEY`, `OLLAMA_BASE_URL`). O botão **Testar** faz um pedido real e traduz os erros
  (401/403/404/429/5xx) numa mensagem em português.
- **Formato do `backend`** no chat: `<fornecedor>` (modelo predefinido) ou
  `<fornecedor>:<modelo>` — ex.: `deepseek:deepseek-reasoner`, `openai:gpt-4o-mini`,
  `google:gemini-2.5-flash`; `gpt2`/`mistral`/`bloomberg` continuam a ser os modelos locais.
  O seletor do chat mostra os grupos **Modelos locais**, **Fornecedores cloud** e **Local
  (Ollama)**, com as opções sem chave desativadas («— sem chave»); a escolha fica guardada
  (`finance-llm-backend`).
- **Como funciona**: nos fornecedores externos, o contexto financeiro (`build_context`) entra no
  *system prompt* e a resposta é transmitida **token a token** pela própria API do fornecedor
  (dialetos OpenAI-compatible, Anthropic `messages` e Google `streamGenerateContent`); nos
  modelos locais o comportamento anterior mantém-se (streaming simulado). Falhas de chave/quota
  aparecem na conversa como `⚠️ <mensagem>` e ficam registadas como eventos de origem
  `providers` (visíveis em Administração → Eventos).
- **Endpoints**: `GET /providers` (catálogo com estado das chaves), `GET /providers/chat-models`
  (lista achatada para o seletor), `PUT /providers/keys`, `PUT /providers/defaults`,
  `POST /providers/test`. Os três *endpoints* de chat continuam a funcionar sem sessão (modelos
  locais); com sessão, resolvem a chave do utilizador através de `Depends(optional_session)`.

### Instalação da aplicação (PWA e pacote Windows)

O IQ OS é **instalável** como aplicação: manifest (`public/manifest.webmanifest`), ícones
(192/512/maskable), atalhos, `display: standalone` e `service worker` (`public/sw.js`, cache do
*shell* + modo offline) fazem-no passar os critérios de instalação do Chromium.

- **Definições → Aplicação IQ OS** mostra o estado real (a correr no browser / pronta a instalar /
  instalada em modo autónomo), o botão **Instalar aplicação** (usa o `beforeinstallprompt`), as
  instruções por browser para quando esse evento não existe (Edge, Chrome, Safari macOS/iOS,
  Firefox), o estado do `service worker` (com **Procurar atualizações**, **Ativar modo offline**
  para registos inválidos e **Limpar cache offline**) e a identidade da aplicação (nome, versão,
  origem).
- Na primeira visita aparece um **convite de instalação** no canto inferior esquerdo, dispensável
  (guardado em `finance-llm-install-dismissed`); o mesmo botão continua em Definições.
- **Pacote Windows**: `public/instalar-iq-os.ps1` cria atalhos no Ambiente de Trabalho e no Menu
  Iniciar que abrem a plataforma numa janela própria do Edge/Chrome (`--app=…`, sem barra do
  browser). Descarregue em Definições ou corra:
  `powershell -ExecutionPolicy Bypass -File .\instalar-iq-os.ps1 -Url http://localhost:5174/`
  (remover com `-Uninstall`; caminho do browser com `-BrowserPath`). A forma preferida continua a
  ser a instalação pelo próprio browser, que cria uma aplicação a sério com arranque offline.

## CLI

Cliente de linha de comandos (não precisa de servidor Python pesado: só `requests`).

```bash
cd finance-llm

python -m cli status                                  # estado da API, ES e sessão
python -m cli auth login nome@empresa.pt              # inicia sessão (token em ~/.finance-llm/config.json)
python -m cli auth register "Nome" nome@empresa.pt    # cria conta (a 1.ª fica administradora)
python -m cli auth whoami                             # dados da conta e preferências
python -m cli auth sessions --revoke-others           # ver/terminar sessões

python -m cli contracts search "reabilitação" --year 2025 --size 5
python -m cli contracts get 15603558
python -m cli contracts analytics --top-entities 5

python -m cli companies search "EDP" --role adjudicatario
python -m cli companies get 503140600                 # ficha + marcas INPI + firmas RNPC
python -m cli companies trademarks 503140600

python -m cli entities search "Sonae" --only-with-nif
python -m cli entities stats

python -m cli market tickers "bank"
python -m cli market quote AAPL
python -m cli forecast AAPL --days 10 --sentiment
python -m cli chat "como está o mercado hoje?"

python -m cli users list                              # administração (só admins)
python -m cli open empresas-iq --print-only
```

Notas de uso:

- `--json` em qualquer comando devolve a resposta crua (útil em scripts);
  `--api`/`--token` permitem apontar a outra instância ou usar um token pontual.
- A configuração fica em `~/.finance-llm/config.json` (ou `$FINANCE_LLM_HOME`), com permissões restritas.
- No Windows há atalhos: `finance-llm.cmd status` ou `.\finance-llm.ps1 status`.
- Os valores monetários, datas e tabelas são formatados para leitura; a codificação é adaptada à consola.

### Terminal na interface web

A página **Terminal** (`/cli`) corre o mesmo CLI no servidor e mostra a saída na aplicação:

- `GET  /cli/commands` — comandos permitidos (alimenta a paleta de sugestões)
- `POST /cli/run` — corpo `{"command": "contracts search \"obras\" --year 2025"}` → stdout/stderr,
  código de saída, duração e indicação de tempo excedido

Segurança: a rota exige sessão e executa o CLI com `shell=False` e **lista de argumentos validada**
(a árvore de comandos vem do próprio `argparse` do CLI). O token da sessão é injetado por variável
de ambiente (nunca aparece no processo) e as operações de conta — login, registo, logout,
alteração de palavra-passe — estão deliberadamente bloqueadas, para se fazerem nas Definições
ou num terminal local.

## Endpoints da API

### Chat

- `GET  /` — health check
- `GET  /health` — health check alternativo com modelos disponíveis
- `POST /chat?backend=gpt2|mistral` — resposta síncrona (inclui detecção automática de perguntas de previsão de preços)
- `POST /chat/stream?backend=gpt2|mistral` — resposta em streaming (SSE)
- `GET  /chat/stream` — endpoint SSE alternativo

### RAG (BloombergGPT-style)

- `GET  /rag/documents` — listar documentos carregados
- `POST /rag/upload` — fazer upload de um PDF
- `POST /rag/chat` — perguntar ao RAG
- `GET  /rag/health` — verificar estado do índice e modelos

### Ontologia (camada semântica)

A ontologia descreve os objetos da plataforma (Empresa, Entidade Pública, Contrato,
CPV, Região, Marca, Firma, Ticker, Cotação, Notícia, Sentimento, Tópico, Conta,
Contacto, Oportunidade, Atividade, Pessoa), as suas propriedades, as ligações entre
eles e as ações disponíveis — tudo ligado aos dados reais do Elasticsearch. É a
mesma definição que fundamenta e **valida** as respostas da IA.

A semente vive em `api/ontology_registry.py` e é copiada para
`data/ontology/ontology.json`; quaisquer alterações feitas na plataforma (tipos
personalizados, propriedades, desativações) ficam guardadas nesse ficheiro.

Leitura:

- `GET  /ontology` — ontologia completa (tipos, ligações, ações)
- `GET  /ontology/summary` — resumo + grafo de tipos
- `GET  /ontology/object-types` · `GET /ontology/object-types/{id}`
- `GET  /ontology/link-types` · `GET /ontology/actions` · `GET /ontology/graph`
- `GET  /ontology/status` — disponibilidade dos índices e volumetria
- `POST /ontology/objects/{tipo}/query` — consulta (pesquisa, filtros, ordenação)
- `GET  /ontology/objects/{tipo}/{id}?with_links=true` — objeto + relações
- `POST /ontology/objects/{tipo}/{id}/links` — navegação nas relações
- `POST /ontology/resolve` — resolução de entidades (texto → objetos canónicos)

IA:

- `POST /ontology/ai/context` — contexto ontológico (grounding) de uma pergunta
- `POST /ontology/ai/answer` — resposta factual construída só com a ontologia
- `POST /ontology/ai/validate` — validação anti-alucinação de uma resposta
- `GET  /ontology/ai/tools` — ferramentas geradas a partir da ontologia

Escrita (requer sessão; apagar/repor exige papel `admin`):

- `POST/PATCH/DELETE /ontology/object-types…` e `/ontology/link-types…`
- `POST /ontology/reset` — repõe a semente

Os tipos ligados ao CRM (`finance_crm`) exigem sessão: cada utilizador só vê os seus
registos (os administradores veem os da equipa); sem sessão ficam de fora dos
resultados e do grounding da IA.

### Autenticação (contas no Elasticsearch)

As contas ficam em `finance_users` e as sessões em `finance_sessions`. O browser
envia `Authorization: Bearer <token>`; o token é assinado (HMAC-SHA256) e apenas
transporta o id da sessão, pelo que terminar sessão é imediato.

- `POST   /auth/register` — criar conta (a primeira conta criada fica como **admin**)
- `POST   /auth/login` — iniciar sessão (`remember: true` dá uma sessão de 30 dias)
- `POST   /auth/logout` — terminar a sessão atual
- `GET    /auth/me` — dados da conta autenticada
- `PATCH  /auth/me` — atualizar perfil e preferências (`default_view`, `dock_position`, `sidebar_hidden`, `sidebar_mode`, `window_mode`, `reduced_motion`)
- `POST   /auth/password` — alterar palavra-passe (revoga as outras sessões)
- `GET    /auth/sessions` — listar sessões ativas
- `DELETE /auth/sessions/{id}` — terminar uma sessão concreta
- `DELETE /auth/sessions` — terminar todas as outras sessões
- `DELETE /auth/me` — apagar a conta (confirmação pela palavra-passe)
- `GET    /auth/stats` — contadores (apenas administradores)

Variáveis de ambiente:

- `FINANCE_AUTH_SECRET` (opcional) — segredo de assinatura dos tokens. Se não for
  definido, é gerado e guardado em `data/.auth_secret`.

As palavras-passe usam `hashlib.scrypt` (salt por conta) e nunca são guardadas em
texto simples. As preferências da conta são aplicadas ao entrar (vista inicial,
posição do dock, modo da barra lateral, modo janelas, animações reduzidas).

A escolha do modelo é feita no frontend (seletor do chat). Quando se escolhe **BloombergGPT-style (RAG)**, as perguntas do chat principal e da página `/rag` são encaminhadas para o motor RAG, que responde com base nos PDFs indexados e cita as fontes.

## Modelos

### GPT-2 financeiro

- Arquitetura: `n_embd=512`, `n_layer=8`, `n_head=8`, `n_positions=1024`
- Vocabulário: ~3000 tokens BPE `ByteLevel`
- Tokens especiais: `<|endoftext|>`, `<pad>`
- Directoria: `model/gpt2-finance/`

### Mistral financeiro

- Arquitetura: `hidden_size=512`, `intermediate_size=1024`, `num_hidden_layers=8`, `num_attention_heads=8`, `num_key_value_heads=4`, `max_position_embeddings=1024`, `sliding_window=512`
- Vocabulário: ~3000 tokens BPE `ByteLevel`
- Tokens especiais: `<s>`, `</s>`, `<pad>`, `<unk>`
- Directoria: `model/mistral-finance/`

### BloombergGPT-style financeiro (RAG)

- Wrapper sobre Mistral com prompts financeiros/RAG em português.
- Directoria preferencial: `model/bloomberg-finance/final`
- Fallback para `model/mistral-finance/final` e `model/gpt2-finance/final` se o modelo principal não existir ou gerar texto incoerente.
- Geração padrão conservadora: `max_new_tokens=64`, `temperature=0.1` para CPU.
- O motor RAG usa `sentence-transformers/all-MiniLM-L6-v2` + FAISS `IndexFlatIP` (similaridade coseno) para recuperar chunks semânticos.

## RAG: PDF → Markdown → FAISS

1. **Upload** de PDF via `/rag/upload` ou no separador **RAG** do UI.
2. **Conversão** para Markdown com PyMuPDF (`fitz`).
3. **Chunking** com sobreposição de 32 tokens e tamanho máximo de 256 tokens.
4. **Armazenamento** em `data/rag/` (Markdowns e índice FAISS).
5. **Recuperação** dos top-k chunks mais relevantes.
6. **Resposta** do modelo BloombergGPT-style com fallback para os chunks recuperados se o texto gerado for considerado "gibberish".

## Notas

- O tokenizer usa BPE com `ByteLevel` para preservar espaços e caracteres especiais.
- A qualidade das respostas depende diretamente do tempo de treino; os demos rápidos usam subconjuntos pequenos por razões de velocidade em CPU.
- Para melhorar a coerência, treinar por mais epochs ou aumentar `max_length` ajuda, mas o corpus deve conter exemplos alinhados com o formato `Question: ... Answer:` usado pelo agente.
- Os modelos pequenos (GPT-2/Mistral) **não são instruction-tuned**; o RAG utiliza robustamente os chunks recuperados quando o modelo não é fiável.
