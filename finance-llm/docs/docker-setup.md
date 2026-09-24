# Docker Setup — IQ OS

Este documento explica como correr toda a solução IQ OS (Elasticsearch + backend FastAPI + frontend React + servidor MCP + aplicações de apoio) com Docker Compose.

## Ficheiros

- `Dockerfile.backend` — container Python 3.11 com FastAPI, uvicorn e dependências.
- `Dockerfile.frontend` — build do React/Vite servido por nginx (build com `VITE_API_URL=/api`).
- `Dockerfile.test` — imagem de testes (`iq-os-tests`): parte da imagem do backend e acrescenta `pytest`.
- `docker-compose.yml` — orquestra `elasticsearch`, `backend`, `frontend`, `searxng` e `n8n` (núcleo) mais `mcp`, `tests` e `hermes-agent` (por perfis).
- `docker/nginx.conf` — nginx com SPA, proxy `/api/` e `/forecast/plot/` para o backend, uploads até 256 MB, SSE sem buffering e os **proxies de incorporação** dos iframes (portos 8891/8892).
- `docker/entrypoint.backend.sh` — cria as pastas de dados e arranca o uvicorn em `0.0.0.0:8000`.
- `docker/smoke_test.py` — teste de fumo que percorre o OpenAPI e valida a API e a SPA.
- `docker/searxng/settings.yml` — configuração do SearXNG (JSON ligado, limiter desligado).
- `docker/hermes/plugins/dashboard-auth-iqos/` — plugin do dashboard do Hermes que valida o login **nas contas do IQ OS**.
- `docker/hermes/init/026-enable-iqos-plugin.sh` — ativa esse plugin em cada arranque do container.
- `.dockerignore` — exclui `data/`, `model/`, `training/`, `logs/` e `node_modules` do contexto da build.
- `.env.example` — portas e variáveis opcionais (copiar para `.env` se necessário).

## Perfis de serviços

| Perfil   | Serviços                                     | Para que serve                                              |
|----------|----------------------------------------------|-------------------------------------------------------------|
| (nenhum) | `elasticsearch`, `backend`, `frontend`, `searxng`, `n8n` | Núcleo da solução — arranca com `docker compose up`. |
| `tools`  | `mcp`                                        | Servidor MCP em HTTP (`http://127.0.0.1:8765/mcp`).          |
| `agents` | `hermes-agent`                               | Agente Hermes: API OpenAI-compatível + dashboard web.        |
| `test`   | `tests`                                      | `pytest tests` + smoke test de todos os endpoints, em Docker. |

## Portas expostas

| Serviço                        | Container | URL de acesso              |
|--------------------------------|-----------|----------------------------|
| Elasticsearch                  | `9200`    | http://127.0.0.1:9200      |
| Backend API                    | `8000`    | http://127.0.0.1:8003      |
| Frontend UI (SPA)              | `80`      | http://127.0.0.1:4180      |
| Servidor MCP                   | `8765`    | http://127.0.0.1:8765/mcp  |
| SearXNG (metasearch)           | `8080`    | http://127.0.0.1:8888      |
| n8n (direto)                   | `5678`    | http://127.0.0.1:5678      |
| n8n (proxy de iframe)          | `8891`    | http://127.0.0.1:8891      |
| Hermes Agent — API OpenAI      | `8642`    | http://127.0.0.1:8642      |
| Hermes Agent — dashboard       | `9119`    | http://127.0.0.1:8892 *(só via proxy)* |

Os portos do host são configuráveis por variáveis (`ELASTICSEARCH_PORT`, `FINANCE_API_PORT`, `FINANCE_UI_PORT`, `IQOS_MCP_PORT`, `SEARXNG_PORT`, `N8N_PORT`, `N8N_EMBED_PORT`, `HERMES_API_PORT`, `HERMES_EMBED_PORT`), com os valores por omissão acima.

## Páginas iframe (Pesquisa, n8n, Hermes Agent)

