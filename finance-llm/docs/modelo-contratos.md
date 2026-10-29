# Modelo de contratos — fine-tuning LoRA com os dados do Elasticsearch

> `Qwen/Qwen2.5-0.5B-Instruct` afinado com contratos, entidades e subsídios
> exportados dos índices do IQ OS, treinado em CPU, com pausa/retoma, avaliação
> em conjunto held-out, API própria e página em `/modelo/contratos`.

Este documento descreve a corrente completa que vive no repositório:

```
  Elasticsearch                  training/                         model/
  ─────────────                ────────────────                  ─────────────
  contratos             ┐
  finance_entities      ├──▶ export_es_dataset.py ──▶ data/final/iqos_contratos_empresas_qwen.jsonl
  finance_subvencoes    ┘        (Alpaca)                     │
                                                              ▼
                                        train_lora_contratos.py  (LoRA + pausa/retoma)
                                                              │
                                                              ▼
                                       model/qwen05-contratos/  (adaptador, metrics.jsonl,
                                                                 run_metadata.json)
                                                              │
                                     ┌────────────────────────┴────────────────────┐
                                     ▼                                             ▼
                     inference/contratos_eval.py                    api/llm_contratos_routes.py
                     (base vs adaptador no held-out)                (/llm/modelo/*) ──▶ página
                                     │                                             │
                                     └──────────▶ finance_llm_model_evals ◀────────┘
```

## 1. Porquê este modelo

| Critério | Escolha | Porquê |
|---|---|---|
| Modelo | `Qwen/Qwen2.5-0.5B-Instruct` | Já fala português, cabe em CPU (0,5 B parâmetros, ~1 GB em fp32) e já estava no cache do Hugging Face desta máquina. É o mesmo modelo que `training/soup/soup-qwen05-empresas-contratos.yaml` já previa. |
| Adaptação | LoRA `r=16`, `alpha=32`, todas as projecções (`q,k,v,o,gate,up,down`) | 8,8 M parâmetros treináveis (~1,7 % do modelo) num ficheiro de 35 MB: treina em CPU e não toca nos pesos do modelo base. |
| Dados | `contratos` + `finance_entities` + `finance_subvencoes` | As três fontes respondem às perguntas reais («quanto custou este contrato?», «quem é esta entidade?», «que subsídio recebeu?»). Um dataset de uma fonte só ensina metade da resposta. |
| Sem `soup` | loop próprio (`train_lora_contratos.py`) | O Soup corre de uma só tacada. Em CPU, um treino leva dezenas de minutos — precisa de **pausa**, **retoma** e progresso legível, como `training/train_mistral.py` já fazia com `training/pause.flag`. |

Medição feita nesta máquina (Intel Core Ultra 7 255U, 14 threads lógicos, sem
GPU): **~0,06 s por token** de forward+backward — um passo de 512 tokens custa
~32 s. O dataset tem 807 pares (~176 mil tokens com o tokenizer do Qwen), o que
dá **~3 horas por época** no dataset inteiro. É por isso que o treino aceita
`--max-pairs`, pausa e retoma.

## 2. Passo 1 — exportar os dados

```powershell
.\.venv\Scripts\python.exe training\export_es_dataset.py `
    --dataset contratos --dataset empresas --dataset subvencoes `
    --max-records 300 --seed 42 `
    --tokenizer Qwen/Qwen2.5-0.5B-Instruct --max-tokens 320 `
    --out data/final/iqos_contratos_empresas_qwen.jsonl
```

- O `--max-records` conta **por fonte** (300 de cada) e o `--seed` pede ao
  Elasticsearch uma amostra dispersa (os primeiros N documentos de um índice vêm
  todos do mesmo ficheiro de origem).
- O `--tokenizer`/`--max-tokens` medem cada par com o tokenizer **do modelo que
  vai ser treinado** e deixam de fora o que não cabe — um par cortado ensinaria
  uma resposta a meio.
- Resultado nesta corrida: 1 128 pares (566 de contratos — descrição, resumo para
  cidadão e auditoria —, 300 entidades, 262 subsídios).

### Regra que o exportador tem de respeitar

**Todos os campos que a resposta cita têm de estar no pedido.** Durante muito
tempo não estavam: `_build_contrato_pt` escrevia no *output*
`publicado a {dataPublicacao} e com regime {regime}` e `CPV principal é {cpv}`,
mas o *input* só levava contrato, adjudicantes, tipo, procedimento, preço e
descrição. O modelo aprendeu exactamente o que lhe foi ensinado: inventar. Com
um contrato sem data, respondia «publicado a 2021-08-26» e «regime
Código dos Contratos Públicos (DL 18/2008)» — dois factos que não existiam em
lado nenhum do pedido. Data, regime e CPV passaram a ir no pedido (contratos PT,
ES e FR) e há um teste (`test_contrato_pt_pede_todos_os_campos_que_a_resposta_cita`)
que falha se a regra for quebrada outra vez.

