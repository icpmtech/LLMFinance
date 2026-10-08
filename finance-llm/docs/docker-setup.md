# Docker Setup — IQ OS

Este documento explica como correr toda a solução IQ OS (Elasticsearch + backend FastAPI + frontend React + servidor MCP + aplicações de apoio) com Docker Compose.

## Ficheiros

- `Dockerfile.backend` — container Python 3.11 com FastAPI, uvicorn e dependências.
- `Dockerfile.frontend` — build do React/Vite servido por nginx (build com `VITE_API_URL=/api`).
- `Dockerfile.test` — imagem de testes (`iq-os-tests`): parte da imagem do backend e acrescenta `pytest`.
- `docker-compose.yml` — orquestra `elasticsearch`, `backend`, `frontend`, `searxng` e `n8n` (núcleo) mais `mcp`, `tests`, `hermes-agent`, `mirofish` e `osif-*` (por perfis).
- `docker/nginx.conf` — nginx com SPA, proxy `/api/` e `/forecast/plot/` para o backend, uploads até 256 MB, SSE sem buffering e os **proxies de incorporação** dos iframes (portos 8891/8892/8893/8894).
- `docker/mirofish/Dockerfile` — imagem do MiroFish: parte da oficial `ghcr.io/666ghj/mirofish`, sobrepõe o código atual do repositório (a imagem publicada é anterior à internacionalização) e aplica dois ajustes: interface em **português** e base da API **relativa**.
- `docker/osif/fetch.ps1` — obtém o código do OSINT Framework (OSIF) do upstream para `docker/osif/src` (clone local, fora do git).
- `docker/osif/frontend.Dockerfile` + `docker/osif/frontend-nginx.conf` — build da SPA Vue do OSIF com um `default.conf` próprio (só estáticos; a API é proxied pelo nginx do IQ OS).
- `docker/osif/README.md` — como o OSIF está montado, portas, chaves opcionais e como atualizar o upstream.
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
| `mirofish` | `mirofish`                                 | Previsão por enxame de agentes: UI + API Flask do MiroFish.  |
| `osif`   | `osif-postgres`, `osif-redis`, `osif-minio`, `osif-backend`, `osif-worker`, `osif-frontend` | OSINT Framework v2: casos, scans OSINT, grafo e evidências. |
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
| MiroFish — API Flask           | `5001`    | http://127.0.0.1:5001      |
| MiroFish — UI (proxy de iframe)| `3000`    | http://127.0.0.1:8893 *(só via proxy)* |
| OSIF — SPA + API (proxy de iframe) | `8894` | http://127.0.0.1:8894      |
| OSIF — API REST/WebSocket      | `6110`    | http://127.0.0.1:6110/api/docs |
| OSIF — consola do MinIO        | `9111`    | http://127.0.0.1:9111      |
| OSIF — PostgreSQL / Redis      | internos  | não publicados             |

Os portos do host são configuráveis por variáveis (`ELASTICSEARCH_PORT`, `FINANCE_API_PORT`, `FINANCE_UI_PORT`, `IQOS_MCP_PORT`, `SEARXNG_PORT`, `N8N_PORT`, `N8N_EMBED_PORT`, `HERMES_API_PORT`, `HERMES_EMBED_PORT`, `MIROFISH_API_PORT`, `MIROFISH_EMBED_PORT`, `OSIF_EMBED_PORT`, `OSIF_API_PORT`, `OSIF_MINIO_CONSOLE_PORT`), com os valores por omissão acima.

## Páginas iframe (Pesquisa, n8n, Hermes Agent, MiroFish, OSIF)

A solução traz cinco aplicações externas **pré-instaladas** como páginas iframe da SPA (ver `chat-ui/src/iframePages.ts`) e abríveis pelo dock:

| Página       | Iframe aponta para        | Notas                                                                 |
|--------------|---------------------------|-----------------------------------------------------------------------|
| Pesquisa     | `http://<host>:8888/`     | SearXNG; não envia cabeçalhos de bloqueio, é incorporado diretamente.  |
| n8n          | `http://<host>:8891/`     | O n8n envia `X-Frame-Options: SAMEORIGIN`; o nginx retira-o.           |
| Hermes Agent | `http://<host>:8892/`     | Dashboard do Hermes; também com os cabeçalhos retirados pelo nginx.    |
| MiroFish     | `http://<host>:8893/`     | UI do MiroFish (perfil `mirofish`); o nginx serve a UI e `/api/`.       |
| OSINT Framework (OSIF) | `http://<host>:8894/` | OSIF v2 (perfil `osif`); o nginx serve a SPA, `/api/`, `/ws/` e `/health`. |

Porquê os portos 8891/8892/8893/8894: uma app HTML que gera caminhos absolutos (`/assets/...`) não pode ser proxied num subcaminho sem reescrever o HTML, por isso cada app é replicada no **seu próprio porto** e o nginx apenas remove `X-Frame-Options` / `Content-Security-Policy`. O `iframePages.ts` usa o host do browser por omissão (funciona em `127.0.0.1` e a partir de outras máquinas), ou `VITE_SEARXNG_URL` / `VITE_N8N_URL` / `VITE_HERMES_URL` / `VITE_MIROFISH_URL` / `VITE_OSIF_URL` se definidos na build.

As páginas são instaladas automaticamente na primeira utilização de cada browser (marcador `finance-llm-iframe-pages:seeded`) e podem ser editadas, desativadas ou removidas em **Páginas iframe**; o botão **Predefinidas** repõe as cinco (acrescentando só as que faltarem, sem tocar nas que já existem).

### Login do dashboard do Hermes: as mesmas contas do IQ OS

O dashboard do Hermes exige autenticação quando está ligado a `0.0.0.0`. Em vez de um par de credenciais próprio, a solução traz um **provider** (`docker/hermes/plugins/dashboard-auth-iqos`) que valida o email+palavra-passe em `POST /auth/login` da API do IQ OS: o formulário **«Sign in with IQ OS»** aceita as mesmas contas da plataforma (e o dashboard passa a mostrar `Logged in as … via iqos`).

O mesmo provider aceita **single sign-on**: o utilizador reservado `iqos-sso` (com o *token* Bearer do IQ OS como palavra-passe) é validado em `GET /auth/me`, o que permite entrar no dashboard sem segundo formulário quando já há sessão na plataforma. Quem injeta esse pedido é o nginx do frontend (`docker/nginx.conf`, `location /hermes-agent/`), que serve também o dashboard **no subcaminho público** `/hermes-agent/` — necessário porque os cookies de sessão são `SameSite=Lax` e não são enviados num iframe cross-origin.

```powershell
docker compose --profile agents up -d hermes-agent
docker compose exec hermes-agent hermes plugins list   # dashboard-auth-iqos -> enabled
docker compose exec frontend nginx -t                  # regras do subcaminho /hermes-agent/
```

O porto `9119` **não** é publicado no host: o dashboard é acessível pelo proxy de incorporação (`:8892`) e, no domínio público, por `https://<domínio>/hermes-agent/`. Detalhe das reescritas e do *single sign-on*: README → «Dashboard do Hermes Agent (subcaminho público e single sign-on)».

## Requisitos

- Docker Desktop ou Docker Engine + Compose.
- ~6 GB de disco para as imagens (PyTorch + transformers).

## Como usar

### 1. Construir e iniciar

Abre um terminal na raiz do projeto (`C:\LLMFinance\finance-llm`) e corre:

```powershell
docker compose up --build -d                     # núcleo (+ SearXNG e n8n)
docker compose --profile agents up -d            # + Hermes Agent
docker compose --profile mirofish up -d          # + MiroFish
docker compose --profile osif up -d --build       # + OSIF (OSINT Framework; ver secção 9)
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

**Configurar o modelo a partir da plataforma** (não precisa do assistente interativo): o painel
**Motor do Hermes Agent**, na página **Hermes** (`/hermes`, coluna da esquerda → *configurar*),
liga o container aos fornecedores de IA que a plataforma já tem. Escolhe-se o fornecedor, vê-se o
plano exato e aplica-se:

```powershell
# o que a plataforma quer vs. o que o container tem
curl http://127.0.0.1:8002/hermes-agent/diagnose -H "Authorization: Bearer <token>"
```

A plataforma resolve a chave com `providers_service.resolve_key(user_id, provider)` (a chave da
conta ou o fallback do ambiente), escreve-a onde o Hermes a lê e recria o container. Ver
`docs/jarvis.md` e `api/hermes_agent_settings.py`:

- fornecedores com **perfil nativo** no Hermes (`deepseek`, `anthropic`, `gemini`, `openrouter`,
  `xai`, `ollama-cloud`) → `model.provider` = o perfil e a chave no `.env`, na variável do perfil
  (`DEEPSEEK_API_KEY`, `ANTHROPIC_API_KEY`, …);
- os restantes (`openai`, `groq`, `mistral-ai`, `ollama`) → `provider: custom` com
  `model.base_url` e `model.api_key` no `config.yaml` (não há perfil equivalente no upstream);
- a **pesquisa web** do agente passa a usar o SearXNG da própria solução (`SEARXNG_URL`).

Notas de implementação (armadilhas já resolvidas):

- O comando tem de ser `["gateway", "run"]` (dois argumentos); `"gateway run"` num só dava
  `'gateway run' is not a hermes command`.
- O plugin de autenticação precisa de `plugin.yaml` **e** de estar ativo em `plugins.enabled` do
  `config.yaml`; sem isso o dashboard recusa ligar-se a `0.0.0.0`. A ativação é feita em cada
  arranque por `docker/hermes/init/026-enable-iqos-plugin.sh` (sobrevive a `down -v`).
- O volume de dados do Hermes deve ser um **volume nomeado** (não uma pasta do host): o `state.db`
  usa SQLite em modo WAL, que se corrompe nos mounts 9p/drvfs do Docker Desktop no Windows.
- Sem configuração, o volume arranca com o `config.yaml` de exemplo (`provider: auto`,
  `anthropic/claude-opus-4.6`) e um `.env` **sem chaves**: o agente não tem modelo. É isso que o
  painel resolve.
- A escrita faz-se com o CLI do próprio Hermes (`hermes config set|unset`, `docker exec -u hermes`),
  não reescrevendo o YAML à mão — é ele que valida as chaves contra o esquema da versão instalada.
- O `docker` tem de estar acessível a **quem corre o backend**: `docker compose` no host funciona;
  dentro de um container seria preciso montar `/var/run/docker.sock` (o `diagnose` di-lo).
- `OPENAI_API_KEY`/`OPENAI_BASE_URL`/`OPENAI_MODEL` **não** são lidos pelo Hermes Agent (só o
  `VOICE_TOOLS_OPENAI_KEY`, para voz). O agente não tem perfil `openai`: endpoints
  OpenAI-compatíveis entram por `custom`.
- `hermes config unset` sai com código 1 quando a chave já não existe — o estado pedido está
  cumprido, por isso conta como sucesso.
- A chave nunca sai em claro nas respostas da API (`/hermes-agent/settings` mascara-a sempre).

### 8. MiroFish (previsão por enxame de agentes)

```powershell
docker compose --profile mirofish up -d
```

- **UI + API pela SPA**: página iframe «Simulador IQ OS · Estúdio» (`http://127.0.0.1:8893`); o
  mesmo porto serve para abrir a app diretamente no browser.
- **API Flask (direto)**: `http://127.0.0.1:5001` — `GET /health` →
  `{"service": "MiroFish Backend", "status": "ok"}`.
- **Dados**: volume `mirofish-uploads` → `/app/backend/uploads` (projetos, materiais-semente,
  relatórios e simulações).
- **Integração com a plataforma**: duas páginas distintas —
  - **Simulador IQ OS** (`/simulador`): lança a simulação com dados do sistema (ficha de empresa,
    tema do Pesquisa 360, notícias, documento do Office ou o panorama global) e **apresenta os
    resultados** — rondas e ações, feed do que os agentes publicaram, elenco de personas (com
    entrevistas), relatório e conversa sobre o grafo. Inclui a aba *Estúdio MiroFish* com a app
    completa embebida;
  - **MiroFish** (`/mirofish`): motor — catálogo de fontes, pré-visualização da semente,
    trabalhos e **chaves** (o LLM pode vir de um fornecedor já configurado na plataforma e a
    chave do Zep é atualizável na UI, que escreve o `.env` e recria o contentor).

  Detalhes em [`docs/mirofish.md`](mirofish.md).
