# Lorenz 1963 aplicado à contratação pública

Página `/lorenz` · router `/lorenz/*` · motor `api/lorenz_service.py` · rotas
`api/lorenz_routes.py` · testes `tests/test_lorenz.py` · sondas `_probe_lorenz.py`

O módulo acompanha as **relações entre entidades ao longo do tempo** e simula
como pequenas alterações podem propagar-se numa rede de contratação pública.
Não prevê o futuro: identifica riscos emergentes, dependências, efeitos em
cadeia e cenários alternativos, **com evidências verificáveis**.

Serve **qualquer área** — a saúde é apenas uma das áreas predefinidas. O escopo
é definido por prefixos de CPV, região (NUTs), intervalo de anos, entidade (NIF),
intervalo de valor, texto e critérios ecológicos.

## 1. O princípio científico

Em 1963, Edward Lorenz mostrou que, em sistemas determinísticos não lineares,
diferenças mínimas nas condições iniciais podem produzir trajetórias muito
diferentes. Aplicado à contratação pública:

- uma alteração pequena num fornecedor pode afetar vários contratos;
- a concentração de compras num fornecedor amplifica o impacto de uma falha;
- a acumulação de anomalias pequenas pode revelar uma vulnerabilidade que não é
  evidente contrato a contrato.

**Importante:** o efeito borboleta **não** diz que qualquer acontecimento pequeno
provoca uma crise. A amplificação depende da **estrutura** do sistema
(graus, concentração, alternativas), das suas condições e dos mecanismos de
propagação. O sistema de Lorenz clássico fornece a inspiração matemática, não um
algoritmo pronto para a contratação pública.

## 2. Arquitetura (as cinco camadas)

| Camada | O que faz | Onde |
|---|---|---|
| Camada de dados | Contratos (PT; os escopos ES/FR entram por `benchmark_countries`) | `elasticsearch_client` |
| Grafo de conhecimento | Quem contrata quem, com que valores, em que datas e com que dependências | `matriz_dependencia`, `matriz_cpv` |
| Motor de relações | Concentração, exposição, propagação e dependências | `dependencias`, `propagar`, `ranking_amplificadores` |
| Motor dinâmico | Estado, sensibilidade, divergência, Lyapunov e cenários Lorenz | `estado_da_serie`, `divergencia_mapa`, `lyapunov_maximo` |
| World Model | Estado → eventos → simulações → cenários futuros → evidências | `panorama`, `propagacao`, `evidencias` |

## 3. Dados de origem

| Fonte | Índice | Uso |
|---|---|---|
| Contratos públicos PT | `contratos` | Valor, partes (nested), CPV (nested), procedimento, datas |
| Execuções guardadas | `finance_lorenz_runs` | Fotografia de um panorama/cenário por `run_id` |

Realidades do índice que o código respeita (todas validadas em sonda):

- `adjudicantes`/`adjudicatarios` são **objetos** com `parsed` **nested**: agregar
  por parte exige `nested` + `reverse_nested` para voltar ao valor do documento.
- O `terms` **não pode** ser ordenado pelo valor de um `reverse_nested`
  («Invalid aggregation order path») → ordena-se por `_count` e reordena-se em Python.
- Dentro de `nested`, o `top_hits` sem `_source` devolve o objeto aninhado
  (`{nif, nome}`); com `_source: ["nif","nome"]` vem **vazio**.
- `percentiles` com `keyed: true` devolve `{"values": {...}}` — ler as chaves na
  raiz dava percentis a zero (e uma «cauda» constante, um defeito silencioso).
- `tipoprocedimento` é `text`: o campo agregável é resolvido no mapping real
  (`_resolve_agg_target`), com `runtime_mappings` quando necessário.
- `from/size` rebenta acima de 10 000 → o cruzamento comprador→fornecedor é feito
  por **`msearch`** (uma consulta por comprador, filtrada por NIF): exato, sem amostra.

## 4. O modelo matemático

### 4.1 Estado observado

