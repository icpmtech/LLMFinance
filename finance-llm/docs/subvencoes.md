# Subvenções públicas — listagem anual da IGF (Lei n.º 64/2013)

O módulo **Subvenções públicas** traz para o IQ OS a *LISTAGEM DAS SUBVENÇÕES E
OUTROS BENEFÍCIOS PÚBLICOS* que a **IGF** (Inspeção-Geral de Finanças) publica
todos os anos, em `.ods`, ao abrigo do artigo 4.º da **Lei n.º 64/2013, de
27/08**. É a resposta a «quem deu, a quem, quanto, quando e com que fundamento
legal» em Portugal: ~415 mil registos em duas listagens anuais, ~18,9 mil
milhões de euros atribuídos por 931 entidades obrigadas ao reporte a 105 983
beneficiários distintos.

O módulo **lê a pasta de dados por ano**, normaliza cada ficheiro e dá-lhe
pesquisa, painel, fichas e exportação.

## Onde ficam os ficheiros

```
finance-llm/data/subvencoes/
├── 2024/
│   └── lista-subvpublicas2024.ods      # ano na SUBPASTA
├── lista-subvpublicas2025_1.ods        # ano no NOME
├── _normalized/
│   ├── subv-lista-subvpublicas2024.jsonl
│   └── subv-lista-subvpublicas2025-1.jsonl
└── _manifest.json                      # o que já foi lido (sha256, totais, datas)
```

A pasta é configurável por `SUBVENCOES_DATA_DIR`. A pasta interna
`_normalized/` é ignorada na descoberta de ficheiros.

### Como o ano é atribuído

É a parte que o pedido original exigia («lê por ano») e o motivo de haver dois
critérios, porque **nesta pasta convivem os dois casos**:

| Ordem | Origem | Exemplo | `ano_origem` |
| --- | --- | --- | --- |
| 1 | Subpasta numérica | `data/subvencoes/2024/…` | `pasta` |
| 2 | Nome do ficheiro | `lista-subvpublicas2025_1.ods` | `nome` |
| 3 | Folha do `.ods` | `Subv_2025` | `—` (só na leitura) |

O primeiro ano de 4 dígitos no nome vence (`…2025_1` → 2025). Sem nenhum dos
três, o ficheiro fica com `ano: null` e aparece como «sem ano».

## O que o ficheiro traz

Cada `.ods` tem uma folha (`Subv_<ano>`), **duas linhas de cabeçalho** (a
segunda subdivide «FUNDAMENTO LEGAL») e uma linha por apoio concedido. O
cabeçalho está precedido do título e das notas a) a d) — incluindo a nota que
explica a letra «E» nos NIF estrangeiros.

| # | Coluna do ficheiro | Campo normalizado |
| --- | --- | --- |
| 0 | `NIF (EO)` | `nif_entidade` |
| 1 | `ENTIDADE OBRIGADA (EO)` | `entidade` |
| 2 | `NIF (B)` | `nif_beneficiario` (+ `beneficiario_estrangeiro`) |
| 3 | `BENEFICIÁRIO (B)` | `beneficiario` |
| 4 | `MONTANTE TRANSFERIDO OU BENEFÍCIO AUFERIDO (euros)` | `montante` |
| 5 | `DATA DA DECISÃO` | `data_decisao`, `ano_decisao` |
| 6 | `FINALIDADE` | `finalidade` |
| 7 | `TIPO DE ATO` | `tipo_ato` |
| 8 | `N.º` | `numero_ato` |
| 9 | `DATA` (do ato) | `data_ato` |

Campos derivados na normalização:

* `beneficiario_tipo` — deduzido do **prefixo do NIF** (`1`/`2`/`3` pessoa
  singular, `5`/`7` pessoa coletiva, `6` entidade pública, `8` empresário em
  nome individual, `9` outro). É uma **aproximação documentada**: o ficheiro
  não publica o tipo.
