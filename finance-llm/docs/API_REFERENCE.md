# IQ OS API — referência

Versão `0.4.0` · **361 operações** em **30 grupos**.

> Ficheiro gerado por `python scripts/export_openapi.py`. A especificação completa está em `docs/openapi.json`; a interface interativa corre em `/docs` (Swagger UI) e `/redoc`.

## Grupos

- **core** — Estado do serviço e chat principal. `/health` confirma os modelos e *features* carregados; `/chat` responde seguindo a *skill* do pedido; `/chat/stream` faz streaming SSE.
- **auth** — Contas e sessões: registo, login/logout, perfil, palavra-passe, dispositivos ligados e estatísticas de administração.
- **admin** — Consola de administração: panorama geral, gestão de contas e sessões, visualizador de eventos e leitura de ficheiros de log.
- **rag** — RAG de documentos: carregar PDF, listar/editar/apagar documentos, reprocessar, responder com citações, explicar a resposta e grafo de *chunks*.
- **market** — Mercado e ativos: lista/pesquisa de tickers (Yahoo Finance), preços, informação fundamental, demonstrações financeiras, SEC filings, detentores, recomendações, calendário, notícias, opções, ações societárias, indicadores técnicos e previsão (ARIMA/Kronos).
- **elastic** — Camada Elasticsearch: estado, ingestão de preços/notícias, pesquisa (preços, notícias, global, autocomplete), análise NLP de notícias, grafo de notícias/entidades e índices da plataforma.
- **contratos** — Contratos públicos portugueses (BASE.gov): pesquisa e ficha, analytics e agregações, região/NUTS, rede de entidades, relações adjudicante↔adjudicatário, grafos por dimensão, ingestão e exportação Excel/PDF.
- **contratos-es** — Contratos públicos de Espanha (PLACSP): volumetria, metadados e listas CODICE, analytics do dashboard, pesquisa, autocomplete, entidades, importação por ano e detalhe de contrato.
- **empresas** — Cadastro de entidades e empresas: pesquisa (GET/POST), estatísticas, países, autocomplete, ficha por NIF, contratos, analytics, marcas (INPI) e firmas (RNPC), enriquecimento a partir dos serviços públicos.
- **companies-global** — Pesquisa global de empresas em todas as fontes (entidades, firmas, marcas, órgãos e adjudicatárias de Espanha, CRM), com contagem por fonte.
- **search** — Pesquisa unificada da plataforma: âmbitos disponíveis, pesquisa em paralelo com resultados agrupados e sugestões para autocompletar.
- **search360** — Dossiê 360: pesquisa federada por tema, biblioteca organizada, grafo de navegação, síntese com citações, projetos e dossiês guardados (criar, refrescar, exportar).
- **hermes** — Investigador Hermes: metamodelo (modos, fontes, índices) e `/hermes/ask` para respostas citadas com evidências e sub-perguntas.
- **researcher** — Agente de investigação com *audit trail* e catálogo fechado de ferramentas.
- **agents** — Agentes dinâmicos (LangGraph): criar/editar/remover configurações, executar (normal ou SSE) e catálogo de ferramentas disponíveis.
- **ontology** — Ontologia: tipos de objeto e de ligação, ações, consulta de objetos, resolução de entidades, contexto/resposta factuais, validação anti-alucinação, desenho e sugestões com IA, projetos, fichas e fontes de dados.
- **crm** — CRM: metamodelo (fases, estados, tipos), panorama do pipeline, contas, contactos, oportunidades, atividades, ligação ao EmpresasIQ e criação/edição de registos.
- **office** — Office: documentos Markdown com pastas e etiquetas, estatísticas, duplicar, exportar (MD/HTML) e trazer dossiês 360 como documentos editáveis.
- **email** — Correio: contas IMAP/SMTP, pastas e mensagens, sinalizadores, mover, apagar e enviar (com anexos).
- **sentiment** — Análise de sentimento: fontes disponíveis, motores (léxico/neural), análise de texto livre e de corpora, gravação em dossiê e em documento Office.
- **visualizador** — Business Intelligence: catálogo de datasets, consultas analíticas (dimensões × medidas × fórmulas), registos (drill-through), valores de dimensão, exportação CSV/Excel e dashboards (templates, guardar, duplicar, exportar).
- **scraper** — Recolha de dados (scraping): definições de fontes, pré-visualização, sugestão assistida por IA, execuções e itens recolhidos, pesquisa no corpus recolhido e agendamentos (cron).
- **vectors** — Embeddings e pesquisa semântica: indexar embeddings, estado das tarefas, pesquisa vetorial/híbrida e garantia de mapeamentos `dense_vector`.
- **skills** — Biblioteca de *skills* (métodos) usada pelos assistentes: listar, guardar, escolher a skill de uma pergunta, garantir/criar, editar e apagar.
- **providers** — Fornecedores de IA (OpenAI, DeepSeek, Ollama, …): catálogo com estado das chaves, modelos disponíveis para o chat, guardar chaves e predefinições, e teste de ligação.
- **cli** — Terminal da interface: comandos disponíveis e execução de comandos do CLI do IQ OS.
- **proxy** — Proxy para ler páginas externas e incorporá-las na interface (iframe), com limites e estado.
- **dossier** — Dossier do utilizador: fichas favoritas (entidades e contratos) e pastas/histórico de consultas.
- **import** — Importação de ficheiros (.zip/.xlsx/.json): pré-visualização das linhas e indexação (contratos no Elasticsearch, entidades em JSONL).
- **spa** — Páginas da interface (single-page app). Devolvem o `index.html` e existem para permitir abrir os ecrãs diretamente pelo endereço — não são endpoints de dados.

