# Insolvências e revitalizações de empresas (CIRE / CITIUS)

Módulo que recolhe e pesquisa a **publicidade dos processos especiais de
revitalização (PER), dos processos especiais para acordo de pagamento (PEAP),
dos processos extraordinários de viabilização de empresas (PEVE) e dos
processos de insolvência** publicados no portal do Ministério da Justiça:

> https://www.citius.mj.pt/portal/consultas/consultascire.aspx

Cada documento traz o **tribunal**, o **processo** (número e juízo), a
**espécie**, o **ato** publicado, a **data de publicação**, a data da propositura
da ação e os **intervenientes com NIF/NIPC** (insolvente/devedor, administrador
da insolvência, fiduciário, credores…).

## Fluxo do portal (ASP.NET WebForms com `UpdatePanel`)

| Passo | Pedido | Resultado |
|---|---|---|
| 1 | `GET ConsultasCire.aspx` | formulário com `__VIEWSTATE`, `__EVENTVALIDATION` e os `select` (tribunais, grupos de atos, atos) |
| 2 | `POST` assíncrono (`__ASYNCPOST=true`, `X-MicrosoftAjax: Delta=true`, `ctl00$ContentPlaceHolder1$ScriptManager1=<painel>\|<botão>`) | *delta* com o painel `upResultados`: ligação `dlResultados` (10 documentos) + paginadores `Pager1`/`Pager2` |
| 3 | `POST` com `__EVENTTARGET=ctl00$ContentPlaceHolder1$Pager1$lnkNext` | página seguinte (usa o `__VIEWSTATE`/`__EVENTVALIDATION` que vieram no delta anterior) |

Detalhes que custaram a descobrir:

- **Sem `ScriptManager1` o postback não é tratado** como *partial postback* pelos
  painéis esperados — a lista volta vazia. O campo tem de acompanhar o
  `__EVENTTARGET` da pesquisa e da paginação.
- **`__VIEWSTATEENCRYPTED` tem de ser enviado** (mesmo vazio): sem ele o servidor
  responde `500` e redireciona para `erro.htm`.
- Os **ids no delta usam `_`** (não o `$` do `UniqueID`): `ctl00_ContentPlaceHolder1_upResultados`.
- O cabeçalho **`X-Requested-With: XMLHttpRequest`** (com `X-MicrosoftAjax`) é o
  que faz o portal devolver o delta com conteúdo.
- **Não há captcha** neste serviço (ao contrário das publicações societárias).
- O valor dos **tribunais vem cifrado** pelo portal: a escolha faz-se pelo
  **rótulo** e o valor é resolvido a partir do formulário (`?` nas opções).
- A **paginação mostra 10 documentos por página** — um mês pode valer centenas de
  páginas, daí os limites (`max_pages`, `max_items`, `window_days`).

## Recolher → JSON → Elasticsearch

O módulo é deliberadamente **em duas fases**, como os restantes da solução:

1. **Recolha** (`POST /cire/collect`): percorre a lista do portal e grava tudo em
   **JSON**, em `data/cire/runs/`:

   | Ficheiro | Conteúdo |
   |---|---|
   | `<run_id>.json` | `{run_id, source, criteria, collected_at, count, items[]}` — os dados, legíveis e reimportáveis |
   | `<run_id>.meta.json` | resumo: critérios, janelas, páginas, totais, tempos, avisos e o que foi indexado |

2. **Importação** (`POST /cire/ingest`): lê o JSON e indexa em
   `finance_cire`. É **idempotente** — o `_id` é o `pub_id` (sha1 da referência +
   processo + data + ato), pelo que repetir a importação atualiza em vez de
   duplicar.

A separação permite inspecionar/repetir a recolha sem tocar no índice e
reimportar depois de alterar o parser.

### Não repetir trabalho

Duas regras evitam reescrever dados e repetir dias:

- **Importação** — antes de indexar, o serviço pergunta ao Elasticsearch quais
  dos `pub_id` **já existem**; esses são ignorados (`skipped_existing`), ou seja,
  recolher/reimportar o mesmo período só acrescenta o que é novo. Para
  reescrever (por exemplo depois de alterar o parser) use `update_existing=true`
  em `POST /cire/ingest` (ou apague antes).
- **Recolha** — as janelas de datas já processadas ficam registadas nos resumos
  em `data/cire/runs/*.meta.json`. Sem `force`, uma janela já feita é **ignorada
  com aviso** (`warnings` no job/meta e `skipped_windows`), tanto na API como na
  secção Recolha da UI. Com `force=true` é recolhida outra vez.

