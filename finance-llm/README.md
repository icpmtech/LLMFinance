# Finance-LLM

Chat financeiro com um modelo de linguagem pequeno (GPT-2) treinado sobre dados do Yahoo Finance, acessível via API FastAPI e interface React semelhante ao ChatGPT.

## Estrutura

```
finance-llm/
├── api/                 # Backend FastAPI + agente financeiro
├── chat-ui/             # Frontend React + Vite + Tailwind CSS v4
├── collectors/          # Recolha de dados (Yahoo Finance, FRED, ECB, ...)
├── processing/          # Normalização e construção do corpus
├── model/               # GPT-2 financeiro e tokenizer BPE
├── training/            # Fine-tuning manual em PyTorch
├── inference/           # Geração de texto com o modelo treinado
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

## Construir corpus e treinar modelo

```bash
.venv\Scripts\python processing/build_corpus.py
.venv\Scripts\python model/gpt2_finance.py
.venv\Scripts\python training/train.py
```

Por defeito o treino usa todo o corpus (`8070` exemplos de treino), o que pode demorar várias horas em CPU. Para um teste rápido:

```bash
.venv\Scripts\python -c "from training.train import train_model; train_model(max_samples=500, save_checkpoints=False)"
```

## Executar

Terminal 1 — backend:

```bash
cd finance-llm
.venv\Scripts\python -m uvicorn api.main:app --reload --host 127.0.0.1 --port 8000
```

Terminal 2 — frontend:

```bash
cd finance-llm/chat-ui
npm run dev
```

Abre http://127.0.0.1:5173 no browser.

## Endpoints da API

- `GET  /` — health check
- `POST /chat` — resposta síncrona
- `POST /chat/stream` — resposta em streaming (SSE)
- `GET  /chat/stream` — endpoint SSE alternativo

## Notas

- O tokenizer usa BPE com `ByteLevel` para preservar espaços e caracteres especiais.
- O modelo base GPT-2 usa `n_embd=512`, `n_layer=8`, `n_head=8`, vocabulário ~3000 tokens.
- A qualidade das respostas depende diretamente do tempo de treino; o demo padrão usa um subconjunto pequeno por razões de velocidade em CPU.
