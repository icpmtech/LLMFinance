# Remunerações dos Eleitos Locais — abonos, eleitores e o mapa por município

O módulo **Remunerações dos Eleitos Locais** responde a uma pergunta muito
concreta — **quanto recebe, por mês, cada eleito local?** — e a uma mais útil
ainda: **quanto é que isso custa em cada município?**

A resposta não está num sítio só. Vem de três peças que só fazem sentido juntas:

1. o **direito aplicável** — a *Tabela de Abonos dos Eleitos Locais*, que fixa a
   remuneração de cada cargo como uma **percentagem da remuneração do Presidente
   da República**, por **escalão de eleitores** (nas freguesias a Lei n.º 11/96,
   artigos 5.º, 5.º-A, 7.º e 8.º; nos municípios o **Estatuto dos Eleitos
   Locais**, Lei n.º 29/87, artigos 6.º a 10.º);
2. o **território** — quantos **eleitores inscritos** tem cada concelho e cada
   freguesia, e onde fica cada um;
3. as **pessoas** — quem foi eleito (presidentes de câmara, vereadores,
   presidentes de junta e assembleias de freguesia) e quanto recebe cada uma.

Sem a segunda metade não se sabe em que escalão cai o território; logo, não se
sabe quanto é que ele recebe. O módulo cruza as três e devolve, para cada um dos
**308 concelhos** e das **3 259 freguesias**, o escalão em que cai e as verbas que
lhe cabem — mais um **mapa OpenStreetMap** navegável onde se vê tudo isso, a
**fotografia de cada câmara municipal** e quem foi **eleito** em cada município
nas autárquicas de 2025.

## As fontes

| Fonte | Onde | O que dá |
| --- | --- | --- |
| Tabela de Abonos 2026 (freguesias) | PDF do despacho anual (`Tabela_Abonos_eleitos_locais 2026.pdf`), transcrito para `data/remuneracoes/abonos_eleitos_locais.json` | Escalões de eleitores, percentagens do PR e os valores de cada verba (tempo inteiro, meio tempo e não permanência) |
| Tabela de Abonos 2026 (municípios) | Circular **CIR: 21/2026-LR** da ANMP («Remunerações dos Eleitos Locais 2026 — Municípios»), conferida com os documentos de 2026 de Tavira, Freixo de Espada à Cinta e Almada | Lisboa e Porto 55 %, 40 mil ou mais 50 %, mais de 10 mil e menos de 40 mil 45 %, restantes 40 % — mais vereadores a 80 % do presidente, meio tempo a 50 % disso, despesas e senhas |
| Recenseamento e cartografia do MAI | `eleicoes.mai.gov.pt/autarquicas2025/assets/static/*` | Eleitores inscritos, votantes e mandatos de cada concelho e freguesia, e os polígonos do mapa do MAI |
| Eleitos nas autárquicas de 2025 (mandatos) | MAI, `assets/static/candidate/candidates-…-candidatesElected=true-page=N.json` e os resultados por órgão (`organId=4`, Câmara Municipal) | Presidente da câmara eleito (nome e lista) e os mandatos e vereadores de cada partido na câmara |
| **Nomes** de todos os eleitos | **Mapa Oficial n.º 2-B/2025** da **CNE** (`2025al-mapa-oficial_retificado.zip`, ficheiros `mapa_3_eleitos` e `mapa_1_resultados`) | O nome de **cada** pessoa eleita — presidente da câmara, vereadores, presidentes de junta e membros das assembleias — com a lista por que foi eleita |
| Câmaras municipais (edifício e fotografia) | Wikidata (classe `Q25550691`, «câmara municipal») e Wikimedia Commons | Designação, coordenadas, classificação patrimonial (SIPA) e uma **fotografia com autor e licença** |
| Executivos municipais (pelouros) | Sites dos municípios (curado à mão em `data/remuneracoes/eleitos_executivo.json`; exemplo: `cm-porto.pt/executivo`) | Os pelouros de cada vereador, onde o município os publica |
| Coordenadas geográficas | Wikidata (classes `Q13217644` município e `Q1131296` freguesia, CC0) | Latitude/longitude de cada concelho e freguesia — as coordenadas que servem o OpenStreetMap |

