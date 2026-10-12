# Inteligência de mercado · empresas, entidades e dependências

Páginas `/mercado` (benchmark) e `/mercado/cenarios` (World Model + sensibilidade) ·
router `/mercado/*` · motor `api/mercado_service.py` · rotas `api/mercado_routes.py` ·
cliente `chat-ui/src/mercadoApi.ts` · testes `tests/test_mercado.py` (41) · sonda
`_probe_mercado.py`

O módulo constrói um **modelo de inteligência empresarial para a contratação
pública**: compara empresas que concorrem no mesmo mercado, mede dependências
recíprocas com as entidades públicas, segue a evolução temporal na malha
`empresa → contrato → entidade → CPV → CAE` e simula alterações na rede (World
Model), com a sensibilidade medida pelo motor do módulo Lorenz.

Serve **qualquer área** — a saúde/medicamentos é apenas uma das áreas
predefinidas (as mesmas de `/lorenz/areas`). O escopo é definido por área,
prefixos de CPV, intervalo de anos, região (NUTs), entidade (NIF), intervalo de
valor, texto e lista de NIFs a comparar.

## 1. As cinco camadas

| Camada | O que faz | Onde |
|---|---|---|
| Ingestão e normalização | Contratos do Portal BASE + CAE do registo (`finance_entities`) + catálogos CAE/CPV | `elasticsearch_client`, `cae_catalog` |
| Grafo temporal | Empresa → contrato → entidade → CPV → CAE, com relações datadas | `grafo_temporal` |
| Motor de indicadores | `P_i` (posição), `D_i` (concentração de compradores), dependência recíproca, evolução | `indice_posicionamento`, `indice_dependencia`, `evolucao_anual` |
| Motor dinâmico | Sensibilidade às condições iniciais, cenários contrafactuais, incerteza | `sensibilidade`, `cenarios` (reutiliza `api.lorenz_service`) |
| Evidências e auditoria | Cada indicador chega aos contratos de origem e às limitações dos dados | `evidencias`, `meta` |

## 2. Indicadores (com fórmulas)

| Indicador | Fórmula | Leitura |
|---|---|---|
| Posicionamento `P_i` | `P_i = V_i / Σ_j V_j` | Quota do valor publicado **dentro do mercado definido** — não é quota de mercado total (exclui compra privada e compras públicas não publicadas) |
| Dependência da empresa `D_i` | `D_i = Σ_e s_ie²` | HHI da carteira de compradores (+ `maior_quota`, `n_entidades`, `entropia`) |
| Dependência da entidade | `Σ_f (valor_f / valor_entidade)²` | Concentração dos fornecedores por entidade **no escopo** (CPV/anos) |
| Evolução temporal | variação, CAGR e declive por ano | Deteta alterações de posição no mercado (`queda_de_atividade` quando ≤ −10 %) |
| Sensibilidade | `D_t` e λ do mapa discreto ajustado à série | Mesma matemática do módulo Lorenz (ver `docs/lorenz.md`) |

Alertas por empresa (`_alertas_empresa`): `dependencia_de_comprador` (maior
comprador ≥ 50 %, alta ≥ 70 %), `sem_concurso` (≥ 50 % dos contratos sem
procedimento competitivo registado), `cae_desconhecido`, `queda_de_atividade`,
`mercado_unico`. O `perfil` é uma frase curta construída a partir destes números —
nunca um juízo absoluto.

## 3. Compatibilidade CPV ↔ CAE

O CAE **não** vem do Portal BASE: vem do registo (`finance_entities.cae_principal`
e `caes_secundarios`). Uma empresa sem CAE fica com o grau `desconhecida` — nunca
se presume atividade a partir do nome da empresa.

