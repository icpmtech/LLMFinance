# Portal da Transparência da ERC — entidades, pessoas e órgãos de comunicação social

O módulo **ERC · Portal da Transparência** traz para o IQ OS o registo público
que a **Entidade Reguladora para a Comunicação Social** mantém em
`portaltransparencia.erc.pt`: as **entidades proprietárias de órgãos de
comunicação social** (OCS), as **pessoas** dos seus órgãos sociais, os **OCS
detidos** e a **estrutura de propriedade** (quem detém quem).

Responde a perguntas como «quem são os gerentes e administradores desta
empresa de media», «que OCS detém esta sociedade», «em que empresas tem cargos
esta pessoa» e «quem detém, afinal, este jornal/rádio». Acrescenta ainda uma
**análise de risco** por entidade — transparência, crédito e uma banda de risco
— calculada só com o que o regulador publica (ver «Análise de risco»).

| Fonte | Onde | O que dá |
| --- | --- | --- |
| Listagem de entidades proprietárias | `/entidades-ocs/?idActividade=all` | **1 440 entidades** com designação, tipo de sociedade, actividade principal e distrito |
| Ficha da entidade | `/entidades-ocs/<slug>/?IdEntidade=<guid>&geral=<secção>` | Dados gerais, **pessoas dos órgãos sociais**, **OCS detidos** |
| Ficha da pessoa | `/pessoas-regulado/?idEntidade=<guid>&geral=<secção>` | Dados gerais, **cargos** e **participações diretas** |
| API de estrutura de capital | `/Umbraco/Api/EstruturaCapitalSocial/*` | Ligações de capital (detentores e detidas) e participações de uma pessoa |
| API financeira | `/Umbraco/Api/CaracterizacaoFinanceira/GetDadosFinanceira` | Activo, passivo, resultados e capital próprio por exercício |

## Onde ficam os ficheiros

```
finance-llm/data/erc/
├── listagem.json       # a listagem do portal (com `cached_at`; TTL de 24 h)
├── entidades.jsonl     # um documento por entidade (pessoas, OCS, estrutura, contas e análise)
├── pessoas.jsonl       # um documento por pessoa regulada (cargos e participações)
├── ocs.jsonl           # um documento por órgão de comunicação social
├── recolhas.jsonl      # histórico: uma entrada por página ou exercício descarregado
└── raw/                # HTML de cada página (re-descarregável; fora do git)
```

A pasta é configurável por `ERC_DATA_DIR` (por omissão, `data/erc`). O HTML em
`raw/` é re-descarregável e fica só em disco; os JSONL são o que fica indexado.

## As secções do portal

Cada ficha (de entidade ou de pessoa) é renderizada **por separador**: o
parâmetro `geral` escolhe a secção e cada pedido devolve a página completa com
uma tabela só.

| Ficha | `geral` | Conteúdo | Como se lê |
| --- | --- | --- | --- |
| Entidade | `geral` | Actividade principal, distrito, contabilidade organizada, tipo de sociedade, detém OCS, capital social | HTML |
| Entidade | `orgs` | Pessoas dos órgãos sociais (pessoa, tipo de órgão, função) | `#orgaosSociaisTable` |
| Entidade | `ocs` | Órgãos de comunicação social detidos (designação, tipo, proprietária, distrito) | `#tabelaEntidadeOcs` |
| Entidade | `estru` | Estrutura de propriedade | API (`GetEmpresasQueDetemEstaEmpresa`) |
| Pessoa | `geral` | Actividade principal, detém OCS, distrito | HTML |
| Pessoa | `orgs` | Empresas onde tem cargos (empresa, tipo de órgão, função) | `#orgaosSociaisTable` |
| Pessoa | `part` | Participações diretas | API (`GetEmpresasQueDetemParticipacao`) |

O coletor lê primeiro a secção `geral` e só pede as restantes se os separadores
existirem na página — evita pedidos a fichas que não os têm.

## Estrutura de propriedade: quem detém quem

A API devolve **conexões** entre dois registos (`record1` e `record2`) com o
papel (`roleid`) de cada lado. O sujeito do pedido fica sempre em `record2` e o
papel **do lado do sujeito** indica o sentido:

- papel em `PAPEIS_DETEM` («Detém diretamente») → a **contraparte detém** o
  sujeito → entra em `detentores`;
- papel em `PAPEIS_DETIDAS` («Diretamente detidas») → a **contraparte é detida**
  pelo sujeito → entra em `detidas`.