### Três instruções, não uma

O modelo só tinha visto «Descreve este contrato público português.». A página
oferece três perfis (descrever, auditar, responder a cidadão): ao pedir
«auditar», a resposta saía a descrever — e a repetir-se («o CPV principal
principal é»). Cada contrato português gera agora **três pares** com o mesmo
pedido e respostas diferentes (`_build_contrato_pt_variantes`), e a instrução
viaja com o perfil na API (`PROMPTS_PREDEFINIDOS[*].instrucao`) para que o
prompt de sistema e a instrução não se contradigam.

O objecto e a descrição ficam limitados a 240 caracteres (`TEXTO_CAMPO_MAX`):
uma descrição de 4 000 caracteres custa 8× mais tempo de treino (a atenção é
quadrática) sem ensinar nada que uma resposta de 2-3 frases use.

## 3. Passo 2 — treinar (com pausa e retoma)

```powershell
# primeira corrida: 120 pares, ~30 min nesta CPU
.\.venv\Scripts\python.exe training\train_lora_contratos.py --max-pairs 120 --grad-accum 4 --lr 2e-4

# pausar a meio (o treino guarda e sai no fim do passo atual; o processo não morre)
New-Item training\pause.flag -ItemType File

# continuar de onde ficou
.\.venv\Scripts\python.exe training\train_lora_contratos.py --resume --max-pairs 400
```

O que fica no disco:

| Ficheiro | Para que serve |
|---|---|
| `adapter_model.safetensors` | O adaptador LoRA (o resultado do treino). |
| `metrics.jsonl` | Uma linha por actualização (`step`, `perda`, `perplexidade`, `tokens`, `segundos`, `ts`) — é a curva que a página desenha. |
| `run_metadata.json` | Modelo base, dados, LoRA, passos, perda final, duração. |
| `state.pt` | Estado para `--resume` (passo + optimizador). |

Cada `--resume` **continua** o plano em vez de o recomeçar: a corrida de
demonstração parou no passo 30 (perda 0,05) e a retoma levou-a ao passo 37 em
10 min, com o mesmo `state.pt`. `--max-minutes` serve para retomar com tecto de
tempo (foi o que se usou na demonstração); `training/pause.flag` serve para
parar a qualquer momento, e o ficheiro é removido no fim para não bloquear a
corrida seguinte.

`.dockerignore` exclui `training/` do contexto das imagens, por isso o treino
corre no venv do host (`.venv`, com `torch`, `transformers` e `peft`). A pasta
`training/` **não** entra na imagem; o que a API precisa vive em `inference/`.

## 4. Passo 3 — avaliar (o modelo aprendeu ou decorou?)

```powershell
.\.venv\Scripts\python.exe training\eval_lora_contratos.py --limite 12 --gerar 3 --indexar
```

Mede o **held-out** (as 60 linhas que o treino nunca viu, escolhidas por
`split_indices` com a mesma semente) em duas famílias:

| Métrica | O que diz |
|---|---|
| `perplexidade` | Quanto o modelo hesita na resposta de referência (menor é melhor). |
| `exactidao_token` | Fracção de tokens em que o modelo acerta no token seguinte. |
| `f1_medio` | Sobreposição de palavras entre a resposta gerada e o gabarito. |
| `fidelidade_numerica` | Fracção dos valores (euros, NIF, datas) do gabarito que aparecem na resposta gerada. É a métrica que apanha «20 806,20 € → 20,00 €». |

Resultado da corrida de demonstração (8 pares, 13 min em CPU — são dois modelos
carregados e duas gerações por par):

| | perplexidade | exatidão token | F1 | números |
|---|---:|---:|---:|---:|
| base (Qwen2.5-0.5B-Instruct) | 2,24 | 0,794 | 0,50 | 30 % |
| adaptador (passo 37) | **1,01** | **0,999** | **1,00** | **100 %** |
| delta | −1,23 | +0,205 | +0,50 | +70 pp |

A amostra é pequena de propósito: o objetivo é provar a corrente ponta a ponta
em CPU, não publicar um número de referência. Com GPU, `--limite 0` mede os 60
pares todos.

A divisão treino/held-out **baralha com semente** antes de cortar: o exporter
grava as linhas agrupadas por fonte, por isso cortar as últimas N daria um
held-out só de subsídios (e um `--max-pairs` pequeno treinaria só contratos).

