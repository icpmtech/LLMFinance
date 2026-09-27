# Citações e notificações editais (CITIUS / Ministério da Justiça)

Módulo que recolhe e pesquisa as **citações e notificações editais eletrónicas**
de executados, réus, requeridos e sujeitos processuais publicadas no portal do
Ministério da Justiça:

> https://www.citius.mj.pt/portal/consultas/ConsultasCitEdital.aspx

São os éditos publicados quando o citando/notificado **não foi encontrado** e é
chamado por édito (artigos 11.º e 12.º da Portaria n.º 282/2013, artigo 24.º da
Portaria n.º 280/2013 e artigo 113.º, n.º 13, do Código de Processo Penal).

Cada édito traz o **tribunal/serviço**, o **ato**, a **referência**, o
**processo** (número e juízo), a **espécie**, a **data de publicação**, os
**intervenientes com o respetivo papel** (exequente, executado, réu, requerido,
credor, agente de execução, …) e o **documento em PDF**.

## Fluxo do portal (ASP.NET WebForms, sem captcha)

| Passo | Pedido | Resultado |
|---|---|---|
| 1 | `GET ConsultasCitEdital.aspx` | formulário com `__VIEWSTATE`, `__EVENTVALIDATION`, `ddlTribunais` (257 serviços) , `txtNome` (obrigatório) e `rblDias` (`15` \| `30` \| `todos`) |
| 2 | `POST` normal com `ctl00$ContentPlaceHolder1$btnSearch` | página inteira com a lista `DataList` (10 éditos), o total («N editais encontrados») e os paginadores `Pager1`/`Pager2` |
| 3 | `POST` com `__EVENTTARGET=ctl00$ContentPlaceHolder1$Pager1$lnkNext` | página seguinte (usa o `__VIEWSTATE`/`__EVENTVALIDATION` da resposta anterior) |

Detalhes que custaram a descobrir:

- **Não há `UpdatePanel`**: ao contrário do CIRE, a resposta é a **página
  inteira** (não um *delta* `X-MicrosoftAjax`). Não é preciso `__ASYNCPOST`.
- **Não há captcha** nem mínimo de caracteres — mas o **nome é obrigatório**
  (validator `cvRequiredFields`).
- A página é **UTF-8** (as publicações societárias é que são Windows-1252).
- Os resultados vêm **ordenados por data descendente**, o que permite **parar a
  recolha** ao passar um limite de datas (é isto que faz o «últimos N meses»).
- Os intervenientes vivem num `span` `…_ReuDataList` (um `<span>` por pessoa,
  `Papel: Nome`); esta consulta **não publica NIF/NIPC** dos intervenientes.
- O documento é servido em `ConsultasCitEditalPDF.ashx?q=<token>`; o token está
  ligado à **sessão**, pelo que o PDF só abre com os cookies da recolha (a
  ligação mostrada na UI funciona no browser do utilizador através do portal).
- O portal limita os pedidos (daí o `min_interval`, 1,2 s por omissão).

## Recolher → JSON → Elasticsearch

O módulo é **em duas fases**, como os restantes da solução:

1. **Recolha** (`POST /citacoes/collect`) — pesquisa o portal pelo **nome do
   interveniente**, percorre a lista e grava tudo em **JSON**:

   | Ficheiro | Conteúdo |
   |---|---|
   | `data/citacoes/runs/<run_id>.json` | `{run_id, source, criteria, collected_at, count, items[]}` — legível e reimportável |
   | `data/citacoes/runs/<run_id>.meta.json` | resumo: critérios, corte aplicado, páginas, totais, tempos e o que foi importado |

2. **Importação** (`POST /citacoes/ingest`) — lê o JSON e indexa em
   `finance_citacoes_edital`. É **idempotente**: o `_id` é o `pub_id`
   (sha1 de referência + processo + data + ato), pelo que reimportar **ignora**
   os documentos já existentes (`skipped_existing`); `update_existing=true`
   força a reescrita.

### «Últimos 6 meses» (por omissão)

O formulário do portal **não tem intervalo de datas livre** — só os atalhos de
15/30 dias ou tudo. Como os resultados vêm por data descendente, a recolha usa
`dias=todos` e **corta na data**: `meses=6` (por omissão) recolhe até
`hoje − 6 meses` e **para** no momento em que uma página inteira fica anterior a
esse limite (`older_than_cutoff` conta os éditos descartados). `meses=0` recolhe
tudo o que o portal tiver para esse nome.