As listas de papéis são as do próprio portal (`checkForDetem`/`checkForDetida`,
na secção `geral=estru`). Nas **participações de uma pessoa** não há filtro por
papel: todas as ligações devolvidas são empresas detidas pela pessoa.

> Nota: a tabela «Entidades detidas» do portal filtra pelo papel do lado errado
> e aparece sempre vazia; aqui o sentido é derivado corretamente, pelo que
> `detidas` traz o que a entidade detém (ex.: a Meglo detém a TVI e a Media
> Capital Digital).

## Recolha

`POST /erc/recolher` corre em segundo plano (o progresso vê-se em `GET /erc/jobs`):

1. lê a **listagem** (com cache de 24 h em `listagem.json`);
2. por cada entidade, lê `geral`, `orgs`, `ocs` e a estrutura de capital;
3. regista as **pessoas** referidas e abre-lhes a ficha (`geral`, `orgs`,
   participações);
4. guarda por *upsert* nos JSONL — voltar a correr **não duplica** nem perde o
   já lido.

O portal tem ~1 440 entidades e vários pedidos por ficha, por isso há:

- `limite` — recolher só as primeiras *N* entidades (amostras, execuções faseadas);
- `pausa` — segundos entre pedidos (por omissão 0,4 s; cortesia com o portal);
- `trabalhadores` — pedidos em paralelo (1 por omissão; 3 já reduz a recolha
  completa de horas para uma fração do tempo — o portal é público, não abuse);
- `saltar_existentes` — ignora as entidades já em `entidades.jsonl`, pelo que
  **retomar depois de uma paragem não repete o que já foi lido**;
- `com_pessoas` / `com_estrutura` / `com_ocs` / `com_financeiro` — ligar ou
  desligar partes (os dados financeiros são o mais lento e vêm desligados);
- `guardar_html` — guardar o HTML de cada página em `raw/`;
- `forcar` — reler a listagem em vez de usar a cache.

O que está lido é gravado em lotes (por omissão a cada 20 itens), portanto uma
paragem a meio perde no máximo esse lote.

```bash
# amostra rápida de 5 entidades, sem guardar HTML
curl -X POST localhost:8000/erc/recolher -H 'Content-Type: application/json' \
  -d '{"limite": 5, "guardar_html": false}'

# recolha completa (3 pedidos em paralelo) e indexação no fim
curl -X POST localhost:8000/erc/recolher -H 'Content-Type: application/json' \
  -d '{"trabalhadores": 3, "indexar": true}'

# retomar de onde parou, sem repetir o que já está em disco
curl -X POST localhost:8000/erc/recolher -H 'Content-Type: application/json' \
  -d '{"trabalhadores": 3, "saltar_existentes": true, "indexar": true}'
```

`POST /erc/indexar` indexa o que está em disco, sem ir ao portal. Com
`{"forcar": true}` **recria** os índices antes de indexar — é o que se usa quando
o *mapping* muda, porque o Elasticsearch não deixa alterar o tipo de um campo já
criado (os dados vêm sempre dos JSONL, por isso não se perde nada).

## Dados financeiros

A secção `dafin` («Dados Financeiros») é servida pela API
`CaracterizacaoFinanceira/GetDadosFinanceira` e **só responde a exercício a
exercício**. Pior: a página não publica a lista de exercícios de uma entidade —
o `select` de anos vem vazio e a API devolve `404` sem `anoFinanceiro`. Só há um
caminho: **varrer a janela ano a ano**, com um pedido por ano e por entidade (os
anos sem publicação devolvem vazio, não erro).

Por isso a recolha financeira é um trabalho próprio:

```bash
# últimos 4 exercícios, 8 pedidos em paralelo (o portal satura acima disso)
curl -X POST localhost:8000/erc/financeiro/recolher -H 'Content-Type: application/json' \
  -d '{"trabalhadores": 8, "indexar": true}'

# histórico mais fundo, parando após 3 exercícios vazios seguidos
curl -X POST localhost:8000/erc/financeiro/recolher -H 'Content-Type: application/json' \
  -d '{"ano_inicio": 2015, "vazios_seguidos": 3, "indexar": true}'
```

Parâmetros: `ano_inicio` / `ano_fim` (por omissão, os últimos 4 exercícios até ao
ano anterior ao corrente), `vazios_seguidos` (0 = varrer a janela toda),
`apenas_sem_financeiro` (por omissão `true` — retoma só o que falta),
`trabalhadores` (8; medido: 16 é **mais lento**, o portal limita por IP),
`limite` e `indexar`.