* `fundamento_legal` — `"Lei n.º 75"`, a partir do tipo de ato e do número.
* `beneficiario_estrangeiro` — verdadeiro quando o `NIF (B)` traz letras (a
  «E» da nota b); a letra é sinal, não dado, e não entra no NIF.

### Ano da listagem ≠ ano da decisão

Um mesmo apoio aparece em **várias listagens** (a de 2025 repete decisões de
2022 e até de 1978). Por isso:

* o campo `ano` é o da **listagem** (o ficheiro) — `ano_decisao` é o da decisão;
* o `_id` no Elasticsearch é `<ano>:<linha>`, pelo que reindexar o mesmo
  ficheiro **sobrepõe-se** em vez de duplicar.

## Documento indexado (`finance_subvencoes`)

```json
{
  "doc_id": "2025:12",
  "ano": 2025,
  "linha": 12,
  "ficheiro": "lista-subvpublicas2025_1.ods",
  "folha": "Subv_2025",
  "nif_entidade": "500051054",
  "entidade": "MUNICÍPIO DE ALMADA",
  "nif_beneficiario": "510557260",
  "beneficiario": "ACADEMIA SHOWIT - ASS. DE ARTES E ESPETACULOS",
  "beneficiario_tipo": "pessoa_coletiva",
  "beneficiario_estrangeiro": false,
  "montante": 12825.0,
  "data_decisao": "2025-07-21",
  "ano_decisao": 2025,
  "finalidade": "Programa Municipal almada Em Forma 2025, …",
  "tipo_ato": "Lei",
  "numero_ato": "75",
  "data_ato": "2013-09-12",
  "fundamento_legal": "Lei n.º 75",
  "lido_em": "2026-10-09T15:04:22+00:00",
  "ingested_at": "2026-10-09T15:06:01+00:00"
}
```

`entidade`, `beneficiario` e `finalidade` usam o analisador **`world_folding`**
(minúsculas + `asciifolding`), pelo que «municipio de almada» encontra
«MUNICÍPIO DE ALMADA». O analisador está declarado em `INDEX_SETTINGS` — sem
essa declaração o índice nunca é criado (ver «Armadilhas»).

Há ainda `finance_subvencoes_lotes`: **um documento por ficheiro lido** (ano,
caminho, `sha256`, folha, linhas, ignoradas, montante total, primeira/última
decisão, quando foi lido e indexado).

## API (`/subvencoes/*`)

| Método | Rota | O que faz |
| --- | --- | --- |
| `GET` | `/subvencoes/meta` | Pasta, ficheiros por ano (lidos/pendentes), índice e colunas |
| `GET` | `/subvencoes/ficheiros` | Ficheiros encontrados na pasta, com o ano e a sua origem |
| `GET` | `/subvencoes/lotes` | Ficheiros já lidos (JSONL) com totais por lote e por ano |
| `POST` | `/subvencoes/ler` | Lê a pasta **por ano** para JSONL (segundo plano; `anos`, `forcar`) |
| `POST` | `/subvencoes/indexar` | Indexa os JSONL em `finance_subvencoes` (segundo plano) |
| `GET` | `/subvencoes/jobs`, `/subvencoes/jobs/{id}` | Progresso dos trabalhos |
| `GET` | `/subvencoes/resumo` | Painel: por ano, top entidades/beneficiários, série mensal |
| `GET` | `/subvencoes/search` | Pesquisa (ano, NIF, entidade, beneficiário, valor, datas, texto) |
| `GET` | `/subvencoes/amostra/{ano}` | Amostra lida do disco — **funciona sem Elasticsearch** |
| `GET` | `/subvencoes/beneficiario/{nif}` | O que um NIF recebeu (por ano e por entidade) |
| `GET` | `/subvencoes/entidade/{nif}` | O que uma entidade obrigada atribuiu (por beneficiário) |
| `GET` | `/subvencoes/export.csv` | Exportação da pesquisa (delimitador `;`, UTF-8 com BOM) |

