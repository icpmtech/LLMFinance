# GLEIF / LEI — registos *Legal Entity Identifier* do Golden Copy

O módulo **GLEIF / LEI** traz para o IQ OS os registos **LEI** (*Legal Entity
Identifier*) publicados pelo **GLEIF** — o identificador global que responde a
«quem é quem» no sistema financeiro: 3,4 milhões de entidades em todo o mundo,
com nome legal, endereço da sede, jurisdição, forma jurídica, estado e datas do
registo, e identificadores associados (BIC, MIC, OCID, QCC, S&P Global).

Os dados vivem em **dois sítios**, para que o módulo funcione mesmo com o
Elasticsearch em baixo:

| Onde | O quê |
| --- | --- |
| `data/gleif/lei.jsonl` | A **golden copy local**: um documento normalizado por linha, inspecionável e exportável. |
| `finance_gleif_lei` (Elasticsearch) | O **índice de pesquisa**: n-gramas no nome legal (pesquisa incremental), facetas e agregações (a base do mapa). |

## Origens dos dados (`POST /gleif/ingest`)

| `source` | O que faz | Quando usar |
| --- | --- | --- |
| `api` | Percorre a **API oficial** (`api.gleif.org/api/v1/lei-records`) por país da sede legal. | Cargas pequenas/médias. **Limite real: 10 000 resultados por consulta** (`page[number] * page[size] <= 10000` → 400 «Deep page-based pagination is not supported»). |
| `golden-copy` | Lê um **ficheiro Golden Copy local** (ZIP do LEI-CDF com CSV/XML, `.csv`, `.xml`, `.json`, `.jsonl`). | Cargas grandes (país inteiro) a partir de um ficheiro já descarregado. |
| `golden-copy-download` | Descarrega o ficheiro mais recente de `leidata.gleif.org` e importa-o. | Quando não há ficheiro local. O ZIP LEI2 tem ~542 MB e contém **um XML de ~8,4 GB**. |
| `file` | (Re)indexa a golden copy local (`data/gleif/lei.jsonl`) sem voltar a ler a origem. | Depois de esvaziar o índice ou de alterar o mapeamento. |

O ficheiro publicado pelo GLEIF é um **ficheiro concatenado por LOU** (não por
país) e usa o *namespace* `lei:` — as notas de desempenho estão no fim.

## Documento normalizado

```json
{
  "lei": "2138004R6N2CRMRIOD60",
  "legal_name": "GALP POWER, S.A.",
  "legal_name_folded": "galp power, s.a.",
  "other_names": [],
  "country": "PT",
  "region": "PT-11",
  "region_name": "Lisboa",
  "city": "LISBOA",
  "postal_code": "1000-000",
  "address_lines": ["RUA TOMÁS DA FONSECA, TORRE C"],
  "jurisdiction": "PT",
  "category": "GENERAL",
  "legal_form": "DFE5",
  "status": "ACTIVE",
  "registration_status": "ISSUED",
  "corroboration_level": "FULLY_CORROBORATED",
  "managing_lou": "213800WAVVOPS85N2205",
  "registered_as": "503923515",
  "registered_at": "RA000487",
  "initial_registration_date": "2014-02-03T00:00:00Z",
  "last_update_date": "2026-09-23T00:00:00Z",
  "next_renewal_date": "2027-02-03T00:00:00Z",
  "bic": null, "mic": null, "ocid": null, "qcc": null,
  "lat": 38.7167, "lon": -9.1333,
  "location": [-9.1333, 38.7167],
  "geo_precision": "postal",
  "source": "golden-copy",
  "ingested_at": "2026-09-24T20:41:12+00:00"
}
```

Os quatro últimos campos são acrescentados na ingestão pela geocodificação da
sede legal (ver «Geocodificação das sedes legais»): `location` é um `geo_point`
na ordem do GeoJSON (**longitude, latitude**), sem o qual o nível «Empresas» do
mapa não tem onde desenhar o círculo.

O `_id` do documento no Elasticsearch é o próprio **LEI** — o que torna a
ingestão idempotente e a ficha uma leitura direta por chave.

### Esquema do LEI-CDF (XML) vs API

O XML do ficheiro Golden Copy **não** usa os mesmos nomes de campo que a API do
GLEIF, e o mapeamento é feito por caminho de elementos (não por nome solto),
porque há blocos com nomes repetidos (`City` na sede legal **e** na sede
operacional):

| Na API (`attributes`) | No XML (LEI-CDF 3.1) |
| --- | --- |
| `entity.legalName.name` | `Entity/LegalName` |
| `entity.legalAddress.*` | `Entity/LegalAddress` (`FirstAddressLine`, `AdditionalAddressLine`, `City`, `Region`, `Country`, `PostalCode`) |
| `entity.headquartersAddress.*` | `Entity/HeadquartersAddress` |
| `entity.legalForm.id` | `Entity/LegalForm/EntityLegalFormCode` |
| `entity.legalForm.other` | `Entity/LegalForm/OtherLegalForm` |
| `entity.registeredAt.id` | `Entity/RegistrationAuthority/RegistrationAuthorityID` |
| `entity.registeredAs` | `Entity/RegistrationAuthority/RegistrationAuthorityEntityID` |
| `registration.corroborationLevel` | `Registration/ValidationSources` |
| `registration.validatedAs` | `Registration/ValidationAuthority/ValidationAuthorityEntityID` |