Os **valores da tabela são um dado de referência escrito à mão** (transcritos do
PDF oficial): ficam versionados em `data/remuneracoes/abonos_eleitos_locais.json`,
apesar do `*.json` do `.gitignore`, porque não há nada de onde os volte a buscar.
A tabela está conferida contra a aritmética do próprio despacho — por exemplo,
25 % de 8 550,10 € (remuneração do PR) dá exactamente os 2 137,53 € do escalão
dos 20 mil ou mais eleitores.

Tudo o resto é **re-descarregável** e fica só em disco: `POST /remuneracoes/refresh`
volta a buscá-lo (recenseamento, cartografia e coordenadas).

## Onde ficam os ficheiros

```
finance-llm/data/remuneracoes/
├── abonos_eleitos_locais.json   # a tabela oficial (versionada)
├── eleitos_executivo.json       # executivos municipais com pelouros (curado, versionado)
├── mai_territorios.json         # a árvore recolhida: eleitores + polígonos (re-descarregável)
├── mai_eleitos.json             # presidentes de câmara e vereadores por partido (re-descarregável)
├── mai_recolha.json             # cache da recolha, para a poder retomar (re-descarregável)
├── cne_eleitos_nomes.json       # nomes de todos os eleitos (Mapa Oficial da CNE)
├── camaras_wikidata.json        # edifícios das câmaras + créditos das fotos (Wikidata/Commons)
└── geo_territorios.json         # coordenadas dos concelhos e freguesias (re-descarregável)
```

`mai_recolha.json` existe porque a recolha completa são **~3 900 pedidos** ao
mesmo servidor: guarda o que já foi pedido e permite **retomar** uma recolha
interrompida, em vez de recomeçar. É também o que impede que uma passagem
truncada substitua a árvore boa — se a recolha trouxer claramente menos do que
os 308 municípios, o serviço recusa-se a gravar e diz para voltar a correr.

## Escalões de eleitores (freguesias, 2026)

| Escalão | % do PR | Presidente da junta (mensal, exclusividade) |
| --- | --- | --- |
| 20 mil ou mais eleitores | 25 % | 2 137,53 € |
| 10 mil eleitores e menos de 20 mil | 22 % | 1 881,02 € |
| 7 mil eleitores e 100 Km² | 19 % | 1 624,52 € |
| 5 mil eleitores até 10 mil | 19 % | 1 624,52 € |
| Menos de 5 mil eleitores | 16 % | 1 368,02 € |

Referências da tabela: remuneração do Presidente da República **8 550,10 €**,
remuneração do presidente de câmara de município com 10 mil ou menos eleitores
**3 421,00 €** e subsídio de refeição **6,15 €**. Os dois escalões de 19 %
partilham o mesmo valor, pelo que a sobreposição dos seus limites não tem
consequência financeira.

A tabela dos **municípios** é outra tabela, com outro regime legal: o **Estatuto
dos Eleitos Locais** (Lei n.º 29/87, de 30 de junho, artigos 6.º a 10.º), e não a
Lei n.º 11/96. Os escalões também não são os mesmos — e o primeiro decide-se pelo
**município**, não pelos eleitores:

| Escalão | % do PR | Presidente da câmara | Vereadores (tempo inteiro) |
| --- | --- | --- | --- |
| Lisboa e Porto | 55 % | 4 703,00 € | 3 762,40 € |
| 40 mil ou mais eleitores | 50 % | 4 276,00 € | 3 420,80 € |
| Mais de 10 mil e menos de 40 mil eleitores | 45 % | 3 848,00 € | 3 078,40 € |
| 10 mil ou menos eleitores (restantes municípios) | 40 % | 3 421,00 € | 2 736,80 € |

