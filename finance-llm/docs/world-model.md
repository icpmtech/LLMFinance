# World Model — do dado público ao relatório de investigação

O **World Model** é a camada que transforma os dados públicos do IQ OS num
**modelo de estado** consultável e simulações. Implementa, de ponta a ponta, o
pipeline:

```
Public Data → World Model → Dynamic Neural Network ↔ Graph/Temporal Engine
                                    ↓
                            Future Simulator → Investigation Agent
```

- **Frontend**: página `World Model` (`/world`, separador *Rede* em `/world/rede`)
  com sete secções: Pipeline, Mundo, Eventos, Grafo, **Rede (grafo)**, Simulador
  e Investigação.
- **Backend**: `api/world_*.py` (rotas, fontes, modelo, grafo/tempo, rede,
  simulador, agente, jobs e agendador).
- **Base de dados**: seis índices no Elasticsearch (estado, eventos, relações,
  estado da rede, simulações e investigações).

---

## 1. Public Data (leituras)

`api/world_sources.py` é o adaptador para os índices que a plataforma já
mantém. Não há recolha nova.

### Fontes do sistema (associáveis)

O conjunto de fontes **não é fixo**: cada fonte do catálogo declara como entra
no mundo (`adapter`) e como se liga às entidades já conhecidas (`join`), e o
utilizador associa/desassocia na página World → *Public Data (fontes do
sistema)* (`PUT /world/sources`). A reconstrução lê **apenas** o que está
associado e o nó *Public Data* do grafo do pipeline mostra exatamente essas
fontes.

| Fonte | Índice | Adaptador | Junção | O que dá | Omissão |
|---|---|---|---|---|---|
| Contratos Públicos (PT) | `contratos` | `contratos` | NIF | adjudicantes/adjudicatários (nested `*.parsed`), valor, CPV, datas | ● obrigatória |
| Contratos Públicos (ES) | `contratos_es` | `contratos_es` | NIF | órgão, adjudicatário, valor, estado (campos planos) | ● |
| Insolvências (CIRE) | `finance_cire` | `insolvencias` | NIF | processos e intervenientes com NIF e papel | ● |
| Pessoas e Cargos | `finance_people` | `pessoas` | NIF | cargos pessoa → empresa | ● |
| Contribuintes | `finance_contribuintes` | `registo` | NIF | designação canónica, tipo, país | ○ |
| Entidades Públicas | `finance_entities` | `registo` | NIF | cadastro (designação, volumetria) | ○ |
| GLEIF LEI | `finance_gleif_lei` | `registo` | nome | identificador LEI, país, forma jurídica | ○ |
| Publicações Societárias (MJ) | `finance_publicacoes_mj` | `publicacoes` | NIF | actos datados (constituição, alterações) | ○ |
| Marcas (INPI) | `finance_trademarks` | `propriedade` | NIF | marcas registadas | ○ |
| Firmas / CAE | `finance_firmas` | `propriedade` | NIF | CAE e situação (atributo) | ○ |
| Menções sociais | `finance_social` | `mencoes` | NIF | menções com sentimento | ○ |
| Recolha de imprensa | `finance_scraped` | `mencoes` | texto | menções na imprensa (nome no título) | ○ |

Regras de honestidade das fontes adicionais:

- **registo** só **enriquece** entidades que já existem (nome, país, tipo,
  `identifiers.lei`, volumetria em falta) — não cria entidades em massa, senão o
  mundo passaria a ser um catálogo de 700 mil contribuintes;
- a junção **por nome** só liga com **igualdade exata** da designação
  normalizada (cada índice tem a sua convenção — no GLEIF é `legal_name_folded`,
  minúsculas com pontuação, pelo que a consulta usa essa normalização);
- **menções** ligam por NIF e, sem NIF, só se o nome da entidade aparecer no
  texto; as que não ligam são contadas e descartadas (`unmatched`);
- nomes ambíguos (a mesma designação em duas entidades) saem do índice de junção
  por nome — mais vale não ligar do que ligar mal.

### Leituras

Duas formas de leitura, ambas limitadas:

- **agregações `terms`** (`pt_party_metrics`, `es_party_metrics`) — contagens e
  somas exatas por entidade, com um teto (`entity_limit`);
- **amostra/junção limitada** (`contract_sample`, `entity_contracts`,
  `insolvency_records`, `people_relations`, `registry_records`,
  `publication_records`, `property_records`, `mention_records`) — os pares,
  valores e datas que alimentam relações, eventos e evidência. As junções por NIF
  vão em blocos de 500 NIF (limite de cláusulas do `terms`).

> **Armadilha validada** (`_probe_world_parties.py`): um `exists` sobre um
> subcampo **nested** (`adjudicatarios.parsed.nif`) devolve **zero**
> documentos; tem de ser embrulhado em `nested`. E `top_hits` dentro de `nested`
> precisa do **caminho completo** no `_source`.

