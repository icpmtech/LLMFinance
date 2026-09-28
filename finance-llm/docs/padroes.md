# Deteção de padrões (contratos, empresas, pessoas e notícias)

Página `/padroes` · router `/padroes/*` · motor `api/padroes_service.py` · testes `tests/test_padroes.py`

## O que responde

O que é **atípico** na contratação pública, **onde** (por CPV), **em quem** (empresas e
pessoas) e **com que sinais externos** (insolvências, notícias). Não há rótulos de
fraude em nenhum portal, pelo que o motor trabalha em duas frentes:

1. **Aprendizagem não supervisionada** — isola desvios sem precisar de casos
   confirmados;
2. **Aprendizagem supervisionada** — estima a probabilidade de **aditivo financeiro**,
   com um rótulo **derivado dos próprios dados do portal** (não é um rótulo de crime).

> Os resultados são **sinais estatísticos para priorizar inspeção**. Um desvio pode ter
> justificação legal (ex.: ajuste direto por urgência imperiosa).

## Dados de origem

| Fonte | Índice | Uso |
| --- | --- | --- |
| Contratos PT (Portal BASE) | `contratos` (2,25 M) | preço base/contratual/efetivo, prazos, CPV, partes, procedimento, concorrentes |
| Contratos ES (PLACSP) | `contratos_es` (4,05 M) | valor base/adjudicado, datas, CPV, órgão, adjudicatário, nº de ofertas |
| Pessoas e cargos | `finance_people` | **órgãos sociais** (gerência, administração, sócios) |
| Insolvências | `finance_cire` | processos (papel «Insolvente»), tribunais, espécies |
| Notícias | leitor RSS (`data/rss/rss.json`), `finance_scraped`, `finance_social` | menções e sentimento |

## Features (o que se mede em cada contrato)

| Feature | PT | ES | Nota |
| --- | --- | --- | --- |
| `log_valor` | `precoContratual` | `valor_adjudicado` | escala logarítmica |
| `ratio_base` | contratual ÷ preço base | adjudicado ÷ valor base | desvio de preço |
| `ratio_efetivo` | valor efetivo ÷ contratual | — | **aditivos** (0 = não registado) |
| `dias_decisao` | decisão − publicação | idem | negativo no PT (publica-se depois de decidir) |
| `dias_assinatura` | celebração − decisão | — | demora a formalizar |
| `dias_publicacao` | publicação − celebração | — | transparência tardia |
| `log_prazo` | `prazoExecucao` | — | duração |
| `ajuste_direto` | ajuste direto, consulta prévia, contratação excluída | contrato menor, negociado sem publicidade, normas internas | sem concurso |
| `n_concorrentes` | **NIFs distintos** no campo `concorrentes` | `num_ofertas` | concorrência efetiva |

As features sem cobertura no país (ex.: `ratio_efetivo` e as datas de assinatura em
Espanha) são **excluídas automaticamente** do motor e o nome fica visível em
`deteccao.features_excluidas`.

## Algoritmos

**Não supervisionado** (todos com scores convertidos em percentis [0,1] e combinados
num **consenso**; sinaliza-se quem tem score alto **e** â‰¥ 2 detetores de acordo):

- `IsolationForest` (300 árvores) — isola contratos atípicos rapidamente;
- `LocalOutlierFactor` — densidade local face aos vizinhos;
- `KMeans` — distância ao centro do grupo (contrato que não pertence a nenhum padrão);
- `OneClassSVM` — fronteira do comportamento normal (sub-amostra acima de 4 000 casos);
- `DBSCAN` — cluster de ruído (`eps` pela distância ao k-ésimo vizinho);
- **z-score robusto (MAD) por CPV** — «normal» depende do setor; exige ≥ 40 contratos no grupo.

**Supervisionado**: `GradientBoostingClassifier` (250 árvores, profundidade 3) com
validação de 30 %. Rótulo = `ratio_efetivo > 1,15`. Métricas reportadas: ROC AUC,
average precision, prevalência e lift no topo 10 %.

> **Sem fuga de informação.** `ratio_efetivo` é a origem do rótulo e por isso **não é
> feature** do modelo. Sem esta exclusão o AUC vinha 1,0 (verificado em
> `tests/test_padroes.py::test_risk_model_nao_usa_o_rotulo_como_feature`).

## Padrões sinalizáveis

