# Contribuintes — índice único de NIF/NIPC do sistema

O módulo **Contribuintes** mantém um índice (`finance_contribuintes`) com **um
documento por NIF/NIPC** que aparece em qualquer índice da plataforma. Serve
para responder, num só sítio, a perguntas como «quem é este NIF?», «onde
aparece?», «com que papéis?» ou «quanto vale em contratos públicos?».

Ao contrário dos restantes módulos, **não tem recolha própria**: é um índice
*derivado*, reconstruído a partir das fontes que já existem — manualmente (botão
na aplicação) ou por **cron** (sincronização automática).

É também um âmbito da **Pesquisa total** (`/search/unified?scope=contribuintes`)
e da **Pesquisa profunda** (`sources=["contribuintes"]`), onde aparece como o
retrato do NIF: quantos registos tem em cada fonte (contratos, insolvências,
atos societários…) e quanto vale em contratos.

## Fontes percorridas

| Índice | O que dá | Campos agregados |
| --- | --- | --- |
| `contratos` | Contratos públicos (PT, Portal BASE) | `adjudicantes.parsed.nif`, `adjudicatarios.parsed.nif` |
| `contratos_es` | Contratos públicos de Espanha (PLACSP) | `adjudicatario_nif` |
| `finance_entities` | Cadastro de entidades do Portal BASE | `nif` |
| `finance_publicacoes_mj` | Publicações societárias (MJ) | `nif`, `matricula_nipc` |
| `finance_cire` | Insolvências e revitalizações (CITIUS) | `intervenientes.nif` |
| `finance_people` | Pessoas e cargos (PessoasIQ) | `nif` |
| `finance_firmas` | Firmas e denominações (RNPC) | `nipc` |
| `finance_trademarks` | Marcas (INPI) | `holder_nif`, `company_nif` |
| `finance_crm` | Contas do CRM | `nif` (registos `kind = account`) |

## O documento de um contribuinte

```json
{
  "nif": "500189412",
  "name": "JANSSEN - CILAG FARMACÊUTICA LDA",
  "names": ["JANSSEN - CILAG FARMACÊUTICA LDA"],
  "type": "empresa",
  "is_company": true,
  "nif_valid": true,
  "country": "Portugal",
  "sources": ["societario", "contratos", "cire"],
  "roles": ["adjudicante", "societario", "insolvente", "credor"],
  "contracts_count": 12,
  "contracts_as_adjudicante": 9,
  "contracts_as_adjudicatario": 3,
  "contracts_value": 1234567.89,
  "societario_count": 93,
  "cire_count": 2,
  "records_total": 107,
  "first_seen": "2006-02-21T00:00:00.000Z",
  "last_seen": "2026-09-22T00:00:00.000Z",
  "location": { "distrito": "Lisboa", "concelho": "Oeiras" },
  "src_societario": { "label": "Publicações societárias (MJ)", "count": 93, "parts": { "publicacao": { "count": 93 } } }
}
```

Campos derivados úteis para filtrar e ordenar:

- **Identificação** — `name` (designação preferida), `names` (todas), `name_norm`
  (sem acentos, para pesquisa), `type`, `is_company`, `country`, `nif_valid`
  (dígito de controlo português, módulo 11).
- **Presença** — `sources` (ids das fontes), `source_labels`, `roles`
  (adjudicante, adjudicatário, insolvente, administrador, credor, gerente,
  firma, titular de marca, conta de CRM, …), `records_total`.
- **Volumes** — `contracts_count` (e `contracts_as_adjudicante` /
  `contracts_as_adjudicatario`) e `contracts_value`; `contratos_es_count` /
  `contratos_es_value`; `societario_count`; `cire_count` (com `cire_roles`);
  `trademarks_count`; `firmas_count`; `people_roles_count`;
  `people_companies_count`; `crm_account`.
- **Tempo** — `first_seen`, `last_seen` e as datas por fonte
  (`contracts_first_date`, `contracts_last_date`, `societario_last_date`,
  `cire_last_date`, …).
- **Evidência** — `src_<fonte>` (não indexado) guarda o contributo de cada
  fonte: contagens, valores, datas, designações, papéis e detalhes
  (concelho, natureza jurídica, situação, etc.). É o que a ficha mostra.
- **Localização** — `location.{pais, distrito, concelho, freguesia, codigo_postal}`,
  ver «De onde vem a localização» abaixo.