Por período `t` (ano, ou trimestre): contratos, valor, valor efetivo,
compradores e fornecedores distintos, percentis do valor (`p50`, `p95`, `p99`),
dispersão `cauda = (p99 − p50)/p50`, `quota_top1` (maior fornecedor),
`hhi` (soma das quotas²), cobertura do topo e taxa de ajuste direto.

As três coordenadas do estado, normalizadas por mediana/MAD (robusto):

- `atividade` = `log1p(valor / valor mediano da série)`
- `dependencia` = `max(quota_top1, hhi)`
- `cauda` = dispersão relativa do valor

### 4.2 Mapa discreto (sensibilidade nos dados)

Ajusta-se `s(t+1) = A·s(t) + b` por mínimos quadrados à série observada. Com
ele estima-se a divergência média entre trajetórias vizinhas:

$$D_t = \lVert s_t^{(A)} - s_t^{(B)} \rVert$$

e o **expoente de Lyapunov empírico** (Benettin: perturba, propaga, renormaliza;
acumula o logaritmo do **fator de expansão de cada passo**, não o logaritmo das
distâncias absolutas — essa era a diferença entre λ ≈ 0,4 e 1,0 no caso de teste):

$$\lambda = \frac{1}{T}\sum_{k=1}^{T}\ln\frac{\lVert \delta_k \rVert}{\lVert \delta_{k-1} \rVert}$$

`λ > 0` ⇒ condições iniciais vizinhas afastam-se (regime sensível);
`λ < 0` ⇒ o sistema contrai perturbações. O **raio espectral** de `A` dá a mesma
leitura de forma direta (`> 1` amplifica).

### 4.3 Sistema de Lorenz (analogia estrutural)

Integra-se o sistema clássico por Runge-Kutta de 4.ª ordem:

```
dx/dt = σ(y − x)        dy/dt = x(ρ − z) − y        dz/dt = xy − βz
```

com parâmetros **análogos medidos na estrutura** (não ajustados ao sistema
original):

- `σ` (oferta/procura) = fornecedores por comprador, relativo a uma referência de
  3, limitado a `[6, 20]`;
- `β` (dissipação/memória) = `8/3 · (2 − ρ₁)`, com `ρ₁` a autocorrelação de ordem 1
  do valor (série com memória ⇒ β menor), limitado a `[2,2; 4,0]`;
- `margem` = dependência do último período sobre a mediana histórica da dependência;
- `ρ = ρ_crit · margem`, onde `ρ_crit = σ(σ+β+3)/(σ−β−1)` é a **fronteira de
  instabilidade** do sistema de Lorenz clássico (σ=10, β=8/3 ⇒ 24,74).

Assim, `margem > 1` significa «do lado amplificador da fronteira» e `margem < 1`
«do lado dissipador». É uma leitura de **regime**, não uma previsão. O expoente de
Lyapunov do próprio sistema é calculado por Benettin (com 12 000 passos ≈ 0,2 s;
com 2 000 ainda não converge e lê o regime errado).

## 5. Fragilidade, propagação e hipóteses

**Fragilidade de um comprador** = `quota_top1 × (1 − cobertura de alternativas no
CPV) × (1 + taxa de ajuste direto)`.

**Propagação** de uma perturbação num fornecedor:

1. **Diretos** — cada comprador com quota `q` no fornecedor; exposição
   `valor da relação × (1 + perda de capacidade × q)`; dificuldade de substituição
   `1 − quota do fornecedor no CPV` (média ponderada pela mistura de CPV do
   comprador); sobrecusto `exposição × prémio(atraso) × (0,5 + dificuldade)`.
2. **Segunda ordem** — a procura realocada nas alternativas aumenta a concentração
   delas: quem passa a ficar acima do limiar é sinalizado como **novo frágil**.
3. **Mitigações** — repartição da quota pelas alternativas observadas, com os
   números de partida e de chegada («repartir por 4 reduz de 86 % para 43 %»).

Prémio de urgência (hipótese configurável em `data/lorenz/config.json`):
0 d → 0 %; 7 d → 2 %; 30 d → 7 %; 60 d → 15 %; 120 d → 25 % (interpolação linear).

