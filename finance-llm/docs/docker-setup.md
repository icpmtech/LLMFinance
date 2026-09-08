# Docker Setup — FinanceLLM

Este documento explica como correr toda a solução FinanceLLM (backend FastAPI + frontend React) com Docker Compose.

## Ficheiros criados

- `Dockerfile.backend` — container Python 3.11 com FastAPI, uvicorn e dependências.
- `Dockerfile.frontend` — build do React/Vite servido por nginx.
- `docker-compose.yml` — orquestra backend e frontend.
- `docker/nginx.conf` — configuração do nginx com proxy `/api/` para o backend.
- `.dockerignore` — ignora ficheiros desnecessários na build.
- `chat-ui/src/api.ts` — `API_BASE` usa caminho relativo `/api` em produção ou `VITE_API_URL` se definido.

## Portas expostas

| Serviço     | Host        | Container | URL de acesso            |
|-------------|-------------|-----------|--------------------------|
| Backend API | `127.0.0.1` | `8000`    | http://127.0.0.1:8003    |
| Frontend UI | `127.0.0.1` | `80`      | http://127.0.0.1:4180    |

## Requisitos

- Docker Desktop ou Docker Engine + Compose.
- ~6 GB de disco para as imagens (PyTorch + transformers).

## Como usar

### 1. Construir e iniciar

Abre um terminal na raiz do projeto (`C:\LLMFinance\finance-llm`) e corre:

```powershell
docker compose up --build -d
```

A primeira build pode demorar vários minutos porque instala PyTorch e faz o download/verificação dos modelos.

### 2. Verificar estado

```powershell
docker compose ps
docker compose logs backend -f
docker compose logs frontend -f
```

### 3. Aceder à aplicação

- Frontend: http://127.0.0.1:4180
- API docs (Swagger): http://127.0.0.1:8003/docs
- Health check: http://127.0.0.1:8003/health

### 4. Parar

```powershell
docker compose down
```

Para remover também volumes e imagens:

```powershell
docker compose down --rmi all -v
```

## Volumes montados

O `docker-compose.yml` monta as seguintes pastas do host no container backend:

- `./data:/app/data` — dados processados, tickers, forecast plots, etc.
- `./model:/app/model` — modelos treinados (GPT-2, Mistral, BloombergGPT-style).
- `./rag:/app/rag` — armazenamento do RAG (índice, markdowns, chunks).

Isto permite que os dados e modelos persistam entre execuções dos containers.

## Variáveis de ambiente

Podes definir `VITE_API_URL` no `docker-compose.yml` ou num ficheiro `.env` para apontar o frontend para outro backend. Por omissão:

- Em desenvolvimento (`npm run dev`): usa `http://127.0.0.1:8003`.
- Em produção (nginx container): usa `/api` (proxy interno para `backend:8000`).

## Notas

- O backend expõe `0.0.0.0:8000` dentro do container; o host mapeia para `8003` para manter consistência com o porto usado localmente.
- O frontend em produção serve a SPA React e redireciona todos os pedidos `/api/*` e `/forecast/plot/*` para o backend.