A solução traz três aplicações externas **pré-instaladas** como páginas iframe da SPA (ver `chat-ui/src/iframePages.ts`) e abríveis pelo dock:

| Página       | Iframe aponta para        | Notas                                                                 |
|--------------|---------------------------|-----------------------------------------------------------------------|
| Pesquisa     | `http://<host>:8888/`     | SearXNG; não envia cabeçalhos de bloqueio, é incorporado diretamente.  |
| n8n          | `http://<host>:8891/`     | O n8n envia `X-Frame-Options: SAMEORIGIN`; o nginx retira-o.           |
| Hermes Agent | `http://<host>:8892/`     | Dashboard do Hermes; também com os cabeçalhos retirados pelo nginx.    |

Porquê os portos 8891/8892: uma app HTML que gera caminhos absolutos (`/assets/...`) não pode ser proxied num subcaminho sem reescrever o HTML, por isso cada app é replicada no **seu próprio porto** e o nginx apenas remove `X-Frame-Options` / `Content-Security-Policy`. O `iframePages.ts` usa o host do browser por omissão (funciona em `127.0.0.1` e a partir de outras máquinas), ou `VITE_SEARXNG_URL` / `VITE_N8N_URL` / `VITE_HERMES_URL` se definidos na build.

As páginas são instaladas automaticamente na primeira utilização de cada browser (marcador `finance-llm-iframe-pages:seeded`) e podem ser editadas, desativadas ou removidas em **Páginas iframe**; o botão **Predefinidas** repõe as três.

### Login do dashboard do Hermes: as mesmas contas do IQ OS

O dashboard do Hermes exige autenticação quando está ligado a `0.0.0.0`. Em vez de um par de credenciais próprio, a solução traz um **provider** (`docker/hermes/plugins/dashboard-auth-iqos`) que valida o email+palavra-passe em `POST /auth/login` da API do IQ OS: o formulário **«Sign in with IQ OS»** aceita as mesmas contas da plataforma (e o dashboard passa a mostrar `Logged in as … via iqos`).

```powershell
docker compose --profile agents up -d hermes-agent
docker compose exec hermes-agent hermes plugins list   # dashboard-auth-iqos -> enabled
```

O porto `9119` **não** é publicado no host: o dashboard só é acessível pelo proxy de incorporação (`:8892`), que serve a SPA.

## Requisitos

- Docker Desktop ou Docker Engine + Compose.
- ~6 GB de disco para as imagens (PyTorch + transformers).

## Como usar

### 1. Construir e iniciar

Abre um terminal na raiz do projeto (`C:\LLMFinance\finance-llm`) e corre:

```powershell
docker compose up --build -d                     # núcleo (+ SearXNG e n8n)
docker compose --profile agents up -d            # + Hermes Agent
docker compose --profile tools up -d             # + servidor MCP
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

### 5. Testes dentro de Docker

O perfil `test` corre os testes unitários e, a seguir, um smoke test que descobre **todos** os
`GET` sem parâmetros no `/openapi.json` e valida a API e a SPA:

```powershell
docker compose --profile test run --rm tests
```

O resultado fica em `logs/smoke_test.json` (volume montado) e o código de saída é 1 se houver
falhas. Para validar um ambiente já a correr sem construir nada:

```powershell
docker compose run --rm --no-deps tests python docker/smoke_test.py --base-url http://backend:8000
```

Rotas autenticadas contam como `GUARDADO` (401/403) quando não há credenciais; para as testar a
sério, define `IQOS_API_EMAIL`/`IQOS_API_PASSWORD` (ou `IQOS_API_TOKEN`) no `.env`.

Como ler o relatório:

| Resultado   | Significado                                                                       |
|-------------|-----------------------------------------------------------------------------------|
| `OK`        | 2xx — o endpoint respondeu.                                                        |
| `SPA`       | 404 numa rota de página: o build da UI é servido pelo nginx, não pelo backend.      |
| `GUARDADO`  | 400/401/403/422 — rota viva, falta token ou parâmetros.                             |
| `AVISO`     | 404 inesperado (rota declarada mas não encontrada).                                 |
| `FALHA`     | 5xx ou erro de ligação — **é isto que faz o comando falhar**.                        |

O timeout por omissão é 180 s porque o RAG carrega o modelo de *embeddings* na primeira
chamada (`GET /rag/documents` leva ~85 s num container acabado de arrancar e ~0,2 s depois);
não é uma avaria, é arranque frio.

### 6. Servidor MCP em container

O VS Code arranca o servidor MCP por `stdio`; dentro de Docker corre-se em HTTP:

```powershell
docker compose --profile tools up -d mcp
```

- Endpoint: `http://127.0.0.1:8765/mcp`
- Ver as ferramentas registadas: `docker compose run --rm mcp python -m mcp_server --list-tools`
- O container fala com a API pelo nome do serviço (`IQOS_API_URL=http://backend:8000`).