- **Controlo** — `run_id` (passagem que escreveu o documento) e `synced_at`.

O `_id` é `finance_contribuintes:{nif}`, pelo que repetir a escrita é
idempotente.

## Como funciona a sincronização

`api/contribuintes_service.py`:

1. **Agregação por fonte** — cada fonte é percorrida com uma *composite
   aggregation* paginada (`page_size`, por omissão 5000 valores distintos por
   pedido). Isto mantém a memória constante mesmo sobre 15 milhões de contratos
   ou 7 milhões de contratos espanhóis. As métricas (contagem, soma de valores,
   primeira/última data) e a designação vêm nos sub-agregados de cada bucket,
   incluindo em campos aninhados (`nested` + `reverse_nested`).
2. **Registo temporário** — os contributos são gravados num SQLite temporário
   (`data/contribuintes/parts.sqlite3`), chaveado por (NIF, fonte, passagem).
   Evita manter centenas de milhares de contribuintes em memória.
3. **Escrita** — o registo é lido por NIF (o índice primário serve de
   ordenação), os contributos das várias fontes são fundidos num documento e a
   escrita é feita em `bulk` de 1000 documentos, com `refresh` no fim.
4. **Reconstrução limpa** — uma sincronização **completa** marca os documentos
   escritos com o `run_id` da passagem e apaga os que não foram vistos
   (`delete_by_query`), pelo que o índice reflete o presente e não acumula
   fantasmas. Uma sincronização **parcial** (subconjunto de fontes) funde-se com
   o que já está indexado e não apaga nada.

Falhas transitórias do Elasticsearch (erro 500 «read past EOF» em agregações
com `top_hits` sobre índices que estão a ser escritos em paralelo) são repetidas
até 4 vezes por página; se uma página continuar a falhar, é repetida com uma
página mais pequena (400 valores) e, em último caso, **sem** `top_hits`
(perdem-se as designações dessa página, mas os totais ficam certos). Se uma
fonte falhar definitivamente, a sincronização continua com as restantes e o erro
(com os NIF já recolhidos) fica em `summary.errors` — e os dados dessa fonte que
já estavam indexados **são preservados** (uma passagem incompleta não apaga a
evidência existente nem remove contribuintes).

> Nota técnica: nas fontes com campos aninhados (`contratos` → `adjudicantes`/
> `adjudicatarios`; `cire` → `intervenientes`) o `top_hits` devolve o objeto
> aninhado, pelo que o filtro `_source` tem de usar o caminho completo
> (`adjudicatarios.parsed.nome`). Com o nome simples a resposta vem vazia e a
> ficha ficava apenas com o NIF.
>
> Os campos que vivem na **raiz** do documento mas são lidos nessa mesma
> passagem aninhada — `localExecucao` (contratos) e `tribunal_comarca`,
> `especie`, `tipo` (CIRE) — são pedidos por `reverse_nested` + `top_hits` na
> spec (`root_detail`). Pedi-los no `top_hits` aninhado com o prefixo do caminho
> (`adjudicantes.parsed.localExecucao`) devolvia sempre vazio: foi isso que, numa
> revisão, deixou os contribuintes **sem localização nenhuma**. Ver
> `tests/test_contribuintes_location.py`.

> Uma sincronização completa soma ~11 passagens de agregação. Em índices
> grandes (`contratos`, `contratos_es`, `finance_cire`) é um trabalho de
> minutos — daí correr em segundo plano (API) ou em cron.

## De onde vem a localização

`location.*` é preenchida por ordem de prioridade — a **sede** manda e o local
onde os contratos são executados só entra no que ficar em falta:

| Ordem | Fonte | Campos | Cobertura |
| --- | --- | --- | --- |
| 1 | `societario` (MJ) | `distrito`, `concelho`, `freguesia`, `codigo_postal` | só nas publicações que os tragam |
| 2 | `firmas` (RNPC) | `concelho` | parcial (muitas firmas sem concelho) |
| 3 | `crm` (contas) | `city`→concelho, `country`→país, `postal_code` | contas do CRM |
| 4 | `contratos` (PT) | `localExecucao` («Portugal, Distrito, Concelho») | **2,2 M de contratos** — é o que dá localização à maioria |

O `localExecucao` dos contratos é o **local de execução**, não a sede da
empresa: serve para responder «onde há atividade deste NIF» e é o que torna o
grafo de localização útil. A distinção está visível na ficha, na evidência da
fonte `Contratos públicos (PT)`.