## 5. API (`/llm/modelo/*`)

| Método | Rota | O que faz |
|---|---|---|
| `GET` | `/llm/modelo` | Ficha: adaptador presente, metadados do treino, curva e fontes. Público. |
| `GET` | `/llm/modelo/metricas` | Pontos de `metrics.jsonl`. Público. |
| `GET` | `/llm/modelo/matriz` | Matriz 24×7 com a magnitude real de cada actualização LoRA. Público. |
| `GET` | `/llm/modelo/matriz/{camada}/{modulo}` | Recorte das matrizes A e B daquela camada/projecção. Público. |
| `GET` | `/llm/modelo/ligacoes` | Proveniência: pares por fonte → dataset → treino → adaptador. Público. |
| `POST` | `/llm/modelo/chat` | Resposta com memória, skills, RAG, traço de raciocínio e verificação. Exige sessão. |
| `POST` | `/llm/modelo/avaliar` | Corre a avaliação base vs adaptador e guarda o resultado. Exige sessão. |
| `GET` | `/llm/modelo/avaliacoes` | Histórico de avaliações (Elasticsearch). Público. |
| `GET/POST` | `/llm/modelo/memoria` | Lista/guarda memórias e skills aprendidas. Escrita exige sessão. |
| `DELETE` | `/llm/modelo/memoria/{id}` | Apaga memória ou skill. Exige sessão. |
| `GET` | `/llm/modelo/skills` | Catálogo das skills executáveis (nome, descrição, gatilhos). Público. |
| `GET/POST` | `/llm/modelo/prompts` | Prompts de sistema (predefinidos + guardados). Escrita exige sessão. |
| `GET/POST` | `/llm/modelo/rag` | Estado do corpus RAG / indexar a partir dos índices. Escrita exige sessão. |
| `GET` | `/llm/modelo/rag/pesquisa` | Pesquisa BM25 no corpus RAG. Público. |
| `GET/POST` | `/llm/modelo/feedback` | Estatísticas / avaliar uma resposta (👍👎 + correção). Escrita exige sessão. |
| `GET/POST` | `/llm/modelo/retreinar` | Estado da adaptação incremental / arrancá-la (`passos`, `lr`, `reutilizar_existentes`). Arrancar exige sessão. |
| `POST` | `/llm/modelo/retreinar/parar` | Pede a paragem cooperativa da adaptação em curso. Exige sessão. |
| `GET` | `/llm/modelo/retreinar/historico` | Últimas entradas de `metricas_adaptacao.jsonl`. Público. |
| `GET` | `/llm/modelo/versoes` | Backups `.bak-<data>` do adaptador (nome, tamanho, data). Público. |
| `POST` | `/llm/modelo/versoes/reverter` | Repõe o adaptador a partir de um backup (guardando o estado atual). Exige sessão. |
| `WS` | `/llm/modelo/retreinar/ws` | Retreino em direto: fase, passo, perda, tokens e a curva desde o passo 1. Token na query (`?token=…`), porque o browser não deixa enviar `Authorization` no handshake. |

Implementação: [api/llm_contratos_routes.py](../api/llm_contratos_routes.py),
[api/llm_contratos_service.py](../api/llm_contratos_service.py),
[api/llm_contratos_agente.py](../api/llm_contratos_agente.py) (memória, skills,
prompts, RAG, feedback, raciocínio) e
[api/llm_contratos_treino.py](../api/llm_contratos_treino.py) (adaptação
incremental). O prompt é definido **uma vez** em
[inference/contratos_lora.py](../inference/contratos_lora.py) e usado pelo
treino, pela avaliação e pela API — três moldes diferentes transformariam um
modelo bom em respostas más.

## 5.1 O agente à volta do modelo

O adaptador sabe o formato; não sabe o que não lhe foi ensinado nem guarda nada
entre pedidos. A camada `llm_contratos_agente` resolve isso sem treinar nada:

| Peça | Índice | Para que serve |
|---|---|---|
| **Memória** | `finance_llm_memoria` (`memoria`) | Factos ensinados pelo utilizador («Chaves = NIF …»), recuperados por BM25 + gatilhos e injectados no prompt. |
| **Skills aprendidas** | `finance_llm_memoria` (`skill`) | Instrução + exemplo guardado pelo utilizador: entra como few-shot e como par de treino. |
| **Skills executáveis** | — (código) | `procurar_contratos`, `ficha_entidade`, `subsidios`, `contagem`: consultam o Elasticsearch antes de o modelo falar. |
| **Prompts** | `finance_llm_prompts` | Perfis de sistema (descrever / auditar / cidadão) editáveis. |
| **RAG** | `finance_llm_rag_chunks` | Pedaços de contratos, entidades e subsídios; a resposta cita-os. |
| **Feedback** | `finance_llm_feedback` | 👍/👎 e correções; as correções são pares de treino. |