> **Armadilha validada** (`_probe_world_sources.py`): ler uma amostra arbitrária
> do GLEIF e comparar nomes localmente dá **zero** ligações; é preciso consultar o
> campo normalizado do índice (`legal_name_folded`) com os nomes do mundo, em
> blocos — assim ligaram 199 entidades (198 com LEI).

---

## 2. World Model (estado, eventos, relações)

`api/world_model.py` constrói o mundo e grava-o em três índices:

| Índice | Documento | Conteúdo |
|---|---|---|
| `finance_world_state` | `entity_ref` (`entidade:<nif>` ou `pessoa:<id>`) | tipo, país, papéis, contagens, valor, risco, atividade, estado |
| `finance_world_events` | `event_id` | adjudicação, contratação, cessação, insolvência e relação criada |
| `finance_world_relations` | `relation_id` | aresta (adjudicou / cargo_em) com peso, valor, datas e evidência |

### Modelação (explícita)

- **Risco** (0–1, heurístico): insolvência declarada (0,45), papel em CIRE sem
  insolvência (0,12), concentração de clientes (0,20), dimensão (0,10), valor
  (0,10) e inatividade (0,13). Rótulos: `baixo` < 0,34 ≤ `médio` < 0,62 ≤
  `elevado`. **Não** é um modelo de crédito validado.
- **Atividade**: eventos nos últimos 12 meses normalizados pelo máximo; a
  tendência compara com os 12 meses anteriores.
- **Concentração**: só sobre relações **comerciais** (`adjudicou`) e só com
  ≥ 3 clientes distintos — com uma ou duas arestas o valor seria sempre 100 %.
  `state.concentration_reliable` diz se a conclusão é sustentada.
- **Valor e contagem**: as agregações são autoritativas para as entidades que
  cobrem; as restantes usam o acumulado da **amostra** de contratos
  (`metrics.value_source` = `agregação` | `amostra` | `sem dados`).
- Cada documento guarda `world_version`; uma reconstrução completa apaga as
  versões anteriores (`delete_stale`).

### Reconstrução

`POST /world/rebuild` (sessão) — em segundo plano (`job_id`) ou com
`wait=true`. Configurável por `data/world/config.json` (`entity_limit`,
`contract_sample`, `insolvency_sample`, `people_sample`, `year_from`,
limiares de risco e agendamento).

---

## 3. Dynamic Neural Network (mostrada como grafo)

`api/world_neural.py`. A rede é um **grafo dinâmico** sobre o estado do mundo:

- **Nós** = entidades, com features normalizadas
  (`contracts`, `value`, `degree`, `events_recent`, `insolvent`,
  `concentration`, `risk`, `recency`, `is_public_entity`, `is_person`).
  Entram por **dois caminhos**: as mais ativas e as que **participam nas
  relações** (sem estas últimas a rede ficava sem arestas).
- **Arestas** = relações, com peso sináptico: a força observada (contratos,
  saturada em 5) entra na primeira observação e depois é mantida com decaimento
  (`decay`), sendo podada abaixo de `prune_threshold`.
- **Memória** = padrões de atividade por aprendizagem competitiva (online
  k-means sobre as features normalizadas): o padrão mais parecido é aproximado,
  ou cria-se um novo até `memory_size`; padrões não usados durante
  `memory_max_age` ciclos são esquecidos.
- **Previsão** = readout linear (ridge, forma fechada). A atividade recente é
  **excluída** das entradas do readout (seria o próprio alvo) e a qualidade é
  medida numa **amostra de validação de 30 %** — `predictions.readout.r2` é,
  por isso, fora da amostra.

`GET /world/network/graph` devolve a rede **como grafo** para o `GraphCanvas`:
nós (ativados, dimensionados pela ativação, coloridos pelo tipo e com previsão,
risco e memória na dica), sinapses (espessura pelo peso) e, opcionalmente, os
**padrões de memória** como nós ligados à entidade que os recordou.

Outras rotas: `POST /world/network/train`, `GET /world/network` (estado
completo), `/world/network/history` (métricas por ciclo),
`/world/network/recall/{ref}` (padrões mais próximos).

---

## 4. Graph / Temporal Engine

`api/world_graph.py`:

- `GET /world/graph` — ego-rede (BFS por `depth`, limites de nós/arestas).
- `GET /world/centrality` — entidades com maior grau.
- `GET /world/paths` — caminhos mais curtos (BFS, até 3 caminhos simples).
- `GET /world/temporal` — série mensal/anual de eventos e valores.
- `GET /world/causality` — **influência temporal candidata**:
  `score = min(1, peso/10) × (1 − Δdias/janela) × severidade`.
  É uma hipótese para orientar a investigação, **nunca** causalidade provada.

---

## 5. Future Simulator

