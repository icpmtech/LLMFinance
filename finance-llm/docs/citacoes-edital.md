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

> O **PDF é lido**: além do texto integral, dele se extraem os **NIF das partes**
> (que a consulta pública não publica), o **valor da execução**, o **modelo do
> formulário** (`547/0.05`), a **referência interna do processo** (`PE/52/2019`) e
> o **prazo** («Vinte Dias»). É isso que alimenta os cartões, o **grafo** e o
> **mapa**.

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
  ligado à **sessão**, pelo que o PDF só abre com os cookies da recolha. É por
  isso que a extração acontece **durante a recolha** (o `token` de cada édito é
  usado na mesma sessão em que a lista foi lida) e que a reanálise de uma recolha
  antiga **volta a pesquisar** o portal pelos critérios gravados.
- Todos os documentos desta consulta são **PDF com texto** (não é preciso OCR).
- O portal limita os pedidos (daí o `min_interval`, 1,2 s por omissão).

## Análise do documento (PDF)

`extract_pdf_text` (PyMuPDF, com `pypdf` como alternativa) devolve
`{texto, paginas, caracteres, truncado}` e `analyze_documento` extrai:

| Campo | Origem no texto |
|---|---|
| `documento_valor` | `Valor: 44.563,46 Euros` |
| `documento_nifs` | `… - NIF: 166611565` |
| `documento_partes` | `Executado(s)/Executado/Exequente(s)/Réu: Nome - NIF: …` |
| `documento_modelo` | `Modelo: 547/0.05` |
| `documento_referencia_interna` | `Referência interna do processo: PE/52/2019` |
| `documento_codigo` | `Documento: kZ4OV9LTDyA` |
| `documento_prazo` | `prazo de VINTE DIAS` |
| `documento_titulo` / `documento_assunto` | primeira linha com palavra-forte (`citação`, `edital`, `venda`, `penhora`, `insolvência`, …); o **título** é a linha imediatamente a seguir a `Página N de M` (a capa: `CITAÇÃO EDITAL ELETRÓNICA`) |

Os NIF lidos são depois **colados aos intervenientes** da lista (`enriquecer_intervenientes`),
por nome normalizado (sem acentos, com tolerância a nomes truncados), de modo a
que a pesquisa por `nif` e o grafo de partes funcionem com os mesmos nomes.

A extração é opcional por recolha (`extrair_documentos`, por omissão ligada) e
limitada por `max_documentos` (0 = todos). Uma recolha de 111 éditos com análise
de PDF demora ~4 minutos (1 pedido por édito).

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

### Recolher **tudo** (sem nome)

O nome é obrigatório no formulário (validator do lado do cliente), mas o
**servidor aceita o campo vazio** e devolve a **lista completa** — todos os éditos
publicados, sem filtro. É o que faz `todos=true` (`"nome"` vazio):

| Medida (27/09/2026) | Valor |
|---|---|
| Éditos na lista completa | **26 992** |
| Páginas (10 éditos/página) | **2 700** |
| Ritmo de publicação | ~100 éditos/dia (~10 páginas/dia) |
| Duração da recolha (1,2 s/página) | ~55 min |
| Histórico do portal | ~9 meses (a lista completa começa ≈ no início de 2026) |

Consequência prática: **«todos os últimos 5 anos» = «tudo o que o portal tem»**,
porque a consulta pública **não guarda 5 anos** de éditos. O corte por `meses=60`
só chega a ser atingido nos serviços com histórico antigo (alguns têm éditos de
2025 e anteriores); no resto, a recolha vai até à última página.

`last_page()` (`Pager1$btnLastPage`) salta para a última página e serve para
medir o âmbito do histórico sem percorrer a lista.

> A análise dos PDF deve ficar **desligada** numa recolha desta dimensão: a 1
> pedido por édito, 27 mil documentos seriam mais de 10 horas. Recolha primeiro a
> lista completa (minutos) e depois analise os PDF que interessam
> (`POST /citacoes/runs/{id}/documentos`, com `max_documentos`).

### Recolha **paralela por serviço** (para os ~27 mil éditos)

