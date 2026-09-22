# Servidor MCP do IQ OS

Expõe o backend do IQ OS (`api.main`, porta **8002**) como ferramentas
*Model Context Protocol* para agentes de IA (VS Code Copilot, Claude Desktop,
Inspector, etc.).

## Conteúdo

| Ficheiro | Papel |
| --- | --- |
| `client.py` | Cliente HTTP assíncrono para a API (login automático, renovação de token em `401`). |
| `catalog.py` | Catálogo curado de operações (nome, descrição, parâmetros, endpoint). |
| `server.py` | Registo das ferramentas/resources/prompts no servidor MCP. |
| `__main__.py` | Ponto de entrada (`python -m mcp_server`). |

## Arranque

```powershell
# stdio (é assim que os clientes MCP o arrancam)
c:/LLMFinance/.venv/Scripts/python.exe -m mcp_server

# HTTP (streamable) — útil para o Inspector ou para outro computador
c:/LLMFinance/.venv/Scripts/python.exe -m mcp_server --transport streamable-http --port 8765

# listar as ferramentas registadas
c:/LLMFinance/.venv/Scripts/python.exe -m mcp_server --list-tools
```

O backend tem de estar a correr (`c:/LLMFinance/.venv/Scripts/python.exe
c:/LLMFinance/finance-llm/_start_8002.py`).

## Configuração (variáveis de ambiente)

| Variável | Omissão | Descrição |
| --- | --- | --- |
| `IQOS_API_URL` | `http://127.0.0.1:8002` | Base URL do backend. |
| `IQOS_API_TOKEN` | — | Token já emitido por `POST /auth/login`. |
| `IQOS_API_EMAIL` / `IQOS_API_PASSWORD` | — | Login automático se não houver token. |
| `IQOS_API_TIMEOUT` | `120` | Tempo limite por pedido (segundos). |
| `IQOS_MCP_TRANSPORT` | `stdio` | `stdio`, `streamable-http` ou `sse`. |
| `IQOS_MCP_HOST` / `IQOS_MCP_PORT` | `127.0.0.1` / `8765` | Só para transporte HTTP. |
| `IQOS_MCP_PATH` | `/mcp` | Caminho do endpoint HTTP. |

## Ferramentas

Três camadas, para que **todo o sistema** esteja acessível:

1. **Curadas** — uma ferramenta por operação relevante, com nome descritivo e
   assinatura tipada (ex.: `contratos_search`, `empresas_global_search`,
   `empresa_detail`, `hermes_ask`, `search360_topic`, `ontology_ai_answer`,
   `visualizador_query`, `crm_deals`, `email_messages`, `scraper_search`).
   Execute `--list-tools` para a lista completa, agrupada por módulo.
2. **Genéricas** — cobrem o resto da API:
   * `iqos_modules` — módulos da plataforma e estado do serviço;
   * `iqos_search_endpoints(query, tag, limit)` — procura na especificação;
   * `iqos_describe_endpoint(path, method)` — esquema de parâmetros e corpo;
   * `iqos_api_call(method, path, query, body)` — chamada direta.
3. **Resources** — `iqos://openapi`, `iqos://modules`, `iqos://health`
   (JSON, sem consumir contexto de ferramentas).

Há ainda o prompt `investigar_empresa`, com o roteiro de investigação de uma
empresa (cadastro → contratos → analytics → marcas/firmas → sentimento).

## Registo no VS Code

O ficheiro `.vscode/mcp.json` na raiz do *workspace* já configura o servidor:

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

Abra o painel **MCP Servers** (ou a paleta → *MCP: List Servers*) e inicie
`iqos`. Para autenticar, defina `IQOS_API_TOKEN` ou
`IQOS_API_EMAIL`/`IQOS_API_PASSWORD` em `env`.

## Verificação

```powershell
cd c:/LLMFinance/finance-llm
c:/LLMFinance/.venv/Scripts/python.exe _test_mcp_server.py
```

O teste confirma o número de ferramentas, os esquemas de entrada, o
agrupamento OpenAPI (nenhuma operação sem grupo), o esquema `bearerAuth` e
uma consulta real (`/contracts/status`).

## Notas

* Ficheiros (>PDF/Excel) não passam por MCP: os *uploads* fazem-se na
  interface e ficam disponíveis através dos endpoints de leitura.
* Operações marcadas com `destructive_hint` (apagar registos, importações)
  são anunciadas ao cliente como tal; confirme antes de as invocar.
* Se a API responder `401`, defina credenciais — o cliente renova o token
  automaticamente na chamada seguinte.
