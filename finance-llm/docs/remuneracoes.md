# Remunerações dos Eleitos Locais — abonos, eleitores e o mapa por município

O módulo **Remunerações dos Eleitos Locais** responde a uma pergunta muito
concreta — **quanto recebe, por mês, cada eleito local?** — e a uma mais útil
ainda: **quanto é que isso custa em cada município?**

A resposta não está num sítio só. Vem de duas peças que só fazem sentido juntas:

1. o **direito aplicável** — a *Tabela de Abonos dos Eleitos Locais*, que fixa a
   remuneração de cada cargo como uma **percentagem da remuneração do Presidente
   da República**, por **escalão de eleitores** (Lei n.º 11/96, artigos 5.º,
   5.º-A, 7.º e 8.º);
2. o **território** — quantos **eleitores inscritos** tem cada concelho e cada
   freguesia, e onde fica cada um.

Sem a segunda metade não se sabe em que escalão cai o território; logo, não se
sabe quanto é que ele recebe. O módulo cruza as duas e devolve, para cada um dos
**308 concelhos** e das **3 259 freguesias**, o escalão em que cai e as verbas que
lhe cabem — mais um **mapa OpenStreetMap** navegável onde se vê tudo isso, e quem
foi **eleito** em cada município nas autárquicas de 2025.

## As duas fontes

| Fonte | Onde | O que dá |
| --- | --- | --- |
| Tabela de Abonos 2026 (freguesias) | PDF do despacho anual (`Tabela_Abonos_eleitos_locais 2026.pdf`), transcrito para `data/remuneracoes/abonos_eleitos_locais.json` | Escalões de eleitores, percentagens do PR e os valores de cada verba (tempo inteiro, meio tempo e não permanência) |
| Recenseamento e cartografia do MAI | `eleicoes.mai.gov.pt/autarquicas2025/assets/static/*` | Eleitores inscritos, votantes e mandatos de cada concelho e freguesia, e os polígonos do mapa do MAI |
| Eleitos nas autárquicas de 2025 | MAI, `assets/static/candidate/candidates-…-candidatesElected=true-page=N.json` e os resultados por órgão (`organId=4`, Câmara Municipal) | Presidente da câmara eleito (nome e lista) e os mandatos e vereadores de cada partido na câmara |
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
├── mai_territorios.json         # a árvore recolhida: eleitores + polígonos (re-descarregável)
├── mai_eleitos.json             # presidentes de câmara e vereadores por partido (re-descarregável)
├── mai_recolha.json             # cache da recolha, para a poder retomar (re-descarregável)
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
| `finance_remuneracoes_territorios` | um **território** (concelho ou freguesia) | Eleitores, votantes, mandatos, escalão, verbas aplicáveis, `lat`/`lon` e `localizacao` (`geo_point`) |

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
| `GET /remuneracoes/concelhos/{id}` | **A ficha do município**: eleitores, escalão, abonos, e as suas freguesias (cada uma com eleitores, escalão, verbas e coordenadas) |
| `GET /remuneracoes/freguesias` | Pesquisa de freguesias por nome, concelho, distrito e escalão |
| `GET /remuneracoes/mapa` | As peças do mapa: `nivel=municipio` (os 308 concelhos) ou `nivel=freguesia&concelho=…` |
| `GET /remuneracoes/eleitos` | Os eleitos de 2025: presidente da câmara (nome, lista, votos) e vereadores por partido, com filtros por distrito, partido e nome |
| `GET /remuneracoes/simular?eleitores=8000&nivel=freguesia` | Em que escalão cai um território com N eleitores e quanto vale |
| `POST /remuneracoes/refresh` | Recolhe do MAI o que falta e reindexa |
| `POST /remuneracoes/eleitos/recolher` | Recolhe os eleitos de 2025 do MAI e reindexa |
| `POST /remuneracoes/reindex` | Reindexa o que está em disco |
| `POST /remuneracoes/tabelas/import` | Importa/substitui uma tabela (ex.: a dos municípios) |

### Eleitos de 2025

`GET /remuneracoes/eleitos` e a ficha do município
(`GET /remuneracoes/concelhos/{id}` → `eleitos`) devolvem:

- **presidente da câmara eleito** — nome, lista (sigla e designação), votos,
  percentagem e os mandatos da lista;
- **vereadores** — o total e a composição por partido (mandatos da lista menos a
  presidência, quando a lista a ganhou).

Os nomes dos **vereadores** não constam dos dados abertos do MAI — a lista de
candidatos que publica só traz as cabeças de lista —, pelo que a composição da
câmara é apresentada por partido. A soma confere com o total nacional: **308
presidentes + 1 750 vereadores = 2 058 mandatos**, exactamente os mandatos
atribuídos que o MAI publica para o país.

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

`/remuneracoes` (`chat-ui/src/pages/RemuneracoesPage.tsx`), com quatro separadores:

- **Mapa** — um **mapa OpenStreetMap** navegável (arrastar para percorrer, roda do
  rato ou `+`/`−` para o zoom, «Enquadrar» para voltar a ver tudo) com um ponto
  por concelho, pintado e dimensionado pela métrica escolhida — eleitores,
  votantes ou abono mensal. Passar por cima mostra o detalhe de cada concelho;
  clicar abre a **ficha do município**, com o número de eleitores, o escalão, os
  abonos, os **eleitos em 2025** e **um mapa próprio das suas freguesias**. A
  navegação fica presa a Portugal: nem o arrasto nem o zoom saem do país, e o
  zoom mínimo é aquele em que o país ainda cabe no mapa.
- **Concelhos** — tabela pesquisável (por nome ou distrito) com eleitores,
  votantes, mandatos, escalão e abono; clicar numa linha abre a ficha no mapa.
- **Freguesias** — a mesma leitura para as 3 259 freguesias.
- **Tabela de abonos** — a tabela oficial linha a linha, com um **simulador** («em
  que escalão cai uma freguesia com N eleitores?») e a distribuição das freguesias
  por escalão.

O componente do mapa vive em `chat-ui/src/components/remuneracoes/MapaOSM.tsx` e
serve os dois níveis (concelhos do país e freguesias de um município), reutilizando
a projecção e os *tiles* do módulo de contratos
(`chat-ui/src/components/graph/geo.ts`).

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
- Os **eleitos** vêm da mesma eleição (Autárquicas 2025) e do mesmo servidor do
  MAI. O MAI publica o nome de quem encabeça a câmara, mas não os restantes
  vereadores eleitos; por isso o módulo mostra a composição da câmara por
  partido, e não por pessoa.