A tabela completa (vereadores a meio tempo, despesas de representação e senhas de
presença da assembleia municipal) está em
`data/remuneracoes/abonos_eleitos_locais.json`. Os valores do presidente da
câmara são a percentagem do PR **arredondada para a unidade de euro imediatamente
superior** (artigo 6.º n.º 2): 45 % de 8 550,10 € dá 3 847,55 €, que a tabela
publica como 3 848,00 €. Foi transcrita da circular da **ANMP** («Remunerações dos
Eleitos Locais 2026 – Municípios», CIR: 21/2026-LR, de 05/02/2026) e conferida
contra os documentos de 2026 de três municípios (Tavira, Freixo de Espada à
Cinta e Almada) — todos com os mesmos valores.

## Recolha

```bash
# Recolhe do MAI o que falta, georreferencia se ainda não houver coordenadas e reindexa
curl -X POST "http://127.0.0.1:8002/remuneracoes/refresh?incluir_freguesias=true&reindexar=true"

# Reindexa sem recolher nada de novo
curl -X POST "http://127.0.0.1:8002/remuneracoes/reindex"

# Recolhe só os eleitos de 2025 (2 pedidos nacionais + 1 por concelho, ~1 minuto)
curl -X POST "http://127.0.0.1:8002/remuneracoes/eleitos/recolher"
```

O servidor do MAI está atrás do **Akamai**, que responde `403` a quem lhe pede
depressa de mais. A recolha vai por isso devagar (concorrência 2, com pausa entre
pedidos) e repete com espera crescente; uma recolha completa demora alguns
minutos. Com `incluir_freguesias=false` recolhe só até ao concelho — ~320 pedidos
em vez de ~3 900. A georreferenciação só se repete quando ainda não há
coordenadas (`forcar=true` obriga a repetir tudo).

O mesmo trabalho fora da API — útil para ver o relatório de cobertura:

```bash
python scripts/georreferenciar_remuneracoes.py
```

O casamento dos nomes entre as duas fontes (o MAI diz «União das freguesias de
Aldeia do Mato e Souto» onde a Wikidata diz «Aldeia do Mato e Souto»; o MAI diz
«Funchal (Sé) (Funchal)» onde a Wikidata diz «Sé») vive no **serviço** —
`chave_territorio`, `variantes_territorio` e `coordenadas` —, para o script e a
API não divergirem.

Cobertura actual: **308/308 concelhos** e **3 222/3 259 freguesias** com
coordenadas. As que faltam são homónimas que a Wikidata não liga ao concelho
(«Belas», «Sesimbra (Santiago)», «Funchal (Sé)»…) e aparecem listadas no mapa
como «sem coordenadas conhecidas», em vez de faltarem em silêncio.

## Índices Elasticsearch

| Índice | Documento | Conteúdo |
| --- | --- | --- |
| `finance_remuneracoes` | uma **linha da tabela** (ano × nível × regime × verba × cargo × modalidade) | Os valores por escalão, com os limites de eleitores e a percentagem do PR |
| `finance_remuneracoes_territorios` | um **território** (concelho ou freguesia) | Eleitores, votantes, mandatos, escalão, verbas aplicáveis, `lat`/`lon` e `localizacao` (`geo_point`), a câmara municipal (edifício e foto) e o presidente eleito |
| `finance_remuneracoes_pessoas` | uma **pessoa eleita** (29 745) | Nome, cargo, tipo, nível, lista, concelho, freguesia, escalão, remuneração mensal, despesas e senhas — pesquisável por nome, concelho, partido e cargo |

O índice dos territórios guarda o `localizacao` como `geo_point`, para permitir
consultas por caixa ou raio sobre o mapa.

## API