O portal responde a **~6 s por página** (medido em 27/09/2026): as ~2 700 páginas
da lista completa levariam **mais de 5 horas** numa só sessão. Como cada édito
pertence a **um** serviço/tribunal (`ddlTribunais`, 257 valores) e o filtro por
serviço **aceita o nome vazio**, o trabalho reparte-se por serviços:

- cada **serviço** é pesquisado e paginado numa **sessão própria** (o
  `__VIEWSTATE` é uma cadeia: não se pode paginar em paralelo na mesma sessão);
- `workers` sessões correm em paralelo (`1`–`8`, por omissão **4**) → ~1 h em vez
  de ~5 h; cada serviço é independente, pelo que a falha de um não para os outros;
- **consequência útil**: nos registos em que o portal não mostra o campo
  «Tribunal», o serviço pesquisado **preenche** o tribunal, a sede e a comarca
  judicial (`completar_tribunal`) — sem isto, ~40% dos éditos ficavam sem
  território e o mapa/facetas por tribunal perdiam dados;
- o corte por data aplica-se **dentro de cada serviço** (a lista de cada serviço
  também vem por data descendente).

Dois cuidados que valem para qualquer recolha longa:

1. **Prazo máximo por pedido** (`deadline`, 45 s): o portal já manteve uma página
   a chegar aos pingos durante mais de 10 minutos (o `timeout` do `requests` nunca
   dispara nesse caso), o que deixava a recolha presa. Ao estourar o prazo a
   sessão é fechada e a recolha termina com o que tem.
2. **Progresso parcial em JSON** a cada `partial_every` páginas (por omissão 50):
   o ficheiro `data/citacoes/runs/<run_id>.json` vai sendo escrito durante a
   recolha (com `partial: true`), pelo que um bloqueio a meio não perde o
   trabalho. Qualquer recolha gravada pode ser importada a meio pela secção
   **Execuções** («importar»).


## Ficheiros

| Ficheiro | Papel |
|---|---|
| `collectors/citius_citacoes.py` | `CitacoesEditalClient` (sessão ASP.NET, pesquisa, paginação, documento) + `parse_items` + `analyze_documento`/`extract_pdf_text` + `EditalCitacao` |
| `api/citacoes_service.py` | meta/opções, corte por meses, recolha, extração de documentos, gravação em JSON, importação e listagem de recolhas |
| `api/citacoes_graph.py` | grafo por dimensões (20 dimensões, 7 receitas, métricas `editais`/`mencoes`, valor em euros por nó/aresta) |
| `api/citacoes_map.py` | mapa por `sede`/`comarca`/`tribunal`, com geocodificação **offline** (`api/gleif_geo`, tabelas GeoNames em `data/gleif/geo/`) |
| `api/citacoes_routes.py` | rotas `/citacoes/*` (recolha em segundo plano com progresso, extração de documentos, importação, pesquisa, grafo, mapa, estado) |
| `api/elasticsearch_client.py` | índice `finance_citacoes_edital` (`citacoes_existing_ids`, `index_citacoes_items`, `search_citacoes`, `scan_citacoes`, `citacoes_status`, `get_citacao`, `delete_citacoes_run`) |
| `chat-ui/src/citacoesApi.ts` | cliente TypeScript das rotas |
| `chat-ui/src/pages/CitacoesPage.tsx` | página: **Pesquisa, Grafo, Mapa, Recolha, Execuções, Estado** |
| `chat-ui/src/components/citacoes/citacoesGraph.ts` + `CitacoesGraphPanel.tsx` | adaptação do grafo ao estúdio de grafos (rede/hierárquico/circular/fluxos/treemap/lista) e *drill-down* para a pesquisa |
| `chat-ui/src/components/citacoes/CitacoesMapPanel.tsx` | mapa em mosaicos OpenStreetMap (arrastar/zoom) com círculos por volume, lista de locais e drill-down |
| `_fix_citacoes_runs.py` | manutenção: recalcula a análise dos documentos de uma recolha, preenche `comarca_judicial`/`has_texto` e reindexa; `--apagar <run_id>` remove ficheiros (e, com `--aplicar`, os documentos do índice) |
| `data/citacoes/runs/` | ficheiros JSON das recolhas |

## Rotas

Leitura (pública)

