# Finance-LLM

Chat financeiro com dois modelos de linguagem pequenos — GPT-2 e Mistral — treinados sobre dados do Yahoo Finance, acessíveis via API FastAPI e interface React semelhante ao ChatGPT. O backend permite escolher o modelo em cada pedido (`gpt2` ou `mistral`).

## Estrutura

```
finance-llm/
├── api/                 # Backend FastAPI + agente financeiro (dual backend)
├── chat-ui/             # Frontend React + Vite + Tailwind CSS v4
├── collectors/          # Recolha de dados (Yahoo Finance, FRED, ECB, ...)
├── processing/          # Normalização e construção do corpus
├── model/               # GPT-2 e Mistral financeiros + tokenizers BPE
│   ├── gpt2_finance.py
│   ├── gpt2-finance/
│   ├── mistral_finance.py
│   └── mistral-finance/
├── training/            # Fine-tuning manual em PyTorch
│   ├── train.py         # GPT-2
│   └── train_mistral.py # Mistral
├── inference/           # Geração de texto
│   ├── generate.py         # GPT-2
│   └── generate_mistral.py # Mistral
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

# Frontend
cd chat-ui
npm install
```

## Recolha de dados

```bash
.venv\Scripts\python collectors/yahoo.py
```

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

Terminal 1 — backend (FastAPI, porta `8001`):

```bash
cd finance-llm
.venv\Scripts\python -m uvicorn api.main:app --reload --host 127.0.0.1 --port 8001
```

Terminal 2 — frontend (Vite dev server, porta `5173`):

```bash
cd finance-llm/chat-ui
npm run dev
```

Abre http://127.0.0.1:5173 no browser.

> Nota: a build de produção do UI pode ser servida em qualquer porta estática (por exemplo `8000`), mas a API está configurada para `http://127.0.0.1:8001` em `chat-ui/src/api.ts`.

## Endpoints da API

- `GET  /` — health check
- `GET  /health` — health check alternativo
- `POST /chat?backend=gpt2|mistral` — resposta síncrona
- `POST /chat/stream?backend=gpt2|mistral` — resposta em streaming (SSE)
- `GET  /chat/stream` — endpoint SSE alternativo

A escolha do modelo é feita com o query parameter `backend` (`gpt2` ou `mistral`). O frontend inclui um seletor de modelo no chat.

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

## Notas

- O tokenizer usa BPE com `ByteLevel` para preservar espaços e caracteres especiais.
- A qualidade das respostas depende diretamente do tempo de treino; os demos rápidos usam subconjuntos pequenos por razões de velocidade em CPU.
- Para melhorar a coerência, treinar por mais epochs ou aumentar `max_length` ajuda, mas o corpus deve conter exemplos alinhados com o formato `Question: ... Answer:` usado pelo agente.
