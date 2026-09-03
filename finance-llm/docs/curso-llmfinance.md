# Cria o teu Modelo LLMFinance: curso completo

> Curso prático para construir, treinar e servir um modelo de língua especializado em finanças, com dados reais do Yahoo Finance.

---

## 1. Visão geral do projeto

O **LLMFinance** é um projeto didático que recolhe dados financeiros públicos, constrói um corpus textual, treina modelos de linguagem (GPT-2 e Mistral) e expõe tudo através de uma API FastAPI e uma interface de chat semelhante ao ChatGPT.

### Objectivos de aprendizagem

- Criar um pipeline completo de dados: coleta → processamento → treino → inferência.
- Construir e treinar modelos de linguagem do zero com PyTorch e Transformers.
- Implementar treino com pausa/continuação e *checkpoints*.
- Servir o modelo via FastAPI com *streaming* de respostas.
- Criar uma interface React moderna para interagir com o modelo.

### Arquitetura

```text
finance-llm/
├── collectors/        # recolha de dados (Yahoo, FRED, etc.)
├── processing/         # normalização e criação do corpus
├── tokenizer/          # tokenizer financeiro
├── model/              # modelos GPT-2 e Mistral
├── training/           # scripts de treino
├── inference/          # geração de texto
├── api/                # FastAPI + agente
└── chat-ui/            # React + Vite
```

---

## 2. Configuração do ambiente

### Requisitos

- Python 3.10 ou superior.
- `uv` para gestão do ambiente virtual (recomendado) ou `venv`.
- Node.js 20+ para o *chat-ui*.

### Criar ambiente e instalar dependências

```powershell
# Windows
cd C:\LLMFinance\finance-llm
uv venv
.venv\Scripts\python -m pip install -r requirements.txt
```

### Instalar dependências do frontend

```powershell
cd chat-ui
npm install
```

---

## 3. Coleta de dados

### Dados do Yahoo Finance

O script `collectors/yahoo.py` descarrega informações de empresa e preços históricos.

```powershell
.venv\Scripts\python -c "from collectors.yahoo import save_raw; save_raw()"
```

Os ficheiros são guardados em:

- `data/raw/yfinance/<TICKER>_info.json`
- `data/raw/yfinance/<TICKER>_1d.parquet`

### Outras fontes

- `collectors/fred.py` — indicadores macro (inflação, taxas de juro).
- `collectors/ecb.py` — dados do Banco Central Europeu.
- `collectors/cmvm.py` — dados da CMVM (Portugal).
- `collectors/sec.py` — *filings* da SEC.

---

## 4. Construção do corpus

O script `processing/build_corpus.py` transforma os dados em frases de treino no formato instrução/resposta.

```powershell
.venv\Scripts\python processing\build_corpus.py
```

Gera:

- `data/final/train.jsonl`
- `data/final/validation.jsonl`
- `data/final/test.jsonl`

### Formato do corpus

Cada linha é um objecto JSON com a chave `text`. Exemplo:

```json
{"text": "Instruction: What was the closing price of AAPL on 2026-09-02?\nResponse: The closing price of AAPL on 2026-09-02 was 225.50."}
```

### Tipos de exemplos gerados

- Resumos de negócio a partir de `longBusinessSummary`.
- Métricas fundamentais: capitalização, *beta*, EPS, dividend yield.
- Cotações diárias: open, high, low, close, volume.
- Médias móveis de 5, 10, 20 e 50 dias.
- Variações percentuais e tendências.
- Perguntas e respostas simples (formato Question/Answer).

---

## 5. Tokenizer financeiro

O tokenizer de 3000 tokens cobre palavras comuns de finanças, tickers e números.

```powershell
.venv\Scripts\python tokenizer\finance_tokenizer.py
```

Guarda o resultado em `tokenizer/finance_tokenizer/` e copia-o para as pastas dos modelos durante o treino.

---

## 6. Treino do GPT-2

### Iniciar treino

