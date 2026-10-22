# Publicidade da Composição da Massa Insolvente (art.º 152.º do CIRE)

Módulo que recolhe e pesquisa os **anúncios da composição da massa insolvente**
publicados pelo **Administrador Judicial**, nos termos do art.º 152.º do CIRE
(Código da Insolvência e da Recuperação de Empresas), no portal do Ministério da
Justiça:

> https://www.citius.mj.pt/portal/consultas/PublicidadeMassaInsolvente.aspx

Ao contrário do [CIRE](./insolvencias-cire.md) (que lista publicações por ato),
esta página descreve **o que compõe a massa**: os bens apreendidos e a sua
avaliação. Cada anúncio traz

- **processo** (número + espécie), **tribunal** (comarca e juízo),
  **insolvente(s)** e **área de negócio** (CAE);
- **valor da avaliação** e **data da última atualização**;
- a **descrição da massa insolvente** (as verbas, em texto corrido);
- a **composição**: lista de ativos, cada um com tipo, descrição, quantidade e
  localização (concelho).

## Fluxo do portal (ASP.NET WebForms com `ScriptManager1`)

| Passo | Pedido | Resultado |
|---|---|---|
| 1 | `GET PublicidadeMassaInsolvente.aspx` | formulário com `__VIEWSTATE`/`__EVENTVALIDATION` e os `select` (tipos de ativo, localizações, áreas de negócio) |
| 2 | `POST` assíncrono (`__ASYNCPOST=true`, `X-MicrosoftAjax: Delta=true`, `ctl00$ContentPlaceHolder1$ScriptManager1=<painel>\|<botão>`) | *delta* com o painel `pnlUpdResults` (10 anúncios) e os paginadores `Pager1`/`Pager2` |
| 3 | `POST` com `__EVENTTARGET=ctl00$ContentPlaceHolder1$Pager1$lnkNext` | página seguinte (usa o `__VIEWSTATE`/`__EVENTVALIDATION` do delta anterior) |

Detalhes que custaram a descobrir:

- **O `ScriptManager1` é obrigatório** na pesquisa *e* na paginação. Sem ele o
  portal processa como postback normal e perde o contexto: a lista volta vazia.
- A resposta assíncrona é um *delta* cujo primeiro registo é `1|#||4|…` — o
  parser de deltas do CIRE (`collectors/citius_cire.parse_delta`) serve tal e
  qual, e `result_panel()` aceita tanto a página completa como o delta.
- **O `__VIEWSTATE` do delta tem de ser reaproveitado** no pedido seguinte.
  Enviar o viewstate da página inicial na paginação dá `pageRedirect` para
  `erro.htm` — o sintoma é uma resposta com `pageRedirect` e nenhum painel.
- Os **ids no delta usam `_`** (não o `$` do `UniqueID`):
  `ctl00_ContentPlaceHolder1_pnlUpdResults`.
- **Não há captcha** neste serviço.
- A **paginação mostra 10 anúncios por página**; o total vem em
  `lblRecordCount` («Número de Registos: N»).
- Os valores dos `select` são **códigos simples** nesta página (ao contrário dos
  tribunais do CIRE, que vêm cifrados). Ainda assim a escolha faz-se pelo
  **rótulo**, resolvido a partir do formulário.

### Certificado TLS incompleto (cadeia)