### 7. Hermes Agent (agente autónomo)

```powershell
docker compose --profile agents up -d hermes-agent
```

- **API OpenAI-compatível / health**: `http://127.0.0.1:8642` (chave em `HERMES_API_KEY`)
- **Dashboard web**: aberto pela SPA, na página iframe «Hermes Agent» (`http://127.0.0.1:8892`)
- **Login**: as mesmas contas do IQ OS (ver acima); o dashboard mostra `Logged in as … via iqos`
- **Dados**: volume `hermes-data` → `/opt/data` (config, sessões, memórias, skills)

O primeiro arranque pode precisar do assistente de configuração para as chaves dos modelos de IA:

```powershell
docker compose --profile agents run --rm hermes-agent setup
```

Notas de implementação (armadilhas já resolvidas):

- O comando tem de ser `["gateway", "run"]` (dois argumentos); `"gateway run"` num só dava
  `'gateway run' is not a hermes command`.
- O plugin de autenticação precisa de `plugin.yaml` **e** de estar ativo em `plugins.enabled` do
  `config.yaml`; sem isso o dashboard recusa ligar-se a `0.0.0.0`. A ativação é feita em cada
  arranque por `docker/hermes/init/026-enable-iqos-plugin.sh` (sobrevive a `down -v`).
- O volume de dados do Hermes deve ser um **volume nomeado** (não uma pasta do host): o `state.db`
  usa SQLite em modo WAL, que se corrompe nos mounts 9p/drvfs do Docker Desktop no Windows.

## Volumes montados

O `docker-compose.yml` monta as seguintes pastas do host no container backend:

- `./data:/app/data` — dados processados, tickers, uploads, índice do RAG, `data/.auth_secret`.
- `./model:/app/model` — modelos treinados (GPT-2, Mistral, BloombergGPT-style).
- `./rag:/app/rag` — armazenamento do RAG (índice, markdowns, chunks).
- `./logs:/app/logs` — `events.jsonl` e restantes logs da aplicação.

Volumes nomeados (persistem em `docker compose down`, são apagados com `-v`):

- `es-data` — índices do Elasticsearch.
- `searxng-cache` — cache do SearXNG.
- `n8n-data` — base de dados, credenciais e workflows do n8n.
- `hermes-data` — `/opt/data` do Hermes Agent (config, `.env`, sessões, memórias, skills).

Montagens de configuração (do repositório para dentro dos containers, só leitura):

- `./docker/searxng` → `/etc/searxng` (SearXNG)
- `./docker/hermes/plugins/dashboard-auth-iqos` → `/opt/data/plugins/dashboard-auth-iqos` (provider de login)
- `./docker/hermes/init/026-enable-iqos-plugin.sh` → `/etc/cont-init.d/` (ativação no arranque)
- `./docker/n8n` → `/files` (import/export manual de workflows)
- `./logs:/app/logs` — `events.jsonl` e restantes logs da aplicação.

Isto permite que os dados e modelos persistam entre execuções dos containers e que a instância Docker partilhe os mesmos dados da instância local (mesma chave de autenticação e mesmos índices).

