# Custo de vida por concelho — índice e orçamento tipo

O módulo **Custo de vida** transforma três séries que já existiam no IQ OS (renda
mediana do INE, gasóleo da DGEG, despesa municipal do INE/DGAL) num **orçamento
mensal comparável** por concelho, e acrescenta os componentes que faltavam e que
têm série oficial: **IMI** (por município) e **eletricidade e gás** (nacionais).
Fecha com um **índice de custo de vida** em que 100 é a mediana do país.

| Componente | Fonte | Varia por concelho? | Onde |
| --- | --- | --- | --- |
| Renda (€/m²) | INE, novos contratos (2.ºT 2026) | sim | base publicada |
| Gasóleo (€/l) | DGEG, preços comunicados pelos postos | sim | `recolher_gasoleo` |
| IMI (taxa urbana) | AT, reproduzida em dados.gov.pt (CC BY 4.0) | sim | `recolher_imi` |
| Eletricidade | ERSE, tarifa transitória (BTN ≤ 20,7 kVA) | **não** | `recolher_erse` |
| Gás natural | ERSE, tarifa transitória (escalão 1) | **não** | `recolher_erse` |

## Como se recolhe

```powershell
# 1. Fontes → data/custo-vida/componentes.json (datado, com a leitura de cada fonte)
python -m collectors.custo_vida

# 2. Construir os 308 documentos e indexar em finance_custo_vida
POST /custo-vida/recolher

# 3. Publicar a página do CMS com o mapa e a tabela
python -m api.custo_vida_pagina
```

O passo 3 grava e publica a página `custo-de-vida` (`/site/solucoes/custo-de-vida`)
com os blocos gerados a partir do índice — a página não tem números escritos à
mão, para não haver dois valores para a mesma coisa.

## Ficheiros

```
finance-llm/
├── collectors/custo_vida.py        # leitores das fontes + LIMITES (o que fica de fora)
├── api/custo_vida_service.py       # orçamento por tipologia e índice de custo de vida
├── api/custo_vida_pagina.py        # blocos do CMS (mapa, metodologia, fontes)
├── api/custo_vida_routes.py        # /custo-vida/*
├── api/es/custo_vida.py            # índice finance_custo_vida (indexar, listar, obter)
├── data/custo-vida/base_concelhos.json   # 308 concelhos já publicados (renda, gasóleo, população, despesa)
├── data/custo-vida/componentes.json      # instantâneo da última recolha
└── data/custo-vida/erse/*.xlsx           # ficheiros de tarifas tal como vieram da ERSE
```

## O orçamento tipo

Soma, para a tipologia escolhida (T0 35 m², T1 50 m², T2 70 m², T3 90 m²):

```
renda      = renda_m2 × área
gasóleo    = preço mediano do concelho × litros/mês (50 por omissão)
eletricidade = 1 900 kWh/ano × €/kWh + termo fixo diário × 365,25/12
gás        = 138 m³/ano × 11,0 kWh/m³ × €/kWh + termo fixo diário × 365,25/12
IMI        = 120 000 € × taxa urbana ÷ 12
```

Os 1 900 kWh e os 138 m³ são os consumos de referência da própria ERSE; os
11,0 kWh/m³ são o poder calorífico usado para converter m³ em kWh. O VPT de
120 000 € é uma **âncora explícita**: a taxa varia com o município, o imóvel de
referência não. As tarifas de energia são **sem impostos** (a TAR não inclui IEC
nem IVA), pelo que a fatura real de uma família é mais alta.

## O índice

```
índice = 100 × custo_mensal(concelho, T2, 50 l) ÷ mediana_nacional(custo_mensal)
```

* 100 = mediana do país; 118 = 18 % acima da mediana (não são 118 €).
* Só entram concelhos **com renda publicada** (251 de 308 — o INE suprime os
  concelhos com menos de 33 contratos novos no trimestre). Sem renda, o
  orçamento não é comparável e preencher com a mediana nacional falsearia o
  ranking; esses concelhos aparecem a cinzento e sem índice.
* Eletricidade e gás somam o mesmo a todos: entram no **custo**, não diferenciam
  o **índice**. Quem quiser a diferença territorial olha para a renda, o gasóleo
  e o IMI.

Cobertura na última recolha (outubro de 2026): **251** concelhos com renda,
**300** com IMI (8 municípios fixam a taxa por freguesia e não têm taxa única),
**278** com gasóleo — os Açores e a Madeira não têm postos comunicados à DGEG
para todos os concelhos.

## O que fica de fora (e porquê)

Está em `collectors.custo_vida.LIMITES`, e a página explica-o a partir daí:

* **Água, saneamento e resíduos.** A ERSAR publica o encargo mensal por concelho
  (10 m³/mês) só numa consulta interativa, e cada entidade gestora publica o
  tarifário em PDF. O único ficheiro aberto da ERSAR no dados.gov.pt (RASARP) é
  de indicadores, não de tarifas. A tarifa é da **entidade gestora**, não do
  município — vários concelhos partilham a mesma.
* **Transportes.** Os passes são fixados por autoridade de transporte (AML, AMP,
  CIM); não há tabela nacional por concelho e os tarifários publicados são
  imagens ou páginas dinâmicas.
* **Alimentação, saúde e educação.** Não há série de preços por município: o INE
  publica no máximo por NUTS II e o cabaz da DECO é nacional.

## API

| Método | Rota | O que devolve |
| --- | --- | --- |
| `GET` | `/custo-vida/concelhos` | lista com filtros (`q`, `distrito`, `nuts`), ordenação (`indice`, `custo`, `renda`, `gasoleo`, `imi`, `nome`, `populacao`) e paginação |
| `GET` | `/custo-vida/meta` | fontes, anos de referência, cobertura e limites |
| `GET` | `/custo-vida/concelho/{nome}` | ficha de um concelho (nome ou slug) |
| `POST` | `/custo-vida/recolher` | recolhe as fontes, reconstrói e indexa |

## Índice Elasticsearch

`finance_custo_vida`, um documento por concelho. Os campos que variam no
território estão a topo (`renda_m2`, `gasoleo_l`, `imi_pct`, `custo_t0..t3`,
`indice`) para se poderem ordenar e filtrar; `custo` fica como objeto opaco (é a
mesma informação por tipologia) e `cobertura` diz que componentes existem em
cada concelho.
