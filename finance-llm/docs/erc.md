# Portal da Transparência da ERC — entidades, pessoas e órgãos de comunicação social

O módulo **ERC · Portal da Transparência** traz para o IQ OS o registo público
que a **Entidade Reguladora para a Comunicação Social** mantém em
`portaltransparencia.erc.pt`: as **entidades proprietárias de órgãos de
comunicação social** (OCS), as **pessoas** dos seus órgãos sociais, os **OCS
detidos** e a **estrutura de propriedade** (quem detém quem).

Responde a perguntas como «quem são os gerentes e administradores desta
empresa de media», «que OCS detém esta sociedade», «em que empresas tem cargos
esta pessoa» e «quem detém, afinal, este jornal/rádio».

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
├── entidades.jsonl     # um documento por entidade (com pessoas, OCS e estrutura)
├── pessoas.jsonl       # um documento por pessoa regulada (cargos e participações)
├── ocs.jsonl           # um documento por órgão de comunicação social
├── recolhas.jsonl      # histórico: uma entrada por página descarregada
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
- `com_pessoas` / `com_estrutura` / `com_ocs` / `com_financeiro` — ligar ou
  desligar partes (os dados financeiros são o mais lento e vêm desligados);
- `guardar_html` — guardar o HTML de cada página em `raw/`;
- `forcar` — reler a listagem em vez de usar a cache.

```bash
# amostra rápida de 5 entidades, sem guardar HTML
curl -X POST localhost:8000/erc/recolher -H 'Content-Type: application/json' \
  -d '{"limite": 5, "guardar_html": false}'

# recolha completa e indexação no fim
curl -X POST localhost:8000/erc/recolher -H 'Content-Type: application/json' \
  -d '{"indexar": true}'
```

`POST /erc/indexar` indexa o que está em disco, sem ir ao portal.

## Índices do Elasticsearch

| Índice | `_id` | Documento |
| --- | --- | --- |
| `finance_erc_entidades` | `IdEntidade` | Dados gerais, contagens, pessoas dos órgãos sociais (`nested`), OCS (`nested`), detentores e detidas (`nested`) |
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
| `POST` | `/erc/recolher` | Recolhe entidades, pessoas e OCS (segundo plano) |
| `POST` | `/erc/indexar` | Indexa os JSONL nos índices `finance_erc_*` (segundo plano) |
| `GET` | `/erc/jobs` · `/erc/jobs/{id}` | Trabalhos e o progresso de cada um |
| `GET` | `/erc/entidades` | Pesquisa entidades (`q`, `distrito`, `tipo_sociedade`) |
| `GET` | `/erc/entidades/{id}` | Ficha da entidade (gerais, pessoas, OCS, estrutura) |
| `GET` | `/erc/pessoas` | Pesquisa pessoas (`q`, `distrito`, `empresa`) |
| `GET` | `/erc/pessoas/{id}` | Ficha da pessoa (cargos e participações) |
| `GET` | `/erc/ocs` | Pesquisa OCS (`q`, `tipo`, `distrito`, `proprietaria`) |
| `GET` | `/erc/export.csv` | Exporta entidades, pessoas ou OCS (`?tipo=`) |

As pesquisas usam o Elasticsearch quando está disponível e caem nos JSONL em
disco quando não está — a lista e as fichas funcionam sempre.

## Relação com o resto do sistema

- As **pessoas** deste módulo são pessoas do regulador dos media; a ligação às
  fichas do **PessoasIQ** (`finance_people`) faz-se por nome, quando aplicável.
- As **entidades** cruzam-se com o **cadastro de entidades** e com o
  **societário** (`finance_societario`, `finance_entities`) pelo nome e pelo NIF
  quando o portal o publica (não publica NIF nas fichas — só a designação).