| Rota | O que devolve |
| --- | --- |
| `GET /remuneracoes/meta` | De onde vêm os dados (tabela, MAI, georreferenciação) e o que já está lido |
| `GET /remuneracoes/stats` | Volumetria: territórios, eleitores, cobertura do mapa e freguesias por escalão |
| `GET /remuneracoes/tabelas` | A tabela de abonos completa, por ano e nível (escalões + verbas) |
| `GET /remuneracoes/escaloes?nivel=freguesia` | Os escalões de eleitores de um nível |
| `GET /remuneracoes/concelhos` | Os concelhos com eleitores, votantes, escalão, abono e coordenadas |
| `GET /remuneracoes/concelhos/{id}` | **A ficha do município**: eleitores, escalão, abonos, os **eleitos de 2025** (com nomes e remunerações) e as suas freguesias (cada uma com eleitores, escalão, verbas, presidente da junta e coordenadas) |
| `GET /remuneracoes/freguesias` | Pesquisa de freguesias por nome, concelho, distrito e escalão |
| `GET /remuneracoes/mapa` | As peças do mapa: `nivel=municipio` (os 308 concelhos) ou `nivel=freguesia&concelho=…` |
| `GET /remuneracoes/eleitos` | Os eleitos de 2025: presidente da câmara (nome, lista, votos) e vereadores por partido, com filtros por distrito, partido e nome |
| `GET /remuneracoes/eleitos/nomes` | Quem foi eleito pelo Mapa Oficial da CNE (presidentes, vereadores, juntas e assembleias) e o que a fonte não traz (lacunas e divergências) |
| `GET /remuneracoes/pessoas` | **Todas as pessoas eleitas** (29 745) com o cargo, o território, a lista e o que cada uma recebe — filtros por nome, distrito, concelho, cargo, partido e nível |
| `GET /remuneracoes/camaras` | Os edifícios das câmaras municipais: designação, coordenadas, património, município e **fotografia com autor e licença** |
| `GET /remuneracoes/eleitos/executivo` | Cobertura dos executivos municipais curados (pelouros por vereador) |
| `GET /remuneracoes/simular?eleitores=8000&nivel=freguesia` | Em que escalão cai um território com N eleitores e quanto vale |
| `POST /remuneracoes/refresh` | Recolhe do MAI o que falta e reindexa |
| `POST /remuneracoes/eleitos/recolher` | Recolhe os eleitos de 2025 do MAI e reindexa |
| `POST /remuneracoes/eleitos/nomes/recolher` | Descarrega o Mapa Oficial da CNE, lê os nomes de todos os eleitos e reindexa |
| `POST /remuneracoes/camaras/recolher` | Recolhe as câmaras municipais (Wikidata) e as fotos do Commons, e reindexa |
| `POST /remuneracoes/eleitos/executivo` | Importa os nomes/pelouros do executivo de um município |
| `POST /remuneracoes/reindex` | Reindexa o que está em disco |
| `POST /remuneracoes/tabelas/import` | Importa/substitui uma tabela (ex.: a dos municípios) |

### Eleitos de 2025

`GET /remuneracoes/eleitos`, `GET /remuneracoes/concelhos/{id}` (chave `eleitos`)
e a ficha de cada freguesia devolvem:

- **presidente da câmara eleito** — nome, lista (sigla e designação), votos,
  percentagem e os mandatos da lista;
- **vereadores** — o total, a composição por partido e os **nomes** de quem foi
  eleito por cada lista;
- **`pessoas`** — presidente e vereadores um a um, com o cargo e o que cada um
  recebe pela tabela dos municípios (o vereador a tempo inteiro vale 80 % do
  presidente);
- nas **freguesias**, o **presidente da junta** (nome, lista e votos), o número de
  membros da assembleia e o valor de cada papel (`pessoas_valores`): senha do
  vogal, compensação do secretário e senha da assembleia.

Os nomes vêm do **Mapa Oficial n.º 2-B/2025 da CNE**, que publica os eleitos de
todos os órgãos — o MAI, nos seus dados abertos, só traz o nome de quem encabeça
a câmara. Os totais recolhidos são **308 presidentes de câmara, 1 737 vereadores,
3 170 presidentes de junta e 24 530 membros de assembleias de freguesia**. A soma
dos mandatos de câmara confere com o total nacional do MAI (308 presidentes +
1 750 vereadores = 2 058 mandatos); a diferença de 13 vereadores está nas
**lacunas do próprio ficheiro oficial**, descritas abaixo.

