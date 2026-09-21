# Contratos públicos de Espanha (PLACSP)

Módulo do **IQ OS** para pesquisar contratos públicos de Espanha. Os dados vêm da
[Plataforma de Contratación del Sector Público](https://contrataciondelestado.es)
(ficheiros abertos em ATOM/CODICE), são normalizados para JSONL e indexados no
Elasticsearch no índice **`contratos_es`**.

É o equivalente espanhol do módulo de contratos portugueses do portal base
(`collectors/contratos.py` + índice `contratos`), mas com **índice e página próprios**:
os identificadores (expediente vs. `idcontrato`), o vocabulário (CODICE/UBL vs. portal
base) e as facetas são diferentes, pelo que misturar os dois só criaria ruído.

## Conceitos

| Conceito | O que é | Onde vive |
| --- | --- | --- |
| **Fonte** (`fonte`) | Conjunto de dados do PLACSP: `licitaciones` (licitações/concorrências) ou `menores` (contratos menores) | ZIP em `data/contratos-espanha` |
| **ZIP anual** | Um ano de uma fonte; contém centenas de ficheiros `.atom` (feeds Atom com entradas CODICE) | `data/contratos-espanha/<fonte>..._<ano>.zip` |
| **Entrada** (`entry`) | Um estado publicado de um expediente (`ContractFolderStatus`) | dentro dos `.atom` |
| **Documento** | Entrada normalizada, uma por expediente e órgão | JSONL + Elasticsearch `contratos_es` |

O `_id` do documento é `sha1("<fonte>|<DIR3 do órgão>|<n.º de expediente>")`. Como o
mesmo expediente é republicado a cada mudança de estado (PUB → ADJ → RES), reprocessar
um ano **atualiza** o documento em vez de o duplicar: **a última publicação processada
vence** (anos por ordem crescente; dentro do ano, ficheiros `.atom` por ordem de nome).
Isto também elimina os ZIPs duplicados (`...(1).zip`).

## Ficheiros

- `collectors/contratos_es.py` — pipeline ZIP/ATOM → JSONL → Elasticsearch.
- `api/elasticsearch_client.py` — índice `contratos_es`, indexação em *bulk*, pesquisa com facetas, autocomplete e detalhe.
- `api/contratos_es_routes.py` — router `/contracts-es/*` (leitura pública, escrita com sessão).
- `chat-ui/src/contratosEsApi.ts` — cliente tipado.
- `chat-ui/src/pages/ContractsEsSearchPage.tsx` — página de pesquisa (app «Contratos Espanha»).
- `data/contratos-espanha/codigos/*.gc` — listas de códigos **oficiais** CODICE (CPV, tipo de contrato, estado, resultado, procedimento) usadas para os rótulos. Foram descarregadas com `_probe_es_listas.py`, que lê os `listURI` declarados no próprio feed (é aí que se vê qual a lista de códigos de cada campo).
- `tests/test_contratos_es.py` — testes da normalização, dos rótulos e da query.
- `_probe_es_contratos.py` (esquema das entradas), `_probe_es_search.py` (filtros/ordenação) e `_probe_es_import_job.py` (importação em segundo plano sem passar pelo HTTP) — sondas de apoio.

## Dados disponíveis

`data/contratos-espanha` (setembro de 2026):

| Fonte | Anos com ZIP | ZIPs | XML descomprimido | Entradas estimadas |
| --- | --- | --- | --- | --- |
| `licitaciones` | 2012–2024, 2026 | 14 | ~94 GB | ~3,9 M |
| `menores` | 2018–2023, 2025, 2026 | 10 | ~30 GB | ~3,6 M |

Notas: faltam os ZIPs de **`licitaciones` 2025** e de **`menores` 2024**; três ZIPs
duplicados (`...(1).zip`) são ignorados automaticamente. A normalização lê os `.atom`
**em streaming de dentro do ZIP** (não extrai ~124 GB para disco).

### Importação completa (todos os ZIPs disponíveis)

Todos os **22 ZIPs únicos** de `data/contratos-espanha` foram importados
(`python -m collectors.contratos_es --datasets licitaciones menores --years … --index --resume`),
**sem um único erro** de normalização ou de indexação:

| Fonte | ZIPs importados | Entradas → documentos normalizados |
| --- | --- | --- |
| `licitaciones` | 14 (2012–2024, 2026) | ~3,4 M |
| `menores` | 8 (2018–2023, 2025, 2026) | ~3,1 M |

Resultado no índice `contratos_es`: **4 050 002 contratos** (5,3 GB) —
`menores` 2 987 476, `licitaciones` 1 062 526. Os JSONL normalizados somam 13,6 GB em
`data/processed/contratos-es/`, com progresso por ficheiro `.atom` nos `.meta.json`
(permite `--resume`).

A diferença entre entradas lidas e documentos no índice é intencional: o mesmo
expediente é republicado a cada mudança de estado e o `_id` por expediente faz ficar
apenas a última publicação processada (nas licitações, ~3,3 publicações por expediente;
nos contratos menores, quase sempre uma só). Anos presentes na faceta `ano` (data do
contrato, não do ficheiro): **2008 a 2026**.

Ritmos medidos nesta máquina: normalizar 430–1 000 documentos/s (XML determinístico),
indexar em *bulk* 1 700–2 800 documentos/s. A importação completa levou ~3 h.

## Pipeline

```powershell
# listar ZIPs disponíveis
python -m collectors.contratos_es --list

# normalizar um ano (JSONL) e indexar no Elasticsearch
python -m collectors.contratos_es --datasets licitaciones menores --years 2023 --index

# amostra rápida (útil para validar)
python -m collectors.contratos_es --datasets menores --years 2023 --limit 5000

# retomar uma execução interrompida (por ficheiro .atom) e reindexar JSONLs existentes
python -m collectors.contratos_es --datasets licitaciones --years 2024 --resume
python -m collectors.contratos_es --index-only --jsonl data/processed/contratos-es/menores_2023.jsonl
```

Saídas: `data/processed/contratos-es/<fonte>_<ano>.jsonl` (documentos) e
`<fonte>_<ano>.meta.json` (progresso, permite `--resume`). A importação também pode ser
lançada pela UI (app «Contratos Espanha» → *Importar ano*), que corre em segundo plano e
mostra o progresso.

## Normalização

Cada documento é plano e orientado a facetas. Campos principais:

- **Identificação**: `fonte`, `pais` (`ES`), `ano` (ano da data mais relevante), `ano_fonte` (ano do ZIP), `id_expediente`, `estado`/`estado_label`, `enlace` (ligação ao PLACSP).
- **Órgão adjudicante**: `organo_nombre`, `organo_id` (DIR3), `organo_ciudad`, `organo_cp`, `organo_web`, `organo_email`, `organo_tipo`.
- **Objeto**: `objeto`, `descripcion`, `tipo_contrato`/`tipo_contrato_label`, `subtipo_contrato`, `cpv[]` (`code` + `nombre` da lista oficial CPV2008), `num_lotes`.
- **Valores**: `valor_estimado`, `valor_presupuesto`, `valor_base`, `valor_adjudicado`, `valor_adjudicado_con_iva`, `moneda`.
- **Datas**: `fecha_publicacion`, `fecha_adjudicacion`, `fecha_actualizacion`, `fecha_limite` + `hora_limite`.
- **Adjudicação**: `resultado`/`resultado_label`, `num_ofertas`, `adjudicatario_nombre`, `adjudicatario_nif`, `adjudicatario_nuts`, `adjudicatario_nacionalidad`, `procedimiento`/`procedimiento_label`, `urgencia`, `duracion_valor`+`duracion_unidad`.
- **Local**: `localidad` (subentidade; `ESPAÑA` é descartado por não informar) e `nuts`.
- **Pesquisa**: `search_text` (objeto, descrição, órgão, adjudicatário, expediente, CPV) — analisador com `asciifolding`, para «adjudicacion» encontrar «adjudicación».

Os códigos são guardados **em bruto** e com o **rótulo oficial** (ex.: `tipo_contrato: "2"` +
`tipo_contrato_label: "Servicios"`), lido das listas `.gc` do CODICE em
`data/contratos-espanha/codigos`. Nada é traduzido à mão.

## API

| Método | Rota | O que faz |
| --- | --- | --- |
| `GET` | `/contracts-es/status` | Total indexado, anos e fontes |
| `GET` | `/contracts-es/meta` | ZIPs disponíveis, JSONLs normalizados e listas de códigos |
| `POST` | `/contracts-es/search` | Pesquisa com filtros + facetas + somas |
| `GET` | `/contracts-es/autocomplete?q=` | Sugestões de órgãos, adjudicatários e CPV |
| `GET` | `/contracts-es/{doc_id}` | Detalhe de um contrato |
| `POST` | `/contracts-es/import` | Importar um ano (normaliza + indexa) — **requer sessão** |
| `GET` | `/contracts-es/imports` e `/contracts-es/import/{job_id}` | Importações e progresso |

Filtros da pesquisa: `q`, `ano`, `fonte`, `tipo`, `estado`, `procedimiento`, `organo`,
`organismo_id` (DIR3), `adjudicatario`, `adjudicatario_nif`, `localidad`, `nuts`,
`cpv_code` (exato ou prefixo), `min_value`/`max_value`, `start_date`/`end_date` +
`date_field`, `solo_menores`, `sort_by`/`sort_order`, `size`/`from`.

O filtro de valor usa `valor_adjudicado` e, quando este não existe, `valor_base`
(documentado no código, em `_contratos_es_value_range`).

Facetas devolvidas: `fonte`, `ano`, `tipo`, `estado`, `procedimiento`, `localidad`,
`nuts`, `cpv` (com descrição), `organo`, `adjudicatario` — mais somas e média de valor.

## Página de pesquisa

App **«Contratos Espanha»** (ícone no dock; rota `/contratos-es`). Tem:

- pesquisa por texto com autocomplete (órgãos, adjudicatários, CPV);
- facetas laterais clicáveis que filtram de imediato;
- filtros avançados (NIF, DIR3, intervalo de valor, datas, ordenação);
- lista de resultados com detalhe expansível (resultado, nº de ofertas, valores, lotes, contacto, documentos) e ligação direta ao PLACSP;
- painel de importação de um ano, com progresso por ficheiro `.atom`.

Por omissão a app fica **parqueada no dock** (aparece no menu de aplicações); arrastar para
o dock fixa-a.

## Limitações (honestas)

- **Lotes**: só se conta `num_lotes`; os lotes não são desdobrados em documentos. Um expediente é um documento.
- **Estados intermédios perdidos**: como um expediente é um documento, o histórico de estados (PUB → ADJ → RES) não é preservado; fica o último estado processado.
- **Faltam anos**: `licitaciones` 2025 e `menores` 2024 não existem na pasta de origem.
- **Valores a zero**: alguns contratos menores trazem `valor_adjudicado` = 0 no feed; nesses casos a UI mostra o valor base como referência.
- **`localidad` heterogénea**: a subentidade vem ora em maiúsculas (`VALENCIA`), ora como `Valencia / València`; o facet é fiel ao feed, sem normalização de nomes.
- **Fonte externa**: os `.atom` são snapshots. Reprocessar o mesmo ano com os ZIPs atuais atualiza os documentos (não guarda versões).
- **Gralhas da fonte**: uma entrada trazia `IssueDate` = `0018-03-02` (4 M de documentos, um caso). A data crua fica no documento, mas um ano implausível (fora de `[1900, ano corrente + 1]`) é ignorado para o campo de faceta `ano`, que cai nas restantes datas ou no ano do ZIP.
- **Ordem de processamento importa**: como a última publicação vence, reindexar **um ano isolado** pode reverter documentos que anos mais recentes já tinham atualizado. Para correções de normalização, o correto é reprocessar todos os anos (por ordem crescente).