`desvio_preco_alto` Â· `desvio_preco_baixo` Â· `aditivo_valor` Â· `publicacao_tardia` Â·
`publicacao_incoerente` Â· `assinatura_tardia` Â· `decisao_muito_anterior` Â·
`baixa_concorrencia` Â· `sem_concorrentes` Â· `ajuste_direto_atipico` Â· `valor_atipico` Â·
`prazo_execucao_longo` Â· `concentracao_fornecedor` Â· `rede_pessoas` Â· `insolvencia` Â·
`noticias_negativas` Â· `risco_aditivo`.

## Regras editáveis e templates (`api/padroes_regras.py`)

As regras **são dados, não código**: vivem em `data/padroes/regras.json` (escrita atómica)
and são geridas no separador **Regras** da página.

### Forma de uma regra

```json
{
  "id": "ajuste_direto_atipico",
  "label": "Ajuste direto atípico no CPV",
  "severidade": "info",
  "modo": "todas",
  "ativo": true,
  "condicoes": [
    { "campo": "ajuste_direto", "operador": "==", "valor": 1 },
    { "campo": "taxa_ajuste_direto_cpv", "operador": "<",
      "valor": { "campo": "taxa_ajuste_direto_global", "fator": 0.6 } }
  ]
}
```

- `modo`: `todas` (E) ou `alguma` (OU);
- `campo` ∈ catálogo de 21 campos (contrato, CPV e globais) — `GET /padroes/regras/campos`;
- `operador` âˆˆ `> >= < <= == != contem comeca`, validado contra o tipo do campo;
- `valor`: número, texto, ou **referência a outro campo com fator** (`{"campo": "x", "fator": 0.6}`),
  que é o que permite regras **relativas** («abaixo de 60 % da taxa global do CPV») em vez de
  limiares fixos.

Sem dado não há hit: se o campo estiver em falta (`None`) a condição falha, para não gerar
falsos positivos.

### Avaliação

`avaliar(contexto, regras)` é aplicado a **toda a amostra** (não só aos contratos que o ML
sinalizou), pelo que uma regra é um caminho alternativo de deteção:

- os hits entram em `razoes` de cada contrato (com `severidade` e o detalhe
  Â«campo operador limite (valor: X)Â»);
- `GET /padroes/regras/hits` devolve os contratos que cumprem pelo menos uma regra ativa,
  ordenados por severidade;
- `overview.contratos_com_regras` conta-os.

### Predefinições

`padroes_regras.REGRAS_DEFAULT` (12) reproduz **exatamente** a lógica que o motor já aplicava;
«Repor predefinidas» reescreve-as (mantendo ou não as personalizadas). Um teste garante que
as predefinições continuam a bater certo com o esperado (limiares, modo E/OU e a regra relativa).

### Templates

`TEMPLATES_DEFAULT` traz cinco conjuntos temáticos — **Essencial**, **Preço e aditivos**,
**Procedimento e concorrência**, **Prazos e transparência**, **Rigor máximo**. Aplicar um
template liga as suas regras e desliga as restantes; qualquer conjunto de regras ativas pode
ser guardado como template novo.

> Armadilha apanhada em produção: os templates predefinidos usavam a chave `ativas` e o resto
do código lia `regras` — aplicá-los não ligava nada e a UI rebentava
(`template.regras.length`). Está normalizado (com migração na leitura) e coberto por
testes em `tests/test_padroes_regras.py`.

### Rotas

| Rota | Descrição |
| --- | --- |
| `GET /padroes/regras` | regras + templates + catálogo de campos/operadores |
| `GET /padroes/regras/campos` | só o catálogo (campos, operadores, severidades, padrões não avaliáveis) |
| `POST /padroes/regras` | criar (sem `id`) ou atualizar (sessão) |
| `PATCH /padroes/regras/{id}/ativo` | ligar/desligar (sessão) |
| `POST /padroes/regras/{id}/duplicar` | duplicar (sessão) |
| `DELETE /padroes/regras/{id}` | apagar (sessão) |
| `POST /padroes/regras/repor` | repor predefinições (sessão) |
| `GET|POST /padroes/regras/templates` | listar/guardar templates (escrita com sessão) |
| `POST /padroes/regras/templates/{id}/aplicar` | aplicar um template (sessão) |
| `DELETE /padroes/regras/templates/{id}` | apagar um template (sessão) |
| `GET /padroes/regras/hits` | contratos apanhados pelas regras ativas |

Qualquer escrita limpa a cache de análises e obriga ao recálculo (a UI recarrega sozinha).

## Relações (grafo)

