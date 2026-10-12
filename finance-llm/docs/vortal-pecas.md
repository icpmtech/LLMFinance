# Peças do procedimento · Vortal

Página `/vortal` · router `/vortal/*` · motor `api/vortal_service.py` · rotas
`api/vortal_routes.py` · cliente `chat-ui/src/vortalApi.ts` ·
testes `tests/test_vortal.py` (42) · sonda `_probe_vortal_pecas.py` ·
índice `finance_vortal_pecas` · destino em disco `data/vortal/`

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
   (`com texto`, `precisa OCR`, `erro`).
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
  (42 + 9, estes últimos cobrem a ligação à ficha: extração, deduplicação,
  aviso por convite e cache).
- Recolha real: `_probe_vortal_pecas.py [URL-ou-UID …]` (descarrega, indexa e
  mostra a pesquisa).
- Ficha (sem HTTP): `_probe_ficha_vortal.py 11970045`; pela API:
  `_probe_ficha_api.py /contracts/11970045/document`.
- Índice: criado automaticamente na primeira utilização (`ensure_indices`); na VM
  foi criado explicitamente com o mesmo corpo (`_probe_vortal_indice_vm.py`), para
  o painel de monitorização não o dar como inexistente antes da primeira recolha.
- Estado em produção: `GET /api/vortal/estado` (disco `/app/data/vortal`, índice
  `finance_vortal_pecas`).
