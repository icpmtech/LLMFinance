# Análise de sentimento

Módulo de análise de texto do IQ OS: classifica e agrega o sentimento de **todas as
fontes do sistema** — recolha de sites, notícias, contratos públicos, firmas (RNPC),
marcas (INPI), documentos do RAG, dossiês de análise, documentos do Office, CRM,
email e texto colado — e devolve um relatório que pode ser guardado no dossiê e
aberto no editor.

## Fontes analisáveis

O catálogo está em `sentiment_service.ORIGINS` e é exposto por `GET /sentiment/sources`
(quantos documentos cada fonte tem disponíveis). No seletor da UI aparece agrupado e
com a contagem; as fontes privadas ficam bloqueadas sem sessão.

| Grupo | Fonte (`origin`) | Índice / origem | Sessão |
| --- | --- | --- | --- |
| Recolha e fontes externas | `scraped` | `finance_scraped` | não |
| Recolha e fontes externas | `news` | `finance_news` | não |
| Dados da plataforma | `contracts` | `contratos` | não |
| Dados da plataforma | `firmas` | `finance_firmas` | não |
| Dados da plataforma | `trademarks` | `finance_trademarks` | não |
| Dados da plataforma | `rag` | `data/documents/index.json` + Markdown | não |
| Trabalho do utilizador | `dossier` | dossiê 360 (`dossier_id`) | não |
| Trabalho do utilizador | `office` | documento do editor (`document_id`) | não |
| Trabalho do utilizador | `crm` | `finance_crm` (só as contas do utilizador) | **sim** |
| Trabalho do utilizador | `email` | caixa de correio (`account_id`) | **sim** |
| Manual | `text` | texto colado | não |

Nota importante sobre os corpora pequenos: `firmas` (12 documentos) e `trademarks`
(17) são **denominações e nomes**, não texto opinativo. A cobertura é 0 % e o
resultado é sempre **neutro** — é o comportamento correto, não uma falha.

## Como é calculado

| Camada | O que faz |
| --- | --- |
| **Léxico PT** (210 entradas / **170 formas** distintas) | peso −2…+2 por termo; **negação** na janela de 3 palavras («não é bom») e **intensificadores** («muito», «ligeiramente») ajustam a magnitude |
| **Expressões** (`PHRASE_RULES`) | regras de frase que sobrepõem o léxico: «acordo quadro» / «acordo-quadro» (contratação pública) passa a **0.0**; «boas práticas» fixa **+0.6** |
| **Termos ambíguos** (`AMBIGUOUS_TERMS`) | peso reduzido quando o termo é ambíguo no domínio: «acordo» 0.3, «alto» 0.4, «redução» 0.4, «reduzir» 0.3, «aumento» 0.2, «aumenta» 0.2 |
| **pandas** | tabela por documento, média, mediana, desvio-padrão, **IC 95 %** da média, **cobertura**, agregados por fonte, por etiqueta e por dia |
| **scikit-learn** | palavras-chave com **TF-IDF** (1–2 gramas, só palavras de 4+ letras) |
| **transformers** (opcional) | modelo neuronal (`SENTIMENT_MODEL`, por omissão `nlptown/bert-base-multilingual-uncased-sentiment`); se faltar, usa o léxico e diz qual foi usado |

Leitura: polaridade ≥ `+0.15` é **positivo**, ≤ `−0.15` é **negativo**, no meio é **neutro**.

### Cobertura e média reportada

Um corpus real tem muito texto sem vocabulário de opinião (uma lista de contratos, um
nome de firma). Diluir tudo numa média esconderia o sinal, por isso a análise devolve
dois números:

- `mean_polarity` — média bruta de todos os documentos (inclui os sem sinal);
- `mean_polarity_signal` (e `reported_mean`) — média **ponderada pela evidência**, só
  dos documentos com termos encontrados, com `peso = min(acertos, 3) / 3`;
- `coverage` — `documents_with_signal / documents`.

`reported_mean` é o que aparece no relatório e nas etiquetas; a cobertura é mostrada
em KPI para se saber em que base o número assenta. Coberturas medidas: notícias ~48–60 %,
contratos ~32–43 %, recolha ~20–22 %, RAG 100 %, firmas/marcas 0 %.

O texto é limpo antes de ser analisado (`clean_text`): são removidas ligações e
parâmetros de imagens/rastreio (`delay_optim`, `crop`, `webp`), que de outra forma
apareceriam nas palavras-chave. As **palavras funcionais são ignoradas** (sem isso
«mas» apanhava o peso de «más») e o **plural simples é resolvido**
(«excelentes» → «excelente», «lucros» → «lucro», «inflações» → «inflação»).

Casos de referência (usados na validação):

