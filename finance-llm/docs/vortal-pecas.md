# Peças do procedimento · Vortal

Página `/vortal` · router `/vortal/*` · motor `api/vortal_service.py` · rotas
`api/vortal_routes.py` · cliente `chat-ui/src/vortalApi.ts` ·
testes `tests/test_vortal.py` (59) · sondas `_probe_vortal_pecas.py` e
`_probe_vortal_lote.py` · índice `finance_vortal_pecas` · destino em disco
`data/vortal/`

O módulo recolhe as **peças do procedimento** publicadas na plataforma de
contratação eletrónica **Vortal** (caderno de encargos, programa do concurso,
mapa de quantidades, modelo de resposta, esclarecimentos, ESPD, retificações…),
guarda-as em disco e indexa o **texto** no Elasticsearch, onde fica pesquisável
por dentro dos documentos.

## 1. Como se obtêm as peças (público, sem sessão)

A página pública é uma SPA:

```
https://community.vortal.biz/Public/public-tender-documents/<token>
```

O bundle `public/main/static/index-*.js` revelou os dois passos que interessam,
ambos públicos (validado por sonda, sem cookies):

| Passo | Pedido | Devolve |
|---|---|---|
| 1 | `GET {base}/public/api/PublicTenderDocuments/GetPublicTenderInformation?uniqueIdentifierEncrypted=<token>&languageCode=pt-PT` | `contractNoticeUrl` (com o **UID do aviso**, ex.: `PT1.NTC.3612674`), `tenderInformation.tenderIsPublished` e uma `documentList` (normalmente vazia) |
| 2 | `GET {base}/public/api/ContractNoticeDetail/GetContractNoticeDocuments?contractNoticeUId=<uid>` | lista de peças: `{id, fileId, name, description, downloadUrl}` |

O `downloadUrl` é um URL público com token próprio
(`{base}/archive/api/PublicDownload/download?token=…`) que devolve o ficheiro
com `Content-Disposition` (PDF, XLSX, DOCX, XML, ZIP…).

Exemplo real (14 peças, 26 MB): `CE_Refª 2026-0206.pdf` (caderno de encargos),
`PC_Retificado.pdf` (programa do concurso), mapas de quantidades e modelos de
resposta em XLSX, `espd-request.pdf|xml`, esclarecimentos e prorrogações.

## 2. Arquitetura do módulo

| Camada | O que faz | Onde |
|---|---|---|
| Resolução | token → UID → lista de peças (API pública) | `token_de_url`, `uid_de_url`, `informacao_aviso`, `documentos_do_aviso` |
| Descarga | streaming para `data/vortal/<uid>/`, com `sha256` e idempotência | `descarregar_peca` |
| Texto | PDF (`pymupdf`), DOCX (`zipfile`+`xml`), XLSX (`openpyxl`), XML/CSV/TXT, ZIP por dentro | `extrair_texto`, `guardar_texto`, `ler_texto` |
| Disco | manifesto por aviso (`_manifesto.json`) + texto em `_texto/<ficheiro>.txt` | `guardar_manifesto`, `listar_avisos_em_disco` |
| Índice | `finance_vortal_pecas` (um documento por peça, `_id = uid::sha256[0:16]`) | `indexar_pecas`, `documento_para_indice` |
| Consulta | listar, pesquisar (com trechos) e estado | `listar_pecas`, `pesquisar`, `estado` |
| Lotes | ano/mês do índice de contratos → avisos únicos → lotes de recolha | `periodos`, `avisos_do_periodo`, `recolher_lote` |
| Monitorização | disco + índice + histórico de recolhas (`_recolhas.json`) | `monitorizacao`, `historico_recolhas` |

## 3. Desenho do índice (`finance_vortal_pecas`)

Um documento por **ficheiro** (a peça), não por aviso — é o que permite
pesquisar e mostrar o trecho exato.