O corte é também o que torna a recolha viável: um nome comum («SILVA») tem
milhares de éditos, mas apenas algumas dezenas nos últimos meses.

## Ficheiros

| Ficheiro | Papel |
|---|---|
| `collectors/citius_citacoes.py` | `CitacoesEditalClient` (sessão ASP.NET, pesquisa, paginação, documento) + `parse_items` + `EditalCitacao` |
| `api/citacoes_service.py` | meta/opções, corte por meses, recolha, gravação em JSON, importação e listagem de recolhas |
| `api/citacoes_routes.py` | rotas `/citacoes/*` (recolha em segundo plano com progresso, importação, pesquisa, estado) |
| `api/elasticsearch_client.py` | índice `finance_citacoes_edital` (`citacoes_existing_ids`, `index_citacoes_items`, `search_citacoes`, `citacoes_status`) |
| `chat-ui/src/citacoesApi.ts` | cliente TypeScript das rotas |
| `chat-ui/src/pages/CitacoesPage.tsx` | página: Pesquisa, Recolha, Execuções, Estado |
| `data/citacoes/runs/` | ficheiros JSON das recolhas |

## Rotas

Leitura (pública)

| Rota | Descrição |
|---|---|
| `GET /citacoes/meta` | metadados (fonte, índice, pasta, limites, meses por omissão) |
| `GET /citacoes/options` | serviços/tribunais do portal (cache de 1 h) |
| `GET /citacoes/status` | volumetria e distribuições do índice |
| `GET /citacoes/search` | pesquisa (texto, nome de interveniente, papel, tribunal, tipo, ato, espécie, datas) com facetas |
| `GET /citacoes/runs` | recolhas gravadas em disco (com a contagem no índice) |
| `GET /citacoes/runs/{run_id}` | resumo de uma recolha (`?with_items=true` devolve os itens) |
| `GET /citacoes/jobs` | recolhas em curso e recentes |

Escrita (sessão)

| Rota | Descrição |
|---|---|
| `POST /citacoes/collect` | arranca a recolha em segundo plano (grava JSON; `index=true` importa no fim) |
| `POST /citacoes/jobs/{id}/stop` | pede a paragem (a página em curso termina primeiro) |
| `POST /citacoes/ingest` | importa uma recolha gravada (só o que ainda não existe) |
| `DELETE /citacoes/runs/{run_id}` | apaga os ficheiros de uma recolha |

Exemplo — recolher os últimos 6 meses de um interveniente e importar:

```bash
curl -X POST http://127.0.0.1:8002/citacoes/collect \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer <token>" \
  -d '{"nome": "MONTEPIO", "meses": 6, "max_pages": 60, "index": true}'
```

O progresso acompanha-se em `GET /citacoes/jobs/{id}` (página, recolhidos,
total declarado, importados).

## Pesquisa

`GET /citacoes/search` aceita:

- `q` — texto livre (interveniente, referência, processo, tribunal, ato, texto);
- `nome` — nome de um **interveniente** (qualquer papel) e `papel` — papel exato
  (`Exequente`, `Executado`, `Réu`, `Credor`, `Agente de Execução (Sol.)`, …);
- `tipo` — `Citação` | `Notificação` | `Anúncio`;
- `tribunal` (texto parcial), `tribunal_comarca`, `ato`, `especie`, `processo`,
  `referencia`, `citado`, `has_documento`;
- `data_from` / `data_to` (intervalo inclusivo sobre a data de publicação);
- `size` / `from` e facetas (tipo, papel, comarca, ato, espécie, ano, mês).

> Nota: `intervenientes.nome` é um campo `nested`; a pesquisa livre do índice
> junta por isso dois caminhos (campos planos e intervenientes) — sem isso, uma
> pesquisa pelo nome de uma parte devolvia zero resultados.

## Limitações conhecidas

- A consulta pública **só pesquisa por nome** (não aceita NIF/NIPC), pelo que a
  ligação a entidades do resto da plataforma é feita por **nome** (o portal não
  publica NIF/NIPC nesta consulta).
- Os PDF estão ligados à **sessão** da recolha: a ligação mostrada na UI abre no
  portal do CITIUS e pode exigir nova pesquisa se a sessão tiver expirado.
- Recolhas grandes (nomes comuns sem corte de meses) podem valer centenas de
  páginas; usar `max_pages`/`max_items` e o corte de meses.