Leituras usam `optional_session` (dados públicos); `ler`/`indexar` exigem
sessão. Com o Elasticsearch em baixo, as rotas de leitura devolvem **503** com
mensagem clara — nunca um erro interno.

## Página «Subvenções públicas»

Quatro separadores, em `chat-ui/src/pages/SubvencoesPage.tsx`:

1. **Painel** — montante, beneficiários, entidades e anos; um cartão por ano
   (com atalho para «ver registos» e amostra lida do disco), quem mais atribuiu,
   quem mais recebeu, decisões por mês e tipo de beneficiário.
2. **Pesquisa** — filtros (texto livre, ano, tipo de beneficiário, NIF de
   beneficiário e de entidade, montante mínimo, intervalo de decisão, ordenação),
   indicadores do filtro, lista paginada, painel de detalhe do registo e
   exportação CSV.
3. **Ficha** — por NIF, em duas perspetivas: **recebeu** (o que o NIF recebeu de
   todas as entidades) e **atribuiu** (o que uma entidade deu, por beneficiário).
4. **Ficheiros** — pasta, botões *Ler pasta (por ano)* / *Reler tudo* /
   *Indexar* / *Reindexar*, progresso do trabalho e o detalhe dos lotes lidos.

A ordem dos *hooks* é fixa (todos antes de qualquer `return` condicional) e o
layout é *mobile-first*: listas que empilham, `min-w-0` nos textos truncados e
sem larguras fixas.

## Como ler os dados (primeira utilização)

1. Pôr os `.ods` da IGF em `data/subvencoes` — um ficheiro por ano, ou uma
   subpasta por ano.
2. Na página, separador **Ficheiros** → **Ler pasta (por ano)**.
   Cada ficheiro tem ~200 mil linhas: **~45 s por ficheiro** (leitura em
   *streaming*, sem carregar o `content.xml` para memória).
3. **Indexar** → ~97 s para os dois ficheiros (415 mil documentos, lotes de
   2000).
4. O manifesto é gravado **ficheiro a ficheiro**, pelo que uma leitura
   interrompida não perde o que já foi feito; a leitura seguinte **reaproveita**
   o que tem o mesmo `sha256` (só relê o que mudou).

## Armadilhas encontradas

* **`world_folding` tem de estar em `INDEX_SETTINGS`.** A entrada
  `finance_subvencoes` foi acrescentada a `api/elasticsearch_client.py`; sem
  ela o `indices.create` falha com «analyzer has not been configured» e o índice
  nunca aparece.
* **`app.routes` não serve para listar rotas.** O `include_router` é preguiçoso
  (fica um `_IncludedRouter`): a prova de rotas lê
  `app.openapi()["paths"]`.
* **`truncate` num filho de `flex` sem `min-w-0` estoura o cartão.** O valor
  padrão de `min-width` num item de `flex` é `auto`, pelo que um `<span>` com
  `truncate` (isto é, `white-space: nowrap`) **cresce até à largura do texto** em
  vez de cortar: um nome de entidade com 516 px alargou o cartão das barras para
  668 px e a página ganhou ~340 px de rolagem horizontal a 390 px. A barra de
  rolagem do documento ficava escondida (`overflow-hidden` na moldura), pelo que
  o sintoma visível era só «conteúdo cortado». Correção: `min-w-0 flex-1` no
  rótulo e `shrink-0` no valor. Medir sempre com
  `getElement.scrollWidth - clientWidth` **por elemento**, não só no `main`.
