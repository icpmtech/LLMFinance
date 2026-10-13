# Partidos políticos e as suas contas — Tribunal Constitucional + CNE

O módulo **Partidos políticos e as suas contas** traz para o IQ OS o
**financiamento partidário português**, juntando as duas fontes oficiais que o
publicam:

| Fonte | Onde | O que dá |
| --- | --- | --- |
| **Tribunal Constitucional** — Financiamento Partidário | `tribunalconstitucional.pt/tc/contas_eleicoes-partidos.html` | Por ano (2004→), as **contas anuais** de cada partido, as **listas de ações e meios** de propaganda política, os **relatórios** da ECFP, os **acórdãos** e as **decisões** |
| **CNE** — Partidos Políticos | `cne.pt/content/partidos-politicos-1` | O **registo oficial**: denominação, sigla, data de inscrição, inscritos/extintos, sítio na Internet, símbolo e descrição |

É a resposta a «que contas entregou cada partido, em que ano, e o que ficou por
entregar» — hoje **1 309 entradas** (1 065 documentos, 191 em falta e 53 notas)
em **22 anos**, para **46 partidos** com contas, cruzadas com os **61 partidos**
do registo da CNE (24 inscritos e 37 extintos). Dos 1 065 documentos, **665 são
pesquisáveis pelo conteúdo** (o Markdown das contas e das listas de ações) e
**400 são digitalizações** sem camada de texto.

Para o que a ECFP publica, ver também o registo das pessoas em
`docs/descoberta-pessoas.md` e a ponte `/partidos/pessoa/{nif}` descrita abaixo.

## Onde ficam os ficheiros

```
finance-llm/data/partidos/
├── paginas/
│   ├── indice.html                     # lista de anos publicados pelo TC
│   └── 2024.html                       # página anual de cada ano
├── cne/
│   ├── partidos.html                   # listagem (inscritos + extintos)
│   ├── inscrito-partido-comunista-portugues.html
│   └── extinto-nova-democracia.html    # uma ficha por partido
├── pdf/<ano>/<ficheiro>.pdf            # os PDF publicados pelo TC
├── _normalized/
│   ├── tc-2024.jsonl                   # um JSONL por ano
│   └── cne.jsonl                       # o registo da CNE
└── _manifest.json                      # o que está lido/indexado (sha256, totais, datas)
```

A pasta é configurável por `PARTIDOS_DATA_DIR`. As páginas, as fichas da CNE e
os PDF são **re-descarregáveis** e não entram no repositório (`.gitignore`); o
manifesto e os JSONL ficam.

## As secções da página anual

Cada página anual do TC (`contas_eleicoes-partidos-<ano>.html`) tem uma ou mais
secções, identificadas pela âncora do link interno:

| Âncora | `secao` | Conteúdo |
| --- | --- | --- |
| `1104` | `lista_acoes` | Lista de ações e meios de propaganda política por partido |
| `1111` | `contas_anuais` | Contas anuais (balanço e demonstração de resultados) |
| `1112` | `relatorios_ecfp` | Relatórios da ECFP sobre as contas de cada partido |
| `1114` | `acordaos` | Acórdãos sobre as contas anuais |
| `1115` | `decisoes_ecfp` | Decisões da ECFP |

Nem todos os anos têm todas as secções (`lista_acoes` começa em 2007,
`decisoes_ecfp` aparece em algumas séries, `acordaos` termina em 2014). A
distribuição atual: 481 entradas em `contas_anuais`, 392 em `lista_acoes`, 308
em `relatorios_ecfp`, 117 em `decisoes_ecfp` e 11 em `acordaos`.

## Como uma entrada é lida

Cada entrada é um `<li class="list">` da secção, com o nome do partido, a sigla e
(quando existe) a ligação ao PDF. O TC escreve o mesmo de várias maneiras, e é
isso que a normalização resolve:

| O que a página traz | `entregou` | Campos |
| --- | --- | --- |
| `Partido Comunista Português` + `PCP` + PDF | `true` | `ficheiro`, `pdf_url`, `pdf_titulo` |
| `Partido Comunista dos Trabalhadores Portugueses` + `PCTP/MRPP (Não entregou)` | `false` | `motivo = "Não entregou"` |
| `Partido da Terra` + `MPT (não comunicou)` | `false` | `motivo = "não comunicou"` |
| `PCP (retificadas em 9/11/2012)` | `true` | `observacao = "retificadas em 9/11/2012"` |
| `PCP [versão retificada em 8.06.2022 (a pedido do partido)]` | `true` | `observacao = "versão retificada em 8.06.2022 (…)"` |
| `PAN (Retificadas em 03-04-2014` (parêntese por fechar) | `true` | `observacao` |
| `PPD/PSD "Retificou em 13/04/2016"` | `true` | `observacao` |
| `PXXI - Contas entregues fora de prazo` | `true`/`false` | `observacao` |
| `Lista de ações por força política, referentes ao ano de 2008` (sem sigla) | `true` | `agregado = true`, sem `partido_chave` |
| `[Publicado no Diário da República n.º 94/2015…]` (prosa sem partido) | `null` | `nota = true`, texto pesquisável |

