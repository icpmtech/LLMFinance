# Governo — nomeações e composição

Recolha das nomeações para os gabinetes dos membros do Governo e da composição
do Governo a uma data, a partir do Portal do Governo (`portugal.gov.pt`).

O coletor usa o **motor de recolha do IQ OS** (`api.scraper_service`) para
descarregar as páginas: `http` para as páginas das áreas (HTML do servidor) e
`dynamic` para a composição (a lista de membros é renderizada no browser).

## Fontes

| Fonte | URL | O que traz |
| --- | --- | --- |
| Nomeações (índice) | `/gc24/governo/nomeacoes` | As 18 áreas de governo e a página de cada uma |
| Nomeações (área) | `/pt/gc24/governo/nomeacoes/<área>` | Uma tabela por membro do Governo: função, nome, rendimento bruto/líquido, data de nomeação e publicação em DRE |
| Composição | `/gc24/governo/composicao?gc_timeline=AAAA-MM-DD` | Primeiro-Ministro, ministros e secretários de Estado em funções na data indicada |

## Utilização

```powershell
# recolha completa (todas as áreas, composição de 2025-06-05, JSON + Elasticsearch)
c:\LLMFinance\.venv\Scripts\python.exe -m collectors.governo

# só ficheiros, sem Elasticsearch
c:\LLMFinance\.venv\Scripts\python.exe -m collectors.governo --no-elastic

# uma ou mais áreas, sem composição
c:\LLMFinance\.venv\Scripts\python.exe -m collectors.governo --areas financas,saude --no-composicao

# outra data da composição
c:\LLMFinance\.venv\Scripts\python.exe -m collectors.governo --timeline 2025-06-05
```

| Opção | Efeito |
| --- | --- |
| `--timeline` | Data da composição (`aaaa-mm-dd`, omissão `2025-06-05`) |
| `--areas` | Áreas a recolher (lista separada por vírgulas; vazio = todas) |
| `--no-composicao` | Não recolher a composição |
| `--no-dre` | Não enriquecer as nomeações com o detalhe do DRE |
| `--no-perfis` | Não enriquecer os membros com a biografia oficial |
| `--delay` | Pausa entre páginas de áreas (omissão `0.5` s) |
| `--dre-delay` | Pausa entre pedidos ao DRE (omissão `0.25` s) |
| `--dre-limit` | Máximo de despachos a enriquecer (útil para testar) |
| `--perfil-delay` | Pausa entre perfis oficiais (omissão `0.3` s) |
| `--out` | Ficheiro JSON de saída (omissão `data/governo/governo_nomeacoes.json`) |
| `--no-elastic` | Não indexar no Elasticsearch |
| `--no-scraped` | Indexar só nos índices dedicados, não em `finance_scraped` |

## Enriquecimento

### Despachos do Diário da República

Cada nomeação tem uma ligação «Despacho» para o DRE. O coletor lê o detalhe
pela API do portal (`DataActionGetAllConteudoDetalheData`) e acrescenta:

`dre_id`, `dre_titulo`, `dre_numero`, `dre_publicacao`, `dre_sumario`,
`dre_texto` (texto integral), `dre_data_publicacao`, `dre_emissor`,
`dre_serie`, `dre_pagina`, `dre_pdf_url`, `dre_diario_pdf_url` e `dre_tipo`.

O texto integral é também indexado no campo `text` de `finance_scraped`, pelo
que a pesquisa do módulo encontra o conteúdo do Despacho.

### Perfis oficiais

A página de cada membro publica a biografia no componente `OfficialProfile`.
O coletor acrescenta `nome_oficial`, `cargo_oficial`, `area_nome`, `biografia`,
`foto_biografia`, `perfil_inicio` e `perfil_fim`. A biografia é indexada no
campo `text` de `finance_scraped`.

## Saídas

- `data/governo/governo_nomeacoes.json` — payload completo: `areas`,
  `ministerios`, `membros`, `nomeacoes`, `fontes` e `stats`.
- `data/governo/governo_nomeacoes.jsonl` — uma nomeação por linha.
- `data/governo/governo_composicao.json` — os membros da composição.

## Índices Elasticsearch

| Índice | Documento | Chave |
| --- | --- | --- |
| `finance_governo_nomeacoes` | Uma nomeação | `item_id` (`governo-nomeacoes:<sha1>`) |
| `finance_governo_composicao` | Um membro do Governo | `item_id` (`governo-composicao:<sha1>`) |
| `finance_governo_ministerios` | Um ministério (titular, secretários e totais) | `item_id` (`governo-ministerios:<sha1>`) |
| `finance_scraped` | Os mesmos registos, para a pesquisa do módulo de recolha | `item_id` |