O campo é multi-valor (`["Portugal", "Portugal, Guarda, Fig. Castelo Rodrigo"]`)
e aproveita-se a entrada **mais completa**; valores só com o país preenchem
apenas `location.pais` (não contam para «com localização», que mede o distrito).
Para reencher a localização depois de uma alteração basta uma passagem parcial:

```powershell
c:\LLMFinance\.venv\Scripts\python.exe _sync_contribuintes.py contratos
```

> A localização só fica no índice **depois de uma sincronização** que percorra
> as fontes que a trazem (basta `_sync_contribuintes.py contratos societario`).

## Relatórios (PDF, Excel e CSV)

`api/contribuintes_report.py` gera os três formatos a partir da **mesma
estrutura de secções**, pelo que dizem sempre o mesmo:

- **Ficha de um contribuinte** — identificação, tipo, país, localização,
  atividade agregada (contratos PT/ES, publicações, CIRE, marcas, firmas,
  cargos, CRM), designações conhecidas e a evidência por fonte.
- **Lista de contribuintes** — resumo do conjunto filtrado (contagem, com
  contratos, com localização, valor contratual, distribuição por tipo) e a
  tabela dos contribuintes com as colunas de NIF, designação, tipo, país,
  localização, fontes, papéis, contratos, valor e último registo.

A marca do **IQ OS** acompanha os relatórios: o logótipo (`chat-ui/public/icon-192.png`)
é embutido no **PDF** (ReportLab) e no **Excel** (openpyxl + Pillow); o **CSV**,
sendo texto, leva o cabeçalho da marca em comentários (`# IQ OS — …`), com BOM
UTF-8 e separador `;` para abrir corretamente no Excel português.

- `GET /contribuintes/export/{nif}?format=pdf|xlsx|csv` — ficha do contribuinte;
- `GET /contribuintes/export?format=…&<filtros de /search>` — lista (até 5000
  linhas, `limit`), com `Content-Disposition` já com o nome do ficheiro
  (`iq-os-contribuinte-<nif>_<data>.pdf`, `iq-os-contribuintes_<data>.xlsx`).

## Robustez da sincronização

- **Cadeado órfão** — o `data/contribuintes/sync.lock` é substituído se o
  processo que o criou já não existir (verificação por PID), além do limite de 6
  horas. Sem isto, uma sincronização interrompida bloqueava as seguintes durante
  6 horas.
- **Página grande a falhar** — perante um erro transitório do Elasticsearch
  («read past EOF», típico quando o índice está a ser escrito/mesclado), a página
  é repetida primeiro com **400 valores** (`RECOVERY_PAGE_SIZE`) — o `after_key`
  da agregação composta não depende do tamanho da página, pelo que a paginação
  continua correta. Só se essa repetição também falhar é que a página é lida
  **sem `top_hits`** (perdem-se as designações e a localização dessa página, mas
  os totais ficam certos).
- **Sincronização parcial** — os blocos `src_*` já indexados são lidos com
  `mget` e fundidos com os da passagem. A chave devolvida tem de perder o
  prefixo `src_` (o `_build_doc` procura pelo id da fonte): sem isso, a passagem
  parcial substituía o documento inteiro e perdia as outras fontes.

## Agendamento (cron)

`api/contribuintes_scheduler.py` mantém um *job* APScheduler
(`contribuintes:sync`) com a expressão cron guardada em
`data/contribuintes/config.json`:

```json
{
  "enabled": true,
  "cron": "0 3 * * *",
  "timezone": "Europe/Lisbon",
  "page_size": 5000,
  "sources": null,
  "last_run": { "...": "resumo da última passagem" },
  "history": [ { "...": "últimas 20 passagens" } ]
}
```

- `enabled` liga/desliga a sincronização automática; `cron` é uma expressão de
  5 campos (minuto hora dia mês dia-semana), validada antes de gravar;
- `sources` limita as fontes (por omissão `null` = todas);
- o agendador arranca no *lifespan* da API e é recarregado sempre que a
  configuração muda (`PUT /contribuintes/schedule`).

## API

Leitura (pública)

- `GET /contribuintes/meta` — fontes, tipos e agendamento.
- `GET /contribuintes/status` — volumetria, distribuições (tipo, país, fonte,
  papel, **distrito e concelho**), `types_by_district` (matriz tipo × distrito),
  valor contratual agregado e histórico.
