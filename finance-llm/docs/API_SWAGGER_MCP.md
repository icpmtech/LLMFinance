# API do IQ OS: Swagger e MCP

Dois acessos complementares ao mesmo sistema:

* **Swagger / OpenAPI** — documentação e exploração interativa de todos os
  endpoints (para pessoas e para gerar clientes);
* **MCP (Model Context Protocol)** — as mesmas operações como ferramentas
  para agentes de IA.

---

## 1. Swagger / OpenAPI

### Endereços

| Recurso | URL | Notas |
| --- | --- | --- |
| Swagger UI | `http://127.0.0.1:8002/docs` | `Cache-Control: no-store`; botão **Authorize**. |
| ReDoc | `http://127.0.0.1:8002/redoc` | Leitura, com índice lateral. |
| Especificação | `http://127.0.0.1:8002/openapi.json` | OpenAPI 3.1. |
| Descarregar (ficheiro) | `http://127.0.0.1:8002/openapi/export` | Com `Content-Disposition`. |
| Resumo do catálogo | `http://127.0.0.1:8002/openapi/summary` | Grupos, segurança, servidores, ligações úteis. |

### O que foi acrescentado

O FastAPI já gerava o `openapi.json` a partir dos routers, mas as rotas
inline de `api/main.py` (mercado, Elasticsearch, contratos, empresas,
dossier, import, páginas SPA) não tinham grupo nem descrição. Agora:

* **30 grupos** documentados, na ordem de leitura (`core`, `auth`, `admin`,
  `rag`, `market`, `elastic`, `contratos`, `contratos-es`, `empresas`,
  `companies-global`, `search`, `search360`, `hermes`, `researcher`,
  `agents`, `ontology`, `crm`, `office`, `email`, `sentiment`,
  `visualizador`, `scraper`, `vectors`, `skills`, `providers`, `cli`,
  `proxy`, `dossier`, `import`, `spa`);
* **0 operações sem grupo** (361 operações em 309 caminhos);
* **segurança `bearerAuth`**: o botão *Authorize* aceita o token de
  `POST /auth/login` e as operações ficam marcadas como autenticadas
  (exceto `health`, `docs`, `redoc`, `openapi*`, `auth/login`,
  `auth/register`, `proxy/status`);
* **servidores** declarados (`8002` e `8003`), de modo a que o "Try it out"
  funcione sem editar o URL;
* **páginas SPA** identificadas no grupo `spa`, para não se confundirem com
  endpoints de dados;
* rotas sem descrição herdam o resumo como descrição.

Tudo isto vive em `api/openapi_meta.py`; `api/main.py` limita-se a ligar:

```python
from api.openapi_meta import DESCRIPTION, TAGS_METADATA, custom_openapi

app = FastAPI(..., description=DESCRIPTION, openapi_tags=TAGS_METADATA, ...)
app.openapi = lambda: custom_openapi(app)
```

### Autenticar no Swagger

```powershell
# 1) obter o token
Invoke-RestMethod -Method Post -Uri http://127.0.0.1:8002/auth/login `
  -ContentType 'application/json' `
  -Body '{"email":"<email>","password":"<palavra-passe>"}'
```

2. Copiar o campo `token` da resposta.
3. Em `/docs`, **Authorize** → colar o token → **Authorize**.

### Ficheiros gerados

```powershell
cd c:/LLMFinance/finance-llm
c:/LLMFinance/.venv/Scripts/python.exe scripts/export_openapi.py
```

* `docs/openapi.json` — especificação completa (importável no Postman,
  Insomnia, `openapi-generator`, etc.);
* `docs/API_REFERENCE.md` — índice por grupo, com método, caminho e resumo.

---

## 2. MCP

O pacote `mcp_server/` expõe a API como ferramentas para agentes de IA.
Detalhes em `mcp_server/README.md`; resumo:

```powershell
# stdio (como os clientes MCP o arrancam)
c:/LLMFinance/.venv/Scripts/python.exe -m mcp_server

# HTTP (streamable)
c:/LLMFinance/.venv/Scripts/python.exe -m mcp_server --transport streamable-http --port 8765

# listar as ferramentas
c:/LLMFinance/.venv/Scripts/python.exe -m mcp_server --list-tools
```

Três camadas, para que **todo o sistema** esteja acessível:

1. **Curadas** — ~205 ferramentas com nomes descritivos por módulo
   (`contratos_search`, `contratos_es_entities`, `empresas_search`,
   `empresa_detail`, `empresas_global_search`, `search_unified`,
   `search360_topic`, `hermes_ask`, `rag_chat`, `market_forecast`,
   `elastic_search_global`, `crm_deals`, `office_documents`,
   `email_messages`, `sentiment_analyze_corpus`, `visualizador_query`,
   `scraper_search`, `ontology_ai_answer`, `vectors_search`, `skills_list`,
   `providers_list`, `admin_overview`, …).
2. **Genéricas** — `iqos_modules`, `iqos_search_endpoints`,
   `iqos_describe_endpoint`, `iqos_api_call`: cobrem qualquer endpoint que
   não esteja nas curadas, lendo a especificação OpenAPI em tempo real.
3. **Resources** — `iqos://openapi`, `iqos://modules`, `iqos://health`.

Mais o prompt `investigar_empresa`, com o roteiro de investigação de uma
empresa.

### Registo no VS Code

`.vscode/mcp.json` já define o servidor `iqos` (stdio) e `iqos-http`:

```json
{
  "servers": {
    "iqos": {
      "type": "stdio",
      "command": "c:/LLMFinance/.venv/Scripts/python.exe",
      "args": ["-m", "mcp_server"],
      "cwd": "c:/LLMFinance/finance-llm",
      "env": { "IQOS_API_URL": "http://127.0.0.1:8002" }
    }
  }
}
```

Para autenticar, acrescente `IQOS_API_TOKEN` ou
`IQOS_API_EMAIL`/`IQOS_API_PASSWORD` ao objeto `env`.

### Verificação

```powershell
cd c:/LLMFinance/finance-llm
c:/LLMFinance/.venv/Scripts/python.exe _test_mcp_server.py
```

Confirma o número de ferramentas, os esquemas de entrada (parâmetros de
caminho obrigatórios, corpo JSON), o agrupamento OpenAPI, o esquema
`bearerAuth` e uma consulta real.

---

## Manutenção

* **Novo endpoint num router** — nada a fazer: o router já declara `tags` e
  o FastAPI herda o grupo.
* **Novo endpoint inline em `main.py`** — acrescente a regra de prefixo
  `(prefixo, grupo)` a `PATH_TAG_RULES` em `api/openapi_meta.py`.
* **Novo grupo** — acrescente a entrada a `TAGS_METADATA` (o grupo novo
  aparece no Swagger assim que tiver operações).
* **Nova ferramenta MCP** — acrescente a operação a `mcp_server/catalog.py`;
  o servidor gera a assinatura e o esquema a partir da entrada.