* **Caminho absoluto no `_manifest.json` não sobrevive ao contentor.** A pasta
  `data/subvencoes` é a mesma no anfitrião (`C:\…`) e dentro do contentor
  (`/app/…`). Guardar `jsonl_path` absoluto fez o painel do Docker mostrar
  «0 registos · 0,00 € · 1 por ler» para ficheiros que estavam lidos e
  indexados (414 759 documentos no índice, ao lado). O manifesto guarda agora
  apenas o **nome** do JSONL, resolvido contra `_normalized/` na leitura
  (`jsonl_path(lote)`, com `tem_jsonl(lote)` para o teste de existência).
  `Path("")` **não** serve como «vazio»: resolve para o diretório atual e
  `.exists()` devolveria `True`; a função devolve `None`.
* **Mensagem errada enquanto carrega.** Com `resumo` ainda a `null`, o painel
  dizia «Sem dados indexados. Abra o separador *Ficheiros*…» — verdade só
  depois de uma consulta de agregações sobre 414 mil documentos. Passou a
  distinguir «a carregar…» de «sem dados».
* **Células tapadas por `span`.** O `FUNDAMENTO LEGAL` do cabeçalho ocupa três
  colunas; se as colunas tapadas não forem contadas como vazias, *tipo de ato*,
  *número* e *data* desalinham. O mesmo para `number-columns-repeated`, que
  aparece com valores enormes nas linhas de colunas vazias (limitado a 64).
* **Cabeçalho detetado por dois rótulos.** As notas mencionam «NIF(B)» e
  «beneficiários»: exigir `ENTIDADE OBRIGADA` **e** `MONTANTE` evita apanhar as
  notas como cabeçalho.
* **Montantes com artefactos de vírgula flutuante** (`19706.849999999999`):
  arredondados a 2 casas na normalização.
* **O `tsc -b` pode falhar por ficheiro de outro agente em edição** (visto duas
  vezes durante o build desta página: `DeepSearchPage.tsx` e
  `RaciusPage`/`App.tsx`, de um trabalho paralelo). Não editar o ficheiro
  alheio; repetir depois.

## Testes

* `tests/test_subvencoes.py` — 40 verificações sem rede nem Elasticsearch:
  deteção de ano (subpasta/nome/folha), cabeçalho em duas linhas, `span` e
  colunas repetidas, montantes e datas, NIF estrangeiro, tipo de beneficiário,
  leitura e reaproveitamento por `sha256`, **portabilidade do manifesto**
  (nome relativo, resolução em `_normalized/`, `None` quando não há JSONL),
  manifesto, *preview* e degradação limpa quando o Elasticsearch não está
  disponível.
* `_probe_subvencoes_asgi.py` — 41 verificações das 13 rotas em processo
  (`TestClient` sem `lifespan`), incluindo validação de parâmetros (422) e a
  amostra lida do disco, contra os ficheiros reais.
* `_probe_subvencoes_ingest.py` — lê a pasta e indexa de verdade (mede tempos).
* `_probe_subvencoes_queries.py` — valida painel, pesquisa sem acentos, filtros
  de valor e fichas.
* `_qa_subvencoes_browser.mjs` — percorre os quatro separadores num browser a
  sério e mede o DOM (KPIs, resultado por filtro, páginas, fichas, lotes) em
  1280×800 e 390×844.
* `_qa_subvencoes_overflow.mjs` — lista os elementos com
  `scrollWidth - clientWidth > 2` a 390 px (foi o que encontrou as barras a
  668 px).

## Resultado da leitura dos ficheiros de exemplo

| Ficheiro | Ano | Folha | Registos | Montante | Decisões |
| --- | --- | --- | --- | --- | --- |
| `2024/lista-subvpublicas2024.ods` | 2024 (pasta) | `Subv_2024` | 202 248 | 8 124 031 975,84 € | 1978-12-01 a 2024-12-31 |
| `lista-subvpublicas2025_1.ods` | 2025 (nome) | `Subv_2025` | 212 511 | 10 817 858 321,30 € | 1978-07-05 a 2025-12-31 |
| **Total** | | | **414 759** | **18 941 890 297,14 €** | |

Nenhuma linha de dados foi ignorada nos dois ficheiros (0 ignoradas).