## core

Estado do serviço e chat principal. `/health` confirma os modelos e *features* carregados; `/chat` responde seguindo a *skill* do pedido; `/chat/stream` faz streaming SSE.

| Método | Caminho | Resumo |
| --- | --- | --- |
| `GET` | `/` | Read Root |
| `POST` | `/chat` | Chat |
| `POST` | `/chat/stream` | Chat Stream Post |
| `GET` | `/chat/stream` | Chat Stream Get |
| `GET` | `/health` | Health |
| `GET` | `/openapi/export` | Openapi Export |
| `GET` | `/openapi/summary` | Openapi Summary |

## auth

Contas e sessões: registo, login/logout, perfil, palavra-passe, dispositivos ligados e estatísticas de administração.

| Método | Caminho | Resumo |
| --- | --- | --- |
| `POST` | `/auth/login` | Login |
| `POST` | `/auth/logout` | Logout |
| `GET` | `/auth/me` | Me |
| `PATCH` | `/auth/me` | Update Me |
| `DELETE` | `/auth/me` | Delete Me |
| `POST` | `/auth/password` | Change Password |
| `POST` | `/auth/register` | Register |
| `GET` | `/auth/sessions` | Sessions |
| `DELETE` | `/auth/sessions` | Revoke Other Sessions |
| `DELETE` | `/auth/sessions/{session_id}` | Revoke Session |
| `GET` | `/auth/stats` | Stats |

## admin

Consola de administração: panorama geral, gestão de contas e sessões, visualizador de eventos e leitura de ficheiros de log.

| Método | Caminho | Resumo |
| --- | --- | --- |
| `GET` | `/admin/events` | Admin Events |
| `POST` | `/admin/events` | Admin Create Event |
| `GET` | `/admin/events/stats` | Admin Events Stats |
| `GET` | `/admin/logs` | Admin Logs |
| `GET` | `/admin/logs/{name}` | Admin Log Tail |
| `GET` | `/admin/overview` | Admin Overview |
| `GET` | `/admin/users` | Admin Users |
| `PATCH` | `/admin/users/{user_id}` | Admin Update User |
| `DELETE` | `/admin/users/{user_id}` | Admin Delete User |
| `POST` | `/admin/users/{user_id}/revoke-sessions` | Admin Revoke Sessions |

## rag

RAG de documentos: carregar PDF, listar/editar/apagar documentos, reprocessar, responder com citações, explicar a resposta e grafo de *chunks*.

| Método | Caminho | Resumo |
| --- | --- | --- |
| `POST` | `/rag/chat` | Rag Chat |
| `POST` | `/rag/chat/stream` | Rag Chat Stream |
| `GET` | `/rag/documents` | List Documents |
| `GET` | `/rag/documents/{doc_id}` | Get Document |
| `PATCH` | `/rag/documents/{doc_id}` | Update Document |
| `DELETE` | `/rag/documents/{doc_id}` | Delete Document |
| `GET` | `/rag/documents/{doc_id}/graph` | Get Document Graph |
| `GET` | `/rag/documents/{doc_id}/history` | Document History |
| `POST` | `/rag/documents/{doc_id}/reprocess` | Reprocess Document |
| `POST` | `/rag/explain` | Explain Rag Answer |
| `POST` | `/rag/upload` | Upload Pdf |

## market

Mercado e ativos: lista/pesquisa de tickers (Yahoo Finance), preços, informação fundamental, demonstrações financeiras, SEC filings, detentores, recomendações, calendário, notícias, opções, ações societárias, indicadores técnicos e previsão (ARIMA/Kronos).