- **Chaves obrigatórias**: `MIROFISH_LLM_API_KEY` (ou `OPENAI_API_KEY`) e `MIROFISH_ZEP_API_KEY`.
  Sem elas o backend sai logo com código 1 (`run.py` valida a configuração) — é por isso que o
  serviço vive num **perfil**: um `docker compose up` do núcleo nunca fica num ciclo de reinícios
  por falta de chaves.
- Se as chaves ainda não estiverem no `.env`, o container fica em `Restarting`; confirmar com
  `docker compose --profile mirofish logs mirofish` — o `run.py` imprime os erros de configuração
  (por exemplo `LLM_API_KEY` ou `ZEP_API_KEY` «não configurado/a») antes de sair.

O fluxo de utilização é: enviar materiais-semente (PDF/MD/TXT) + descrever a previsão → gerar a
ontologia e construir o grafo (Zep) → gerar *personas* → correr a simulação (OASIS, dois mundos
paralelos) → relatório final, com um agente de relatório para perguntas de seguimento. Cada ronda
chama o LLM para **cada** agente: começar com poucas rondas (`MIROFISH_MAX_ROUNDS`, 10 por omissão)
e poucos agentes — o README do projeto sugere menos de 40 rondas nas primeiras tentativas.

#### Porque é que a imagem é derivada (e não a oficial tal e qual)

`docker/mirofish/Dockerfile` parte da imagem oficial (`ghcr.io/666ghj/mirofish:v0.1.2`), **sobrepõe-lhe
o código atual do repositório** e aplica quatro ajustes:

1. **Interface em português** — o upstream só traz `zh`/`en`; a imagem acrescenta
   `locales/pt.json` (tradução completa dos 635 textos), passa o idioma por omissão a `pt` (com
   *fallback* em inglês) e traduz o título/idioma do `index.html`;
2. **Base da API relativa** — sem isto a SPA do MiroFish só funciona em `localhost`;
3. **Respostas do LLM em português** — os *prompts* do upstream são em chinês e as personas e
   publicações dos agentes saíam em chinês; a diretiva de idioma é injetada em
   `LLMClient._create_completion` (`pt_language.py`, ativa por `MIROFISH_REPLY_LANGUAGE=pt-PT`);
4. **Mensagens do backend em português** — progresso da geração de personas e erros de operação
   construídos em código (`pt_backend_strings.py`).

O ajuste da base da API é uma linha no cliente do frontend:

```js
// antes
baseURL: import.meta.env.VITE_API_BASE_URL || 'http://localhost:5001'
// depois
baseURL: import.meta.env.VITE_API_BASE_URL || ''
```

O código é sobreposto porque a imagem publicada (`latest` = `v0.1.2`) é **anterior à camada de
tradução** (não tem `locales/` nem `frontend/src/i18n`): sem trazer o código atual não há forma de
ter a interface em português. O tarball usado é configurável
(`--build-arg MIROFISH_TARBALL=...`) e só os diretórios de código são substituídos — `node_modules`,
`backend/.venv` e os caches da imagem base são reaproveitados.

A SPA do MiroFish chama a API num URL **absoluto** por omissão. Dentro de um iframe servido a partir
de `http://<host>:8893/`, `localhost:5001` apontaria para a máquina do **browser** — não para o
container — pelo que a app só funcionaria em `127.0.0.1` (e, com a plataforma em HTTPS, o browser
bloquearia ainda o pedido por conteúdo misto). Com a base **relativa**, os pedidos `/api/...` seguem
a origem da página e o nginx do IQ OS encaminha-os para `mirofish:5001`.

