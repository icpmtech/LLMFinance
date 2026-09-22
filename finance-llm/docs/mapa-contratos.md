# Mapa de contratos — Portugal e Espanha

Página do **IQ OS** que coloca os contratos públicos dos dois países no mapa
(`/contracts/map`, app «Mapa de Contratos»). Junta os dois índices já existentes,
`contratos` (portal base) e `contratos_es` (PLACSP), numa única leitura geográfica.

## O problema da geografia

Os contratos publicados **não trazem coordenadas**: trazem a divisão administrativa.
Cada país expõe essa divisão num campo diferente, com coberturas muito diferentes:

| País | Campo | Geografia | Cobertura |
| --- | --- | --- | --- |
| Portugal | `localExecucao` («Portugal, Lisboa, Cascais») | **Distrito** (18 + Açores + Madeira) | 2,05 M / 2,25 M (91%) |
| Portugal | `NUTs` («PT11A - Área Metropolitana do Porto») | NUTS III | 309 mil / 2,25 M (14%) |
| Espanha | `nuts` («ES300») | **Província** (NUTS 3) | ~4,0 M / 4,05 M (99,8%) |

Por isso o mapa agrega Portugal por **distrito de execução** (não por NUTS: só existiria
em 14% dos contratos) e Espanha por **província**. Nenhuma das duas é inventada: o que
não tem geografia utilizável é apresentado à parte («Sem localização»), nunca colocado
num sítio plausível.

## Endpoint

`GET /contracts/analytics/iberia-map?ano=<int>&pais=all|pt|es` (implementado em
`api/elasticsearch_client.py::get_contracts_iberia_map`):

- Portugal: `terms` em `localExecucao` (agrupado em Python pelo segundo segmento) com
  `sum(precoContratual)`; `Ano` filtra o ano.
- Espanha: `terms` em `nuts` com `_contratos_es_value_source("valor_adjudicado")`
  (valor adjudicado, com queda para `valor_base`); `ano` filtra o ano.
- Devolve `countries`, `regions` (com `level`), `unspecified` (por país),
  `other_locations` (contratos espanhóis executados fora do país) e `warnings`.

Nomes de distrito que o portal escreve de forma irregular são normalizados
(«Braganca» → «Bragança»), usando `_PT_DISTRICT_BY_KEY`. Valores que não são distritos
(«Portugal Continental», «Distrito não determinado», «Consulado situados no estrangeiro»)
ficam como região própria e a página lista-os em «Sem posição no mapa».

## Pesquisa

Há duas pesquisas, com a mesma semântica (todos os termos exigidos):

- **No mapa** (`?q=`, `?entidade=`, `?cpv=`): re-agrega os contratos dos dois países.
  Sugere regiões (salto no mapa, tabela local), entidades e CPV (autocomplete dos dois
  índices). Exemplo: «Metropolitano de Lisboa» → 2 967 contratos concentrados em Lisboa.
- **Na janela da região** (`/contracts/region-detail?q=` e `?cpv=`): filtra métricas,
  entidades e contratos **do mesmo conjunto**. Um valor só com dígitos (4 a 8) é
  tratado como CPV. Exemplo: Bragança + «escola» → 3 336 contratos, 111 entidades
  adjudicantes (agrupamentos de escolas) e 544 empresas.

A pesquisa livre das páginas de contratos usa `best_fields` **sem** mínimo de termos,
pelo que três palavras devolvem milhões de resultados (basta o «de»). Num mapa isso
acenderia o país inteiro, por isso o mapa e a ficha de região usam
`_iberia_text_query` (`operator: and`).

## Abrir as fichas das entidades

Nas listas **Quem adjudica** e **Empresas adjudicatárias** da janela da região cada linha
abre a entidade (e as linhas de Portugal têm ainda um ícone para a lista completa de
contratos):

- **Portugal** — dossiê da entidade (`company-detail:<NIF>`), porque os contratos trazem o
  NIF de adjudicantes e adjudicatárias (`adjudicantes.parsed.nif`); o segundo ícone abre
  `entity-contracts:<NIF>` (todos os contratos da entidade).
- **Espanha** — a app **Contratos Espanha** filtrada pelo órgão (`organo`) ou pela empresa
  (`adjudicatario`), que é o caminho que a Pesquisa total e a Empresas Global já usavam
  (o PLACSP não tem dossiê de entidade). Para isso a agregação passou a agrupar por
  **identificador** (`organo_id` / `adjudicatario_nif`, com o nome em `top_hits`) em vez de
  pelo nome: um órgão é uma entidade, mesmo que o nome apareça com variantes.

Ao deixar um pedido à app de Contratos Espanha (`writeContratosEsEntry`) é disparado o
evento `finance-llm-contratos-es-entry`; a página, se **já estiver aberta** numa janela,
aplica os filtros e pesquisa sem precisar de remontar (antes o pedido só era lido no
arranque, pelo que abrir uma segunda entidade não mudava nada).

## Ficha de região (menu de contexto)