| Método | Caminho | Resumo |
| --- | --- | --- |
| `POST` | `/forecast` | Forecast |
| `GET` | `/forecast/plot/{filename}` | Forecast Plot |
| `POST` | `/sentiment/analyze/{ticker}` | Sentiment Analyze |
| `GET` | `/tickers` | List Tickers |
| `POST` | `/tickers/add` | Add New Ticker |
| `GET` | `/tickers/search/yahoo` | Yahoo Ticker Search |
| `GET` | `/tickers/{ticker}/actions` | Ticker Actions |
| `GET` | `/tickers/{ticker}/calendar` | Ticker Calendar |
| `GET` | `/tickers/{ticker}/financials` | Ticker Financials |
| `GET` | `/tickers/{ticker}/history` | Ticker History |
| `GET` | `/tickers/{ticker}/holders` | Ticker Holders |
| `GET` | `/tickers/{ticker}/info` | Ticker Info |
| `GET` | `/tickers/{ticker}/news` | Ticker News |
| `GET` | `/tickers/{ticker}/options` | Ticker Options |
| `GET` | `/tickers/{ticker}/recommendations` | Ticker Recommendations |
| `GET` | `/tickers/{ticker}/sec-filings` | Ticker Sec Filings |
| `GET` | `/tickers/{ticker}/sustainability` | Ticker Sustainability |
| `GET` | `/tickers/{ticker}/technical` | Ticker Technical |
| `GET` | `/tickers/{ticker}/technical/explain` | Ticker Technical Explain |

## elastic

Camada Elasticsearch: estado, ingestão de preços/notícias, pesquisa (preços, notícias, global, autocomplete), análise NLP de notícias, grafo de notícias/entidades e índices da plataforma.

| Método | Caminho | Resumo |
| --- | --- | --- |
| `POST` | `/elastic/analyze/news/{ticker}` | Elastic Analyze News |
| `GET` | `/elastic/graph/news/{ticker}` | Elastic News Graph |
| `GET` | `/elastic/indices` | Elastic List Indices |
| `POST` | `/elastic/ingest/news/{ticker}` | Elastic Ingest News |
| `POST` | `/elastic/ingest/prices/{ticker}` | Elastic Ingest Prices |
| `POST` | `/elastic/ingest/{ticker}` | Elastic Ingest Ticker |
| `GET` | `/elastic/search/autocomplete` | Elastic Search Autocomplete |
| `GET` | `/elastic/search/global` | Elastic Search Global |
| `GET` | `/elastic/search/news/{ticker}` | Elastic Search News |
| `GET` | `/elastic/search/prices/{ticker}` | Elastic Search Prices |
| `GET` | `/elastic/status` | Elastic Status |
| `GET` | `/elastic/tickers` | Elastic List Tickers |
| `DELETE` | `/elastic/tickers/{ticker}` | Elastic Delete Ticker |

## contratos

Contratos públicos portugueses (BASE.gov): pesquisa e ficha, analytics e agregações, região/NUTS, rede de entidades, relações adjudicante↔adjudicatário, grafos por dimensão, ingestão e exportação Excel/PDF.

| Método | Caminho | Resumo |
| --- | --- | --- |
| `GET` | `/contracts/analytics` | Contracts Analytics |
| `GET` | `/contracts/analytics/graph` | Contracts Graph |
| `GET` | `/contracts/analytics/graph/dimensions` | Contracts Graph Dimensions |
| `GET` | `/contracts/analytics/network` | Contracts Network |
| `GET` | `/contracts/analytics/regional` | Contracts Regional Analytics |
| `GET` | `/contracts/analytics/relations` | Contracts Relations |
| `GET` | `/contracts/autocomplete` | Contracts Autocomplete Endpoint |
| `POST` | `/contracts/chat` | Contracts Chat |
| `POST` | `/contracts/export/excel` | Contracts Export Excel |
| `POST` | `/contracts/export/pdf` | Contracts Export Pdf |
| `POST` | `/contracts/ingest` | Contracts Ingest |
| `POST` | `/contracts/search` | Contracts Search |
| `GET` | `/contracts/status` | Contracts Status Endpoint |
| `GET` | `/contracts/years` | Contracts Years |
| `GET` | `/contracts/{idcontrato}` | Contract Detail |
| `POST` | `/contracts/{idcontrato}/analyze` | Analyze Contract Endpoint |

## contratos-es

Contratos públicos de Espanha (PLACSP): volumetria, metadados e listas CODICE, analytics do dashboard, pesquisa, autocomplete, entidades, importação por ano e detalhe de contrato.