- **adjudicante → adjudicatária**, com valor e nº de contratos;
- **concentração**: adjudicantes em que uma empresa leva ≥ 50 % do valor da amostra;
- **laço societário**: pessoa com **cargos de órgão social** em ≥ 2 adjudicatárias que
  ganham ao mesmo adjudicante;
- **insolvência partilhada**: duas adjudicatárias insolventes no **mesmo processo**.

Duas decisões importantes, ambas validadas nos dados:

1. `finance_people` tem ~600 mil cargos do CIRE (Â«CredorÂ», Â«InsolventeÂ», Â«Administrador
   da insolvência») e apenas **algumas dezenas** de órgãos sociais. Sem filtrar por
   `role_org`, o grafo ligava pessoas por serem credoras de várias falências — ruído.
2. No CIRE, só o **insolvente** conta como ligação. A Segurança Social, a Autoridade
   Tributária e a banca aparecem como credores em milhares de processos: incluí-los
   ligaria tudo a tudo.
### Grafo do dossiê (`entity_dossier.grafo`)

Cada dossiê traz um grafo próprio, na mesma forma de `ContractGraphBuildResponse`
(a que o `GraphCanvas` já sabe desenhar):

- centro = a empresa (`type: entidade`);
- **adjudicantes** (10 com mais valor) com aresta empresa→adjudicante (valor e nº de contratos);
- **órgãos sociais** (12) com aresta pessoa→empresa — a direção diz «quem gere»;
- **processos do CIRE** (8) e os **intervenientes desses processos** (20), ligados ao
  processo (é aí que se vê quem se cruza com a empresa numa insolvência);
- `lacos` reproduz essas ligações em texto, para a lista «quem se cruza nos processos».

Os limites são apertados de propósito: o desenho corre **no browser** e é o passo mais
caro do dossiê. Por isso o grafo é **desenhado a pedido** («desenhar grafo», fechado por
omissão) e o layout por omissão é `hierarchical`, que é **determinístico** (sem
simulação de forças). O detalhe não se perde: contratos, cargos, processos e
intervenientes vêm nas listas do próprio dossiê, e o sinal pode ser aberto para ver
exatamente o que está contado.
## Amostragem

A análise usa uma **amostra estratificada por ano** (`sort: ["_doc"]`, `_track_total_hits:
false`), com `sample_per_year` contratos por ano (omissão 1200, teto 40 000). É rápida,
reprodutível e permite medir a cobertura face ao universo (`overview.cobertura`). A
amostra está documentada em todos os payloads — não é a totalidade do índice.

## Rotas

| Rota | Descrição |
| --- | --- |
| `GET /padroes/meta` | catálogo de padrões, algoritmos, fontes e parâmetros |
| `GET /padroes/analysis` | análise completa (KPIs, CPV, anomalias, entidades, rede, modelo) |
| `GET /padroes/anomalies` | contratos sinalizados (`min_score`, `detector`, `padrao`) |
| `GET /padroes/entities` | ranking de adjudicatárias (`min_score`, `insolventes`) |
| `GET /padroes/relations` | grafo, laços, concentração e insolvências |
| `GET /padroes/news` | menções em notícias das entidades sinalizadas |
| `GET /padroes/entity/{nif}` | dossiê: contratos, sinais, cargos, CIRE e notícias |
| `GET /padroes/empresas/sugestoes?q=` | nome, marca ou NIF â†’ empresas com contratos (e candidatos alternativos) |
| `GET /padroes/empresas/analise` | análise de uma empresa (portefólio, CPV, regras, pares e relações) |
| `POST /padroes/empresas/browser` | ler páginas externas e indexá-las em `finance_scraped` (sessão) |
| `POST /padroes/empresas/ia` | ficha analítica por IA (+ browser e gravação opcionais) (sessão) |
| `POST /padroes/empresas/guardar` | guardar a análise em `finance_analises_empresa` (sessão) |
| `GET /padroes/empresas/guardadas` | análises guardadas (lista, sem a fotografia completa) (sessão) |
| `GET /padroes/empresas/guardada/{doc_id}` | análise guardada completa (`pais:nif`) (sessão) |
| `DELETE /padroes/empresas/guardada/{doc_id}` | apagar uma análise guardada (sessão) |
| `GET /padroes/empresas/relatorio` | relatório da empresa em PDF, Excel ou CSV |
| `POST /padroes/cache/clear` | limpar a cache de análises (sessão) |

Leitura pública; `refresh=true` e `cache/clear` exigem sessão. Cache em memória com
TTL de 15 minutos, chaveada por `(país, ano_from, ano_to, cpv, per_year, contaminação, semente)`.
As análises por empresa têm cache própria (mesma TTL, chave `pais|nif|anos|amostra`).

