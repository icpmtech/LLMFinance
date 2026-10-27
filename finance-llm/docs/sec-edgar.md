# SEC EDGAR · filings oficiais de empresas cotadas

Página `/sec` · router `/sec/*` · motor `api/sec_service.py` · rotas
`api/sec_routes.py` · agendador `api/sec_scheduler.py` · cliente
`chat-ui/src/secApi.ts` · página `chat-ui/src/pages/SecPage.tsx`.

O módulo recolhe, indexa e permite pesquisar os **filings oficiais** submetidos
à U.S. Securities and Exchange Commission (SEC) através do sistema EDGAR.
Inclui relatórios anuais (`10-K`), trimestrais (`10-Q`), comunicações
imediatas (`8-K`), prospetos (`S-1`, `424B2`) e outras formas.

## 1. Fonte de dados

A SEC disponibiliza os dados publicamente, sem autenticação, mas **exige um
User-Agent institucional descritivo** em todos os pedidos. O módulo usa:

```
User-Agent: Sabemos Studio IQ OS sec@sabemos.studio
```

> Se alterares o contacto, atualiza `_SEC_USER_AGENT` em `api/sec_service.py`.

Os endpoints usados são:

| Dados | URL | Notas |
|---|---|---|
| Catálogo de empresas | `https://www.sec.gov/files/company_tickers.json` | Mapeia CIK → ticker e nome. |
| Submissions | `https://data.sec.gov/submissions/CIK{cik}.json` | Filings recentes por empresa. |
| Documentos | `https://www.sec.gov/Archives/edgar/data/{cik}/{accession}/{doc}` | Texto integral de cada filing. |
| XBRL / companyfacts | `https://data.sec.gov/api/xbrl/companyfacts/CIK{cik}.json` | Factos financeiros estruturados. |

Entre pedidos consecutivos é aplicado um throttle mínimo de **~120 ms** para
respeitar os limites de utilização da SEC.

## 2. Arquitetura

```
┌─────────────┐      ┌──────────────┐      ┌─────────────────────┐
│  SecPage    │──────▶│   secApi.ts  │──────▶│   /sec/* (FastAPI)  │
│  (React)    │      │              │      │   sec_routes.py     │
└─────────────┘      └──────────────┘      └──────────┬──────────┘
                                                      │
                                           ┌──────────▼──────────┐
                                           │   sec_service.py    │
                                           │  SEC EDGAR + ES     │
                                           └──────────┬──────────┘
                                                      │
                              ┌───────────────────────┼───────────────┐
                              │                       │               │
                              ▼                       ▼               ▼
                   finance_sec_filings      finance_sec_facts   finance_sec_recolhas
```

### Índices Elasticsearch

- `finance_sec_filings` — metadados e texto integral dos filings.
- `finance_sec_facts` — factos extraídos por heurística do texto **e** factos
  XBRL estruturados (companyfacts API).
- `finance_sec_recolhas` — registo de cada execução de ingestão manual ou
  agendada.

## 3. API endpoints

### Leitura pública

| Endpoint | Descrição |
|---|---|
| `GET /sec/meta` | Metadados e contagem dos índices. |
| `GET /sec/companies?q={nome/ticker}` | Pesquisar empresas na SEC. |
| `GET /sec/filings/{cik}?limit=40&form=` | Filings recentes de uma empresa. |
| `GET /sec/document?url={url}` | Texto integral de um documento EDGAR. |
| `GET /sec/search` | Pesquisar filings indexados. |
| `GET /sec/facts` | Pesquisar factos extraídos/indexados. |
| `GET /sec/facts/{cik}/xbrl` | Factos XBRL estruturados de uma empresa. |
| `GET /sec/filings/{doc_id}/ficha` | Filing indexado pelo ID. |
| `GET /sec/analytics` | Agregações por tipo, ano e ticker. |
| `GET /sec/schedule` | Estado do agendador automático. |

### Operações protegidas (exigem sessão)