| Campo | Tipo | Nota |
|---|---|---|
| `uid` | keyword | UID do aviso (`PT1.NTC.…`) |
| `token`, `url_aviso`, `publicado` | keyword/boolean | origem |
| `nome`, `descricao`, `ficheiro`, `extensao` | text/keyword | nome da peça e do ficheiro em disco |
| `tipo`, `tipo_label` | keyword | `caderno_encargos`, `programa_concurso`, `mapa_quantidades`, `modelo_resposta`, `esclarecimentos`, `retificacao`, `prorrogacao`, `espd`, `convite`, `proposta`, `anexo`, `relatorio`, `outro` |
| `doc_id`, `file_id`, `url`, `sha256`, `bytes` | long/keyword | identificação e integridade |
| `paginas`, `texto_chars`, `texto_metodo`, `precisa_ocr` | integer/keyword/boolean | como o texto foi obtido (`pdf`, `docx`, `xlsx`, `texto`, `zip`, `binario`, `pdf-sem-texto`) |
| `texto` | text (`world_folding`) | **é isto que se pesquisa** (acentos e maiúsculas dobrados) |
| `recolhido_em`, `descarregado_em`, `indexado_em` | date | auditoria |

`analysis.world_folding` (standard + lowercase + asciifolding) é o mesmo
analisador usado no resto da plataforma, pelo que `caucao` encontra «caução».

## 4. Endpoints

| Método | Caminho | O que faz |
|---|---|---|
| GET | `/vortal/meta` | metamodelo: endpoints públicos, hosts autorizados, tipos, limites |
| GET | `/vortal/estado` | disco (avisos, peças, bytes, por tipo) + índice (documentos, avisos, bytes) |
| GET | `/vortal/avisos` | avisos já recolhidos (pelos manifestos) |
| GET | `/vortal/aviso?url=&idioma=` | resolve o aviso e lista as peças **sem descarregar** |
| POST | `/vortal/recolha` | descarrega para disco e (opcional) indexa — **exige sessão** |
| GET | `/vortal/periodos` | anos e meses com avisos Vortal publicados (para o seletor de lotes) |
| GET | `/vortal/periodo?ano=&mes=&limite=&escanear=` | o que há num mês/ano, sem descarregar |
| POST | `/vortal/lote` | recolhe e indexa, **em lotes**, os avisos de um mês/ano — **exige sessão** |
| POST | `/vortal/indexar` | indexa o que já está em disco (por `uid` ou tudo) — **exige sessão** |
| GET | `/vortal/pecas?uid=&limite=` | peças indexadas |
| GET | `/vortal/pesquisa?q=&uid=&limite=` | pesquisa no texto, com trechos (`highlight`) |
| DELETE | `/vortal/aviso/{uid}?disco=` | remove do índice (e do disco, se `disco=true`) — **exige sessão** |
| GET | `/vortal/admin/monitorizacao` | disco + índice + avisos + histórico — **só `admin`** |
| GET | `/vortal/admin/recolhas` | histórico de recolhas/indexações — **só `admin`** |
| GET | `/vortal/admin/indice` | estado do índice — **só `admin`** |

## 5. Página (`/vortal`)

Quatro leituras, com KPIs no cabeçalho (peças em disco, documentos no índice):

1. **Recolher** — uma caixa para colar um ou vários URLs/tokens; botões **Rever
   aviso** (lista as peças sem descarregar) e **Recolher** (descarrega +
   extrai + indexa, com opções de indexação, extração e nova descarga). Mostra a
   tabela das peças com tipo, tamanho, texto extraído e estado
   (`com texto`, `precisa OCR`, `erro`). A mesma aba traz o cartão **Recolher em
   lote por mês e ano** (ver 5.2).
2. **Peças** — o que está indexado (por aviso), com páginas e caracteres de texto.
3. **Pesquisa** — pesquisa no texto das peças, com trechos destacados.
4. **Monitorização** — **só administradores**: peças em disco, com texto, avisos,
   destino, distribuição por tipo, avisos recolhidos e **histórico** de recolhas
   (quando, quem, quantas peças, bytes, quantas indexadas, erros) com ações para
   indexar o que está em disco e remover um aviso do índice.

A aba de monitorização só aparece a quem tem `role === "admin"`; o servidor
devolve **403** a qualquer outro (a autorização não depende do cliente).

A página aceita `?url=<URL do aviso>` (e `?uid=`) no endereço: chega com a caixa
preenchida, para vir da ficha de um contrato sem repetir a procura.

