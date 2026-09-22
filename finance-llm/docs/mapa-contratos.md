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
  como aproximação (círculo tracejado). `resolveIberiaRegion()` e `isOffshoreRegion()`.
- `chat-ui/src/contractsMapApi.ts` — cliente tipado do endpoint.
- `chat-ui/src/pages/ContractsMapPage.tsx` — mapa OpenStreetMap (projeção Mercator de
  `components/graph/geo.ts`), filtros (país, ano, métrica valor/contratos), bolhas por
  região dimensionadas por √métrica, painel com totais por país, ranking, ficha da região
  escolhida e os seus maiores contratos, regiões insulares e notas de cobertura.
- `dock.ts` (app `contracts-map`), `App.tsx` (vista, rota `/contracts/map`, moldura de
  ecrã inteiro como o Chat/Hermes), `api/main.py` (rota SPA `/contracts/map`).

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