| Texto | Polaridade | Leitura |
| --- | --- | --- |
| «Os resultados foram excelentes e o crescimento superou as expectativas. Grandes ganhos…» | +1.000 | positivo |
| «A empresa falhou os objetivos e registou prejuízos elevados. O mercado está em crise.» | −1.000 | negativo |
| «Os resultados não são bons, mas o produto é excelente.» | +0.318 | positivo (a 2.ª oração domina) |
| «O crescimento foi muito forte mas os custos subiram ligeiramente.» | +1.000 | positivo |
| «A reunião decorreu na terça-feira na sede da empresa, em Lisboa.» | 0.000 | neutro |

## API

| Método | Rota | Descrição |
| --- | --- | --- |
| GET | `/sentiment/meta` | Motores disponíveis, tamanho do léxico, limites e catálogo de fontes |
| GET | `/sentiment/sources` | Fontes do sistema com contagem de documentos (e as contas de email com sessão) |
| POST | `/sentiment/analyze` | Analisar um texto colado |
| POST | `/sentiment/corpus` | Analisar um corpus de **qualquer** origem (ver tabela acima) |
| POST | `/sentiment/save/dossier` | Anexar a análise a um dossiê *(sessão)* |
| POST | `/sentiment/save/office` | Criar/atualizar um documento no Office *(sessão)* |

O corpo do corpus aceita `origin` (obrigatório, por omissão `scraped`), `q`,
`source_id`, `dossier_id`, `document_id`, `account_id`, `folder`, `limit`, `engine`
(`lexicon` | `neural` | `auto`), `title` e `term`.

Respostas de erro verificadas: **401** para `crm`/`email` sem sessão; **422** para
origem desconhecida ou parâmetro em falta (`dossier_id`, `document_id`, `account_id`).

## Integrações

- **Dossiê de análise** — `search360_store.save_sentiment()` guarda o bloco em
  `dossier["sentiment"]` (com `sentiment_history` das análises anteriores) e o
  `dossier_markdown()` passa a incluir a secção «## Análise de sentimento». Como o
  Office constrói o documento a partir do dossiê (`POST /office/documents/from-dossier/{id}`),
  a análise aparece automaticamente no editor.
- **Editor Office** — `POST /sentiment/save/office` cria um documento `relatorio`
  com o relatório em Markdown (tabelas de indicadores, por fonte, por dia e por
  documento).
- **Exportação** — a UI permite descarregar Markdown ou **CSV** (a tabela de pandas)
  e copiar o relatório para colar em qualquer documento.

## Testes

`finance-llm/tests/test_sentiment.py` fixa o contrato do motor: casos de referência
(positivo/negativo/neutro/plurais/crise), negação a inverter o sinal, intensificador a
aumentar a magnitude, «mas» a não ser pontuado, expressão de domínio neutralizada,
agregação com cobertura e aspetos, corpus sem termos (firmas/marcas) a não rebentar e
o catálogo de fontes a cobrir todas as origens.

```
c:\LLMFinance\.venv\Scripts\python.exe -m pytest tests/test_sentiment.py -q
```

## Ficheiros

- `api/sentiment_service.py` — motor, léxico/expressões, 11 construtores de corpus,
  agregação, cobertura, relatório (Markdown/CSV), integrações.
- `api/sentiment_routes.py` — router `/sentiment/*` (leitura pública; escrita com sessão).
- `api/search360_store.py` — `save_sentiment`, `_summary` (flags de sentimento) e exportação.
- `chat-ui/src/sentimentApi.ts`, `chat-ui/src/pages/SentimentPage.tsx` (app «Sentimento», `/sentimento`).
- `tests/test_sentiment.py` — testes do motor e do catálogo de fontes.

## Notas

- A análise de um **texto** devolve também as frases com a polaridade de cada uma
  (`sentences`), útil para perceber o que puxou o resultado.
- O CSV é gerado com `pandas.DataFrame.to_csv`, por isso abre diretamente no Excel.
- Correr a API com `c:\LLMFinance\.venv\Scripts\python.exe` (o `transformers`/`pandas`/`scikit-learn`
  estão aí). O interpretador usado é visível em `/scraper/status`.

## Limitações conhecidas e próximos passos

- A **cobertura** é o limite prático do motor de léxico: em texto onde não há nenhum
  termo reconhecido o documento fica neutro e não contribui para o sinal. Um léxico PT
  maior (estilo LIWC) e mais formas verbais seriam o maior ganho.
- A segmentação por frase divide apenas em `.!?`; dividir também em `;`, `:` e
  conjunções daria uma leitura por oração mais fina.
- O léxico é **genérico**. Afinar o léxico por fonte (linguagem de contratos,
  linguagem de notícias de mercado) reduziria falsos positivos como o de «acordo».
- `SENTIMENT_ENGINE=neural` (ou o motor «Modelo neuronal» na UI) está disponível para
  comparar em corpora de baixa cobertura; é mais lento e não é offline.