| Método | Caminho | Resumo |
| --- | --- | --- |
| `GET` | `/contracts-es/analytics` | Contratos Es Analytics Endpoint |
| `GET` | `/contracts-es/autocomplete` | Contratos Es Autocomplete Endpoint |
| `GET` | `/contracts-es/entities` | Contratos Es Entities Endpoint |
| `POST` | `/contracts-es/import` | Contratos Es Import Endpoint |
| `GET` | `/contracts-es/import/{job_id}` | Contratos Es Import Status Endpoint |
| `GET` | `/contracts-es/imports` | Contratos Es Imports Endpoint |
| `GET` | `/contracts-es/meta` | Contratos Es Meta |
| `POST` | `/contracts-es/search` | Contratos Es Search Endpoint |
| `GET` | `/contracts-es/status` | Contratos Es Status Endpoint |
| `GET` | `/contracts-es/{doc_id}` | Contrato Es Detail Endpoint |

## empresas

Cadastro de entidades e empresas: pesquisa (GET/POST), estatísticas, países, autocomplete, ficha por NIF, contratos, analytics, marcas (INPI) e firmas (RNPC), enriquecimento a partir dos serviços públicos.

| Método | Caminho | Resumo |
| --- | --- | --- |
| `POST` | `/companies/role-summary` | Companies Role Summary |
| `POST` | `/companies/search` | Companies Search |
| `GET` | `/companies/{nif}` | Companies Detail |
| `GET` | `/companies/{nif}/analytics` | Companies Analytics |
| `GET` | `/companies/{nif}/contracts` | Companies Contracts |
| `POST` | `/companies/{nif}/enrich` | Companies Enrich |
| `GET` | `/companies/{nif}/firmas` | Companies Firmas |
| `GET` | `/companies/{nif}/trademarks` | Companies Trademarks |
| `GET` | `/enrichment/indices` | Enrichment Indices |
| `GET` | `/entities/autocomplete` | Entities Autocomplete |
| `GET` | `/entities/countries` | Entities Countries |
| `POST` | `/entities/ingest` | Entities Ingest |
| `GET` | `/entities/search` | Entities Search Get |
| `POST` | `/entities/search` | Entities Search Post |
| `GET` | `/entities/stats` | Entities Stats |
| `GET` | `/entities/{nif}` | Entities Detail |
| `POST` | `/firmas/ingest` | Firmas Ingest |
| `GET` | `/firmas/search` | Firmas Search |
| `POST` | `/firmas/search` | Firmas Search Post |
| `POST` | `/trademarks/ingest` | Trademarks Ingest |
| `GET` | `/trademarks/search` | Trademarks Search |
| `POST` | `/trademarks/search` | Trademarks Search Post |

## companies-global

Pesquisa global de empresas em todas as fontes (entidades, firmas, marcas, órgãos e adjudicatárias de Espanha, CRM), com contagem por fonte.

| Método | Caminho | Resumo |
| --- | --- | --- |
| `GET` | `/companies-global/search` | Companies Global Search |
| `GET` | `/companies-global/sources` | Companies Global Sources |

## search

Pesquisa unificada da plataforma: âmbitos disponíveis, pesquisa em paralelo com resultados agrupados e sugestões para autocompletar.

| Método | Caminho | Resumo |
| --- | --- | --- |
| `GET` | `/search/scopes` | Search Scopes |
| `GET` | `/search/suggest` | Search Suggest |
| `GET` | `/search/unified` | Search Unified |

## search360

Dossiê 360: pesquisa federada por tema, biblioteca organizada, grafo de navegação, síntese com citações, projetos e dossiês guardados (criar, refrescar, exportar).

| Método | Caminho | Resumo |
| --- | --- | --- |
| `POST` | `/search360/ai/synthesis` | Synthesis |
| `POST` | `/search360/cache/clear` | Clear Cache |
| `GET` | `/search360/dossiers` | List Dossiers |
| `POST` | `/search360/dossiers` | Save Dossier |
| `GET` | `/search360/dossiers/{dossier_id}` | Get Dossier |
| `PATCH` | `/search360/dossiers/{dossier_id}` | Rename Dossier |
| `DELETE` | `/search360/dossiers/{dossier_id}` | Delete Dossier |
| `GET` | `/search360/dossiers/{dossier_id}/export` | Export Dossier |
| `POST` | `/search360/dossiers/{dossier_id}/refresh` | Refresh Dossier |
| `POST` | `/search360/graph` | Graph |
| `POST` | `/search360/library` | Library |
| `GET` | `/search360/meta` | Meta |
| `GET` | `/search360/projects` | List Projects |
| `POST` | `/search360/projects` | Save Project |
| `DELETE` | `/search360/projects/{project_id}` | Delete Project |
| `POST` | `/search360/search` | Search |
| `GET` | `/search360/status` | Status |
| `GET` | `/search360/suggest` | Suggest |
| `POST` | `/search360/topic` | Topic |

## hermes

Investigador Hermes: metamodelo (modos, fontes, índices) e `/hermes/ask` para respostas citadas com evidências e sub-perguntas.

