# Administração Central — entidades do setor institucional (INE / SEC 2010)

O módulo **Administração Central** traz para o IQ OS o *Setor Institucional das
Administrações Públicas* que o **INE** publica todos os anos em PDF
(`Entidades que integram o Setor Institucional das Administrações Públicas`), e
liga cada entidade ao **NIF com que contrata no portal BASE**. É a resposta a
«quem são os serviços e fundos autónomos do Estado, quanto contratam, a quem
compram e o que compram».

Números da edição de **2025** (medidos no índice de contratos da plataforma,
período 2012–2026):

| Subsetor | Entidades | Ligadas a NIF | Contratos | Valor adjudicado | Adjudicatárias distintas |
| --- | ---: | ---: | ---: | ---: | ---: |
| `S.13111` — Estado | 1 | 0 | — | — | — |
| `S.13112` — Serviços e Fundos Autónomos | 301 | 222 | 840 253 | 56,3 mil M€ | 26 532 |
| `S.13113` — Instituições Sem Fim Lucrativo | 55 | 43 | 35 000 | 2,2 mil M€ | 5 909 |

## A fonte

```
finance-llm/data/entidades-sector/
├── Entidades que integram o Setor Institucional das Administrações Públicas - 2025.pdf
├── administracao-central.json     # o índice construído (entidades + ligações a NIF)
└── ligacoes-manuais.json          # correções manuais da ligação nome→NIF (opcional)
```

O PDF é a edição de **2025** (publicada em setembro de 2026, CTAP do INE). Traz a
desagregação completa do setor S.13 em subsetores SEC 2010; o módulo indexa os
três subsetores da **Administração Central**:

| Código | Designação |
| --- | --- |
| `S.13111` | Estado (serviços integrados e Caixa Geral de Aposentações) |
| `S.13112` | Serviços e Fundos Autónomos da Administração Central |
| `S.13113` | Instituições Sem Fim Lucrativo da Administração Central |

A administração regional e local (`S.1313…`) fica de fora **por decisão**: os
municípios, as freguesias e os seus serviços já têm módulos próprios na
plataforma (Remunerações, Despesas das câmaras, PessoasIQ dos municípios).

## Como a ligação nome→NIF é feita

O PDF do INE **não traz NIF** — traz a designação oficial. Os contratos do
portal BASE, pelo contrário, identificam as partes pelo **NIF** e por um nome que
nem sempre é o do INE («Instituto da Mobilidade e dos Transportes» no INE,
«Instituto da Mobilidade e dos Transportes - IMT» no contrato, ou um nome
truncado). A ligação é construída uma vez (na indexação) e guardada no
`administracao-central.json`:

1. agrega-se, numa única consulta ao Elasticsearch, **cada NIF adjudicante** com
   o nome usado nos contratos, o nº de contratos, o valor e o intervalo de anos;
2. cada designação do INE é comparada com esses nomes, por ordem de confiança:

| Tipo | Critério | Confiança |
| --- | --- | --- |
| `exato` | mesma chave de nome (sem formas societárias nem parênteses) | 1,00 |
| `nome` | igual ao nome do contrato depois de retirada a sigla que o abre | 0,96–0,97 |
| `prefixo` | a chave mais curta é prefixo da outra (`…, Migrações e Asilo` truncado) | 0,95 |
| `sigla` | a sigla que abre o nome é a mesma e as palavras coincidem em ≥ 60 % | 0,90 |
| `forte` | palavras significativas coincidem em ≥ 80 % (Jaccard) | 0,85 |
| `manual` | entrada em `ligacoes-manuais.json` | 1,00 |
| `nenhuma` | não se encontrou — a entidade fica **sem NIF** | — |

A normalização dos nomes absorve as diferenças que a fonte tem: acentos e
pontuação, formas societárias no fim do nome (`I.P.`, `S.A.`, `E.P.E.`,
`Unipessoal Lda.`), **grafia anterior ao Acordo Ortográfico**
(`Direcção`/`Direção`, `Actividades`/`Atividades`) e marcas ordinais
(`2.º`/`2º`).

Os critérios são **conservadores de propósito**: um nome mais curto que apenas
*contém* o do INE é outra entidade («Secretaria Regional da Juventude» não é a
«Secretaria Regional de Inclusão, Trabalho e Juventude»), e nomes que só diferem
numa sílaba (`Lezíria`/`Leiria`) não são aceites. Uma ligação errada atribuiria a
uma entidade os contratos de outra.

Em **265 das 357 entidades** (74 %) há NIF ligado. As restantes ou não contratam
publicamente (fundos de garantia, fundos de resolução, veículos de liquidação
como o Banif ou a Parvalorem) ou usam um nome que a comparação automática não
aceita — e podem ser corrigidas à mão:

```json
{
  "Fundo Inventado, I.P.": "123456789"
}
```

Qualquer entrada em `data/entidades-sector/ligacoes-manuais.json` (chave = nome
do PDF, valor = NIF) tem precedência sobre a ligação automática; basta correr
`POST /administracao-central/reindexar` ou
`python scripts/indexar_administracao_central.py`.

### NIF partilhado por mais de uma entidade do INE

**23 dos 265 NIF ligados** aparecem em mais de uma linha do PDF — quase sempre o
caso dos serviços de ação social, que o INE lista como entidade própria mas que
contratam sob o NIF da instituição:

| NIF | Entidades do INE |
| --- | --- |
| `600023265` | Instituto Politécnico da Guarda · SAS - Instituto Politécnico da Guarda |
| `519102622` | Instituto de Educação, Qualidade e Avaliação, I.P. · UL - Instituto de Educação |
| … | (idem nos politécnicos de Beja, Bragança, Castelo Branco, Coimbra, Leiria, Lisboa, …) |

Consequência prática: na **lista** de entidades, duas linhas com o mesmo NIF
mostram os mesmos números (é a mesma entidade contratante no portal BASE). Já as
**analíticas não contam duas vezes**: a agregação filtra por um conjunto de NIF
(o `terms` do Elasticsearch deduplica) e o ranking de entidades é indexado por
NIF.

## O índice

`administracao-central.json` é a **fonte da verdade da lista** (não depende do
Elasticsearch para responder) e guarda, por entidade: `id`, `nome`, `subsetor`,
`nif`, `nome_contratos`, `ligacao`/`ligacao_confianca`, `contratos`, `valor`,
`ano_min` e `ano_max`. Os valores são os do momento da indexação; o painel de
analíticas e as fichas vão sempre ao índice de contratos.

| Onde | Como |
| --- | --- |
| Fora da API | `python scripts/indexar_administracao_central.py [--relatorio] [--sem-contratos]` |
| Na interface | botão **Reindexar** da página |
| Pela API | `POST /administracao-central/reindexar` |

Sem Elasticsearch (`--sem-contratos`) o índice é construído à mesma — fica só
sem ligações a NIF e sem totais de contrato.

## A página

A aplicação **Administração Central** (`/administracao-central`) tem três
leituras:

1. **Entidades** — lista pesquisável (por nome, nome usado nos contratos ou NIF)
   com filtros por subsetor e por tipo de ligação, ordenação por valor ou nº de
   contratos, e exportação CSV. Cada linha mostra os contratos, o valor
   adjudicado e o **período de atividade** (primeiro e último ano com
   contratos);
2. **Analíticas** — volume e valor dos contratos do setor, evolução anual,
   ranking das entidades que mais adjudicam, adjudicatárias, CPV, tipo de
   procedimento e tipo de contrato;
3. **Contratos** — pesquisa os contratos adjudicados pelo setor por objeto,
   subsetor, ano, adjudicatária, CPV e intervalo de valor.

Abrir uma entidade mostra a **ficha**: contratos e valor adjudicado, contrato
médio e maior contrato, valor por ano, adjudicatárias, CPV e os contratos mais
recentes (com ligação à ficha do contrato). O cabeçalho da ficha indica o NIF, o
nome usado nos contratos e o período de atividade (`2012–2026`).

### Fichas e regresso

Em **modo página** as fichas (`contract-detail:<id>`, `company-detail:<NIF>`) não
têm janela própria: abrem-se na vista atual, o caminho (`/administracao-central`)
mantém-se no URL e o «Voltar» da ficha devolve o utilizador ao módulo de onde
saiu — a origem da ficha é guardada ao abri-la, pelo que não se fica preso. Em
**modo janelas** abre-se (ou foca-se) a janela correspondente.

## Analytics de contratos e de adjudicatárias

As agregações são uma única consulta ao índice `contratos`, filtrada por
`adjudicantes.parsed.nif` **nos NIF do setor** (o papel é sempre «adjudicante»:
são os contratos que estas entidades celebram). Devolvem:

* totais (contratos, valor, valor médio e máximo, adjudicatárias distintas);
* `por_ano` — contratos e valor por ano;
* `top_entidades` — o ranking das entidades do setor (do cruzamento do índice
  com os baldes por NIF, sem consulta adicional);
* `top_adjudicatarios` — as empresas que mais lhes vendem, por valor;
* `top_cpv` — o que compram (código + descrição);
* `tipos_procedimento` e `tipos_contrato`.

O resultado é memorizado 10 minutos (`?forcar=true` ignora a cache): a agregação
percorre 2,3 milhões de contratos.

## Rotas

| Método | Caminho | Para quê |
| --- | --- | --- |
| `GET` | `/administracao-central/meta` | Fonte, ficheiros e cobertura das ligações |
| `GET` | `/administracao-central/subsetores` | Subsetores indexados e nº de entidades ligadas |
| `GET` | `/administracao-central/entidades` | Pesquisa do índice (`q`, `subsetor`, `ligacao`, `ordenar`, `size`, `from`) |
| `GET` | `/administracao-central/entidades/{id}` | Ficha da entidade (contratos, adjudicatárias, CPV, últimos) |
| `GET` | `/administracao-central/entidades/{id}/contratos` | Contratos adjudicados por uma entidade |
| `GET` | `/administracao-central/contratos` | Pesquisa de contratos do setor |
| `GET` | `/administracao-central/analiticas` | Painel do setor (`subsetor`, `ano`, `nif`, `top`) |
| `GET` | `/administracao-central/export.csv` | Exportação do índice |
| `POST` | `/administracao-central/reindexar` | Relê o PDF e refaz as ligações |

## Testes

`tests/test_administracao_central.py` cobre o que não depende da rede: a leitura
do PDF, a normalização dos nomes, a ligação nome→NIF (incluindo os casos em que
**não** deve ligar) e a pesquisa/ordenação/exportação do índice.

```bash
python -m pytest tests/test_administracao_central.py -q
```