Botão direito sobre um círculo abre um menu; «Abrir janela · contratos, entidades e
métricas» abre `region-detail:<pais>:<código>` (janela própria no modo janelas; vista
`region-detail` com rota `/contracts/region/<pais>/<código>` no modo página, via
`openRegionDetail` no `App`). O backend `get_contract_region_detail` faz **uma só
pesquisa por país** — métricas (ano, CPV, procedimento, tipo, escalões), ranking de
adjudicantes e adjudicatárias (por NIF, com nome e anos) e os maiores contratos
(`top_hits`) — para que os números e a lista venham sempre do mesmo conjunto.
No menu de fundo há ainda reenquadrar, ver as ilhas e limpar filtros/seleção.

## Filtro por distrito na pesquisa

`_region_filter` passou a aceitar **nome de distrito** além de NUTS:

- `"PT11A - Área Metropolitana do Porto"` → `term` em `NUTs` (comportamento antigo);
- `"PT11A"` → `wildcard` em `NUTs` (comportamento antigo);
- `"Lisboa"` (nome de distrito, com ou sem acentos) → `term`/`prefix` em `localExecucao`
  (`Portugal, Lisboa` e `Portugal, Lisboa, *`), para não colidir com distritos cujo nome
  é prefixo de outro (Braga/Bragança).

Com isto `POST /contracts/search` com `region: "Lisboa"` devolve os contratos do distrito,
que é o que o mapa usa no *drill-down* (o mesmo que o Investigador já tentava fazer com
`district`). Do lado espanhol o *drill-down* usa `POST /contracts-es/search` com `nuts`.

## Frontend

- `chat-ui/src/components/geo/iberia.ts` — tabela de geografia: 20 distritos PT e 59
  províncias ES (capital de distrito / de província), mais NUTS 2 e NUTS 1 espanholas
  como aproximação (círculo tracejado). `resolveIberiaRegion()`, `isOffshoreRegion()`,
  `allIberiaRegions()` e `foldIberiaText()` (sugestões «ir para» e comparação sem acentos).
- `chat-ui/src/contractsMapApi.ts` — cliente tipado do agregado do mapa e da ficha de região.
- `chat-ui/src/pages/ContractsMapPage.tsx` — mapa OpenStreetMap (projeção Mercator de
  `components/graph/geo.ts`), filtros (país, ano, métrica valor/contratos), pesquisa com
  sugestões, bolhas por região dimensionadas por √métrica, menu de contexto (botão direito),
  painel com totais por país, ranking, ficha da região escolhida e os seus maiores contratos,
  regiões insulares e notas de cobertura.
- `chat-ui/src/pages/RegionDetailWindow.tsx` — ficha da região (`region-detail:<pais>:<código>`):
  KPIs, quem adjudica, empresas adjudicatárias, por ano, top CPV, procedimento, tipo,
  escalões, maiores contratos e pesquisa própria.
- `dock.ts` (app `contracts-map`), `App.tsx` (vistas, rotas `/contracts/map` e
  `/contracts/region/<pais>/<código>`, moldura de ecrã inteiro como o Chat/Hermes),
  `api/main.py` (rotas SPA `/contracts/map` e API `/contracts/region-detail`).


## Armadilhas

- A rota SPA `/contracts/map` tem de ser registada **antes** de `GET /contracts/{idcontrato}`,
  senão o *deep link* devolve o JSON de «contrato não encontrado».
- O endpoint é lento a frio (16 s na primeira chamada: `terms` de 600 buckets sobre 4 M
  documentos + script de valor). A quente fica em ~0,3 s; a página mostra «A agregar…».
- Açores, Madeira, Canárias, Ceuta e Melilla não cabem no enquadramento da Península:
  são listados à parte e o botão foca o mapa neles (`isOffshoreRegion`).
- Correção adjacente: `export_contracts_to_excel` e `export_contracts_to_pdf` chamavam
  `_build_contract_query` com argumentos posicionais desalinhados (o CPV caía em `region`,
  o preço mínimo em `cpv_code`…), pelo que os filtros de CPV/valor/data das exportações
  não funcionavam. Passaram a usar argumentos por nome.

## Validação

- `python -m pytest tests -q` → 45 passed, 2 skipped.
- `npm run build` sem erros.
- Verificado no browser (`/contracts/map`): 90 bolhas na Península a nível 6, seleção de
  Lisboa (531 155 contratos · 52,8 mil M € · 33,7% do país) com os maiores contratos do
  distrito, e de Madrid (Espanha · Província · 417 033 contratos · 201,7 mil M €) com as
  cinco fragatas F-110 à cabeça. Sem *scroll* de página e sem sobreposição dos painéis.
- Pesquisa: «Hospital de Cascais» → 225 contratos; «Metropolitano de Lisboa» → 2 967
  (Lisboa 2 785); CPV 45 em Espanha → 292 983.
- Menu de contexto e janela da região: botão direito em Bragança → janela com 28 349
  contratos, 629 adjudicantes e 4 590 adjudicatárias; com a pesquisa «escola» → 3 336
  contratos e os agrupamentos de escolas no topo; «Focar no mapa», reenquadrar, ver
  ilhas e `Esc` a fechar o menu também verificados.

