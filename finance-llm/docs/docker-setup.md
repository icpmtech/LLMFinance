# Docker Setup — IQ OS

Este documento explica como correr toda a solução IQ OS (Elasticsearch + backend FastAPI + frontend React) com Docker Compose.

## Ficheiros

- `Dockerfile.backend` — container Python 3.11 com FastAPI, uvicorn e dependências.
- `Dockerfile.frontend` — build do React/Vite servido por nginx (build com `VITE_API_URL=/api`).
- `docker-compose.yml` — orquestra `elasticsearch`, `backend` e `frontend`.
- `docker/nginx.conf` — nginx com SPA, proxy `/api/` e `/forecast/plot/` para o backend, uploads até 256 MB e SSE sem buffering.
- `docker/entrypoint.backend.sh` — cria as pastas de dados e arranca o uvicorn em `0.0.0.0:8000`.
- `.dockerignore` — exclui `data/`, `model/`, `training/`, `logs/` e `node_modules` do contexto da build.
- `.env.example` — portas e variáveis opcionais (copiar para `.env` se necessário).

## Portas expostas

| Serviço       | Container | URL de acesso            |
|---------------|-----------|--------------------------|
| Elasticsearch | `9200`    | http://127.0.0.1:9200    |
| Backend API   | `8000`    | http://127.0.0.1:8003    |
| Frontend UI   | `80`      | http://127.0.0.1:4180    |

Os portos do host são configuráveis por variáveis (`ELASTICSEARCH_PORT`, `FINANCE_API_PORT`, `FINANCE_UI_PORT`), com os valores por omissão acima.

## Requisitos

- Docker Desktop ou Docker Engine + Compose.
- ~6 GB de disco para as imagens (PyTorch + transformers).

## Como usar

### 1. Construir e iniciar

Abre um terminal na raiz do projeto (`C:\LLMFinance\finance-llm`) e corre:

```powershell
docker compose up --build -d
```

A primeira build pode demorar vários minutos (PyTorch, transformers, faiss). O `data/`, `model/` e `rag/` do host **não** entram na imagem: são montados como volumes, portanto a build não copia os ~16 GB de dados/modelos.

### 2. Verificar estado

```powershell
docker compose ps
docker compose logs backend -f
docker compose logs frontend -f
docker compose logs elasticsearch -f
```

Os três serviços têm healthcheck: o backend só arranca depois de o Elasticsearch estar saudável (`/health` responde) e o frontend só depois de o backend estar saudável.

### 3. Aceder à aplicação

- Frontend: http://127.0.0.1:4180
- API docs (Swagger): http://127.0.0.1:8003/docs
- Health check: http://127.0.0.1:8003/health
- Elasticsearch: http://127.0.0.1:9200/_cluster/health

### 4. Parar

```powershell
docker compose down
```

Para remover também volumes e imagens:

```powershell
docker compose down --rmi all -v
```

O volume `es-data` guarda os índices do Elasticsearch (utilizadores, contratos, entidades, etc.); `down` sem `-v` preserva-os.

## Volumes montados

O `docker-compose.yml` monta as seguintes pastas do host no container backend:

- `./data:/app/data` — dados processados, tickers, uploads, índice do RAG, `data/.auth_secret`.
- `./model:/app/model` — modelos treinados (GPT-2, Mistral, BloombergGPT-style).
- `./rag:/app/rag` — armazenamento do RAG (índice, markdowns, chunks).
- `./logs:/app/logs` — `events.jsonl` e restantes logs da aplicação.

Isto permite que os dados e modelos persistam entre execuções dos containers e que a instância Docker partilhe os mesmos dados da instância local (mesma chave de autenticação e mesmos índices).

## Variáveis de ambiente

| Variável | Omissão | Descrição |
|----------|---------|-----------|
| `FINANCE_API_PORT` | `8003` | Porto do host para a API. |
| `FINANCE_UI_PORT` | `4180` | Porto do host para a UI. |
| `ELASTICSEARCH_PORT` | `9200` | Porto do host para o Elasticsearch. |
| `VITE_API_URL` | `/api` | Base da API compilada na SPA. `/api` usa o proxy do nginx (mesma origem, sem CORS). |
| `FINANCE_ES_URL` | `http://elasticsearch:9200` | Endereço do Elasticsearch **visto de dentro do container**. |
| `FINANCE_AUTH_SECRET` | vazio | Se vazio, é usado/reutilizado `data/.auth_secret`. |
| `FRED_API_KEY`, `BRAVE_API_KEY`, `SERPAPI_KEY`, `OPENAI_API_KEY`, `OPENAI_BASE_URL`, `OPENAI_MODEL`, `OLLAMA_URL` | vazio | Chaves/endpoints opcionais das ferramentas do agente. |

## Notas e armadilhas resolvidas

- **Elasticsearch dentro do container**: o cliente lê `ELASTICSEARCH_URL` (não `ES_HOST`). No container tem de apontar para o nome do serviço (`http://elasticsearch:9200`); `127.0.0.1` apontaria para o próprio backend.
- **API base da SPA**: `chat-ui/src/api.ts` usa `VITE_API_URL` e cai em `http://127.0.0.1:8002` quando a variável está vazia. Por isso o Dockerfile compila com `VITE_API_URL=/api` — deixar vazio partiria a UI em container.
- **Uploads**: o nginx tem `client_max_body_size 256m`; sem isto os uploads de PDF devolviam 413.
- **Chat em streaming**: `/api/` é proxiado com `proxy_buffering off` e `proxy_read_timeout 3600s` para as respostas SSE não ficarem em buffer nem serem cortadas.
- **Contexto da build**: `data/` (~12 GB) e `model/` (~3 GB) estão no `.dockerignore`. Sem isso a build enviaria >16 GB para o daemon.