**Elasticidade** = impacto por unidade de perda de capacidade (inclinação de três
perturbações: 10 %, 25 %, 50 %). **Amplificação** de um fornecedor =
`alcance (fração de compradores tocados) × exposição (fração do valor) ×
(0,5 + dificuldade média)`, com a decomposição por relação (`contribuintes`).

Todas as hipóteses são devolvidas no campo `hipoteses` de cada resposta. Sem
stocks, prazos de entrega, substitutibilidade técnica e criticidade, **não** se
calculam efeitos operacionais nem clínicos: o custo é um cenário.

## 6. Áreas (configuráveis)

`data/lorenz/config.json` guarda as áreas (id, rótulo, prefixos de CPV) e os
parâmetros. Predefinições: todas, saúde (`33`, `851`), medicamentos (`336`),
dispositivos (`331`, `3314`, `3319`, `3843`), construção (`45`), TI (`30`, `48`,
`72`, `73`), energia, transportes, alimentar, serviços públicos, limpeza e
manutenção. Qualquer prefixo de CPV pode ser usado diretamente na query (`cpv=`).

## 7. API

| Rota | Descrição |
|---|---|
| `GET /lorenz/meta` | Arquitetura, áreas, parâmetros, limites e volumetria |
| `GET /lorenz/areas` | Áreas e parâmetros atuais |
| `PUT /lorenz/areas` | Substituir áreas/parâmetros (**sessão**) |
| `GET /lorenz/panorama` | Estado, regime, dependências, CPV, alertas e amplificadores (`grafo=true` inclui o grafo) |
| `GET /lorenz/serie` | Série por período + coordenadas do estado + parâmetros estimados |
| `GET /lorenz/grafo` | Grafo comprador↔fornecedor no formato do `GraphCanvas` |
| `GET /lorenz/cpv` | Concentração e fragilidade por classe de CPV |
| `GET /lorenz/entidades` | Compradores frágeis, fornecedores expostos e ranking de amplificação |
| `GET /lorenz/propagacao` | Cenário de propagação (fornecedor + atraso) com evidências, segunda ordem e mitigações |
| `GET /lorenz/cenarios` | Comparação 7/30/60 dias e elasticidade |
| `GET /lorenz/evidencias` | Contratos que sustentam uma relação ou um CPV |
| `POST /lorenz/execucoes` | Calcular e guardar um panorama (**sessão**) |
| `GET /lorenz/execucoes[/{run_id}]` | Execuções guardadas |

Parâmetros comuns do escopo: `area`, `cpv`, `ano_de`, `ano_ate`, `regiao`, `nif`,
`nif_contraparte`, `valor_min`, `valor_max`, `texto`, `ecologico`.

## 8. Página

`/lorenz` (menu lateral em *Investigação e IA*, item do dock «Lorenz 1963»), com
seis leituras: **Panorama** (KPIs, série, regime, alertas, cobertura e hipóteses),
**Sensibilidade** (D(t), raio espectral, R², Lorenz e as matrizes do mapa),
**Propagação** (7/30/60 dias, entidades afetadas, segunda ordem, mitigações e
elasticidade), **CPV**, **Entidades** (frágeis e amplificadores com contribuintes),
**Grafo** (desenhado a pedido no canvas; clique num nó para ver os contratos).

## 9. Comandos

```powershell
# sondas e testes
python finance-llm/_probe_lorenz.py medicamentos 2022 2026
python -m pytest finance-llm/tests/test_lorenz.py -q      # 52 testes puros
```

## 10. Limites (o que este módulo não faz)

- Não prevê valores futuros nem datas de rutura.
- Não mede efeitos clínicos, operacionais ou de stock — exigem dados que o Portal
  BASE não publica.
- O cruzamento comprador↔fornecedor é exato **dentro dos topos** configurados
  (por omissão 40 compradores por escopo e 24 classes de CPV); o resto fica
  registado em `cobertura`.
- Com poucos períodos anuais, o mapa discreto e o Lyapunov são uma indicação de
  regime, não uma medida precisa (o R² ajustado in-sample não é validação).