A tabela curada (`CAE_CPV_DEFAULT`, 42 regras; prefixo de CAE → prefixo de CPV,
com `grau` alta/média-alta/média/baixa, `nota` e `fonte`) vive em
`data/mercado/cae_cpv.json` (env `MERCADO_CONFIG_PATH`) e é **editável** por
`PUT /mercado/tabela`. A compatibilidade de uma empresa com um CPV é a **melhor**
regra entre todos os seus CAE (`compatibilidade_empresa`).

Consequência honesta: cada mercado declara a sua **cobertura de CAE**
(`empresas_com_cae / empresas`) e a **cobertura de valor compatível** — quando são
baixas, a comparação é indicativa e o mercado é classificado `limitada`.

```
GET /mercado/compatibilidade?cae=46460&cpv=33600000-6
→ {"grau": "alta", "score": 0.9, "motivo": "…", "regra": {...}}
```

## 4. Endpoints

| Método | Caminho | O que devolve |
|---|---|---|
| GET | `/mercado/meta` | Camadas, indicadores, eventos, tabela CPV↔CAE, parâmetros e limites |
| GET | `/mercado/tabela` | Regras CPV↔CAE e parâmetros atuais |
| PUT | `/mercado/tabela` | Substitui a tabela e/ou os parâmetros (**exige sessão**) |
| GET | `/mercado/compatibilidade?cae=&cpv=` | Grau de compatibilidade de um par |
| GET | `/mercado/mercados` | Mercados comparáveis (classe de CPV × CAE × período) com cobertura e qualidade |
| GET | `/mercado/benchmark` | Comparação entre empresas do mesmo mercado (tabela completa) |
| GET | `/mercado/empresa/{nif}` | Ficha de mercado: CAE, posição, dependências, evolução e evidências |
| GET | `/mercado/pares?nif=` | Empresas comparáveis (mesmos CPV, CAE compatível, mesmo período) |
| GET | `/mercado/dependencias` | Empresa→entidades e entidade→fornecedores, com alternativas |
| GET | `/mercado/grafo` | Grafo temporal com os cinco tipos de nó |
| GET | `/mercado/cenarios` | Os seis eventos do World Model + sensibilidade |
| GET | `/mercado/sensibilidade` | Motor Lorenz aplicado à série do mercado |
| GET | `/mercado/evidencias` | Contratos que sustentam um indicador (filtros por comprador/fornecedor/CPV) |
| POST | `/mercado/execucoes` | Guarda uma execução (**exige sessão**) — índice `finance_mercado_runs` |
| GET | `/mercado/execucoes[/{id}]` | Lista / lê execuções guardadas |

## 5. Os seis eventos (World Model)

Cada evento devolve `medicao`, `hipoteses` (declaradas) e `evidencia`:

| Evento | O que mede | Hipóteses declaradas |
|---|---|---|
| `perda_maior_comprador` | Valor perdido, quota do valor, valor residual, `D_i` antes/depois | O comprador deixa de contratar esta empresa (não desaparece o mercado); o valor não é redistribuído |
| `entidade_sem_fornecedor` | Exposição da entidade ao fornecedor, cobertura das 3 melhores alternativas, dificuldade de substituição | A exposição é no **escopo**, não na despesa total; as alternativas são as que já contratam no escopo |
| `novo_concorrente` | Quota estimada do entrante, empresas afetadas, HHI antes/simulado, efeito por empresa | Multinomial (`concursos_simulados`, semente fixa): a probabilidade de ganhar é proporcional à força histórica; a força do entrante é `força_relativa × mediana`; não se modelam preços de proposta |
| `contratos_a_expirar` | Duas leituras: **estrita** (`dataFechoContrato`) e **estimada** (celebração + `prazoExecucao`), com cobertura da amostra e `prazos_ignorados` | `prazoExecucao` em dias, aceites [1, 3650]; a amostra são os maiores contratos por valor; exposição à renovação ≠ perda de receita |
| `precos_mais` | Valor atual → simulado com variação uniforme, exposição por empresa | Variação uniforme (não é modelo de formação de preços); sem elasticidade |
| `diversificacao` | `D_i` e maior quota antes → simulados, repartindo o maior comprador em dois | Valor total constante: a diversificação redistribui |