O `www.citius.mj.pt` serve o certificado sem o intermédio correto — ver
[insolvencias-cire.md](./insolvencias-cire.md#certificado-tls-incompleto-cadeia).
O coletor usa o mesmo `collectors/tls_chain.py` (reparação pelo AIA), sem
desligar a verificação.

## Recolher → JSON → Elasticsearch

O módulo é **em duas fases**, como os restantes da solução:

1. **Recolha** (`POST /massa-insolvente/collect`): percorre a lista do portal e
   grava tudo em **JSON**, em `data/massa_insolvente/runs/`:

   | Ficheiro | Conteúdo |
   |---|---|
   | `<run_id>.json` | `{run_id, source, criteria, collected_at, count, items[]}` |
   | `<run_id>.meta.json` | resumo: critérios, janelas, páginas, totais, tempos, avisos e o que foi indexado |

2. **Importação** (`POST /massa-insolvente/ingest`): lê o JSON e indexa em
   `finance_massa_insolvente`. É **idempotente** — o `_id` é o `pub_id` (sha1 do
   processo + data de atualização + tribunal), pelo que repetir a importação
   atualiza em vez de duplicar.

A separação permite inspecionar/repetir a recolha sem tocar no índice e
reimportar depois de alterar o parser.

### Não repetir trabalho

Duas regras evitam reescrever dados e repetir dias:

- **Importação** — antes de indexar, o serviço pergunta ao Elasticsearch quais
  dos `pub_id` já existem; esses são ignorados (`skipped_existing`). Para
  reescrever use `update_existing=true` em `POST /massa-insolvente/ingest`.
- **Recolha** — as janelas de datas já processadas ficam registadas nos resumos
  em `data/massa_insolvente/runs/*.meta.json`. Sem `force`, uma janela já feita é
  **ignorada com aviso** (`warnings` e `skipped_windows`), tanto na API como na
  secção Recolha da UI. `GET /massa-insolvente/coverage` devolve-as.

Com `split_runs=true` cada janela de datas é gravada e importada como uma
recolha própria (`<run_id>-<desde>_<ate>`), mantendo a memória constante.

## Ficheiros

| Ficheiro | Papel |
|---|---|
| `collectors/citius_massa.py` | `MassaInsolventeClient` (sessão ASP.NET, postback assíncrono, paginação) + `parse_items` + `AnuncioMassa`/`Ativo` |
| `api/massa_insolvente_service.py` | meta/opções, janelas de datas, recolha, gravação em JSON, importação, listagem de recolhas |
| `api/massa_insolvente_routes.py` | rotas `/massa-insolvente/*` (recolha em segundo plano com progresso, importação, pesquisa, estado) |
| `api/es/massa_insolvente.py` | índice `finance_massa_insolvente` (indexação, pesquisa, estado) |
| `chat-ui/src/massaInsolventeApi.ts` | cliente TypeScript das rotas |
| `chat-ui/src/pages/MassaInsolventePage.tsx` | página: Pesquisa, Recolha, Execuções, Estado |
| `data/massa_insolvente/runs/` | ficheiros JSON das recolhas |

## Rotas

Leitura (pública)

| Rota | Descrição |
|---|---|
| `GET /massa-insolvente/meta` | metadados (fonte, índice, pasta, limites) |
| `GET /massa-insolvente/options` | tipos de ativo, localizações e áreas de negócio do portal (cache de 1 h) |
| `GET /massa-insolvente/status` | volumetria e distribuições do índice |
| `GET /massa-insolvente/search` | pesquisa (texto, processo, tipo, espécie, tribunal, comarca, insolvente, tipo de ativo, localização, área de negócio, datas e valor) com facetas |
| `GET /massa-insolvente/coverage` | janelas/dias já recolhidos |
| `GET /massa-insolvente/runs` | recolhas gravadas em disco, com a contagem no índice |
| `GET /massa-insolvente/runs/{run_id}` | resumo de uma recolha (`?with_items=true` devolve os itens) |
| `GET /massa-insolvente/jobs` | recolhas em curso e recentes |

Escrita (sessão)

| Rota | Descrição |
|---|---|
| `POST /massa-insolvente/collect` | arranca a recolha em segundo plano (grava JSON; `index=true` importa no fim) |
| `POST /massa-insolvente/jobs/{id}/stop` | pede a paragem (a página em curso termina primeiro) |
| `POST /massa-insolvente/ingest` | importa uma recolha gravada (só o que ainda não existe) |
| `DELETE /massa-insolvente/runs/{run_id}` | apaga os ficheiros de uma recolha |

Exemplo — recolher os últimos 15 dias e importar:

```bash
curl -X POST http://127.0.0.1:8000/massa-insolvente/collect \
  -H "Authorization: ******" -H "Content-Type: application/json" \
  -d '{"dias":"15","max_pages":20,"index":true}'
```

Exemplo — recolher um mês por tipo de ativo «Imóvel», em janelas de 10 dias:

```bash
curl -X POST http://127.0.0.1:8000/massa-insolvente/collect \
  -H "Authorization: ******" -H "Content-Type: application/json" \
  -d '{"desde":"2026-09-01","ate":"2026-09-30","tipo_ativo":"Imóvel",
       "window_days":10,"split_runs":true,"index":true}'
```

## Índice `finance_massa_insolvente`

Campos principais: `pub_id`, `titulo`, `processo` / `processo_numero` /
`especie` / `tipo` (Insolvência, PER, PEAP, PEVE), `tribunal` /
`tribunal_comarca` / `juizo`, `insolventes[]` / `insolvente`,
`area_negocio`, `valor_avaliacao` / `valor_texto`, `data_atualizacao`,
`descricao`, `ativos[]` (nested: tipo, descrição, quantidade, localização),
`ativo_tipos[]`, `localizacoes[]`, `texto`, `run_id`, `source`, `ingested_at`.

Facetas devolvidas pela pesquisa: tipo de processo, tipo de ativo, comarca,
tribunal, espécie, localização, área de negócio, ano e mês — mais as
estatísticas de `valor_avaliacao` (`min`, `max`, `avg`, `sum`).

## Limites e boa conduta

- A recolha é **sequencial** e respeita `min_interval` (1,2 s por omissão).
- Cada página = 1 pedido, com **10 anúncios**. Um mês pode valer dezenas de
  páginas: prefira janelas pequenas (`window_days`) e recolhas incrementais.
- O portal só publica anúncios **enquanto a massa está em composição**; períodos
  antigos podem não ter registos (o total do portal é o que manda).

## Testes

| Script | Cobre |
|---|---|
| `tests/test_massa_insolvente.py` | parser do anúncio e dos ativos, valores/datas do portal, deteção do delta, estado do paginador, janelas de datas e metadados |
| `_test_cire.py` / `_test_cire_routes.py` | (módulo CIRE) servem de referência para o fluxo recolha → JSON → índice |