### O que a fonte não traz (e o módulo diz)

Nada é inventado: quando o ficheiro oficial não publica um nome, o módulo conta-o
em vez de o preencher. Em `GET /remuneracoes/eleitos/nomes` → `lacunas`:

| Município | Mandatos | Nomes publicados | Faltam |
| --- | --- | --- | --- |
| Braga | 11 | 9 | 2 |
| Vila Verde | 7 | 6 | 1 |
| Alandroal | 5 | 0 | 5 |
| Cascais | 11 | 6 | 5 |
| Oeiras | 11 | 10 | 1 |
| Horta | 7 | 6 | 1 |

Há ainda **uma divergência** entre fontes, registada em `divergencias`: em
**Resende** o MAI indica *Fernando Silvério Cardoso de Sousa* e o Mapa Oficial
*Jorge José Pereira Sala Monteiro* para a presidência. O módulo segue o Mapa
Oficial (é a versão retificada e a que lista os eleitos) e di-lo na ficha.

Nas freguesias, **52** não têm presidente de junta identificado (a coluna
vencedora do mapa não lista nomes) e **19** não se conseguiram ligar por nome aos
blocos do Mapa Oficial; também não são adivinhadas.

### Importar ou substituir uma tabela

As tabelas de 2026 (freguesias e municípios) já estão transcritas em
`data/remuneracoes/abonos_eleitos_locais.json`. Quando sair a tabela de um novo
ano, importa-se pela API — o corpo é uma tabela inteira, e importar o mesmo
`ano` + `nivel` **substitui** a anterior (corrigir em vez de duplicar):

```bash
curl -X POST http://127.0.0.1:8002/remuneracoes/tabelas/import \
  -H "Content-Type: application/json" \
  -d '{
        "ano": 2027,
        "nivel": "municipio",
        "titulo": "ABONOS DOS ELEITOS LOCAIS - MUNICÍPIO - ANO 2027",
        "escaloes": [
          {"id": "mun-lisboa-porto", "designacao": "Lisboa e Porto",
           "municipios": ["Lisboa", "Porto"], "percentagem_pr": 55.0},
          {"id": "mun-40mil-ou-mais", "designacao": "40 mil ou mais eleitores",
           "min_eleitores": 40000, "percentagem_pr": 50.0},
          {"id": "mun-10mil-a-40mil", "designacao": "Mais de 10 mil e menos de 40 mil eleitores",
           "min_eleitores": 10001, "max_eleitores": 40000, "percentagem_pr": 45.0},
          {"id": "mun-10mil-ou-menos", "designacao": "10 mil ou menos eleitores (restantes municípios)",
           "max_eleitores": 10001, "percentagem_pr": 40.0}
        ],
        "rubricas": [
          {"id": "mun-ti-remuneracao-presidentes",
           "regime": "Tempo Inteiro",
           "grupo": "Remuneração mensal e subsídio extraordinário de junho e novembro",
           "cargo": "Presidentes da Câmara Municipal",
           "modalidade": "Permanência (exclusividade)", "natureza": "remuneracao",
           "percentagens": {"mun-lisboa-porto": 55.0, "mun-40mil-ou-mais": 50.0,
                            "mun-10mil-a-40mil": 45.0, "mun-10mil-ou-menos": 40.0},
           "valores": {"mun-lisboa-porto": 4804.0, "mun-40mil-ou-mais": 4367.0,
                       "mun-10mil-a-40mil": 3930.0, "mun-10mil-ou-menos": 3495.0}}
        ]
      }'
```

O campo `min_eleitores` é inclusivo e `max_eleitores` exclusivo, como nos
escalões das freguesias; como os eleitores são números inteiros, «mais de 10 mil»
escreve-se `10001`. Um escalão com `municipios` só se aplica a esses municípios —
nunca cai lá um concelho pelo número de eleitores.