**Cálculo de expirações em Python, não em Painless.** `dataFechoContrato` está
preenchido numa minoria dos contratos (~8 %), pelo que a leitura estrita é
declaradamente parcial. A leitura estimada devolve os maiores contratos cuja
celebração cai na janela alargada (até 10 anos antes) e calcula
`celebração + prazoExecucao` em Python (`_dias_para_data`) — auditável e sem
`runtime` scripts no Elasticsearch (neste cluster, `doc[...].value.plusDays()`
falha com «runtime error»).

## 6. Limites de leitura (o que o modelo não afirma)

- `P_i` é quota do mercado **definido**, não quota de mercado total.
- **Concentração não é dependência económica**: faltam receitas privadas e outros
  mercados da empresa.
- A compatibilidade CPV↔CAE vem de uma tabela curada (indicativa e editável).
- Sem CAE no registo a compatibilidade é `desconhecida` — não se presume atividade.
- Nas entidades, «maior fornecedor» e alternativas são do **escopo** escolhido.
- Partilhar clientes/fornecedores é uma relação **observada**: não é prova de
  coordenação nem de irregularidade.
- Os eventos são **contrafactuais medidos nos contratos do escopo**, não
  previsões; o comportamento do modelo tem de ser confrontado com dados
  históricos e cenários economicamente plausíveis.

## 7. Realidades do Elasticsearch que o código respeita

- `reverse_nested` **só** é válido dentro de uma agregação `nested`: em `anos` o
  `terms` é simples (com `sum` de `precoContratual`), não aninhado.
- `top_hits` dentro de `nested` **sem** `_source` devolve o objeto aninhado.
- O **nome da própria empresa** não pode vir do maior comprador: `_aggs_empresa`
  acrescenta uma agregação `nested` + `filter` (`eu`) com o nome da empresa.
- `terms` não pode ser ordenado por um valor de `reverse_nested`; ordena-se por
  `_count` e reordena-se em Python.
- Uma consulta por empresa num único `msearch` (o universo é o topo do mercado).

## 8. Frontend

- `chat-ui/src/mercadoApi.ts` — cliente tipado de `/mercado/*`.
- `chat-ui/src/pages/MercadoPage.tsx` — escopo + abas **Mercados** (classes de CPV,
  cobertura de CAE, empresas compatíveis), **Benchmark** (a tabela do modelo:
  Contratos · Valor · `P_i` · Entidades · Maior entidade · `D_i` · Evolução · CAE ·
  Compatibilidade · sinais, com ficha lateral e pares), **Dependências**,
  **Grafo** (`GraphCanvas`, construído a pedido) e **Evidências**.
- `chat-ui/src/pages/MercadoCenariosPage.tsx` — os seis eventos com hipóteses e
  evidência + sensibilidade (divergência, coordenadas de estado, sistema de Lorenz
  e efeito do entrante por empresa).
- Entradas de menu/dock: `App.tsx` (`mercado`, `mercado-cenarios`),
  `sidebarCatalog.ts` (grupo «Investigação e IA») e `dock.ts` (ícones `Scale` e
  `Gauge`). Rotas: `/mercado` e `/mercado/cenarios`.

## 9. Operação

- O catálogo CAE (`data/docs/CAE-Rev.4.md`) **não** entra na imagem de produção (o
  `data/` é excluído do contexto de build) e chega por volume
  (`/opt/iqos/servicos/backend/data/docs`). Sem ele, `_label_cae` devolve `None` em
  vez de derrubar a medição (há teste para isso) — mas as descrições de CAE ficam
  em falta.
- Testes: `.\.venv\Scripts\python.exe -m pytest tests/test_mercado.py -q` (41).
- Sonda de dados reais: `_probe_mercado.py <area> <ano_de> <ano_ate>`.