## 5.1 Ligação à ficha do contrato (`/contracts/search` → «Ver detalhe»)

Quem consulta um contrato vê, na secção **Peça do procedimento**, o que a peça diz
sem sair da ficha:

- `api/contract_document.py` autoriza os anfitriões `community.vortal.biz`,
  `www.vortal.biz` e `vortal.biz`; quando a ligação das peças é da Vortal segue o
  ramo `_vortal_pieces()` em vez de tentar ler a página (que é uma aplicação, não
  um ficheiro);
- `vortal.pecas_em_memoria()` resolve o aviso, descarrega as primeiras 8 peças
  (caderno de encargos, programa…), extrai até 20 000 caracteres por peça e
  devolve texto + origem **sem tocar no disco**;
- o texto passa por `extract_values()`, por isso os valores publicados (preço
  base, caução, prazos, IVA…) aparecem como destaques; valores repetidos em peças
  diferentes são deduplicados;
- a resposta traz `source` (`vortal` ou `arquivo`), `uid`, `url_aviso`,
  `publicado` e `pieces_total`, e é guardada em cache por URL durante o TTL
  normal;
- a ficha mostra no cabeçalho «· plataforma Vortal», o UID em monoespaçado, a
  linha «N de M peças lidas nesta ficha · K valor(es) reconhecido(s)» e o botão
  **Obter peças no módulo**, que abre `/vortal?url=<aviso>` já preenchido.

Um aviso **publicado sem peças de acesso público** (procedimento por convite)
responde **200** com `pieces: []` e `pieces_total: 0`, e a nota di-lo com todas as
letras — não é erro nem falha de leitura: as ligações oficiais e os valores do
contrato continuam na ficha. Exemplo real: `11970015` (convite), contra
`11970045` (2 peças) e `11970139` (3 peças, 7 valores) — os 324 994 contratos com
ligação Vortal seguem o mesmo caminho.

## 5.2 Recolher em lote por mês e ano

Colar URLs não escala: cada contrato publicado já traz a **ligação das peças**
no índice de contratos (`contratos.linkPecasProc` — 330 911 contratos com ligação
Vortal, dos quais 64 600 publicados em 2026). O cartão **Recolher em lote por mês
e ano** usa esse campo para não ser preciso colar nada:

| Passo | O que faz | Onde |
|---|---|---|
| Período | agrega `dataPublicacao` dos contratos com ligação Vortal → anos e meses | `GET /vortal/periodos` (`periodos`) |
| Leitura | contas do período em contratos, **avisos únicos** (o mesmo token repete-se por lote/adjudicação), quantos **já em disco** e quantos por recolher | `GET /vortal/periodo` (`avisos_do_periodo`) |
| Recolha | corre N lotes de M avisos: resolve, descarrega, extrai e indexa | `POST /vortal/lote` (`recolher_lote`) |

Decisões que valem a pena fixar:

- o período é o da **publicação** (`dataPublicacao`), não o campo `Ano` do
  contrato: 5 751 contratos com `Ano = 2025` foram publicados em 2026, e o mês
  pedido tem de bater com o que se recolhe;
- por omissão só entram avisos **ainda não recolhidos**, pelo que repetir
  «Recolher lote» **avança** no período (a resposta traz `restantes`) em vez de
  voltar ao princípio — com `forcar` o período é refeito desde o início;
- a lista do período é lida com `search_after` e um teto (`escanear`, 5 000
  contratos por omissão, 20 000 no máximo); acima disso a resposta vem com
  `truncado: true`;
- o mesmo aviso usado por vários contratos é recolhido **uma vez** (dedupe pelo
  token) e o cartão mostra os contratos de origem;
- uma ligação que não seja `*.vortal.biz` é ignorada na leitura (guarda contra
  SSRF, como no resto do módulo);
- cada lote é independente: um aviso que falhe fica nos `erros` e não aborta os
  outros; o disco continua a ser a fonte de verdade (repetir é seguro);
- `recolhidos` conta os avisos que ficaram **em disco** (é o progresso real) e
  `restantes` os que ainda faltam; a Vortal limita o ritmo por IP e uma rajada
  passa a dar `403` (ver 7.1).