```powershell
.venv\Scripts\python training\train.py --epochs 3 --batch_size 4 --max_length 128 --learning_rate 5e-5
```

### Estrutura do modelo

- `n_embd = 512`
- `n_layer = 8`
- `n_head = 8`
- `n_positions = 1024`

### Resultados esperados

- Modelo guardado em `model/gpt2-finance/final/`.
- *Checkpoints* a cada 200 passos em `model/gpt2-finance/checkpoints/`.

---

## 7. Treino do Mistral

### Estrutura do modelo mini-Mistral

- `hidden_size = 512`
- `intermediate_size = 1024`
- `num_hidden_layers = 8`
- `num_attention_heads = 8`
- `num_key_value_heads = 4` (attenção agrupada)
- `max_position_embeddings = 1024`
- `sliding_window = 512`

### Iniciar treino do zero

```powershell
.venv\Scripts\python training\train_mistral.py --epochs 3 --batch_size 4 --max_length 128 --learning_rate 2e-5
```

### Continuar treino a partir do modelo final anterior

```powershell
.venv\Scripts\python training\train_mistral.py --epochs 5 --batch_size 4 --max_length 128 --learning_rate 2e-5 --resume
```

### Pausar treino

```powershell
.venv\Scripts\python training\train_mistral.py --pause
```

### Continuar após pausa

```powershell
.venv\Scripts\python training\train_mistral.py --continue
```

### Estado de treino

- Guardado em `training/mistral_state.pt`.
- Flag de pausa em `training/pause.flag`.

---

## 8. Avaliação

O script `inference/generate_mistral.py` pode avaliar perplexidade no test set.

```powershell
.venv\Scripts\python inference\generate_mistral.py --eval --model_dir model/mistral-finance/final
```

Métricas úteis:

- **Loss** médio no test set.
- **Perplexidade** (`exp(loss)`).
- Inspeção manual de respostas no chat.

---

## 9. API FastAPI

### Iniciar o servidor

```powershell
.venv\Scripts\python -m uvicorn api.main:app --host 127.0.0.1 --port 8001
```

### Endpoints principais

- `GET /health` — verifica estado.
- `POST /chat` — resposta completa.
- `POST /chat/stream` ou `GET /chat/stream?message=...&backend=mistral` — resposta em *streaming*.

### Selecionar backend

Passe `backend=gpt2` ou `backend=mistral` nos pedidos de *stream*.

---

## 10. Interface de chat

### Iniciar frontend

```powershell
cd chat-ui
npm run dev
```

A interface abre em `http://localhost:5173`.

### Funcionalidades

- Troca de mensagens estilo ChatGPT.
- Escolha entre GPT-2 e Mistral.
- Mostra respostas de fallback factual quando o modelo não é coerente.

---

## 11. Melhorias e próximos passos

- Aumentar a dimensão do modelo (mais camadas, *hidden size* maior).
- Treinar com mais epochs e *learning rate* menor.
- Usar LoRA/QLoRA para treino eficiente.
- Adicionar dados de notícias financeiras (RSS, APIs de notícias).
- Implementar *RAG* com embeddings de documentos.
- Adicionar avaliação automática com BLEU/ROUGE.

---

## 12. Resumo de comandos

```powershell
# 1. Coletar dados
.venv\Scripts\python -c "from collectors.yahoo import save_raw; save_raw()"

# 2. Construir corpus
.venv\Scripts\python processing\build_corpus.py

# 3. Treinar tokenizer
.venv\Scripts\python tokenizer\finance_tokenizer.py

# 4. Treinar GPT-2
.venv\Scripts\python training\train.py --epochs 3 --learning_rate 5e-5

# 5. Treinar Mistral
.venv\Scripts\python training\train_mistral.py --epochs 5 --learning_rate 2e-5 --resume

# 6. Iniciar API
.venv\Scripts\python -m uvicorn api.main:app --host 127.0.0.1 --port 8001

# 7. Iniciar chat UI
cd chat-ui; npm run dev
```

---

*Curso criado para reutilização permanente no projeto LLMFinance.*