A imagem oficial corre o frontend em modo *dev* (Vite dev server), que serve o código-fonte — daí
bastar corrigir o ficheiro na imagem, sem reconstruir o bundle. Como contrapartida, o dev server do
Vite recusa pedidos cujo `Host` não seja `localhost` nem um IP literal (proteção contra DNS
rebinding): o proxy do IQ OS envia `Host: localhost` (ver `docker/nginx.conf`), senão a app só
abriria em `127.0.0.1` e responderia «Blocked request. This host is not allowed.» pelo IP da LAN ou
por túnel.

### 9. OSIF (OSINT Framework v2 — investigação OSINT)

Integração do [fr4nc1stein/osint-framework](https://github.com/fr4nc1stein/osint-framework)
(OSIF v2.0, AGPL-3.0) como app incorporada. É uma stack própria (PostgreSQL, Redis, MinIO,
API FastAPI, worker `arq` e SPA Vue), por isso vive num perfil:

```powershell
# 1. Código do upstream (só na primeira vez; -Force para re-clonar/atualizar)
powershell -ExecutionPolicy Bypass -File docker/osif/fetch.ps1

# 2. Stack completa
docker compose --profile osif up -d --build
```

- **UI + API pela SPA**: página iframe «OSINT Framework (OSIF)» (`http://127.0.0.1:8894`); a
  mesma origem serve a SPA e a API (o nginx do IQ OS reencaminha `/api/`, `/ws/`, `/health` e
  `/ready` para `osif-backend:6000`), por isso também serve para abrir a app diretamente no browser.
- **API REST/WebSocket (direto)**: `http://127.0.0.1:6110/api/docs` (Swagger do OSIF);
  `GET /health` → `{"status":"healthy",…}`.
- **Consola do MinIO**: `http://127.0.0.1:9111` (`osif_minio` / `osif_minio_password`).
- **Dados**: volumes `osif-postgres-data` (casos, grafo, scans), `osif-redis-data` (fila/cache)
  e `osif-minio-data` (evidências).
- **Chaves de APIs OSINT (opcionais)**: sem nenhuma funcionam `dns_records`, `subdomain_enum`,
  `whois_lookup`, `ip_geolocation`, `urlscan_lookup` e `email_domain`. As restantes
  (`shodan_lookup`, `virustotal_domain`, `abuseipdb`, `email_hunter`, `hibp_breach`) precisam de
  `SHODAN_API_KEY`, `VIRUSTOTAL_API_KEY`, `ABUSEIPDB_API_KEY`, `TOMBA_API_KEY`/`TOMBA_SECRET_KEY`,
  `HUNTER_API_KEY` ou `HIBP_API_KEY` no `.env` — ou de as guardar no separador *Integrations* da
  própria app (ficam cifradas em PostgreSQL).
- **Atualizar o upstream**: `docker/osif/fetch.ps1 -Force` e repetir o `up --build`.
- Detalhes de arquitetura, portas e decisões em [`docker/osif/README.md`](../docker/osif/README.md).

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
- `mirofish-uploads` — `/app/backend/uploads` do MiroFish (projetos, materiais-semente, relatórios e simulações).
- `osif-postgres-data` / `osif-redis-data` / `osif-minio-data` — base de dados (casos, grafo, scans), fila/cache e evidências do OSIF.

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
| `MIROFISH_API_PORT` | `5001` | API Flask do MiroFish (acesso direto). |
| `MIROFISH_EMBED_PORT` | `8893` | Proxy de incorporação do MiroFish (UI + `/api/`, sem `X-Frame-Options`). |
| `MIROFISH_LLM_API_KEY` / `MIROFISH_LLM_BASE_URL` / `MIROFISH_LLM_MODEL_NAME` | `OPENAI_*` | LLM do MiroFish (formato OpenAI); vazio = reutiliza `OPENAI_API_KEY` / `OPENAI_BASE_URL` / `OPENAI_MODEL`. |
| `MIROFISH_ZEP_API_KEY` | vazio | Chave do **Zep Cloud** (memória de longo prazo dos agentes). O backend do MiroFish não arranca sem ela. |
| `MIROFISH_LLM_BOOST_*` | vazio | Acelerador opcional (2.º modelo para tarefas de volume); vazio = desligado. |
| `MIROFISH_MAX_ROUNDS` | `10` | `OASIS_DEFAULT_MAX_ROUNDS`: rondas de simulação por omissão. |
| `MIROFISH_REPLY_LANGUAGE` | `pt-PT` | Idioma das respostas do LLM do MiroFish (prompts do upstream são em chinês); vazio = idioma do prompt. |
| `MIROFISH_BASE_IMAGE` | `ghcr.io/666ghj/mirofish:v0.1.2` | Imagem base do MiroFish (usar `ghcr.nju.edu.cn/...` como espelho). |
| `MIROFISH_TARBALL` | tarball de `main` no GitHub | Código do MiroFish aplicado sobre a imagem base (usar o URL de uma tag para fixar a versão). |
| `MIROFISH_URL` | `http://mirofish:5001` | API do MiroFish **vista pelo backend** do IQ OS (módulo `/mirofish/*`). |
| `MIROFISH_PUBLIC_URL` | vazio | Endereço público da UI usado nos links da plataforma (vazio = host do browser + `8893`). |
| `IQOS_API_URL` | `http://backend:8000` | API do IQ OS vista pelo container `hermes-agent`/`mcp`/`tests`. |
| `HERMES_DASHBOARD_IQOS_SECRET` | vazio | Chave HMAC das sessões do dashboard (vazio = gerada por processo). |
| `HERMES_API_KEY` | `iqos-hermes-api-key-…` | Chave da API OpenAI-compatível do Hermes. |
| `VITE_SEARXNG_URL` / `VITE_N8N_URL` / `VITE_HERMES_URL` / `VITE_MIROFISH_URL` / `VITE_OSIF_URL` | vazio | URLs das páginas iframe na build; vazio = host do browser + porto por omissão. |
| `OSIF_EMBED_PORT` | `8894` | Porto do proxy de incorporação do OSIF (SPA + `/api/` + `/ws/` na mesma origem). |
| `OSIF_API_PORT` | `6110` | Porto do host para a API REST/WebSocket do OSIF (diagnóstico). |
| `OSIF_MINIO_CONSOLE_PORT` | `9111` | Porto do host para a consola do MinIO do OSIF. |
| `OSIF_DB_PASSWORD` / `OSIF_MINIO_USER` / `OSIF_MINIO_PASSWORD` / `OSIF_S3_BUCKET` / `OSIF_SECRET_KEY` | `osif` / `osif_minio` / `osif_minio_password` / `osif-evidence` / vazio | Credenciais internas do OSIF (PostgreSQL, MinIO e segredo das sessões). |
| `SHODAN_API_KEY`, `VIRUSTOTAL_API_KEY`, `ABUSEIPDB_API_KEY`, `TOMBA_API_KEY`, `TOMBA_SECRET_KEY`, `HUNTER_API_KEY`, `HIBP_API_KEY`, `URLSCAN_API_KEY`, `CENSYS_APPID`, `CENSYS_SECRET` | vazio | Chaves das APIs OSINT (todas opcionais). Também se configuram no separador *Integrations* da própria app. |
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
- **Base da API do MiroFish**: a SPA do MiroFish usa `http://localhost:5001` quando `VITE_API_BASE_URL` não está definido; como a app é incorporada por iframe (origem `:8893`), `localhost` apontaria para a máquina do browser. O `docker/mirofish/Dockerfile` substitui esse URL por uma cadeia vazia (base relativa) e o nginx encaminha `/api/` para `mirofish:5001`. Se o upstream mudar essa linha, a build da imagem falha de propósito (`grep` antes e depois do `sed`).
- **Host do Vite dev server (MiroFish)**: o frontend do MiroFish corre em modo *dev*, e o Vite recusa pedidos cujo `Host` não seja `localhost`/IP (`Blocked request. This host is not allowed.`). O proxy `:8893` envia `Host: localhost`; sem isso a app só abriria em `127.0.0.1`.
- **MiroFish sem chaves**: `mirofish` está no perfil `mirofish` porque o `run.py` valida `LLM_API_KEY` e `ZEP_API_KEY` e sai com código 1 — com `restart: unless-stopped` fora de um perfil, o `docker compose up` ficaria num ciclo de reinícios.