| Método | Caminho | Resumo |
| --- | --- | --- |
| `POST` | `/hermes/ask` | Ask |
| `GET` | `/hermes/meta` | Meta |

## researcher

Agente de investigação com *audit trail* e catálogo fechado de ferramentas.

| Método | Caminho | Resumo |
| --- | --- | --- |
| `POST` | `/researcher/investigate` | Researcher Investigate |
| `GET` | `/researcher/tools` | List Researcher Tools |

## agents

Agentes dinâmicos (LangGraph): criar/editar/remover configurações, executar (normal ou SSE) e catálogo de ferramentas disponíveis.

| Método | Caminho | Resumo |
| --- | --- | --- |
| `GET` | `/agents` | List Agents |
| `POST` | `/agents` | Create Or Update Agent |
| `GET` | `/agents/tools/catalog` | Tools Catalog |
| `GET` | `/agents/{agent_id}` | Get Agent |
| `DELETE` | `/agents/{agent_id}` | Delete Agent |
| `POST` | `/agents/{agent_id}/run` | Run Agent Endpoint |
| `POST` | `/agents/{agent_id}/stream` | Stream Agent Endpoint |

## ontology

Ontologia: tipos de objeto e de ligação, ações, consulta de objetos, resolução de entidades, contexto/resposta factuais, validação anti-alucinação, desenho e sugestões com IA, projetos, fichas e fontes de dados.

| Método | Caminho | Resumo |
| --- | --- | --- |
| `GET` | `/ontology` | Get Ontology |
| `GET` | `/ontology/actions` | List Actions |
| `POST` | `/ontology/actions/{action_id}/resolve` | Resolve Action |
| `GET` | `/ontology/active` | Active Ontology |
| `POST` | `/ontology/ai/answer` | Ai Answer |
| `POST` | `/ontology/ai/context` | Ai Context |
| `POST` | `/ontology/ai/design` | Ai Design |
| `POST` | `/ontology/ai/dossier` | Ai Dossier |
| `POST` | `/ontology/ai/extract` | Ai Extract |
| `POST` | `/ontology/ai/suggest-links` | Ai Suggest Links |
| `GET` | `/ontology/ai/tools` | Ai Tools |
| `POST` | `/ontology/ai/validate` | Validate |
| `GET` | `/ontology/dossiers` | List Dossiers |
| `POST` | `/ontology/dossiers` | Upsert Dossier |
| `DELETE` | `/ontology/dossiers/{dossier_id}` | Delete Dossier |
| `POST` | `/ontology/dossiers/{dossier_id}/draft` | Draft Dossier |
| `POST` | `/ontology/dossiers/{dossier_id}/facts` | Dossier Facts |
| `GET` | `/ontology/graph` | Get Graph |
| `POST` | `/ontology/graph/explore` | Explore Graph |
| `GET` | `/ontology/link-types` | List Link Types |
| `POST` | `/ontology/link-types` | Upsert Link Type |
| `PATCH` | `/ontology/link-types/{link_id}` | Patch Link Type |
| `DELETE` | `/ontology/link-types/{link_id}` | Delete Link Type |
| `GET` | `/ontology/object-types` | List Object Types |
| `POST` | `/ontology/object-types` | Upsert Object Type |
| `GET` | `/ontology/object-types/{type_id}` | Get Object Type Detail |
| `PATCH` | `/ontology/object-types/{type_id}` | Patch Object Type |
| `DELETE` | `/ontology/object-types/{type_id}` | Delete Object Type |
| `POST` | `/ontology/objects/{type_id}/query` | Query Objects |
| `GET` | `/ontology/objects/{type_id}/{object_id}` | Get Object |
| `POST` | `/ontology/objects/{type_id}/{object_id}/links` | Get Object Links |
| `GET` | `/ontology/ontologies` | List Ontologies |
| `POST` | `/ontology/ontologies` | Create Ontology |
| `PATCH` | `/ontology/ontologies/{ontology_id}` | Update Ontology |
| `DELETE` | `/ontology/ontologies/{ontology_id}` | Delete Ontology |
| `GET` | `/ontology/projects` | List Projects |
| `POST` | `/ontology/projects` | Upsert Project |
| `GET` | `/ontology/projects/{project_id}` | Get Project |
| `DELETE` | `/ontology/projects/{project_id}` | Delete Project |
| `POST` | `/ontology/reset` | Reset |
| `POST` | `/ontology/resolve` | Resolve Entities |
| `GET` | `/ontology/sources` | List Sources |
| `POST` | `/ontology/sources` | Upsert Source |
| `DELETE` | `/ontology/sources/{source_id}` | Delete Source |
| `POST` | `/ontology/sources/{source_id}/infer` | Infer From Source |
| `POST` | `/ontology/sources/{source_id}/probe` | Probe Source |
| `GET` | `/ontology/status` | Get Status |
| `GET` | `/ontology/summary` | Get Summary |