**Raciocínio** (`service.responder`) é um ciclo explícito, todo devolvido na
resposta como `passos` (a interface desenha-o em árvore):

```
pergunta → skills (consulta ES) → memória → evidências RAG → documento
        → geração (com probabilidade por token) → verificação dos números
```

A verificação compara os números da resposta com os do contexto: um valor que
não esteja lá é devolvido em `verificacao.inventados` e a interface avisa. Foi
esta verificação que apanhou, durante os testes, o bug de normalização em que
`20806.2` era lido como 208 062 (corrigido em `inference/contratos_eval.py`).

## 5.2 Auto-aprendizagem (retreinar com o que o utilizador corrigiu)

```
feedback (👎 + correção)  ─┐
skills com exemplo        ─┴─▶ data/final/iqos_adaptacao.jsonl ──▶ 12 passos de LoRA
                                                                  (sobre o adaptador actual)
                                                                        │
                                    backup .bak-<data> ◀────────────────┤
                                    metricas_adaptacao.jsonl ◀──────────┤
                                    finance_llm_model_runs ◀────────────┘
```

Regras: mínimo **3 pares** (uma correção sozinha move o modelo numa direção e
estraga o formato), **uma adaptação de cada vez**, **backup antes de escrever**
e **perda antes/depois** registada. Na demonstração: 4 pares, 12 passos, perda
0,9458 → 0,1185 (Δ −0,83) em 155 s, e a resposta seguinte já saía no formato
corrigido.

A interface (`/modelo/retreino`, e o bloco «auto-aprendizagem» do painel do
chat) expõe o ciclo todo sem tocar em ficheiros: escolher **passos** e
**learning rate**, **reutilizar pares já treinados** (quando `por_utilizar` é 0
e não se quer esperar por feedback novo), **parar** a meio, **reverter** para
qualquer `.bak-<data>`, ver o **histórico** de adaptações e disparar
**reindexação do RAG** e **avaliação**. A paragem é cooperativa: o ciclo termina
no passo seguinte; se ainda não houve nenhum passo, o adaptador fica intacto e o
resultado regista `estado: "parado"`.

## 5.3 Diagramas da interface

| Diagrama | O que mostra | De onde vêm os números |
|---|---|---|
| Grafo do modelo | tokens → embedding → 24 camadas → lm head → texto, com partículas no sentido do forward (e do backward quando há treino) | normas reais do adaptador; clicar numa camada abre a matriz |
| Matriz de pesos | 24 × 7 (q,k,v,o,gate,up,down) com ‖A‖·‖B‖ de cada actualização | `adapter_model.safetensors` |
| Detalhe da matriz | recorte real de A (16×d) e B (d×16), verde/rosa por sinal | idem, via `/matriz/{camada}/{modulo}` |
| Ligações | 3 índices → dataset → treino → adaptador, com a largura dos pares | linhas do dataset usado no treino |
| Árvore do raciocínio | pedido → skills → memória → evidências → documento → geração → verificação | resposta do `/chat` |
| Fita de tokens | probabilidade de cada token gerado (verde = convicto, âmbar/rosa = a adivinhar) | `output_scores` do `generate` |

Tudo em SVG/CSS: as animações são declarativas e param com
`prefers-reduced-motion`.

## 6. Índices do Elasticsearch

Criados pela primeira escrita (mapeamentos em `llm_contratos_service.MAPPINGS` e
`llm_contratos_agente.MAPPINGS`):

| Índice | Documento |
|---|---|
| `finance_llm_model_runs` | Uma corrida de treino (ou adaptação incremental): modelo base, adaptador, pares, passos, perda final, segundos, fontes. |
| `finance_llm_model_evals` | Uma avaliação: conjunto, métricas base/treinado, deltas, fidelidade numérica e três amostras geradas. |
| `finance_llm_memoria` | Memórias (`memoria`) e skills aprendidas (`skill`) com gatilhos, usos e datas. |
| `finance_llm_prompts` | Prompts de sistema guardados pelo utilizador. |
| `finance_llm_rag_chunks` | Pedaços de contratos/entidades/subsídios para o RAG (BM25). |
| `finance_llm_feedback` | Avaliações das respostas, correções e marca de «já usado no treino». |

O histórico vive no Elasticsearch (e não só em `eval.json`) porque é o que
sobrevive a uma recriação do contentor.

