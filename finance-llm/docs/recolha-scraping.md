# Recolha de dados de sites (scraping)

Módulo de recolha do **IQ OS**, assente na biblioteca [Scrapling](https://github.com/D4Vinci/Scrapling).
Permite definir **fontes** (que site, que campos, com que periodicidade), executá-las
à mão ou por **cron**, e **pesquisar** tudo o que foi recolhido.

## Conceitos

| Conceito | O que é | Onde vive |
| --- | --- | --- |
| **Fonte** | Definição declarativa: URL, *fetcher*, seletores, campos, paginação, cron | `data/scraper/sources.json` |
| **Template** | Definição pronta para um site concreto (Jornal Económico, ECO, Público…) | `api/scraper_templates.py` |
| **Execução** (`run`) | Uma recolha concreta de uma fonte | metadados em `data/scraper/runs/<fonte>/<run_id>.meta.json` |
| **Item** | Um registo extraído (um produto, um contrato, uma notícia…) | `data/scraper/runs/<fonte>/<run_id>.jsonl` |
| **Texto integral** | Corpo do artigo, obtido na página de cada item (opcional) | campo `text` do item |
| **Repetido** | Cartão que a página devolve duas vezes (mesmo URL ou mesmo título) | contador `duplicates` da execução |
| **Índice** | Cópia pesquisável dos itens | Elasticsearch `finance_scraped` |

O `item_id` (derivado dos `id_fields` da fonte) é usado como `_id` no Elasticsearch:
repetir uma recolha **atualiza** os itens conhecidos em vez de os duplicar.

## Ficheiros

- `api/scraper_service.py` — definições (CRUD/validação), motor Scrapling, extração, JSONL, estatísticas.
- `api/scraper_templates.py` — catálogo de **templates de sites** (definições prontas e verificadas).
- `api/scraper_scheduler.py` — *jobs* de cron (APScheduler), arranque/paragem no *lifespan* da API.
- `api/scraper_routes.py` — router `/scraper/*`.
- `api/elasticsearch_client.py` — índice `finance_scraped`, indexação e pesquisa (campo `data` do tipo `flattened`).
- `chat-ui/src/scraperApi.ts` — cliente tipado.
- `chat-ui/src/pages/ScraperPage.tsx` — 5 secções: Templates, Fontes, Execuções, Pesquisa, Agenda.

## Ver os itens recolhidos

Os itens aparecem em três vistas — **Cartões**, **Lista** e **Imagens** — em dois
sítios: no painel de cada execução (*Execuções*) e nos resultados da **Pesquisa
total**. Todas mostram **os valores extraídos** (os campos da definição da fonte),
por isso uma lista de resultados não é uma lista de títulos.

- **Cartões**: imagem, título, fonte, data, resumo, valores e etiquetas.
- **Lista**: linhas compactas com miniatura, valores e ligação (onde cabem mais
  itens).
- **Imagens**: mosaico só com os itens que têm imagem (diz quantos ficaram de fora).

As imagens são o URL original do site (não há cópia local): o componente partilhado
`chat-ui/src/components/ItemsView.tsx` envia `referrerPolicy="no-referrer"` (muitos
CDNs de imprensa recusam pedidos com referência de outra página) e mostra um
marcador quando a imagem já não existe.

Do lado da extração há duas regras que mantêm as imagens úteis:

- valores `data:` (o GIF transparente de 1×1 pixel do carregamento preguiçoso) são
  **descartados** — o campo passa ao seletor alternativo seguinte;
- nos sites que só revelam a imagem em `data-src` (Jornal de Negócios), o campo usa
  `selectors: ["img::attr(data-src)", "img::attr(src)"]`.

A pesquisa total devolve, para os itens recolhidos, a imagem e os valores
(`_scraped_image`/`_scraped_values` em `api/search_service.py`); valores muito
longos (texto integral) ficam de fora da lista, mas continuam pesquisáveis.

## Templates de sites

O caminho mais rápido para começar: escolher um site e criar a fonte a partir do
template. Os seletores foram escritos e **validados contra as páginas reais** (ver
*Validação* abaixo).

| Template | Site | Requer | Texto integral |
| --- | --- | --- | --- |
| `jornal-economico` | `jornaleconomico.sapo.pt` | HTTP | sim |
| `eco` | `eco.sapo.pt` | HTTP | sim |
| `dinheiro-vivo` | `dinheirovivo.pt` (`dinheirovivo.dn.pt`) | HTTP | não (a notícia é renderizada no cliente) |
| `observador-economia` | `observador.pt/seccao/economia` | HTTP | sim |
| `publico-economia` | `publico.pt/economia` | HTTP | sim |
| `jornal-de-negocios` | `jornaldenegocios.pt` | **browser** | não |
| `expansion` | `expansion.com` | HTTP | sim |
| `investing-mercados` | `investing.com/news/stock-market-news` | HTTP | não |
| `quotes-demo` | `quotes.toscrape.com` | HTTP | não (site de exemplo) |

Como se cria uma fonte a partir de um template:

1. **Templates** → *Testar* (recolhe 3 itens da página, sem guardar nem indexar).
2. *Ajustar* abre o editor já preenchido (nome, campos, cron, texto integral) para revisão.
3. *Criar fonte* guarda a definição — fica **desligada**; ligue o interruptor em *Fontes* para o cron passar a correr.

### Manter as fontes alinhadas com o template

Os sites mudam de `class` e os templates são corrigidos aqui. Uma fonte criada há
semanas continuaria com os seletores antigos, por isso o cartão da fonte (quando
veio de um template) tem o botão **Template**: reaplica a definição do template e
mantém o **nome**, a **agenda**, o **interruptor** e as **etiquetas**. Equivale a
`POST /scraper/sources/{id}/apply-template`.

Sem tocar na UI, a mesma coisa por API:

```bash
# testar
curl -X POST "http://127.0.0.1:8002/scraper/templates/eco/preview?limit=3"
# criar (com cron próprio, a partir do cron sugerido pelo template)
curl -X POST http://127.0.0.1:8002/scraper/templates/eco/source \
  -d '{"name":"ECO (manhã)","cron":"0 7 * * 1-5","detail_max_items":10}'
# reaplicar o template a uma fonte já criada (quando os seletores do site mudam)
curl -X POST http://127.0.0.1:8002/scraper/sources/eco-sapo-27cd8a/apply-template
```

### Texto integral (`detail`)

Os templates de jornais trazem o bloco `detail`, que faz a recolha guardar
também o **corpo do artigo**:

```json
{
  "detail": {
    "enabled": true,
    "selector": "div.entry__content",
    "max_items": 20,
    "delay": 0.6,
    "max_chars": 20000
  }
}
```

- `selector` aponta para o contentor do texto na página de detalhe; é escolhido
  o **maior** dos nós que casam com o seletor (as páginas repetem as classes do
  corpo em painéis de data e caixas «últimas notícias»).
- `max_items` limita quantos itens são abertos por execução (cada um é um pedido
  extra) e `delay` é a pausa entre pedidos — a recolha respeita o `robots.txt`
  também nestas páginas.
- Falhas individuais contam-se em `detail_errors` no `.meta.json` e não
desligam a recolha; `detail_count` diz quantos itens trouxeram texto.

### Validação

```powershell
c:\LLMFinance\.venv\Scripts\python.exe _test_scraper_templates.py           # todos
c:\LLMFinance\.venv\Scripts\python.exe _test_scraper_templates.py eco publico-economia
```

O relatório (`_test_scraper_templates.txt` e `_test_scraper_templates.json`)
mostra, por template, o número de itens, a cobertura de cada campo e o tamanho do
texto integral obtido — é o que se olha depois de mexer nos seletores.

Ferramentas de apoio:

| Ficheiro | Para quê |
| --- | --- |
| `_probe_scraper_templates.py <url…>` | Candidatos a seletor de lista e cobertura de campos numa página |
| `_probe_tree.py "url\|seletor\|fetcher"` | Árvore compacta de um cartão (classes, atributos e texto) |
| `_probe_body.py "url\|fetcher"` | Contentores com mais texto de parágrafos — encontra o corpo do artigo |
| `_probe_titulos.py <template_id>` | Amostra larga de títulos de um template (à procura de vazios ou repetidos) |
| `_probe_repetidos.py [n]` | Itens repetidos (URL/título) nas últimas execuções |
| `_probe_imagens.py` | Campos e imagens dos itens indexados, por fonte |
| `_fix_scraper_sources.py --verificar` | Testa todas as fontes criadas a partir de templates |
| `_fix_scraper_sources.py --template [id]` | Reaplica o template às fontes que dele vieram |
| `_fix_scraper_sources.py --recolher <id>` | Corre uma recolha dessas fontes (para atualizar dados antigos) |
| `_test_scraper_templates_flow.py` | Galeria → preview → criar fonte → reaplicar → apagar (sem browser) |
| `_test_scraper_templates_run.py` | Recolha real de um template + verificação no Elasticsearch |
| `_test_scraper_templates_api.py` | Rotas `/scraper/templates*` na API em execução |

Os relatórios das sondagens saem em `_probe_*.txt` (UTF-8: o console do Windows
estraga os acentos).

**Sites que ficaram de fora:** os que bloqueiam HTTP simples com 403 depois de
poucos pedidos (idealista/news, Expresso) precisariam do *fetcher* `stealth`, que
muda de IP/impressão digital a cada pedido; como falham de forma intermitente,
não entram no catálogo para não dar fontes que “às vezes funciona”.

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
- **Vários seletores no mesmo campo**: `selectors: ["p[title]::attr(title)", "a::text"]`
  usa o **primeiro que devolver valor** — é o que resolve páginas que desenham o
  mesmo dado de duas maneiras (cartão de destaque e cartão de lista).
- **Títulos iguais não entram duas vezes**: dentro da mesma execução, um item cujo
  `item_id` já foi recolhido **ou** cujo título (≥ 40 caracteres) já apareceu é
  ignorado e contado em `duplicates` no `.meta.json`. Evita o caso típico dos
  sites que repetem o mesmo cartão no topo e na lista.
- **Fetchers**: `http` (rápido, sem browser), `dynamic` (renderiza JavaScript),
  `stealth` (anti-bot/Cloudflare). Os dois últimos precisam de
  `scrapling install` para descarregar os browsers.
- **Cron**: 5 campos (`minuto hora dia mês dia-semana`), validado antes de guardar.
- **`id_fields`**: campos que identificam um item. Se ficar vazio usa-se o `url`
  (ou todos os campos) — evita duplicados entre execuções.
- **`respect_robots`**: quando ligado (omissão), o `robots.txt` do domínio é
  consultado e respeitado; se não for legível, a recolha prossegue.
- **Ligações relativas**: os campos `url`, `link`, `href`, `imagem`… são resolvidos
  contra o URL da página (é o que faz o template do Jornal de Negócios guardar
  endereços completos, e não `/empresas/...`).
- **Datas**: o `cast: "date"` normaliza para `AAAA-MM-DD` os formatos que
  aparecem nas páginas — ISO, `2026/09/22`, `22 de Setembro de 2026`, `22 Set 2026`
  e o RFC 822 do Público (`Tue, 22 Sep 2026 12:54:36 GMT`).

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
| GET | `/scraper/templates?category=` | Galeria de templates de sites |
| GET | `/scraper/templates/{id}` | Template + definição que cria |
| POST | `/scraper/templates/{id}/preview` | Testar o template sem guardar *(sessão)* |
| POST | `/scraper/templates/{id}/source` | Criar a fonte a partir do template *(sessão)* || POST | `/scraper/sources/{id}/apply-template` | Reaplicar o template à fonte *(sessão)* |
Leitura é pública; escrever definições, disparar recolhas e ver a agenda exige sessão.

## Instalação

```powershell
c:\LLMFinance\.venv\Scripts\python.exe -m pip install "scrapling[fetchers]>=0.4.15" "apscheduler>=3.10,<4"
# só se precisar dos fetchers dynamic/stealth (browsers):
c:\LLMFinance\.venv\Scripts\scrapling.exe install
```

O comando dos browsers descarrega o Chromium do Playwright (`%LOCALAPPDATA%\ms-playwright`).
Sem ele, `/scraper/status` indica que só o *fetcher* HTTP está disponível e os
templates que pedem browser falham com «Executable doesn't exist».

## Pitfalls

- As sessões do Scrapling (`FetcherSession`, `DynamicSession`, `StealthySession`) só
  expõem `get`/`post` **depois** de entrar no *context manager* — abrir sempre com `with`.
- A API é servida sem `--reload`: alterações em `api/*.py` só entram depois de reiniciar.
- O `top_hits` não se aplica aqui: os campos variáveis vivem em `data`
  (`flattened`), pesquisável com `query_string` sobre `data.*`.
- Recolhas longas correm numa *thread*; o estado é atualizado no `.meta.json`
  (a UI faz *polling* enquanto houver execuções em curso).