## crm

CRM: metamodelo (fases, estados, tipos), panorama do pipeline, contas, contactos, oportunidades, atividades, ligação ao EmpresasIQ e criação/edição de registos.

| Método | Caminho | Resumo |
| --- | --- | --- |
| `GET` | `/crm/accounts` | Accounts List |
| `POST` | `/crm/accounts/from-entity` | Account From Entity |
| `POST` | `/crm/accounts/{account_id}/sync-entity` | Account Sync Entity |
| `GET` | `/crm/accounts/{account_id}/timeline` | Account Timeline |
| `GET` | `/crm/activities` | Activities List |
| `GET` | `/crm/contacts` | Contacts List |
| `GET` | `/crm/deals` | Deals List |
| `GET` | `/crm/entities/search` | Entities Search |
| `GET` | `/crm/meta` | Crm Meta |
| `GET` | `/crm/overview` | Crm Overview |
| `POST` | `/crm/{kind}` | Record Create |
| `GET` | `/crm/{kind}/{record_id}` | Record Get |
| `PATCH` | `/crm/{kind}/{record_id}` | Record Update |
| `DELETE` | `/crm/{kind}/{record_id}` | Record Delete |

## office

Office: documentos Markdown com pastas e etiquetas, estatísticas, duplicar, exportar (MD/HTML) e trazer dossiês 360 como documentos editáveis.

| Método | Caminho | Resumo |
| --- | --- | --- |
| `GET` | `/office/documents` | List Documents |
| `POST` | `/office/documents` | Save Document |
| `POST` | `/office/documents/from-dossier/{dossier_id}` | Document From Dossier |
| `GET` | `/office/documents/{document_id}` | Get Document |
| `PATCH` | `/office/documents/{document_id}` | Patch Document |
| `DELETE` | `/office/documents/{document_id}` | Delete Document |
| `POST` | `/office/documents/{document_id}/duplicate` | Duplicate Document |
| `GET` | `/office/documents/{document_id}/export` | Export Document |
| `GET` | `/office/dossiers/available` | Available Dossiers |
| `GET` | `/office/folders` | List Folders |
| `POST` | `/office/folders` | Save Folder |
| `DELETE` | `/office/folders/{folder_id}` | Delete Folder |
| `GET` | `/office/stats` | Stats |

## email

Correio: contas IMAP/SMTP, pastas e mensagens, sinalizadores, mover, apagar e enviar (com anexos).

| Método | Caminho | Resumo |
| --- | --- | --- |
| `GET` | `/email/accounts` | List Accounts |
| `POST` | `/email/accounts` | Save Account |
| `POST` | `/email/accounts/test` | Test New Account |
| `DELETE` | `/email/accounts/{account_id}` | Delete Account |
| `GET` | `/email/accounts/{account_id}/folders` | List Folders |
| `GET` | `/email/accounts/{account_id}/messages` | List Messages |
| `GET` | `/email/accounts/{account_id}/messages/{uid}` | Get Message |
| `DELETE` | `/email/accounts/{account_id}/messages/{uid}` | Delete Message |
| `POST` | `/email/accounts/{account_id}/messages/{uid}/flags` | Set Flags |
| `POST` | `/email/accounts/{account_id}/messages/{uid}/move` | Move Message |
| `POST` | `/email/accounts/{account_id}/send` | Send Message |
| `POST` | `/email/accounts/{account_id}/test` | Test Account |
| `GET` | `/email/meta` | Meta |
| `GET` | `/email/stats` | Stats |

## sentiment

Análise de sentimento: fontes disponíveis, motores (léxico/neural), análise de texto livre e de corpora, gravação em dossiê e em documento Office.

| Método | Caminho | Resumo |
| --- | --- | --- |
| `POST` | `/sentiment/analyze` | Analyze |
| `POST` | `/sentiment/corpus` | Analyze Corpus |
| `GET` | `/sentiment/meta` | Sentiment Meta |
| `POST` | `/sentiment/save/dossier` | Save To Dossier |
| `POST` | `/sentiment/save/office` | Save To Office |
| `GET` | `/sentiment/sources` | Sentiment Sources |

## visualizador

Business Intelligence: catálogo de datasets, consultas analíticas (dimensões × medidas × fórmulas), registos (drill-through), valores de dimensão, exportação CSV/Excel e dashboards (templates, guardar, duplicar, exportar).