## 7. Páginas `/modelo/contratos`, `/modelo/chat`, `/modelo/playground` e `/modelo/retreino`

A página do modelo mostra o **que se está a passar no treino**, com diagramas
animados:

- **Pipeline** — índices → exportador → dataset → LoRA → adaptador → avaliação,
  com fluxo animado enquanto há treino a correr e cada nó aceso quando a fase já
  produziu algo;
- **Grafo do modelo** — 24 camadas com a LoRA colada, partículas no forward e no
  backward, clique para abrir os pesos;
- **Matriz de pesos** — 24×7 com valores reais e recorte de A/B;
- **Ligações** — 3 índices → dataset → treino → adaptador com a espessura dos pares;
- **Curva de perda** — desenha-se à medida que chegam pontos (actualiza a cada
  8 s enquanto o treino está em curso), com perplexidade, tokens e velocidade;
- **Ciclo de um passo** — lote → forward → perda (só nos tokens da resposta) →
  backward → update;
- **Avaliação** — base vs adaptador, fidelidade numérica e histórico;
- **Chat** — com árvore do raciocínio, fita de tokens, 👍/👎 com correção,
  «guardar como skill» e o botão de retreinar.

O **playground** (`/modelo/playground`) é o sítio para experimentar: prompt de
sistema editável (e guardável), perfis da plataforma, temperatura e tokens, com
o mesmo traço e a mesma verificação.

O **chat** (`/modelo/chat`) é a conversa em ecrã inteiro, ao estilo ChatGPT:
histórico na `sessionStorage`, exemplos rápidos, upload/paste de documento,
relatório da conversa, painel lateral com memórias, skills e o bloco de
auto-aprendizagem.

O **retreino** (`/modelo/retreino`) é o painel de auto-aprendizagem completo:
estado e progresso da adaptação, formulário com passos e learning rate,
reutilizar pares já treinados, parar, versões guardadas com reverção, histórico
de adaptações, reindexação do corpus RAG e avaliação. O mesmo controlo aparece
resumido no painel do chat e no cartão «chat do modelo» da página do modelo.

Dentro do painel, o bloco **«processo em direto»** liga-se por WebSocket a
`/llm/modelo/retreinar/ws` e mostra o que está a acontecer enquanto acontece:

- as **quatro fases** do processo (pares e modelo → passos LoRA → perda
  antes/depois → guardar com backup), com a fase atual acesa e as concluídas
  marcadas;
- a **curva de perda** desenhada passo a passo (SVG), com a perda inicial, a
  atual e a variação;
- contagem de passos, tokens, tempo decorrido e previsão do que falta;
- um **registo** das transições, para se ver o que já passou;
- quando o treino completo (`training/train_lora_contratos.py`) está a correr
  **fora** da API, uma segunda curva lê o `metrics.jsonl` e assinala-a como
  «treino completo (script)» — o sinal de vida é o `mtime` desse ficheiro.

O canal envia o retrato completo a cada mudança (não deltas), por isso abrir a
página a meio do treino reconstrói a curva desde o passo 1; e há `ping` a cada
15 s para o proxy não fechar uma ligação parada.

A animação é CSS (`chat-ui/src/modeloContratos.css`) e respeita
`prefers-reduced-motion`: um `setInterval` a 60 fps roubaria tempo ao treino, que
está a correr na mesma máquina.

## 8. Limitações honestas

- **CPU**: o dataset inteiro (807 pares) é ~3 h por época; a corrida de
  demonstração treinou 120 pares (e depois 200 na retoma). Com GPU,
  `--max-pairs 0` e mais épocas.
- **0,5 B parâmetros**: aprende o formato e o vocabulário dos contratos, não
  raciocina como um 7 B. O «raciocínio» aqui é um **ciclo orquestrado** (skills
  + RAG + verificação), não cadeia de pensamento do próprio modelo.
- **Fidelidade**: a verificação de números existe precisamente porque um modelo
  pequeno troca valores — e apanhou casos reais durante os testes. Qualquer
  resposta do adaptador deve ser lida como rascunho, não como fonte de verdade:
  a fonte é o índice.
- **Auto-aprendizagem**: 12 passos sobre 3-4 pares mudam o estilo, não o
  conhecimento. Para conhecimento novo, use memória/skills (que entram no
  prompt) ou um novo treino grande. Cada adaptação deixa backup — reverter é
  copiar o `.bak-<data>` por cima do `adapter_model.safetensors`.
- **RAG por BM25**: sem embeddings, a recuperação é lexical. Um contrato descrito
  com outras palavras pode não aparecer; para isso existe a skill
  `procurar_contratos`, que usa a pesquisa do próprio índice.
