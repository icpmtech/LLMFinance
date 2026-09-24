# Pesquisa social — LinkedIn, TikTok, Reddit e Facebook

O módulo **Pesquisa social** recolhe publicações das redes sociais para o índice
`finance_social`, onde ficam pesquisáveis (com facetas e sentimento) e
exportáveis para a Pesquisa total.

Não recolhe por seletores de HTML genéricos: cada plataforma tem um **coletor
próprio** (`api/social_collectors.py`) que fala a API, o `oembed` ou o JSON-LD
que aquela plataforma expõe. Percebe-se rapidamente porquê assim que se olha
para o que cada uma deixa fazer sem credenciais.

## O que cada plataforma permite

| Plataforma | Variante (`kind`) | Sem credenciais | O que traz |
| --- | --- | --- | --- |
| **LinkedIn** | `company` | ✅ | Página pública da empresa: JSON-LD com a publicação em destaque (texto, data, ligação e nº de reações) |
| **Reddit** | `subreddit` | ✅ | Listagem da comunidade pelo JSON público; se o IP estiver bloqueado, cai na página `shreddit-post` |
| **Reddit** | `search` | ❌ | Pesquisa por palavra-chave: a página é fechada a IPs de servidor → API OAuth (`client_id`/`client_secret`) |
| **TikTok** | `hashtag` | ✅ | Métricas da hashtag (vídeos/vistas) + vídeos em destaque da página de incorporação, enriquecidos por `oembed` |
| **TikTok** | `video` | ✅ | Metadados de um vídeo concreto (título, autor, miniatura) pelo `oembed` oficial |
| **Facebook** | `page` | ❌ | Publicações da página pela Graph API (exige `access_token`) |

Notas de campo (verificadas nesta instalação):

- o **LinkedIn** varia o HTML (às vezes serve uma versão sem JSON-LD) → o coletor
  repete o pedido uma vez antes de dar a página por vazia;
- o **Reddit bloqueia IPs de datacenter** (403 em todos os endereços públicos) →
  sem proxy residencial ou credenciais OAuth, o canal fica com estado
  **«bloqueada»** e a indicação do que fazer — não é uma falha silenciosa;
- o **TikTok serve a lista de vídeos por JavaScript** (sem `itemStruct` no HTML)
  → a hashtag dá as métricas e os vídeos que a página de incorporação expõe; para
  vídeos concretos, canais `video` com a ligação respetiva;
- o **Facebook** sem token devolve o erro da Graph API → o canal fica **«precisa
  de credenciais»**, com a ligação para criar a aplicação.

Um `429` (limite de pedidos) é repetido uma vez, respeitando o `Retry-After`.

## O canal (definição de recolha)

`data/social/channels.json` guarda os canais:

```json
{
  "id": "linkedin-microsoft",
  "name": "LinkedIn · Microsoft",
  "platform": "linkedin",
  "kind": "company",
  "target": "microsoft",
  "enabled": true,
  "limit": 25,
  "options": { "proxy": "", "token": "", "client_id": "", "client_secret": "" },
  "schedule": { "cron": "0 */6 * * *", "timezone": "Europe/Lisbon" },
  "tags": ["linkedin", "tecnologia"]
}
```

- **`platform` + `kind` + `target`** identificam o que se recolhe (o `target` é o
  slug da empresa, o subreddit, a hashtag, a página ou a ligação do vídeo);
- **`options`** leva o proxy e as credenciais. Os segredos (token, `client_secret`,
  `_api_key`…) **nunca saem mascarados** na API: a listagem mostra `••••••` e o
  estado (`credentials.ok` / `missing`);
- **`schedule.cron`** é validado antes de gravar (5 campos); só os canais com o
  interruptor ligado (`enabled`) entram no agendador;
- **`limit`** é o teto de publicações por recolha (1–200).

Há seis **modelos** prontos na galeria (`/social/templates`) — LinkedIn de uma
empresa, subreddit, pesquisa do Reddit, hashtag e vídeo do TikTok, página do
Facebook — com teste ao vivo antes de criar o canal.

## A publicação (`finance_social`)

O `_id` do documento é o `item_id`
(`sha1(plataforma|tipo|alvo|id-da-publicação)`), pelo que repetir a recolha
**atualiza** a publicação (métricas mais recentes) em vez de a duplicar.

```json
{
  "platform": "linkedin",
  "channel_id": "linkedin-microsoft",
  "kind": "company",
  "post_id": "7500953194492096512",
  "url": "https://www.linkedin.com/posts/microsoft_...",
  "title": "A look back at last year's Microsoft Ignite…",
  "text": "…",
  "author": "Microsoft",
  "community": "linkedin.com/company/microsoft",
  "image": "",
  "tags": ["linkedin", "microsoft", "tecnologia"],
  "likes": 665, "comments": 0, "shares": 0, "views": 0,
  "published_at": "2026-09-02T16:30:02.508Z",
  "collected_at": "2026-09-24T15:25:11Z",
  "sentiment": "positivo", "sentiment_score": 0.42, "sentiment_engine": "lexicon",
  "trigger": "manual",
  "data": { "headline": "…" }
}
```

As métricas de interação têm campos próprios (`likes`, `comments`, `shares`,
`views`) para se poder **ordenar e filtrar** por elas; o resto da informação
específica de cada plataforma vive em `data` (pesquisável com `data.*`).

## Sentimento