## Procura e análise de uma empresa

### Resolver o nome (o campo é `keyword`, não texto)

No índice `contratos` o nome da parte é um **`keyword`** (`adjudicatarios.parsed.nome`),
pelo que `match` só encontra o nome exato e `match_phrase_prefix` dá erro (400). A
resolução passa, por isso, por outra ordem:

1. `finance_contribuintes` (campo `name` com analisador próprio + `search_text`),
   ordenado por contratos e com preferência por quem tem `roles: adjudicatario`;
2. recuo para o próprio índice de contratos com `wildcard` insensível a maiúsculas
   dentro do `nested` e um `filter` que restringe os baldes à parte que casou;
3. no PLACSP (`adjudicatario_nombre` é `text`) usa-se `match`; os NIF vêm em
   capitalizações diferentes (`A28791069` / `a28791069`) e são agrupados em maiúsculas.

Quem pesquisa Â«psgÂ» recebe a empresa principal **e** os candidatos alternativos.

### O que a análise calcula

- **régua por CPV** — mediana e MAD do log do valor, desvio mediano e taxas de ajuste
  direto/aditivo do próprio CPV (amostra do setor, até 6 grupos);
- **σ no CPV** — desvio robusto de cada contrato face aos pares do seu CPV;
- **regras** — as regras ativas do registo são avaliadas contrato a contrato, com
  exemplos por sinal;
- **relações** — quem mais ganha aos mesmos adjudicantes, órgãos sociais, CIRE e menções.

### IA, browser e persistência

- **browser** (`api/padroes_empresa_ia.py`): `httpx` com agente identificado, extração
  de título e texto útil (sem `script`/`style`, sem linhas de menu), limite de 8 páginas
  × 6000 caracteres; o texto é indexado em `finance_scraped` com `item_id` derivado do
  URL, pelo que **reler substitui** em vez de duplicar;
- **factos**: a análise + o cadastro das entidades contratantes (tipo, concelho) num JSON
  compacto — é tudo o que o modelo pode afirmar;
- **ficha** (`ficha_ia`): pede ao modelo configurado uma ficha em Markdown (síntese,
  portefólio, CPV, sinais, entidades, relações, o que verificar, limitações). Sem modelo
  disponível sai a **ficha factual**, com os mesmos números e sem redação por IA;
- **persistência**: `finance_analises_empresa`, com `_id = <pais>:<nif>` (guardar de novo
  **substitui**). Guarda a fotografia completa (`analise`, não indexada) e indexa o que
  serve para listar e filtrar (nome, valor, severidade, sinais, modelo de IA).

### Comparar várias empresas (`POST /padroes/empresas/analise-multipla`)

A comparação corre `analise_empresa` por empresa (com cache) e devolve o que serve
para decidir, não 300 contratos por empresa:

- **linhas comparáveis** — contratos, valor, valor mediano, desvio do preço base,
  ajuste direto, aditivos, adjudicantes, concentração, atípicos no CPV, sinais e
  severidade, lado a lado e ordenáveis;
- **cruzamentos** — adjudicantes comuns (concorrência no mesmo cliente), pessoas
  comuns (o mesmo gerente em duas empresas), processos do CIRE partilhados e CPV
  comuns (o mesmo mercado). Só entra o que toca **duas ou mais** empresas: um
  adjudicante de uma só não é um cruzamento;
- **rede do conjunto** (`_grafo_conjunto`) — empresas ao centro, ligadas pelo
  comprador, pelo mercado (CPV), pelo gerente e pelo processo. Inclui os
  compradores partilhados **e** os maiores compradores de cada empresa, para a
  rede não ficar vazia quando as empresas não se cruzam em nada. Limites: 18
  compradores, 12 pessoas, 8 processos, 10 mercados;
- **distribuição por CPV** do conjunto e o **relatório** em PDF/Excel/CSV
  (`/padroes/empresas/multipla/relatorio`, ou `formato` no corpo do pedido).

Limites: até 12 empresas (`MAX_EMPRESAS_CONJUNTO`), 20 a 400 contratos por
empresa (omissão 120). As empresas que não resolvem (NIF/nome desconhecido ou sem
contratos) não travam o conjunto: ficam em `avisos`.

### Relatório (PDF, Excel, CSV)