| Método | Caminho | Resumo |
| --- | --- | --- |
| `GET` | `/visualizador/dashboards` | List Dashboards |
| `POST` | `/visualizador/dashboards` | Save Dashboard |
| `GET` | `/visualizador/dashboards/{dashboard_id}` | Get Dashboard |
| `DELETE` | `/visualizador/dashboards/{dashboard_id}` | Delete Dashboard |
| `POST` | `/visualizador/dashboards/{dashboard_id}/duplicate` | Duplicate Dashboard |
| `GET` | `/visualizador/datasets/{dataset_id}` | Visualizador Dataset |
| `POST` | `/visualizador/export/csv` | Visualizador Export Csv |
| `GET` | `/visualizador/export/dashboards` | Export Dashboards |
| `POST` | `/visualizador/export/xlsx` | Visualizador Export Xlsx |
| `GET` | `/visualizador/meta` | Visualizador Meta |
| `POST` | `/visualizador/query` | Visualizador Query |
| `POST` | `/visualizador/records` | Visualizador Records |
| `GET` | `/visualizador/templates` | List Templates |
| `POST` | `/visualizador/templates/{template_id}/dashboard` | Create From Template |
| `POST` | `/visualizador/values` | Visualizador Values |

## scraper

Recolha de dados (scraping): definições de fontes, pré-visualização, sugestão assistida por IA, execuções e itens recolhidos, pesquisa no corpus recolhido e agendamentos (cron).

| Método | Caminho | Resumo |
| --- | --- | --- |
| `GET` | `/scraper/jobs` | List Jobs |
| `POST` | `/scraper/jobs/reload` | Reload Jobs |
| `GET` | `/scraper/meta` | Scraper Meta |
| `POST` | `/scraper/preview` | Preview Source |
| `GET` | `/scraper/runs` | List Runs |
| `GET` | `/scraper/runs/{run_id}` | Get Run |
| `GET` | `/scraper/runs/{run_id}/items` | Get Run Items |
| `GET` | `/scraper/search` | Search Scraped Items |
| `GET` | `/scraper/sources` | List Sources |
| `POST` | `/scraper/sources` | Create Source |
| `GET` | `/scraper/sources/{source_id}` | Get Source |
| `PATCH` | `/scraper/sources/{source_id}` | Update Source |
| `DELETE` | `/scraper/sources/{source_id}` | Delete Source |
| `POST` | `/scraper/sources/{source_id}/preview` | Preview Saved Source |
| `POST` | `/scraper/sources/{source_id}/run` | Run Source |
| `GET` | `/scraper/sources/{source_id}/runs` | List Source Runs |
| `GET` | `/scraper/stats` | Scraper Stats |
| `GET` | `/scraper/status` | Scraper Availability |
| `POST` | `/scraper/suggest` | Suggest Source |

## vectors

Embeddings e pesquisa semântica: indexar embeddings, estado das tarefas, pesquisa vetorial/híbrida e garantia de mapeamentos `dense_vector`.

| Método | Caminho | Resumo |
| --- | --- | --- |
| `POST` | `/elastic/vectors/ensure-mappings` | Ensure Mappings |
| `POST` | `/elastic/vectors/index` | Index Embeddings |
| `GET` | `/elastic/vectors/index/jobs` | List Index Jobs |
| `GET` | `/elastic/vectors/index/jobs/{job_id}` | Get Index Job |
| `POST` | `/elastic/vectors/search` | Vector Search |
| `GET` | `/elastic/vectors/status` | Vector Status |

## skills

Biblioteca de *skills* (métodos) usada pelos assistentes: listar, guardar, escolher a skill de uma pergunta, garantir/criar, editar e apagar.

| Método | Caminho | Resumo |
| --- | --- | --- |
| `GET` | `/skills` | List Skills |
| `POST` | `/skills` | Save Skill |
| `DELETE` | `/skills` | Clear Skills |
| `POST` | `/skills/ensure` | Ensure Skill |
| `POST` | `/skills/match` | Match Skill |
| `GET` | `/skills/{skill_id}` | Get Skill |
| `PATCH` | `/skills/{skill_id}` | Patch Skill |
| `DELETE` | `/skills/{skill_id}` | Delete Skill |

## providers

Fornecedores de IA (OpenAI, DeepSeek, Ollama, …): catálogo com estado das chaves, modelos disponíveis para o chat, guardar chaves e predefinições, e teste de ligação.

| Método | Caminho | Resumo |
| --- | --- | --- |
| `GET` | `/providers` | List Providers |
| `GET` | `/providers/chat-models` | Chat Models |
| `PUT` | `/providers/defaults` | Save Defaults |
| `PUT` | `/providers/keys` | Save Key |
| `GET` | `/providers/ollama-cloud/models` | Ollama Cloud Models |
| `POST` | `/providers/test` | Test Provider |

## cli

Terminal da interface: comandos disponíveis e execução de comandos do CLI do IQ OS.