## A página no portal

`/remuneracoes` (`chat-ui/src/pages/RemuneracoesPage.tsx`), com seis separadores:

- **Mapa** — um **mapa OpenStreetMap** navegável (arrastar para percorrer, roda do
  rato ou `+`/`−` para o zoom, «Enquadrar» para voltar a ver tudo) com um ponto
  por concelho, pintado e dimensionado pela métrica escolhida — eleitores,
  votantes ou abono mensal. Passar por cima mostra o detalhe de cada concelho,
  com a **fotografia da câmara municipal** e o crédito de quem a tirou; clicar
  abre a **ficha do município**, com o número de eleitores, o escalão, os abonos,
  os **eleitos em 2025** (presidente, vereadores, nomes por lista e o que cada um
  recebe) e **um mapa próprio das suas freguesias**. A navegação fica presa a
  Portugal: nem o arrasto nem o zoom saem do país, e o zoom mínimo é aquele em que
  o país ainda cabe no mapa.
- **Concelhos** — tabela pesquisável (por nome ou distrito) com eleitores,
  votantes, mandatos, escalão e abono; clicar numa linha abre a ficha no mapa.
- **Freguesias** — a mesma leitura para as 3 259 freguesias, com o **presidente da
  junta** (nome e lista) e o **valor de cada pessoa da freguesia**: presidente
  (mensal), vogal (senha), secretário (compensação) e assembleia (senha), mais o
  número de membros da assembleia.
- **Eleitos** — as **29 745 pessoas eleitas**: nome, cargo, município, freguesia,
  lista e remuneração mensal, com filtros por cargo e nível e pesquisa livre.
- **Câmaras** — galeria dos **267 edifícios com fotografia**, com município,
  coordenadas, classificação patrimonial, autor e licença da imagem e ligação ao
  Commons e à Wikipédia.
- **Tabela de abonos** — a tabela oficial linha a linha, com um **simulador** («em
  que escalão cai uma freguesia com N eleitores?») e a distribuição das freguesias
  por escalão.

O componente do mapa vive em `chat-ui/src/components/remuneracoes/MapaOSM.tsx` e
serve os dois níveis (concelhos do país e freguesias de um município), reutilizando
a projecção e os *tiles* do módulo de contratos
(`chat-ui/src/components/graph/geo.ts`). Os *tiles* são desenhados à escala do
zoom fraccionário do mapa (`2 ** (zoom - nivel)`), senão os pontos aparecem
deslocados do seu sítio real — a diferença chega a 25 % a meio do país.

## Notas

- O MAI **não publica** latitude/longitude: os polígonos que serve vivem no
  sistema de coordenadas do seu próprio mapa e não se sobrepõem a um mapa real.
  Por isso o mapa assenta nas coordenadas da Wikidata, e não nos polígonos do MAI
  (que continuam guardados, para consulta).
- As coordenadas são o **ponto de referência oficial** de cada divisão
  administrativa, não o centroide do polígono — servem para situar, não para
  medir áreas.
- Os eleitores são os **inscritos no recenseamento** das Autárquicas 2025
  (9 303 840 no total nacional, que é exactamente a soma dos concelhos e das
  freguesias recolhidos — serve de conferência da recolha).
- Os **eleitos** vêm da mesma eleição (Autárquicas 2025): os mandatos e os
  presidentes do servidor do MAI, os **nomes de todos os eleitos** do Mapa Oficial
  n.º 2-B/2025 da CNE. Onde o mapa oficial não publica um nome — 15 mandatos de
  câmara em seis municípios, 52 juntas sem presidente identificado —, o módulo
  conta-o em vez de o preencher.
- As **fotografias** das câmaras são do Wikimedia Commons e são servidas em
  miniatura (480 px), com autor, licença e ligação à página do ficheiro: usar o
  original seria trazer dezenas de megabytes para um *tooltip*.