Cada exercício guardado traz activo, passivo, capital próprio, rendimentos,
resultados (antes de custos, operacionais+depreciações e líquidos),
**responsabilidades não inscritas** (garantias e compromissos fora do balanço) e
um sinal de confidencialidade — mais os rácios derivados (`autonomia_financeira`,
`endividamento`, `margem_liquida`, `crescimento_rendimentos`). O crescimento
compara com o exercício **publicado anteriormente**, não com o ano civil, porque
há entidades que falham anos.

Quando a ERC defere uma **exceção de divulgação**, o portal escreve a deliberação
no lugar dos valores («Deliberação ERC/2024/532 - Defere a exceção de divulgação…»).
Esses campos ficam a `null` — nunca se extraem dígitos de texto, que davam valores
absurdos — o texto fica em `nota`, o exercício conta como confidencial e a análise
assinala-o. Como é a entidade que pede a exceção, isso conta para o risco.

O documento da entidade fica também com indicadores de topo
(`n_anos_financeiro`, `ultimo_ano_financeiro`, `ultimo_rendimentos`,
`ultimo_resultados`, `ultimo_autonomia`, `ultimo_endividamento`, …), que é o que
permite ordenar e agregar sem passar por `nested`.

## Análise de risco

`POST /erc/analisar` recalcula a análise de todas as entidades **sem ir à rede** (é
só disco) e `GET /erc/analise` serve o ranking. A análise é determinística e
explicável: cada score devolve os indicadores que o compõem, com os pontos e o
máximo de cada um.

| Score | O que mede | Escala |
| --- | --- | --- |
| **Transparência** | Quanto, com que completude e com que actualidade a entidade publica: contabilidade organizada, existência de contas, nº de exercícios, actualidade do último, campos do balanço preenchidos, OCS declarados, órgãos sociais, estrutura de capital, capital social | 0–100 · `muito_baixa` <25, `baixa` <50, `media` <75, `alta` ≥75 |
| **Crédito** | Só com as contas publicadas: resultado líquido do último exercício, consistência dos resultados, autonomia financeira (capital próprio/activo), endividamento (passivo/activo), tendência dos rendimentos, escala | 0–100 · `A` ≥80, `B` ≥65, `C` ≥50, `D` ≥35, `E` <35, `sem dados` |
| **Risco** | Falta de solidez financeira (défice de crédito, 40) somada à opacidade (défice de transparência, 20), prejuízos no último exercício (10) e repetidos (10), capital próprio quase nulo (10), endividamento crítico (8), confidencialidade pedida (7) e ausência de contas (8–25) | 0–100 (quanto **maior**, pior) · `baixo` ≤24, `moderado` ≤49, `elevado` ≤74, `critico` ≥75 |

Uma entidade que **não publica contas** não tem crédito atribuível (`credito:
null`, nível `sem dados`) — mas o risco sobe, porque a opacidade é ela própria um
risco. Os alertas (`alertas`) e as limitações (`limitacoes`) vão no mesmo
documento, e o campo `cobertura` diz em quantos exercícios a análise se baseia.

O que esta análise **não** é: um rating de crédito. Não inclui incumprimentos,
processos, garantias bancárias, ratings de agências nem verificação independente
das contas — é uma leitura dos dados autodeclarados ao regulador.

## Índices do Elasticsearch

| Índice | `_id` | Documento |
| --- | --- | --- |
| `finance_erc_entidades` | `IdEntidade` | Dados gerais, contagens, pessoas dos órgãos sociais (`nested`), OCS (`nested`), detentores e detidas (`nested`), série financeira (`financeiro`, `nested`), indicadores de topo do último exercício e análise de risco (`analise.risco.banda`, `analise.credito.score`, …) |
| `finance_erc_pessoas` | GUID da pessoa | Dados gerais, cargos (`orgaos`, `nested`) e participações (`participacoes`, `nested`) |
| `finance_erc_ocs` | `<entidade>:<designação>:<tipo>` | Órgão de comunicação social, tipo, proprietária e distrito |
| `finance_erc_recolhas` | `recolha_id` | Histórico: página, `sha256`, bytes, itens e erro |

Os nomes e as actividades são indexados com `world_folding` (minúsculas + sem
acentos), para uma pesquisa sem acentos («comunicacao», «guimaraes») os
encontrar.

## API