| Método | Caminho | Resumo |
| --- | --- | --- |
| `GET` | `/cli/commands` | Cli Commands |
| `POST` | `/cli/run` | Cli Run |

## proxy

Proxy para ler páginas externas e incorporá-las na interface (iframe), com limites e estado.

| Método | Caminho | Resumo |
| --- | --- | --- |
| `GET` | `/proxy` | Proxy Get |
| `POST` | `/proxy` | Proxy Post |
| `GET` | `/proxy/status` | Proxy Status |

## dossier

Dossier do utilizador: fichas favoritas (entidades e contratos) e pastas/histórico de consultas.

| Método | Caminho | Resumo |
| --- | --- | --- |
| `GET` | `/favorites` | Favorites List |
| `PUT` | `/favorites` | Favorites Save |
| `DELETE` | `/favorites` | Favorites Clear |
| `DELETE` | `/favorites/{kind}/{item_id}` | Favorites Delete |
| `GET` | `/workspace` | Workspace Get |
| `PUT` | `/workspace/folders/{folder_id}` | Workspace Save Folder |
| `DELETE` | `/workspace/folders/{folder_id}` | Workspace Delete Folder |
| `PUT` | `/workspace/history` | Workspace Save History |

## import

Importação de ficheiros (.zip/.xlsx/.json): pré-visualização das linhas e indexação (contratos no Elasticsearch, entidades em JSONL).

| Método | Caminho | Resumo |
| --- | --- | --- |
| `POST` | `/import/ingest` | Import Ingest |
| `POST` | `/import/preview` | Import Preview |

## spa

Páginas da interface (single-page app). Devolvem o `index.html` e existem para permitir abrir os ecrãs diretamente pelo endereço — não são endpoints de dados.

| Método | Caminho | Resumo |
| --- | --- | --- |
| `GET` | `/adjudicantes` | Serve Entities Spa Page |
| `GET` | `/adjudicatarios` | Serve Entities Spa Page |
| `GET` | `/companies` | Serve Companies Spa Page |
| `GET` | `/companies/dashboard` | Serve Companies Spa Page |
| `GET` | `/companies/search` | Serve Companies Spa Page |
| `GET` | `/contracts` | Página da interface (SPA) |
| `GET` | `/contracts/dashboard` | Página da interface (SPA) |
| `GET` | `/contracts/search` | Página da interface (SPA) |
| `GET` | `/crm` | Página da interface (SPA) |
| `GET` | `/crm/agenda` | Página da interface (SPA) |
| `GET` | `/crm/contactos` | Página da interface (SPA) |
| `GET` | `/crm/contas` | Página da interface (SPA) |
| `GET` | `/crm/relatorios` | Página da interface (SPA) |
| `GET` | `/elastic` | Página da interface (SPA) |
| `GET` | `/empresas-global` | Página da interface (SPA) |
| `GET` | `/empresas-iq` | Página da interface (SPA) |
| `GET` | `/entities/adjudicantes` | Serve Entities Spa Page |
| `GET` | `/entities/adjudicatarios` | Serve Entities Spa Page |
| `GET` | `/entities/compare` | Serve Entities Spa Page |
| `GET` | `/entities/dashboard` | Serve Entities Spa Page |
| `GET` | `/forecast` | Página da interface (SPA) |
| `GET` | `/hermes` | Página da interface (SPA) |
| `GET` | `/import` | Página da interface (SPA) |
| `GET` | `/office` | Página da interface (SPA) |
| `GET` | `/office/documentos` | Página da interface (SPA) |
| `GET` | `/office/dossies` | Página da interface (SPA) |
| `GET` | `/pesquisa` | Página da interface (SPA) |
| `GET` | `/rag` | Página da interface (SPA) |
| `GET` | `/scraper` | Página da interface (SPA) |
| `GET` | `/scraper/agenda` | Página da interface (SPA) |
| `GET` | `/scraper/execucoes` | Página da interface (SPA) |
| `GET` | `/scraper/fontes` | Página da interface (SPA) |
| `GET` | `/scraper/pesquisa` | Página da interface (SPA) |
| `GET` | `/search` | Página da interface (SPA) |
| `GET` | `/search360` | Página da interface (SPA) |
| `GET` | `/search360/biblioteca` | Página da interface (SPA) |
| `GET` | `/search360/dossie` | Página da interface (SPA) |
| `GET` | `/search360/grafo` | Página da interface (SPA) |
| `GET` | `/search360/projetos` | Página da interface (SPA) |
| `GET` | `/sentimento` | Página da interface (SPA) |
| `GET` | `/ticker-detail` | Página da interface (SPA) |
| `GET` | `/trading` | Página da interface (SPA) |
| `GET` | `/{full_path}` | Página da interface (SPA) |
