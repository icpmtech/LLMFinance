# Recolha de dados de sites (scraping)

Módulo de recolha do **IQ OS**, assente na biblioteca [Scrapling](https://github.com/D4Vinci/Scrapling).
Permite definir **fontes** (que site, que campos, com que periodicidade), executá-las
à mão ou por **cron**, e **pesquisar** tudo o que foi recolhido.

## Conceitos

| Conceito | O que é | Onde vive |
| --- | --- | --- |
| **Fonte** | Definição declarativa: URL, *fetcher*, seletores, campos, paginação, cron | `data/scraper/sources.json` |
| **Execução** (`run`) | Uma recolha concreta de uma fonte | metadados em `data/scraper/runs/<fonte>/<run_id>.meta.json` |
| **Item** | Um registo extraído (um produto, um contrato, uma notícia…) | `data/scraper/runs/<fonte>/<run_id>.jsonl` |
| **Índice** | Cópia pesquisável dos itens | Elasticsearch `finance_scraped` |

O `item_id` (derivado dos `id_fields` da fonte) é usado como `_id` no Elasticsearch:
repetir uma recolha **atualiza** os itens conhecidos em vez de os duplicar.

## Ficheiros

- `api/scraper_service.py` — definições (CRUD/validação), motor Scrapling, extração, JSONL, estatísticas.
- `api/scraper_scheduler.py` — *jobs* de cron (APScheduler), arranque/paragem no *lifespan* da API.
- `api/scraper_routes.py` — router `/scraper/*`.
- `api/elasticsearch_client.py` — índice `finance_scraped`, indexação e pesquisa (campo `data` do tipo `flattened`).
- `chat-ui/src/scraperApi.ts` — cliente tipado.
- `chat-ui/src/pages/ScraperPage.tsx` — 4 secções: Fontes, Execuções, Pesquisa, Agenda.

## Definição de uma fonte

```json
{
  "id": "contratos-portal-base",
  "name": "Contratos do portal base",
  "url": "https://www.base.gov.pt/Base4/pt/resultados/",
  "enabled": true,
  "fetcher": "http",
  "list": { "selector": "table.tabela tbody tr", "type": "css" },
  "fields": [
    { "name": "objeto", "selector": "td:nth-child(1)::text", "type": "css" },
    { "name": "preco", "selector": "td:nth-child(3)::text", "type": "css", "cast": "float" },
    { "name": "data", "selector": "td:nth-child(4)::text", "type": "css", "cast": "date" },
    { "name": "link", "selector": "a", "type": "css", "attr": "href" }
  ],
  "pagination": { "selector": "a.seguinte", "type": "css", "attr": "href", "max_pages": 10 },
  "schedule": { "cron": "0 7 * * 1-5", "timezone": "Europe/Lisbon" },
  "respect_robots": true,
  "tags": ["contratos"],
  "id_fields": ["link"]
}
```

Notas:

- **Seletores**: `css`, `xpath`, `text` (por conteúdo) ou `regex` (sobre o texto do nó).
  Nos `css` aceitam-se pseudo-elementos do estilo Scrapy: `::text`, `::attr(href)`.
  O campo `attr` acrescenta `::attr(...)` quando o seletor ainda não o traz.
- **Campos**: `all: true` recolhe todas as ocorrências (lista); `cast` converte
  (`text`, `int`, `float`, `bool`, `date`); `max_length` limita o tamanho.
- **Fetchers**: `http` (rápido, sem browser), `dynamic` (renderiza JavaScript),
  `stealth` (anti-bot/Cloudflare). Os dois últimos precisam de
  `scrapling install` para descarregar os browsers.
- **Cron**: 5 campos (`minuto hora dia mês dia-semana`), validado antes de guardar.
- **`id_fields`**: campos que identificam um item. Se ficar vazio usa-se o `url`
  (ou todos os campos) — evita duplicados entre execuções.
- **`respect_robots`**: quando ligado (omissão), o `robots.txt` do domínio é
  consultado e respeitado; se não for legível, a recolha prossegue.

## API

| Método | Rota | Descrição |
| --- | --- | --- |
| GET | `/scraper/meta` | Fetchers, tipos de seletor, presets de cron |
| GET | `/scraper/status` | Scrapling/browsers, Elasticsearch, agendador |
| GET | `/scraper/stats` | Resumo (fontes, execuções, itens) |
| GET | `/scraper/sources` | Listar fontes |
| POST | `/scraper/sources` | Criar fonte *(sessão)* |
| GET | `/scraper/sources/{id}` | Obter fonte |
| PATCH | `/scraper/sources/{id}` | Atualizar (parcial) *(sessão)* |
| DELETE | `/scraper/sources/{id}?purge_items=` | Apagar fonte *(sessão)* |
| POST | `/scraper/sources/{id}/run` | Recolher agora, em segundo plano *(sessão)* |
| POST | `/scraper/preview` | Testar uma definição sem guardar *(sessão)* |
| POST | `/scraper/sources/{id}/preview` | Testar uma fonte guardada *(sessão)* |
| GET | `/scraper/runs` | Histórico de execuções |
| GET | `/scraper/runs/{run_id}/items?source_id=` | Itens gravados (JSONL) |
| GET | `/scraper/search` | Pesquisar itens no Elasticsearch |
| GET | `/scraper/jobs` / POST `/scraper/jobs/reload` | Jobs de cron *(sessão)* |

Leitura é pública; escrever definições, disparar recolhas e ver a agenda exige sessão.

## Instalação

```powershell
c:\LLMFinance\.venv\Scripts\python.exe -m pip install "scrapling[fetchers]>=0.4.15" "apscheduler>=3.10,<4"
# só se precisar dos fetchers dynamic/stealth (browsers):
c:\LLMFinance\.venv\Scripts\python.exe -m scrapling install
```

## Pitfalls

- As sessões do Scrapling (`FetcherSession`, `DynamicSession`, `StealthySession`) só
  expõem `get`/`post` **depois** de entrar no *context manager* — abrir sempre com `with`.
- A API é servida sem `--reload`: alterações em `api/*.py` só entram depois de reiniciar.
- O `top_hits` não se aplica aqui: os campos variáveis vivem em `data`
  (`flattened`), pesquisável com `query_string` sobre `data.*`.
- Recolhas longas correm numa *thread*; o estado é atualizado no `.meta.json`
  (a UI faz *polling* enquanto houver execuções em curso).