Notas de secção (o enquadramento legal, o aviso «(Vem a Entidade das Contas e
Financiamentos Políticos…)») ficam com `nota = true`: continuam pesquisáveis,
mas não contam como partido.

Nos anos em que o `<span class="links">` não existe (2008, por exemplo), a sigla
é retirada do próprio nome — `PCP - Partido Comunista Português` dá `PCP` +
`Partido Comunista Português`.

## A chave que liga as duas fontes

O TC e a CNE não escrevem a sigla da mesma maneira: em 2008 o TC publica `CDS`
onde a CNE diz `CDS-PP`, e `B.E.` onde a CNE diz `BE`. A ligação faz-se por uma
chave normalizada — **maiúsculas, sem acentos e sem pontuação**:

| Sigla | `chave` | `siglas` (aliases) |
| --- | --- | --- |
| `PCP` | `PCP` | `["PCP"]` |
| `CDS-PP` | `CDSPP` | `["CDS", "CDSPP", "PP"]` |
| `PPD/PSD` | `PPDPSD` | `["PPD", "PPDPSD", "PSD"]` |
| `B.E.` | `BE` | `["BE"]` |
| `PCTP/MRPP` | `PCTPMRPP` | `["MRPP", "PCTP", "PCTPMRPP"]` |

Os aliases saem **só da sigla** (nunca das palavras da denominação, que ligariam
partidos errados) e são o que permite abrir a ficha de um partido pelo `CDS` e
encontrar o registo `CDS - Partido Popular` da CNE.

## O que fica indexado

| Índice | `_id` | Um documento por… |
| --- | --- | --- |
| `finance_partidos` | `<ano>:<secao>:<chave>:<n>` | entrada da página anual (partido × ano × secção) |
| `finance_partidos_registo` | `<chave>` | partido do registo oficial da CNE |
| `finance_partidos_recolhas` | `tc-<ano>` / `cne` | página anual ou listagem da CNE recolhida |

Campos mais relevantes de `finance_partidos`: `ano`, `secao`, `secao_titulo`,
`partido_nome`, `partido_sigla`, `partido_chave`, `entregou`, `motivo`,
`observacao`, `nota`, `agregado`, `documento`, `ficheiro`, `ficheiro_kb`,
`pdf_url`, `pdf_sha256`, `paginas`, `pdf_digitalizado`, `precisa_ocr`,
`texto_metodo`, `texto`, `texto_chars`, `texto_extraido`, `pagina_url`.

## O texto dos PDF: MarkItDown, e por que alguns não têm texto

Cada PDF é descarregado e convertido em **Markdown** pelo **MarkItDown**
(Microsoft, `markitdown[pdf]`), que — ao contrário de uma extração de texto
simples — **preserva a estrutura das tabelas**. É o que faz diferença aqui,
porque as contas anuais e as listas de ações são exatamente isso: tabelas de
ação × meio × gasto × receita × fornecedor. O que fica no campo `texto` (e no
índice) é esse Markdown, pelo que uma linha da tabela continua a ser uma linha
pesquisável — «Povo Livre Digital», um NIF de fornecedor ou «492,00» encontram o
documento **e a linha a que pertencem**.

O campo `texto_metodo` diz como o texto foi obtido:

| `texto_metodo` | O que significa |
| --- | --- |
| `markitdown` | Markdown do MarkItDown (caminho normal) |
| `pymupdf` | Texto simples do **PyMuPDF**, usado como recurso quando o MarkItDown falha ou não está instalado |
| `pdf-sem-texto` | O PDF é uma **digitalização** (imagem sem camada de texto): não há texto nenhum a indexar |

O **PyMuPDF** continua a ser quem conta as páginas (`paginas`) e quem garante o
texto de recurso. O Markdown é limitado a 900 000 caracteres
(`MAX_MARKDOWN_CHARS`; o texto simples de recurso, a 400 000) e um PDF acima de
40 MB não é descarregado (`MAX_PDF_BYTES`).

**As digitalizações.** Boa parte das **contas anuais** e algumas **listas de
ações** são imagens digitalizadas: o MarkItDown não faz OCR (nem o módulo), por
isso dessas fica o documento, o `pdf_sha256` e o número de páginas, com
`texto_metodo = pdf-sem-texto` e `precisa_ocr = true`. Do conjunto já recolhido,
**665 dos 1 065 documentos** deram texto (≈46,8 M de caracteres indexados, sobre
21 509 páginas) e **400 são digitalizações** — para ler essas é preciso abrir o
PDF, que o módulo serve em `/partidos/documento/pdf`, sem voltar ao TC. O
Markdown guardado de qualquer documento (o que ficou indexado) está em
`/partidos/documento/markdown`, e a página **Partidos e contas** mostra-o ao
clicar em **ver Markdown**.