| Rota | Descrição |
|---|---|
| `GET /citacoes/meta` | metadados (fonte, índice, pasta, limites, meses por omissão) |
| `GET /citacoes/options` | serviços/tribunais do portal (cache de 1 h) |
| `GET /citacoes/status` | volumetria e distribuições do índice (inclui PDF analisados, NIF distintos, valor total/médio/máximo, comarcas judiciais, modelos) |
| `GET /citacoes/search` | pesquisa (texto, nome de interveniente, papel, tribunal, tipo, ato, espécie, datas, NIF, modelo, título) com facetas |
| `GET /citacoes/entidades` | **entidades** (intervenientes) agregadas por nome, com éditos, papéis e NIF, e os mesmos filtros |
| `GET /citacoes/graph/dimensions` | dimensões, métricas e receitas do grafo |
| `GET /citacoes/graph` | grafo agregado (`dimension_a`, `dimension_b`, `metric`, filtros, `limit`, `edge_limit`) |
| `GET /citacoes/map` | agregação geográfica (`nivel=sede\|comarca\|tribunal`, filtros) com `points`/`sem_localizacao` |
| `GET /citacoes/runs` | recolhas gravadas em disco (com a contagem no índice) |
| `GET /citacoes/runs/{run_id}` | resumo de uma recolha (`?with_items=true` devolve os itens) |
| `GET /citacoes/documentos/{pub_id}` | texto integral do PDF analisado de um édito |
| `GET /citacoes/jobs` | recolhas em curso e recentes |

Escrita (sessão)

| Rota | Descrição |
|---|---|
| `POST /citacoes/collect` | arranca a recolha em segundo plano (grava JSON; `extrair_documentos` analisa os PDF; `index=true` importa no fim). Com `todos=true` (sem `nome`) recolhe a lista completa |
| `POST /citacoes/jobs/{id}/stop` | pede a paragem (a página em curso termina primeiro) |
| `POST /citacoes/ingest` | importa uma recolha gravada (só o que ainda não existe; `update_existing` reescreve) |
| `POST /citacoes/runs/{run_id}/documentos` | (re)analisa os PDF de uma recolha gravada — volta a pesquisar o portal pelos critérios guardados e casa os éditos pelo `pub_id` (`force` refaz todos, `index` reindexa no fim) |
| `DELETE /citacoes/runs/{run_id}?drop_index=true` | apaga os ficheiros de uma recolha e, opcionalmente, os documentos dessa recolha no índice |

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

- `q` — texto livre (interveniente, referência, processo, tribunal, ato, **e o texto do PDF**);
- `nome` — nome de um **interveniente** (qualquer papel) e `papel` — papel exato
  (`Exequente`, `Executado`, `Réu`, `Credor`, `Agente de Execução (Sol.)`, …);
- `tipo` — `Citação` | `Notificação` | `Anúncio`;
- `tribunal` (texto parcial), `tribunal_comarca`, `comarca_judicial`, `ato`,
  `especie`, `processo`, `referencia`, `citado`, `has_documento`;
- `nif` (do documento), `modelo` (ex.: `547/0.05`), `titulo`, `has_texto` (só
  éditos com PDF analisado) e `with_texto` (devolve também o texto, mais pesado);
- `data_from` / `data_to` (intervalo inclusivo sobre a data de publicação);
- `size` / `from` e facetas (tipo, papel, comarca, comarca judicial, sede,
  tribunal, ato, espécie, modelo, assunto, ano, mês) — e o **valor total/médio**
  das execuções dos resultados.

> Nota: `intervenientes.nome` é um campo `nested`; a pesquisa livre do índice
> junta por isso dois caminhos (campos planos e intervenientes) — sem isso, uma
> pesquisa pelo nome de uma parte devolvia zero resultados.

### Pesquisar **entidades** por nome

`GET /citacoes/entidades` pergunta «quem aparece nos éditos» em vez de «que
éditos existem»: agrega os intervenientes (`nested`) por nome e devolve, por
entidade, **éditos distintos**, papéis exercidos, NIF/NIPC dos documentos e
tribunais. Aceita `q` (nome, com ou sem acentos) mais os mesmos filtros da
pesquisa (`papel`, `tipo`, `tribunal`, `tribunal_comarca`, `comarca_judicial`,
`data_from`/`data_to`, `has_texto`, `min_editais`, `size`).