| Método | Rota | O que faz |
| --- | --- | --- |
| `GET` | `/erc/meta` | Pastas, volumetria em disco e índices usados |
| `GET` | `/erc/resumo` | Painel: contagens, distritos, tipos de sociedade e funções |
| `GET` | `/erc/listagem` | Entidades anunciadas pelo portal (`?refrescar=true` relê) |
| `GET` | `/erc/recolher` | Recolhe entidades, pessoas e OCS (segundo plano) |
| `POST` | `/erc/financeiro/recolher` | Recolhe os dados financeiros por exercício (segundo plano) |
| `POST` | `/erc/analisar` | Recalcula transparência, crédito e risco (sem rede) |
| `POST` | `/erc/indexar` | Indexa os JSONL nos índices `finance_erc_*` (segundo plano) |
| `GET` | `/erc/jobs` · `/erc/jobs/{id}` | Trabalhos e o progresso de cada um |
| `GET` | `/erc/entidades` | Pesquisa entidades (`q`, `distrito`, `tipo_sociedade`) |
| `GET` | `/erc/entidades/{id}` | Ficha da entidade (gerais, pessoas, OCS, estrutura) |
| `GET` | `/erc/pessoas` | Pesquisa pessoas (`q`, `distrito`, `empresa`) |
| `GET` | `/erc/pessoas/{id}` | Ficha da pessoa (cargos e participações) |
| `GET` | `/erc/ocs` | Pesquisa OCS (`q`, `tipo`, `distrito`, `proprietaria`) |
| `GET` | `/erc/analise` | Ranking de risco/transparência/crédito (`banda`, `nivel_*`, `ordenar`, …) |
| `GET` | `/erc/financeiro` | Painel financeiro: cobertura, totais por exercício e distribuição de risco |
| `GET` | `/erc/export.csv` | Exporta `entidades`, `pessoas`, `ocs`, `analise` ou `financeiro` (`?tipo=`) |

As pesquisas usam o Elasticsearch quando está disponível e caem nos JSONL em
disco quando não está — a lista e as fichas funcionam sempre.

## Produção

O código vai com o deploy incremental (`deploy/kamatera/19-deploy-codigo.ps1`),
que constrói o `dist` do frontend aqui e corre os `Dockerfile.*.incremental` na
VM, sobre a imagem que lá está:

```powershell
cd deploy\kamatera
.\19-deploy-codigo.ps1 -Servico ambos
```

Os índices migram-se com `deploy/kamatera/es/migrar_contratos.ps1 -Indices erc`.
Falta o **disco**: `/erc/resumo`, `/erc/listagem` e as fichas
(`/erc/entidades/{id}`, `/erc/pessoas/{id}`) leem os JSONL de `data/erc`, que não
existem na VM — sem eles o painel mostra zeros e as fichas dão 404, mesmo com os
índices cheios (as pesquisas destes continuam a funcionar, porque caem no
Elasticsearch). `ERC_DATA_DIR` aponta para `/app/data/erc`, que é o volume
`/opt/iqos/servicos/backend/data` montado no `iqos-backend`:

```powershell
$b64 = [Convert]::ToBase64String([IO.File]::ReadAllBytes('data\erc\entidades.jsonl'))
$b64 | docker exec -i iqos-origin-tunnel ssh -i /root/.ssh/id_ed25519 root@45.147.251.188 `
    "tr -d '\r\n' > /tmp/f.b64 ; base64 -d /tmp/f.b64 > /opt/iqos/servicos/backend/data/erc/entidades.jsonl ; rm -f /tmp/f.b64"
```

O `tr -d '\r\n'` é necessário porque o pipeline do PowerShell acrescenta `CR` a
cada linha: o `base64 -d` do coreutils descodifica na mesma, mas termina com
`base64: invalid input` e código de saída 1 — o que aborta qualquer
encadeamento com `&&`. Repetir para `pessoas.jsonl`, `ocs.jsonl`,
`recolhas.jsonl` e `listagem.json` e conferir os bytes com `wc -c`.

## Relação com o resto do sistema

- As **pessoas** deste módulo são pessoas do regulador dos media; a ligação às
  fichas do **PessoasIQ** (`finance_people`) faz-se por nome, quando aplicável.
- As **entidades** cruzam-se com o **cadastro de entidades** e com o
  **societário** (`finance_societario`, `finance_entities`) pelo nome e pelo NIF
  quando o portal o publica (não publica NIF nas fichas — só a designação).