## Recolha

Dois passos, ambos em segundo plano (a página **Partidos e contas** → separador
**Recolha** faz os dois com um clique):

1. **Recolher** (`POST /partidos/recolher`) — páginas anuais do TC + PDF +
   registo da CNE → JSONL. Com `com_pdf: false` lê só metadados e ligações
   (rápido); com `secoes: ["contas_anuais"]` limita a uma secção; com
   `anos: [2024]` limita os anos.
2. **Indexar** (`POST /partidos/indexar`) — JSONL → Elasticsearch.

O site do TC responde **HTTP 429** a rajadas: todos os pedidos passam por um
recurso com **recuo exponencial** (5 tentativas) e há uma pausa de 1,5 s entre
pedidos. O que já está em disco não se volta a descarregar (salvo `forcar:
true`). A recolha completa com PDF leva alguns minutos (~350 ficheiros, centenas
de MB); sem PDF leva menos de um minuto.

Pedir um ano que o TC não publica **não** recolhe tudo: o ano fica em
`ignorados` e a resposta traz o aviso.

## Endpoints

| Método | Rota | Para quê |
| --- | --- | --- |
| `GET` | `/partidos/meta` | Pasta, anos recolhidos, volumetria em disco, índices |
| `GET` | `/partidos/anos` | Anos publicados pelo TC e o que já está recolhido |
| `GET` | `/partidos/fontes` | As duas fontes e as secções da página anual |
| `GET` | `/partidos/ficheiros` | Páginas, PDF e JSONL em disco |
| `POST` | `/partidos/recolher` | Recolha (segundo plano) |
| `POST` | `/partidos/indexar` | Indexação (segundo plano) |
| `GET` | `/partidos/jobs`, `/partidos/jobs/{id}` | Progresso dos trabalhos |
| `GET` | `/partidos/resumo` | Painel: por ano, por secção, top partidos, cumprimento |
| `GET` | `/partidos/search` | Pesquisa (texto, ano, secção, partido, cumprimento, método do texto) |
| `GET` | `/partidos/registo` | Registo oficial da CNE (inscritos/extintos) |
| `GET` | `/partidos/partido/{termo}` | Ficha do partido: registo da CNE + contas por ano |
| `GET` | `/partidos/partido/{termo}/pessoas` | Pessoas do PessoasIQ ligadas ao partido |
| `GET` | `/partidos/pessoa/{nif}` | A pessoa e o partido dela, com as contas do partido |
| `GET` | `/partidos/amostra/{ano}` | Amostra lida do disco (funciona sem Elasticsearch) |
| `GET` | `/partidos/documento/pdf` | O PDF guardado (`ano` + `ficheiro`), sem sair da pasta |
| `GET` | `/partidos/documento/markdown` | O Markdown que ficou indexado (com o método e o aviso de OCR) |
| `GET` | `/partidos/export.csv` | Exportação da pesquisa |

### A ponte «pessoas e partidos»

`GET /partidos/pessoa/{nif}` lê a ficha da pessoa em `finance_people`
(PessoasIQ), extrai o **partido** que lá está (`metadata.party`, `metadata.partido`
ou `party`) e devolve, no mesmo documento, a **ficha do partido** com as suas
contas. É o que permite partir de um deputado e chegar às contas anuais do
partido dele sem procurar a sigla à mão. No sentido inverso,
`GET /partidos/partido/{termo}/pessoas` usa o filtro `party` do PessoasIQ (com
recurso à denominação e à sigla da CNE quando a sigla do TC não coincide).

## Notas e limitações

* O **ano** de cada documento é o da **página anual** do TC — o exercício a que
  as contas respeitam, que é também o ano do ficheiro publicado.
* `acordaos` (2004–2014) e `relatorios_ecfp` (2004–2020) **deixaram de ser
  publicados**; a página mostra o que existe.
* As entradas **agregadas** (a lista de todas as forças políticas, publicada em
  2007 e 2008) e as **notas de secção** não têm `partido_chave` — aparecem na
  pesquisa mas não na ficha de um partido.
* Um mesmo partido pode ter **duas entradas no mesmo ano e secção** (a versão
  original e a retificada): são documentos distintos, ambos indexados.
* `finance_partidos_recolhas` guarda o `sha256` de cada página descarregada, o
  que permite saber se o TC republicou o ano.
* O **Markdown** de uma tabela de PDF nem sempre sai perfeito: os cabeçalhos
  multi-linha das listas de ações (que o próprio PDF desenha em várias linhas)
  aparecem por vezes desalinhados. As **linhas de dados** — designação, datas,
  valores, fornecedores — mantêm-se legíveis e pesquisáveis, que é o que
  interessa para encontrar e conferir.