`api/world_simulator.py`. Monte Carlo (`samples`) sobre três cenários —
**Otimista**, **Base**, **Pessimista** (pesos 25/50/25) — com passos de
`step_months` meses:

| Quantidade | Como é estimada |
|---|---|
| Novos contratos | Poisson com a taxa de eventos/trimestre da série recente, corrigida pela tendência e pela previsão da rede |
| Atrasos | binomial sobre a exposição do passo (contratos novos + 25 % da taxa como carteira herdada), agravada por risco e concentração — **proxy** |
| Cancelamentos | binomial, multiplicada por ~4 em entidades insolventes |
| Novas relações | Poisson sobre o grau × fator de crescimento |
| Δ financeiro | valor bruto − valor cancelado − penalização dos atrasos (8 %/atraso) |
| Risco | rácios (`cancelamentos/exposição`, `atrasos/exposição`, atividade vs. taxa) — evita saturar |

Cada passo devolve média e p10/p50/p90 por quantidade; o cenário matriz mostra a
divergência entre cenários. `POST /world/simulate`, `GET /world/simulations`.

---

## 6. Investigation Agent

`api/world_investigation.py` — `POST /world/investigate` (sessão) corre o ciclo:

1. **Observe** — resolve o sujeito (sujeito indicado → NIF na pergunta →
   designação no mundo) e recolhe estado, métricas, previsão, relações, linha
   temporal e série.
2. **Hypothesize** — regras explícitas sobre o estado (insolvência, papel no
   CIRE, concentração sustentada, queda de atividade, vizinhos em risco,
   carteira assimétrica), cada uma com o modo de a testar.
3. **Search** — evidência com `source_index`/`source_id`, com **teto de 6 itens
   por tipo** (uma entidade que é credora em centenas de insolvências enchia a
   lista).
4. **Validate** — verificações programáticas (soma da evidência vs. valor do
   mundo; insolvência corroborada por CIRE; existência de eventos) e afirmações
   classificadas em `FACT`, `CALCULATION`, `INFERENCE`, `HYPOTHESIS`. As contas
   são feitas em Python.
5. **Simulate** — corre o simulador para o sujeito e anexa as distribuições.
6. **Report** — relatório Markdown com observação, hipóteses, evidência,
   validação, simulação e limitações.

Fica tudo guardado em `finance_world_investigations` (passos, tempos,
hipóteses, evidência, validações, afirmações e relatório) — auditoria completa.

---

## 7. Índices

| Índice | Documento |
|---|---|
| `finance_world_state` | estado por entidade |
| `finance_world_events` | eventos (append-only por versão) |
| `finance_world_relations` | arestas do grafo |
| `finance_network_state` | uma versão por ciclo da rede (nós, arestas, memória, métricas, previsões) |
| `finance_world_simulations` | execuções do simulador (passos, cenários, parâmetros) |
| `finance_world_investigations` | investigações (auditoria + relatório) |

Objetos grandes (listas de nós/arestas, memória, relatório) são guardados mas
**não indexados** (`enabled: false`); o que é pesquisável vive em campos
próprios.

---

## 8. Operação

```powershell
# Reconstruir o mundo (segundo plano) e acompanhar
POST /world/rebuild {"contract_sample": 8000, "entity_limit": 2000}
GET  /world/jobs

# Ciclo da rede (crescimento → poda → memória → previsão)
POST /world/network/train
GET  /world/network/graph?limit=90&memory=true

# Simular e investigar
POST /world/simulate {"subject": "entidade:501234567", "horizon": 4, "samples": 300}
POST /world/investigate {"question": "...", "subject": "503504564"}

# Agendamento (cron) da reconstrução + ciclo da rede
PUT  /world/schedule {"enabled": true, "cron": "0 4 * * *", "train_network": true}

# Fontes do sistema associadas ao Public Data (aplicam-se na reconstrução)
GET  /world/sources
PUT  /world/sources {"ids": ["contratos", "contratos_es", "cire", "pessoas", "contribuintes", "gleif"]}
```

Sondas e testes de apoio: `_probe_world.py` (`--full` reconstrói e treina),
`_probe_world_parties.py` (variantes de filtro nested), `_probe_world_sources.py`
(catálogo → associação → reconstrução → verificação do efeito),
`_test_world_mermaid.py` (identificadores/rótulos Mermaid),
`_test_world_api.py` (ponta a ponta pelas rotas, com sessão de QA) e
`tests/test_world.py`.

### Limitações assumidas

- O mundo assenta em **amostras** de contratos para eventos e relações; as
  contagens por entidade vêm de agregações com teto.
- A causalidade é influência temporal candidata.
- O risco é heurístico; a previsão da rede é transversal (validação de 30 %);
  a simulação usa cenários com pesos subjetivos.
- Nada disto substitui leitura documental: a evidência são metadados indexados.