Os `item_id` são determinísticos: repetir a recolha **atualiza** os documentos
conhecidos em vez de os duplicar.

### Campos principais

Nomeações: `area`, `area_slug`, `membro`, `funcao`, `nome`,
`rendimento_bruto_eur`, `rendimento_liquido_eur`, `data_nomeacao`, `dre_url`,
`encargos_servico_origem` (a nota «(1)» da página) e os campos `dre_*` do
detalhe do Despacho.

Composição: `grupo` (`Primeiro-Ministro`, `Ministros`, `Secretários de Estado`),
`nome`, `cargo`, `area_slug`, `periodo_inicio`, `periodo_fim`,
`secretarios_count` e os campos do perfil oficial (`biografia`,
`foto_biografia`, `cargo_oficial`, `area_nome`, …).

Ministérios: `area`, `area_slug`, `tipo`, `titular`, `cargo`,
`secretarios_count`, `nomeacoes_count`, `url` e a lista `membros` (titular e
secretários de Estado). O Primeiro-Ministro entra como `tipo`
`Primeiro-Ministro`; os restantes 17 como `Ministério`. O portal usa
`ministro-adjunto-e-da-coesao-territorial` na composição e
`coesao-territorial` nas nomeações — o coletor normaliza os dois para a mesma
chave.

## Fichas, remunerações e grafo de relações

O módulo expõe os dados recolhidos como ontologia navegável — `api/governo_service.py`
constrói as fichas e os grafos, `api/governo_routes.py` serve as rotas e o
frontend (`chat-ui/src/pages/GovernoPage.tsx` e `GovernoFichaPage.tsx`) desenha-os
com o `GraphCanvas` dos restantes grafos do IQ OS.

| Rota | Devolve |
| --- | --- |
| `GET /governo/overview` | Totais, 18 pastas, 59 membros e o grafo geral |
| `GET /governo/graph` | Só o grafo ministério → membro → gabinete |
| `GET /governo/membros?q=&area=&size=&offset=` | Lista/pesquisa de membros |
| `GET /governo/ficha/{item_id}` | Ficha do membro: detalhe, remunerações, relações e grafo |
| `GET /governo/pessoa/{nif}` | Ficha de uma pessoa de entidade, com a ligação ao Governo |
| `GET /governo/pesquisa?q=` | Membros do Governo e pessoas com o mesmo nome |

Páginas da interface: `/governo` (grafo e lista), `/governo/pasta/<slug>` (pasta
escolhida), `/governo/ficha/<item_id>` e `/governo/pessoa/<nif>`.

**Remunerações.** A ficha de um membro agrega as nomeações do **seu** gabinete —
as linhas da área cujo `membro` («Gabinete da Ministra da Cultura») contém o
`cargo` da composição — e mostra o total, a média, o mínimo, o máximo, a
distribuição por função e a tabela de despachos com bruto, líquido e ligação ao
Diário da República.

**Relações.** A ficha liga o membro ao ministério (titular/secretário), ao
gabinete, aos despachos e — quando o nome coincide com uma pessoa indexada em
`finance_people` — à ficha dessa pessoa, com os cargos e as empresas dela.

**Grafo.** Cada nó tem `type` (`ministerio`, `membro`, `gabinete`, `nomeacao`,
`pessoa`, `empresa`) e cada aresta tem `label`/`role`; o `meta` segue o formato
`StudioGraph`, para o `GraphCanvas` o desenhar sem conversão. O grafo geral tem
95 nós e 136 relações (18 ministérios + 18 gabinetes + 59 membros); a ficha de um
membro desenha até 60 nomeações, para o layout continuar legível.

**Pesquisa.** Os documentos `governo-*` de `finance_scraped` levam `open` para o
cartão da pesquisa abrir a ficha: `governo-composicao` abre
`/governo/ficha/<item_id>` e os restantes (`governo-ministerios`,
`governo-nomeacoes`) abrem `/governo/pasta/<area_slug>`.

## Notas de manutenção

- A página do índice de nomeações e a da composição são renderizadas no browser.
  O coletor espera por `a.navigation-link[href*="/governo/nomeacoes/"]` e por
  `.search-composite-group .govinfo`, respetivamente; se o portal mudar as
  classes, é aí que se ajusta.
- As tabelas das áreas têm sempre seis colunas; a última coluna («Publicação em
  DRE») traz uma ligação para o Diário da República.
- Linhas exatamente repetidas na mesma página são ignoradas (o portal publica
  por vezes a mesma nomeação em dois blocos).