### Recolhas longas (uma por janela)

Com `split_runs=true` cada janela de datas é gravada e importada como uma
recolha própria (`<run_id>-<desde>_<ate>`), mantendo a memória constante,
permitindo reimportar janelas isoladas e dando progresso por janela. É o modo
recomendado para períodos de anos.

`GET /cire/coverage` devolve as janelas/dias já feitos (a UI usa-o para avisar
dentro do formulário antes de a pessoa clicar em «Recolher»).

### Recolha histórica (2020 → hoje)

```bash
python _recolha_cire_historico.py --desde 2020-01-01 --ate 2026-09-23 \
    --window-days 31 --max-pages 3000 --min-interval 1.0
```

O processo é **retomável**: como cada janela fica registada, voltar a arrancá-lo
salta o que já está feito (avisa no log). O estado corrente fica em
`data/cire/historico_status.json` e o log em `logs/cire_historico.out`.
`--no-index` recolhe só para JSON; `--force` reconstrói tudo.

## Ficheiros

| Ficheiro | Papel |
|---|---|
| `collectors/citius_cire.py` | `CireClient` (sessão ASP.NET, postback assíncrono, paginação) + `parse_items` + `PublicacaoCire` |
| `api/cire_service.py` | meta/opções, janelas de datas, recolha, gravação em JSON, importação, listagem de recolhas |
| `api/cire_graph.py` | grafo das insolvências: dimensões, valores por papel, agregação exata e varredura |
| `api/cire_routes.py` | rotas `/cire/*` (recolha em segundo plano com progresso, importação, pesquisa, grafo, estado) |
| `api/elasticsearch_client.py` | índice `finance_cire` (mapping, `index_cire_items`, `search_cire`, `cire_status`) |
| `chat-ui/src/cireApi.ts` | cliente TypeScript das rotas |
| `chat-ui/src/components/cire/cireGraph.ts` | modelo do grafo: dimensões→`StudioGraph`, cores, drill-down e CSV |
| `chat-ui/src/components/cire/CireGraphPanel.tsx` | secção **Grafo** (receitas, filtros, vistas, detalhe do nó) |
| `chat-ui/src/pages/CirePage.tsx` | página: Pesquisa, **Grafo**, Recolha, Execuções, Estado |
| `data/cire/runs/` | ficheiros JSON das recolhas |

## Rotas

Leitura (pública)

| Rota | Descrição |
|---|---|
| `GET /cire/meta` | metadados (fonte, índice, pasta, limites, grupos de atos) |
| `GET /cire/options` | tribunais e atos do portal (cache de 1 h) |
| `GET /cire/status` | volumetria e distribuições do índice |
| `GET /cire/search` | pesquisa (texto, NIF, processo, tribunal, tipo, ato, papel, datas) com facetas |
| `GET /cire/intervenientes/{nif}` | publicações em que o NIF/NIPC é interveniente |
| `GET /cire/graph/dimensions` | dimensões, métricas e receitas disponíveis para o grafo |
| `GET /cire/graph` | constrói o grafo (nós/arestas) a partir dos filtros |
| `GET /cire/runs` | recolhas gravadas em disco, com a contagem no índice |
| `GET /cire/runs/{run_id}` | resumo de uma recolha (`?with_items=true` devolve os itens do JSON) |
| `GET /cire/jobs` | recolhas em curso e recentes |

Escrita (sessão)

| Rota | Descrição |
|---|---|
| `POST /cire/collect` | arranca a recolha em segundo plano (grava JSON; `index=true` importa no fim) |
| `POST /cire/jobs/{id}/stop` | pede a paragem (a página em curso termina primeiro) |
| `POST /cire/ingest` | importa uma recolha gravada (só o que ainda não existe) |
| `DELETE /cire/runs/{run_id}` | apaga os ficheiros de uma recolha |

| Rota | Descrição |
|---|---|
| `GET /cire/coverage` | janelas/dias já recolhidos (para avisar antes de repetir) |

Exemplo — recolher uma semana de 2026 (uma janela, até 40 páginas) e importar:

```bash
curl -X POST http://127.0.0.1:8002/cire/collect \
  -H "Authorization: Bearer <token>" -H "Content-Type: application/json" \
  -d '{"desde":"2026-09-16","ate":"2026-09-23","max_pages":40,"index":true}'
```

## Índice `finance_cire`