Limites da rota: `lote` ≤ 100 avisos, `lotes` ≤ 20 por chamada, `escanear` ≤
20 000 contratos. As recolhas em lote entram no histórico de administração com
`tipo: "lote"` e o período em `urls`.

## 6. Limites e decisões

- Só se descarrega de anfitriões `*.vortal.biz` (guarda contra SSRF, como em
  `api/contract_document.py`).
- Limites: 200 MB por peça, 200 000 caracteres de texto por peça, 90 s de
  timeout por pedido. Uma peça que falhe **não** aborta a recolha: fica com o
  erro no manifesto e no relatório.
- **Sem OCR**: 3 dos 14 PDF do aviso de exemplo são digitalizados (imagem sem
  camada de texto). Ficam marcados `pdf-sem-texto` / `precisa_ocr` em vez de
  parecerem vazios; o índice dá-os como «sem texto».
- O disco é a fonte de verdade (`data/vortal/<uid>/`): o índice pode ser
  reconstruído com `POST /vortal/indexar` sem voltar a descarregar nada.
- As peças são **dados de terceiros**: guardar cópia local e indexar serve para
  pesquisa interna; o URL oficial permanece a referência.

## 7. Operação

- Testes: `.\\.venv\\Scripts\\python.exe -m pytest tests/test_vortal.py tests/test_contract_document_vortal.py -q`
  (59 + 9, estes últimos cobrem a ligação à ficha: extração, deduplicação,
  aviso por convite e cache).
- Recolha real: `_probe_vortal_pecas.py [URL-ou-UID …]` (descarrega, indexa e
  mostra a pesquisa).
- Lote real: `_probe_vortal_lote.py [ANO] [MÊS] [--recolher] [--lotes N]` — sem
  `--recolher` só lê o período (contratos, avisos únicos, o que está em disco);
  com `--recolher` corre os lotes (5 avisos por lote) e mostra as peças.
- Lote longo (destacado, com log): `scripts/recolher_vortal_lotes.py --ano 2026
  --mes 10 --lote 4 --lotes 1 --pausa 60`; na VM fica a correr com
  `docker exec -d iqos-backend sh -c 'nohup python -u
  /app/scripts/recolher_vortal_lotes.py … >> /app/logs/vortal_lote_2026-10.log 2>&1 &'`
  (o log e o PID ficam no volume `logs/`).

### 7.1 Ritmo (medido em produção)

A Vortal **limita por IP** e responde `403` (e às vezes `500`) quando se excede
o ritmo. Medição de 2026-10-13, na VM: uma recolha de outubro **sem pausas**
(50 avisos por lote, um lote a cada 8 s) recolheu o primeiro lote (43 peças) e
depois caiu para **~97 % de recusas** — 968 linhas `403 Client Error` em ~1 000
tentativas, 41 avisos em disco. Os **mesmos tokens**, em pedido isolado,
voltaram a responder **200 da VM** ~15 min depois: era ritmo, não bloqueio
permanente nem token inválido.

O que ficou a impedir que isto se repita:

- `recolher_lote` conta o progresso pelo que **ficou em disco** (`recolhidos`) e
  o `restantes` reflete os avisos que ainda faltam, não as tentativas — antes,
  uma corrida de recusas dava `restantes: 0` sem ter trazido nada;
- o runner começa com pausas de **60 s** entre lotes, **abranda** (até 600 s)
  quando um lote falha em mais de metade e **para** ao fim de 3 lotes sem nada
  recolhido.

Regra prática: ~4 avisos por minuto é sustentável; qualquer coisa acima de ~100
pedidos por minuto pára o IP durante alguns minutos.
- Ficha (sem HTTP): `_probe_ficha_vortal.py 11970045`; pela API:
  `_probe_ficha_api.py /contracts/11970045/document`.
- Índice: criado automaticamente na primeira utilização (`ensure_indices`); na VM
  foi criado explicitamente com o mesmo corpo (`_probe_vortal_indice_vm.py`), para
  o painel de monitorização não o dar como inexistente antes da primeira recolha.
- Estado em produção: `GET /api/vortal/estado` (disco `/app/data/vortal`, índice
  `finance_vortal_pecas`).