Ler o XML por um dicionário achatado produzia dois erros silenciosos: a cidade
da sede operacional ficava com o NIF da autoridade de registo e o nível de
corroboração (que no XML se chama `ValidationSources`) ficava sempre vazio.

## API (`/gleif/*`)

Leitura (pública):

| Rota | O que devolve |
| --- | --- |
| `GET /gleif/meta` | Metadados: índice, ficheiro, origens, facetas e os distritos de Portugal. |
| `GET /gleif/status` | Volumetria (índice + ficheiro), distribuições por faceta e série temporal por ano de registo. |
| `GET /gleif/search` | Pesquisa por nome/LEI/NIF de registo/BIC/cidade, com filtros e facetas. |
| `GET /gleif/suggest` | Sugestões para a caixa de pesquisa. |
| `GET /gleif/records/{lei}` | Ficha completa de um LEI. |
| `GET /gleif/map?level=country\|region\|grid` | Agregado por país/região (contagem, ativos, nº de cidades) ou por **célula geográfica da sede legal** (`grid`, com `precision` de 5 a 7 e `size` até 5000) — a base do mapa. |
| `GET /gleif/export.csv` | Exportação da golden copy local em CSV. |
| `GET /gleif/jobs`, `GET /gleif/jobs/{id}` | Ingestões em curso e recentes. |

Escrita (exige sessão): `POST /gleif/ingest` e `DELETE /gleif/index`.

A ficha vive em `/gleif/records/{lei}` (e **não** em `/gleif/{lei}`) para não
competir com as páginas da SPA `/gleif/mapa` e `/gleif/ingestao`.

## Aplicação (`/gleif`)

Três ecrãs no mesmo módulo:

- **Pesquisa** (`/gleif`) — caixa única no estilo da *Pesquisa total*
  (nome legal, LEI, NIF de registo, BIC ou cidade), com sugestões enquanto se
  escreve, facetas (país, região, estado, categoria, forma jurídica, nível de
  corroboração e LOU emissor), ordenação, paginação e a ficha completa do LEI
  (com atalho para a ficha oficial no `search.gleif.org`);
- **Mapa** (`/gleif/mapa`) — os registos agregados em **círculos sobre tiles do
  OpenStreetMap**, em três níveis: **Empresas** (cada empresa na sua sede legal),
  **Regiões** (distritos de Portugal e comunidades/províncias de Espanha) e
  **Países**, com lista ordenada, destaque e menu de contexto (botão direito);
- **Ingestão** (`/gleif/ingestao`) — recolha/indexação, acompanhamento das
  tarefas, exportação CSV e esvaziamento do índice.

### Como o mapa é desenhado

Os registos LEI não têm coordenadas: o que existe é o **país** e a **região**
(ISO 3166-2) da sede legal. O mapa resolve esses códigos para um centroide
(`chat-ui/src/components/geo/world.ts`):

- **país** — tabela completa de 240 centroides (`countries.ts`, gerada por
  `_gen_countries_ts.py` a partir da lista pública *average-latitude-longitude-countries*);
- **região** — 20 distritos/regiões autónomas de Portugal e 70
  comunidades/províncias de Espanha.

Uma região sem centroide conhecido **não** é colocada numa posição inventada: cai
no centroide do país e o círculo sai **tracejado** (com o aviso «posição
aproximada»), tal como no mapa dos contratos. O raio do círculo é proporcional à
raiz quadrada da contagem (a área representa o volume).

O nível **Empresas** não usa centroides: coloca cada empresa no ponto da sua
**sede legal** (`Entity.LegalAddress`), obtido a partir do código postal e da
localidade (ver abaixo).

### Geocodificação das sedes legais

O GLEIF dá o endereço completo da sede legal (linhas de rua, código postal,
localidade, região e país), mas **não** dá coordenadas. A conversão é feita
**offline**, a partir dos ficheiros livres da **GeoNames**, porque uma geocodificação
por serviço externo (Nominatim: 1 pedido/s) seria impossível para 212 mil registos:

| Peça | Origem | Resultado |
| --- | --- | --- |
| Códigos postais | `download.geonames.org/export/zip/{CC}.zip` | `pt.json` (198 522 códigos) · `es.json` (11 150) |
| Localidades | `download.geonames.org/export/dump/{CC}.zip` | `pt.json` (27 775) · `es.json` (75 648) |

`_gleif_geo_build.py PT ES` constrói as tabelas em `data/gleif/geo/<cc>.json`
(10 MB no total, ignoradas pelo git). `api/gleif_geo.py` resolve cada documento:

1. **código postal exato** (`2680-102`) → precisão `postal`;
2. base de 4 dígitos (`2680`) e depois `2680-000` (Portugal) → `postal`;
3. **localidade** dobrada (sem acentos, minúsculas) → `city`;
4. nada disto → o registo fica **sem ponto** (`geo_precision` ausente).