- `editais` vem de um `reverse_nested` (conta o **documento** e não a entrada do
  interveniente): quem aparece duas vezes no mesmo édito não conta a dobrar.
- **Grafias da mesma designação são agrupadas** por caixa, acentos, pontuação e
  abreviaturas escritas letra a letra («INSTITUTO DA SEGURANÇA SOCIAL - I P» ≡
  «… IP»; «CAIXA ECONÓMICA MONTEPIO GERAL» ≡ «Caixa Económica Montepio Geral»).
  Cada grupo devolve as suas `variants`/`nomes` e nomes que **não** coincidam
  ficam separados — no domínio judicial, ligar de mais é pior do que ligar de
  menos.
- A página filtra os éditos por **todas** as grafias do grupo (a rota de pesquisa
  aceita `nomes`, repetido). É isso que faz a contagem da entidade explicar a
  lista: verificado em `_probe_citacoes_entidades.py` (grupo com 43 éditos → o
  filtro por 3 grafias devolve 43).
- As entidades acompanham os **filtros ativos** (ex.: com `papel=Executado` o
  Montepio aparece com 31 éditos em vez de 43).

Na página (`/citacoes` → *Pesquisa* → cartão **Entidades**): escrever o nome
filtra a lista por debaixo, clicar no nome filtra os éditos, e os botões de papel
e de NIF acrescentam esses filtros; um chip no cabeçalho dos resultados mostra o
filtro por entidade e remove-o.

## Grafo

`GET /citacoes/graph` agrega o índice em **nós** e **arestas** por dimensões
(20: parte ativa/passiva, agente, credor, interveniente, NIF, sede, comarca
judicial, tribunal, juízo, tipo, ato, espécie, processo, papel, modelo, título,
assunto, ano, mês), com a métrica `editais` (documentos distintos) ou `mencoes`
(ocorrências) e o **valor das execuções** acumulado por nó/aresta.

- Percorre o índice com `scan_citacoes` (cursor `search_after`) até 50 000
documentos — sem carregar o texto (é preciso lembrar que `search_after` **não
pode ser uma lista vazia**: daí o `scan=True` no `search_citacoes`);
- redes dirigidas (`parte ativa → citado`) contam a **aresta** uma vez por
  documento (sem isso, `count` ficava a 0 porque só as menções subiam);
- os nomes de empresas são normalizados numa **chave de entidade** (corta no
  primeiro `,`, remove `S.A./Lda./Unipessoal/…`) para juntar o mesmo exequente
  escrito de formas diferentes na lista e no PDF.

As **receitas** (7) pré-configuram perguntas frequentes: quem cita quem, partes
do mesmo processo, agentes por comarca, citados por tribunal, tipo por comarca,
evolução por mês/tipo e modelos por tribunal. Qualquer nó abre a **pesquisa**
filtrada (`NIF`/`nome`/`tribunal_comarca`/`comarca_judicial`/datas/…).

## Mapa

`GET /citacoes/map` agrega por **sede do tribunal**, **comarca judicial** ou
**tribunal** e resolve as coordenadas **offline** — as terras dos serviços
(`Lisboa - Tribunal Judicial da Comarca de Lisboa` → `Lisboa`) são procuradas nas
tabelas do GeoNames (`data/gleif/geo/pt.json`), sem qualquer pedido a serviços de
geocodificação. Devolve `points` (com `lat`, `lon`, `precisao`) e
`sem_localizacao` (ex.: `Não especificado`), além do valor das execuções por
local.

## Limitações conhecidas

- A consulta pública **só pesquisa por nome** (não aceita NIF/NIPC). A ligação aos
  NIF é feita **pelo documento**: o PDF traz `Nome - NIF: …`, que é colado aos
  intervenientes — mas só nos éditos cujo PDF foi analisado.
- Os PDF estão ligados à **sessão** da recolha: a ligação mostrada na UI abre no
  portal do CITIUS e exige sessão válida; a reanálise volta a pesquisar o portal.
- A geocodificação é por **terra da sede** (a lista do portal não dá endereços),
  pelo que locais como `Não especificado` ficam fora do mapa.
- Recolhas grandes (nomes comuns sem corte de meses) podem valer centenas de
  páginas; usar `max_pages`/`max_items` e o corte de meses.