| Endpoint | Descrição |
|---|---|
| `POST /sec/filings/{cik}/ingestao` | Indexa filings e extrai factos do texto. |
| `POST /sec/facts/{cik}/indexar` | Indexa factos XBRL da empresa. |
| `POST /sec/schedule/recarregar` | Sincroniza jobs com a lista de tickers. |
| `POST /sec/schedule/{ticker}/executar` | Executa recolha manual para um ticker. |
| `GET /sec/bulk/status` | Estado dos arquivos bulk ZIP locais. |
| `POST /sec/bulk/submissions` | Ingestão completa de `submissions.zip`. |
| `POST /sec/bulk/companyfacts` | Ingestão completa de `companyfacts.zip`. |
| `POST /sec/bulk/ambos` | Ingestão completa de ambos os arquivos. |
| `POST /sec/bulk/ambos-limitado` | Ingestão limitada (`limit`) para testes. |

### Integração com tickers

O endpoint existente `/tickers/{ticker}/sec-filings` passou a tentar primeiro a
SEC EDGAR (`use_edgar=true` por omissão) e recua para o Yahoo Finance quando o
ticker não está mapeado no catálogo SEC.

## 4. Agendador

O ficheiro `api/sec_scheduler.py` arranca no *lifespan* da API e cria:
- um job do APScheduler para cada ticker guardado em `data/tickers_extended.json`;
- um job bulk diário (`sec:bulk`) que descarrega e ingere os arquivos ZIP diários
  `submissions.zip` e `companyfacts.zip`.

- Expressão por omissão do job por ticker: `0 4 * * 0` (domingo, 04h00 UTC).
- Expressão por omissão do job bulk: `0 5 * * *` (diariamente 05h00 UTC).
- Cada execução por ticker ingere os últimos 20 filings **e** indexa os factos XBRL.
- O job bulk utiliza os ficheiros locais em `data/sec_bulk` e só os volta a
  descarregar se estiverem em falta.
- O agendador só funciona se o `apscheduler` estiver instalado
  (`pip install "apscheduler>=3.10"`).

## 5. Página web

`/sec` apresenta seis separadores:

1. **Painel** — sobre o EDGAR e contagem dos índices.
2. **Empresas** — pesquisa de empresas/tickers, listagem de filings e ingestão.
3. **Filings indexados** — pesquisa nos documentos recolhidos.
4. **Factos** — pesquisa nos factos extraídos do texto dos filings.
5. **XBRL** — métricas financeiras estruturadas da SEC por CIK.
6. **Documentos** — visualizador de texto integral (URL ou ID).
7. **Análises** — agregações por tipo de form, ano e ticker.
8. **Agendador** — estado e execução manual do cron SEC.

## 6. Configuração e deploy

### Requisitos

- Python: o projeto já requer as dependências principais (`requests`,
  `elasticsearch`). Adicionar `apscheduler>=3.10` para recolha automática.
- Elasticsearch: o `ensure_indices` cria os três índices SEC no arranque.
- User-Agent: verifica que o contacto é válido antes de fazer pedidos à SEC em
  produção.

### Variáveis de ambiente

Não são obrigatórias, mas podem ser úteis:

| Variável | Efeito |
|---|---|
| `SEC_USER_AGENT` | (não implementado) Podes adicionar suporte para ler desta variável em `sec_service.py`. |

### Instalação local

```bash
cd finance-llm
python -m pip install "apscheduler>=3.10"
python -m uvicorn api.main:app --reload
```

O frontend:

```bash
cd finance-llm/chat-ui
npm install
npm run dev
```

### Notas de fiabilidade

- A SEC pode bloquear ou limitar pedidos se o User-Agent for genérico ou se a
  frequência for excessiva. Mantém o throttling e um contacto real.
- O catálogo `company_tickers.json` já mudou de localização várias vezes; o
  serviço tenta os caminhos conhecidos.
- companyfacts XBRL só está disponível para empresas que reportam XBRL à SEC.
- Os arquivos `submissions.zip` (~1.5 GB) e `companyfacts.zip` (~1.4 GB) são
  recompilados todas as noites. A primeira descarga é lenta; as seguintes usam
  os ficheiros locais até serem removidos.
- A ingestão completa dos arquivos bulk pode demorar vários minutos e gerar
  milhões de documentos no Elasticsearch. Usa `/sec/bulk/ambos-limitado` para
  validar em desenvolvimento.

## 7. Testes rápidos

```bash
# Backend
python -m pytest tests/test_app_shell.py -q

# Frontend
cd chat-ui
npm run build
```

Para validar a ligação à SEC em desenvolvimento:

```bash
curl "http://localhost:8000/sec/companies?q=AAPL"
curl "http://localhost:8000/sec/filings/0000320193"
curl "http://localhost:8000/sec/facts/0000320193/xbrl"
```