Campos principais: `referencia`, `data_publicacao`, `data_propositura`,
`tribunal` / `tribunal_comarca` / `tribunal_sede`, `ato`, `processo` /
`processo_numero` / `juizo`, `especie`, `tipo` (Insolvência, PER, PEAP, PEVE),
`insolvente`, `intervenientes[]` (nested: papel, nome, nif), `nifs[]`,
`has_documento`, `documento_url`, `run_id`, `ingested_at`.

Facetas devolvidas pela pesquisa: tipo, comarca, tribunal, espécie, ato, ano,
mês e papel do interveniente.

## Grafo (`/cire/graph`)

A secção **Grafo** da página desenha a rede das insolvências a partir do índice.
Cada nó é o valor de uma **dimensão**; cada aresta é a **co-ocorrência na mesma
publicação** (ou a ligação entre duas dimensões, ex.: administrador → insolvente).

Dimensões (papéis extraídos de `intervenientes[]`):

| Chave | O que agrega |
|---|---|
| `insolvente` | papéis «Insolvente» e «Devedor» |
| `administrador` | papel «Administrador Insolvência» |
| `credor` / `requerente` | papéis «Credor» / «Requerente» |
| `interveniente` | qualquer papel com NIF ou nome |
| `tribunal`, `comarca`, `sede`, `juizo` | campos planos do processo |
| `tipo`, `especie`, `ato`, `papel` | classificação da publicação |
| `ano`, `mes` | derivados de `data_publicacao` |

Métricas: `publicacoes` (documentos distintos) ou `mencoes` (intervenções).

Modos (`mode`):

- `exato` — dimensões planas/temporais resolvem-se por **agregações** (contagens
  exatas e completas, ~50 ms); nas restantes percorre as publicações até ao teto
  do servidor (`sample=0`);
- `amostra` — percorre as `sample` publicações mais recentes;
- `auto` — `exato` sem dimensão B e dimensão agregável, senão amostra.

Limites devolvidos em `meta.limits` (300 000 publicações por varredura,
10 000 nós, 30 000 arestas). Nos grafos de duas dimensões o orçamento de nós é
repartido: cada lado garante ~1/4 do orçamento, escolhido pelas **arestas mais
fortes**, pelo que o subgrafo devolvido é ligado (sem um lado a sufocar o outro).

A UI (`CireGraphPanel`) oferece receitas prontas (quem administra quem,
insolvente × credores, co-credores, administradores por comarca, território,
tipos, evolução mensal, atos), vistas (rede, hierárquico, circular, fluxos,
treemap, lista), exportação CSV e navegação: clicar num nó mostra os vizinhos
mais fortes e **abre a pesquisa** com os filtros desse nó.

```bash
# Rede administrador → insolvente (amostra de 20 mil publicações)
curl "http://127.0.0.1:8002/cire/graph?dimension_a=administrador&dimension_b=insolvente&limit=60"
# Ranking exato das comarcas (agregação, sem amostragem)
curl "http://127.0.0.1:8002/cire/graph?dimension_a=comarca&mode=exato&limit=30"
```

## Limites e boa conduta

- O portal não publica `robots.txt` restritivo para esta página; ainda assim a
  recolha é **sequencial** e respeita `min_interval` (1,2 s por omissão).
- Cada página = 1 pedido. Recolher um mês inteiro (>2 000 documentos) são
  centenas de pedidos: **prefira janelas pequenas** (`window_days`) e
  recolhas incrementais dos últimos dias.
- O documento PDF de cada publicação abre por
  `Viewer/MostraPdf.aspx?q=<token>` → `Viewer/DocumentoPDF.ashx?q=<token>`, mas
  o token está preso à sessão e ao visualizador; por isso guarda-se o
  `documento_url` (o PDF não é descarregado em massa).

## Testes

| Script | Cobre |
|---|---|
| `_test_cire.py` | formulário, pesquisa, paginação, itens e documento |
| `_test_cire_backend.py` | recolha → JSON → importação → pesquisa → estado |
| `_test_cire_routes.py` | rotas HTTP (recolha em segundo plano, jobs, runs, importação, validações) |
| `_test_cire_dedupe.py` | não repetir dias já processados e não reindexar o que já existe |
| `_test_cire_graph.py` | construtor do grafo contra o Elasticsearch real (agregação, amostra, arestas) |
| `_test_cire_graph_routes.py` | rotas `/cire/graph*` pelo `TestClient` |
| `_recolha_cire_historico.py` | recolha histórica por janelas (retomável) |