## Variáveis de ambiente

| Variável | Omissão | Descrição |
|----------|---------|-----------|
| `FINANCE_API_PORT` | `8003` | Porto do host para a API. |
| `FINANCE_UI_PORT` | `4180` | Porto do host para a UI. |
| `ELASTICSEARCH_PORT` | `9200` | Porto do host para o Elasticsearch. |
| `VITE_API_URL` | `/api` | Base da API compilada na SPA. `/api` usa o proxy do nginx (mesma origem, sem CORS). |
| `SEARXNG_PORT` | `8888` | Porto do host para o SearXNG. |
| `N8N_PORT` | `5678` | Porto do host do n8n (acesso direto). |
| `N8N_EMBED_PORT` | `8891` | Proxy de incorporação do n8n (sem `X-Frame-Options`). |
| `HERMES_API_PORT` | `8642` | API OpenAI-compatível do Hermes Agent. |
| `HERMES_EMBED_PORT` | `8892` | Proxy de incorporação do dashboard do Hermes. |
| `IQOS_API_URL` | `http://backend:8000` | API do IQ OS vista pelo container `hermes-agent`/`mcp`/`tests`. |
| `HERMES_DASHBOARD_IQOS_SECRET` | vazio | Chave HMAC das sessões do dashboard (vazio = gerada por processo). |
| `HERMES_API_KEY` | `iqos-hermes-api-key-…` | Chave da API OpenAI-compatível do Hermes. |
| `VITE_SEARXNG_URL` / `VITE_N8N_URL` / `VITE_HERMES_URL` | vazio | URLs das páginas iframe na build; vazio = host do browser + porto por omissão. |
| `IQOS_MCP_PORT` | `8765` | Porto do host para o servidor MCP (perfil `tools`). |
| `IQOS_API_TOKEN` / `IQOS_API_EMAIL` + `IQOS_API_PASSWORD` | vazio | Sessão para o MCP e para o smoke test cobrirem rotas autenticadas. |
| `FINANCE_ES_URL` | `http://elasticsearch:9200` | Endereço do Elasticsearch **visto de dentro do container**. |
| `FINANCE_AUTH_SECRET` | vazio | Se vazio, é usado/reutilizado `data/.auth_secret`. |
| `FRED_API_KEY`, `BRAVE_API_KEY`, `SERPAPI_KEY`, `OPENAI_API_KEY`, `OPENAI_BASE_URL`, `OPENAI_MODEL`, `OLLAMA_URL` | vazio | Chaves/endpoints opcionais das ferramentas do agente. |

## Notas e armadilhas resolvidas

- **Elasticsearch dentro do container**: o cliente lê `ELASTICSEARCH_URL` (não `ES_HOST`). No container tem de apontar para o nome do serviço (`http://elasticsearch:9200`); `127.0.0.1` apontaria para o próprio backend.
- **Versão do cliente Elasticsearch**: o `requirements.txt` fixa `elasticsearch>=8.11.0,<9.0.0`. Com `>=8.11.0` sem limite, o pip instalava o cliente 9.x, que **não fala com o servidor 8.x** — `es.ping()` devolvia `False` e a API respondia `{"available": false, "message": "Elasticsearch indisponível"}`.
- **API base da SPA**: `chat-ui/src/api.ts` usa `VITE_API_URL` e cai em `http://127.0.0.1:8002` quando a variável está vazia. Por isso o Dockerfile compila com `VITE_API_URL=/api` — deixar vazio partiria a UI em container.
- **Uploads**: o nginx tem `client_max_body_size 256m`; sem isto os uploads de PDF devolviam 413.
- **Chat em streaming**: `/api/` é proxiado com `proxy_buffering off` e `proxy_read_timeout 3600s` para as respostas SSE não ficarem em buffer nem serem cortadas.
- **Contexto da build**: `data/` (~12 GB) e `model/` (~3 GB) estão no `.dockerignore`. Sem isso a build enviaria >16 GB para o daemon.

