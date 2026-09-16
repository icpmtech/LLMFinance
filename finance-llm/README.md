# Finance-LLM

Chat financeiro com três modelos de linguagem — GPT-2, Mistral e um **BloombergGPT-style (RAG)** — treinados sobre dados do Yahoo Finance, acessíveis via API FastAPI e interface React semelhante ao ChatGPT. O backend permite escolher o modelo em cada pedido (`gpt2`, `mistral` ou `bloomberg`). O modelo BloombergGPT-style lê documentos PDF convertidos para Markdown e responde com base no conhecimento indexado.

> **Arquitetura completa do RAG:** ver [`docs/bloomberggpt_rag_architecture.md`](docs/bloomberggpt_rag_architecture.md).

## Estrutura

```
finance-llm/
├── api/                 # Backend FastAPI + agente financeiro + RAG
│   ├── main.py          # Entrypoint FastAPI
│   ├── rag_routes.py    # Endpoints RAG
│   ├── rag_service.py   # Serviço RAG singleton + cache de modelos
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

Para correr backend + frontend em containers, garante que tens Docker Desktop/Engine instalado e corre:

```bash
docker compose up --build -d
```

- Frontend: http://127.0.0.1:4180
- API docs (Swagger): http://127.0.0.1:8003/docs

Para parar:

```bash
docker compose down
```

Mais detalhes em [`docs/docker-setup.md`](docs/docker-setup.md).

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

> Nota: a API está configurada para `http://127.0.0.1:8003` em `chat-ui/src/api.ts`. Se alterares a porta, atualiza também o frontend e reconstrói o UI.

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

### Autenticação (contas no Elasticsearch)

As contas ficam em `finance_users` e as sessões em `finance_sessions`. O browser
envia `Authorization: Bearer <token>`; o token é assinado (HMAC-SHA256) e apenas
transporta o id da sessão, pelo que terminar sessão é imediato.

- `POST   /auth/register` — criar conta (a primeira conta criada fica como **admin**)
- `POST   /auth/login` — iniciar sessão (`remember: true` dá uma sessão de 30 dias)
- `POST   /auth/logout` — terminar a sessão atual
- `GET    /auth/me` — dados da conta autenticada
- `PATCH  /auth/me` — atualizar perfil e preferências (`default_view`, `dock_position`, `sidebar_hidden`, `reduced_motion`)
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
posição do dock, barra lateral, animações reduzidas).

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