A resolução corre **uma vez, na ingestão** (`gleif_geo.enrich`), e grava no
documento `lat`, `lon`, `location` (`geo_point`, ordem `[lon, lat]`) e
`geo_precision`. Cobertura medida sobre 30 000 registos: **99,0 % código postal ·
0,9 % localidade · 0,1 % sem ponto** (no índice completo, 212 058 de 212 134 têm
ponto).

O agregado do nível `grid` usa um `geohash_grid` sobre `location`: cada célula
tem o centro (latitude/longitude), a contagem, os ativos e a **cidade dominante**
(sub-agregação `terms` sobre `city`), o que permite abrir a janela das empresas
daquela cidade com um clique. `precision` 5 ≈ 4,9 km, 6 ≈ 1,2 km e 7 ≈ 150 m.
Como o `geohash_grid` só devolve as células maiores, a interface mostra quantos
registos ficaram em células menores (com `size` = 1200 são 32 018; com 4000 são
5 753) e oferece um botão para aumentar ou reduzir o número de pontos desenhados.

**Armadilhas conhecidas** (custaram uma sessão inteira):

- o ZIP da GeoNames traz `readme.txt` **antes** do `PT.txt` — escolher o membro
  pelo nome e não o primeiro;
- no *dump*, a capital de Portugal chama-se **`Lisbon`**, não `Lisboa`: é preciso
  indexar também `alternatenames` (para localidades com mais de 20 000 habitantes);
- ao indexar alternativos, os **distritos** (2 milhões de habitantes) ganham às
  cidades: é preciso preferir `feature class = P` (localidade) e ordenar por
  população;
- Portugal tem códigos postais de **4 e de 7 dígitos** (continente e ilhas), pelo
  que a tabela tem de aceitar os dois comprimentos.

## Notas de desempenho (importantes)

1. **A API do GLEIF não permite paginação profunda** — acima de 10 000
   resultados devolve 400. Para o universo completo de um país grande (Espanha
   tem 193 590 LEI) é obrigatório o ficheiro Golden Copy.
2. O ZIP do GLEIF contém **um XML de ~8,4 GB** (não um CSV) com o *namespace*
   `lei:`. `ElementTree.iterparse` sobre este ficheiro é uma armadilha: com
   `events=("end",)` a árvore acumula 3,4 milhões de nós vazios (memória a
   crescer e leitura a degradar-se) e com a pilha de elementos são 600 milhões
   de eventos. A implementação (`collectors/gleif.py`) lê em blocos de 4 MB,
   recorta cada `<lei:LEIRecord>` com uma regex de tag e interpreta-o
   isoladamente — memória constante.
3. **Nunca fatiar o buffer a cada registo**: com 2 000 registos por bloco de
   4 MB, `buffer = buffer[poso:]` copia 4 MB duas mil vezes. Usa-se um índice
   `pos` e fatia-se uma vez por bloco lido.
4. **Pré-filtro por país no texto** (`>\s*(PT|ES)\s*<`) antes de interpretar o
   XML: na golden copy completa 94% dos registos não interessam.
5. Velocidades medidas: leitura do ZIP ~130 MB/s, recorte 557 k registos/s,
   `ET.fromstring` + leitura do país 16 k registos/s, cadeia completa
   (documento normalizado) 2,9 k registos/s, `bulk` no Elasticsearch
   ~6 000 documentos/s. Uma ingestão PT+ES (~212 mil documentos, ~226 MB em
   `lei.jsonl`) leva ~18 minutos com a máquina ocupada (e poucos minutos se
   estiver livre).
6. O ficheiro é **agrupado por LOU**: a densidade de registos de um país varia
   ao longo do ficheiro, pelo que amostras curtas dão taxas enganadoras.
7. A **geocodificação** de cada documento acrescenta ~0,7 s por cada 1 000
   registos (dois *lookups* em dicionários de dicionários): a ingestão PT+ES
   passou de 241 s para 432 s, o que continua a ser aceitável porque só corre
   uma vez por ingestão. As coordenadas ficam também no `lei.jsonl`, pelo que
   uma reindexação a partir do ficheiro (`--source file`) é mais rápida.

## Recolha fora da aplicação

```powershell
# Portugal (18 544 LEI) pela API oficial
python _gleif_ingest.py PT

# Portugal + Espanha a partir do ficheiro Golden Copy local
python _gleif_ingest.py PT ES --source golden-copy --path lei2-latest.zip

# Descarregar o Golden Copy e importar (ZIP ~542 MB)
python _gleif_ingest.py PT ES --source golden-copy-download

# Reindexar a golden copy local
python _gleif_ingest.py --source file

# Reconstruir as tabelas de geocodificação (GeoNames, ficheiros livres)
python _gleif_geo_build.py PT ES

# Verificar a cobertura da geocodificação numa amostra
python _gleif_geo_coverage.py

# Validação automática do módulo (API + agregados + ficheiros servidos)
python _gleif_validar_ui.py
```