- `GET /contribuintes/schedule` — cron, próxima execução e últimos resultados.
- `GET /contribuintes/search` — `q`, `source`, `role`, `type`, `country`,
  `is_company`, `has_contracts`, `sort` (`relevance`, `activity`, `contracts`,
  `value`, `name`, `nif`), `page`, `size`.
- `GET /contribuintes/autocomplete?q=` — sugestões (nome/NIF).
- `GET /contribuintes/jobs` e `GET /contribuintes/jobs/{job_id}` — progresso.
- `GET /contribuintes/{nif}` — ficha completa, com `src_*` por fonte.
- `GET /contribuintes/export/{nif}` e `GET /contribuintes/export` — relatórios
  PDF/Excel/CSV (ficha e lista).

Escrita (sessão)

- `POST /contribuintes/sync` — `{"sources": [...], "page_size": 5000, "wait": false}`.
  Sem `sources`, sincronização completa em segundo plano; devolve `job_id`.
- `PUT /contribuintes/schedule` — `{"enabled": true, "cron": "0 3 * * *", "timezone": "Europe/Lisbon"}`.
- `DELETE /contribuintes/index` — esvazia o índice (só administradores).

## Aplicação (chat-ui)

Página `/contribuintes` (aplicação «Contribuintes» no dock e no menu), com
quatro secções:

- **Pesquisa** — caixa com autocompletar (nome/NIF), filtros por tipo, fonte,
  papel, país e ordenação; lista de resultados com etiquetas de papel e a
  **ficha** do contribuinte ao lado (identificação, indicadores, localização,
  evidência detalhada por fonte e controlo da sincronização). A lista e a ficha
exportam-se em **PDF, Excel e CSV** (botões «Relatório», com o logótipo do IQ OS
no PDF e no Excel).
- **Sincronização** — «Sincronizar agora» (todas as fontes), sincronização de
  uma seleção de fontes, progresso em direto (fonte a fonte, contagem escrita),
  esvaziar o índice (administradores) e o histórico das últimas passagens.
- **Agenda** — ligar/desligar a sincronização automática, expressão cron, fuso
  horário, próxima execução e histórico.
- **Cobertura** — indicadores (contribuintes, pessoas coletivas, com contratos,
  com CIRE, com localização, distritos representados), **gráficos** de tipo de
  contribuinte e de distrito, o **grafo composto tipo × distrito**, os concelhos
  com mais contribuintes e as facetas de país, fontes e papéis. Exporta a lista
  dos 1000 contribuintes com mais contratos.

## Ficheiros

| Ficheiro | Papel |
| --- | --- |
| `api/contribuintes_service.py` | Catálogo de fontes, agregação, sincronização, pesquisa e configuração |
| `api/contribuintes_report.py` | Relatórios PDF/Excel/CSV (com a marca do IQ OS) |
| `api/contribuintes_scheduler.py` | Job de cron da sincronização |
| `api/contribuintes_routes.py` | Router `/contribuintes/*` |
| `api/elasticsearch_client.py` | Índice `finance_contribuintes` (constante, analisadores e mapping) |
| `chat-ui/src/contribuintesApi.ts` | Cliente da API no frontend |
| `chat-ui/src/pages/ContribuintesPage.tsx` | Página (pesquisa, sincronização, agenda, cobertura) |
| `_sync_contribuintes.py` | Sincronização pela linha de comandos (registo em `logs/contribuintes_sync.log` e `.json`) |
| `_contribuintes_api_sync.py` | Lança a sincronização pela API e acompanha o job (progresso em direto) |
| `_test_contribuintes_api.py` | Verificação dos endpoints (leitura, escrita e recusa sem sessão) |
| `_test_contribuintes_report.py` | Relatórios (PDF/Excel/CSV), agregações de localização e marca |
| `data/contribuintes/config.json` | Agendamento, página e histórico de sincronizações |

## Operação

```powershell
# Sincronizar tudo (script rápido, fora da API)
c:\LLMFinance\.venv\Scripts\python.exe _sync_contribuintes.py

# Só algumas fontes (funde com o que já está indexado)
c:\LLMFinance\.venv\Scripts\python.exe _sync_contribuintes.py contratos cire

# Lançar pela API e acompanhar o job (progresso em direto)
c:\LLMFinance\.venv\Scripts\python.exe _contribuintes_api_sync.py
```

Na aplicação, a sincronização também se pode lançar por
`POST /contribuintes/sync` (o agendador faz o mesmo quando o cron dispara).