Cada publicação é classificada na recolha com o motor do módulo de Sentimento
(por omissão o **léxico PT local** — sem custo de IA e imediato). O resultado
alimenta a faceta **sentimento** da pesquisa e o tom agregado do conjunto. O
módulo de Sentimento também ganhou a origem **«Redes sociais»**, pelo que se pode
analisar um corpus social (com TF-IDF, distribuições e relatório) como qualquer
outra fonte.

## Agendamento (cron)

`api/social_scheduler.py` mantém um *job* do APScheduler por canal
(`social:<id>`), sincronizado com as definições: criar, alterar, ligar/desligar ou
apagar um canal reaplica os jobs de imediato. O estado (próximas execuções) está
em `/social/jobs` e na secção **Agenda**.

## API

Leitura (pública)

- `GET /social/meta` — plataformas, variantes, presets de cron, motores de sentimento e o índice.
- `GET /social/platforms` · `GET /social/status` · `GET /social/stats`.
- `GET /social/channels` · `GET /social/channels/{id}`.
- `GET /social/runs` · `GET /social/runs/{run_id}` · `GET /social/runs/{run_id}/items?channel_id=`.
- `GET /social/search` — `q`, `platform`, `channel_id`, `tag`, `sentiment`, datas, `sort` (`recent`, `oldest`, `relevance`, `engagement`, `views`).
- `GET /social/templates` · `GET /social/templates/{id}`.

Escrita (sessão)

- `POST /social/channels` · `PATCH /social/channels/{id}` · `DELETE /social/channels/{id}?purge_items=`.
- `POST /social/channels/{id}/run` — recolha imediata em segundo plano (devolve `run_id`).
- `POST /social/preview` · `POST /social/channels/{id}/preview` — testar a definição sem guardar.
- `POST /social/templates/{id}/preview` · `POST /social/templates/{id}/channel`.
- `GET /social/jobs` · `POST /social/jobs/reload`.

## Aplicação (chat-ui)

Página `/social` (aplicação «Pesquisa social» no dock e no menu), com seis
secções:

- **Pesquisa** — a caixa única (estilo da Pesquisa total) com filtros por
  plataforma, canal, sentimento, etiqueta e ordenação; facetas por plataforma e
  etiqueta, tom do conjunto e resultados em **cartões, lista ou imagens** (o
  mesmo componente da Recolha e da Pesquisa total);
- **Canais** — as definições, com o estado das credenciais, recolha imediata
  (com progresso e as publicações gravadas), teste de amostra, agenda, etiquetas
  e apagar;
- **Execuções** — histórico com contagens, notas do coletor e publicações;
- **Modelos** — galeria de canais prontos, com teste ao vivo;
- **Agenda** — jobs ativos e o cron de cada canal;
- **Estado** — ambiente (HTTP, Scrapling, browsers, proxy, Elasticsearch),
  volumetria por plataforma (gráfico) e o que cada plataforma permite.

A Pesquisa total (`/pesquisa`) ganhou o âmbito **«Redes sociais»**, que devolve
as mesmas publicações junto dos outros âmbitos.

## Ficheiros

| Ficheiro | Papel |
| --- | --- |
| `api/social_collectors.py` | Coletores por plataforma (o que se pede, como se interpreta) |
| `api/social_service.py` | Canais (definições), execuções, JSONL, indexação, pesquisa e estatísticas |
| `api/social_scheduler.py` | Jobs de cron por canal |
| `api/social_routes.py` | Router `/social/*` |
| `api/elasticsearch_client.py` | Índice `finance_social` (mapeamento e funções `index_social_items`, `search_social`, `social_status`) |
| `chat-ui/src/socialApi.ts` | Cliente da API no frontend |
| `chat-ui/src/pages/SocialPage.tsx` | Página (pesquisa, canais, execuções, modelos, agenda, estado) |
| `data/social/channels.json` | Canais guardados |
| `data/social/runs/<canal>/<run_id>.{jsonl,meta.json}` | Publicações e metadados de cada recolha |
| `_test_social.py` | Testes do módulo (catálogo, definições, coletores ao vivo, indexação, agendador) |
| `_probe_social*.py` | Sondas usadas para descobrir o que cada plataforma expõe |

## Operação

```powershell
# Testes do módulo (recolhas ao vivo incluídas)
c:\LLMFinance\.venv\Scripts\python.exe _test_social.py
c:\LLMFinance\.venv\Scripts\python.exe _test_social.py --fast   # sem rede

# Uma recolha concreta, sem UI
c:\LLMFinance\.venv\Scripts\python.exe -c "from api import social_service as s; print(s.execute_run_sync('linkedin-microsoft'))"
```

Reiniciar a API depois de mexer em `api/social_*` (o agendador arranca no
*lifespan*). No browser, desregistar o service worker antes de validar um build
novo.

## Limitações conhecidas

- **Reddit** — sem proxy residencial nem OAuth, a recolha por subreddit fica
  bloqueada a partir desta rede; o estado do canal di-lo com a indicação.
- **TikTok** — não há API pública de listagem de vídeos sem assinatura
  (`X-Bogus`), pelo que a hashtag dá métricas + os vídeos da página de
  incorporação; para cobertura vídeo a vídeo, use canais `video`.
- **Facebook** — depende de um token válido (expira); o estado do canal mostra
  quando falta ou é recusado.
- **LinkedIn** — a página pública costuma trazer a publicação mais recente (a
  vista «guest» não lista o histórico).