`api/padroes_report.py` constrói **uma** estrutura de secções a partir da análise
(identificação, cadastro, resumo, ficha de IA, sinais, CPV, entidades contratantes,
procedimentos, evolução por ano, pares, órgãos sociais, CIRE, notícias, contratos,
páginas lidas e fontes/limitações) e entrega-a aos renderizadores de
`api/contribuintes_report.py` (ReportLab, openpyxl e CSV com `;` e BOM).

- `doc_id` emite o relatório de uma análise **guardada**: diz o mesmo que no dia em que
  foi feita (exige sessão);
- `ficha_ia=true` acrescenta a ficha redigida por IA (mais lento);
- a lista de contratos é limitada a 200 linhas — o relatório mostra a amostra, não o
  inventário.

## Frontend

- `chat-ui/src/padroesApi.ts` — cliente tipado;
- `chat-ui/src/components/padroes/padroesKit.tsx` — formatadores, KPIs, chips e marcas;
- `chat-ui/src/components/padroes/PadroesEmpresa.tsx` — pesquisa e análise de uma empresa;
- `chat-ui/src/components/padroes/PadroesEmpresaIA.tsx` — browser, ficha de IA, gravação e relatório;
- `chat-ui/src/components/padroes/PadroesEmpresasComparar.tsx` — página «Comparar empresas»
  (escolha múltipla, comparação, cruzamentos, gráfico, rede e exportação);
- `chat-ui/src/pages/PadroesPage.tsx` — a página (filtros, 9 painéis e dossiê lateral);
- registo em `dock.ts` (`padroes`), `sidebarCatalog.ts` (módulo «Investigação e IA»),
  `App.tsx` (vista + rota `/padroes`) e `AppNav.tsx`.

O painel «Analisar empresa» guarda a última empresa analisada em `localStorage`
(`padroes:empresa`), para a investigação não recomeçar do zero ao voltar à página.

No **dossiê**, os sinais são botões: «Insolvência / PER: 7 processo(s)» abre a lista dos 7
processos (número, tribunal, data), «Laço societário» abre os órgãos sociais e os sinais de
preço/aditivo/ajuste direto abrem os contratos que os sustentam. O detalhe é derivado da
amostra já carregada — não custa um pedido novo. O **grafo do dossiê** está fechado por
omissão («desenhar grafo») porque o desenho corre no browser: é o passo mais caro da página
e o layout por omissão é determinístico (sem simulação de forças).

O grafo reutiliza o `GraphCanvas` através de `toStudioGraph`, pelo que a resposta de
`/padroes/relations` segue o formato `ContractGraphBuildResponse`.

## Operação

```powershell
# testes (puros, sem ES)
$env:PYTHONPATH='c:\LLMFinance\finance-llm'
c:\LLMFinance\.venv\Scripts\python.exe -m pytest finance-llm\tests\test_padroes.py -q
c:\LLMFinance\.venv\Scripts\python.exe -m pytest finance-llm\tests\test_padroes_empresa.py finance-llm\tests\test_padroes_empresa_ia.py -q

# sonda do motor sobre dados reais (amostra pequena)
c:\LLMFinance\.venv\Scripts\python.exe finance-llm\_probe_padroes_engine.py
```

O índice das análises guardadas cria-se no arranque (`ensure_indices`):
`finance_analises_empresa`. O browser escreve em `finance_scraped` com
`source_id = padroes-empresa`.

## Limites conhecidos

- **Sem rótulos de fraude** em nenhum portal: nada aqui é prova de ilícito.
- O rótulo do modelo supervisionado é um **proxy** (aditivo registado), não crime.
- A rede de órgãos sociais é escassa (poucas dezenas de registos): muitos laços
  simplesmente não são detetáveis com os dados disponíveis.
- O PLACSP não publica data de assinatura nem prazo de candidatura fiável, pelo que as
  regras de prazos só correm em Portugal.
- As notícias dependem de haver itens no leitor RSS / índices de recolha.
- A insistência no nome do CPV para identificar uma empresa é uma limitação dos dados:
  o mesmo grupo económico pode ter vários NIF, e o motor analisa **um NIF** de cada vez.
- **A ficha de IA pode falhar ou ser omissa**: sem chave de modelo sai a ficha factual e,
  quando o modelo responde, o texto é uma leitura dos dados fornecidos — os números e a
  evidência estão no relatório, o texto ajuda a ler.
- O browser lê apenas páginas **públicas** acessíveis por HTTP (sem `robots.txt`),
  com limite de 8 páginas e 6000 caracteres por página: não substitui a consulta ao
  portal, serve para juntar contexto (site da empresa, imprensa regulada).
