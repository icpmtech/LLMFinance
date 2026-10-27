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
- Resultado nesta corrida: 807 pares (245 contratos, 300 entidades, 262
  subsídios).

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
| `metrics.jsonl` | Uma linha por actualização (`step`, `perda`, `perplexidade`, `tokens`, `segundos`) — é a curva que a página desenha. |
| `run_metadata.json` | Modelo base, dados, LoRA, passos, perda final, duração. |
| `state.pt` | Estado para `--resume` (passo + optimizador). |

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

A divisão treino/held-out **baralha com semente** antes de cortar: o exporter
grava as linhas agrupadas por fonte, por isso cortar as últimas N daria um
held-out só de subsídios (e um `--max-pairs` pequeno treinaria só contratos).

## 5. API (`/llm/modelo/*`)

| Método | Rota | O que faz |
|---|---|---|
| `GET` | `/llm/modelo` | Ficha: adaptador presente, metadados do treino, curva e fontes. Público. |
| `GET` | `/llm/modelo/metricas` | Pontos de `metrics.jsonl`. Público. |
| `POST` | `/llm/modelo/chat` | Resposta do adaptador a um documento. Exige sessão (custa CPU). |
| `POST` | `/llm/modelo/avaliar` | Corre a avaliação e guarda o resultado no índice. Exige sessão. |
| `GET` | `/llm/modelo/avaliacoes` | Histórico de avaliações (Elasticsearch). Público. |

Implementação: [api/llm_contratos_routes.py](../api/llm_contratos_routes.py) e
[api/llm_contratos_service.py](../api/llm_contratos_service.py). O prompt é
definido **uma vez** em [inference/contratos_lora.py](../inference/contratos_lora.py)
e usado pelo treino, pela avaliação e pela API — três moldes diferentes
transformariam um modelo bom em respostas más.

## 6. Índices do Elasticsearch

Criados pela primeira escrita (mapeamento em `llm_contratos_service.MAPPINGS`):

| Índice | Documento |
|---|---|
| `finance_llm_model_runs` | Uma corrida de treino: modelo base, adaptador, pares, passos, perda final, segundos, fontes. |
| `finance_llm_model_evals` | Uma avaliação: conjunto, métricas base/treinado, deltas, fidelidade numérica e três amostras geradas. |

O histórico vive no Elasticsearch (e não só em `eval.json`) porque é o que
sobrevive a uma recriação do contentor.

## 7. Página `/modelo/contratos`

Mostra o **que se está a passar no treino**, com diagramas animados:

- **Pipeline** — índices → exportador → dataset → LoRA → adaptador → avaliação,
  com fluxo animado enquanto há treino a correr e cada nó aceso quando a fase já
  produziu algo;
- **Curva de perda** — desenha-se à medida que chegam pontos (actualiza a cada
  8 s enquanto o treino está em curso), com perplexidade, tokens e velocidade;
- **Ciclo de um passo** — lote → forward → perda (só nos tokens da resposta) →
  backward → update;
- **Mapa da LoRA** — 24 camadas × 7 projecções, com o gradiente a percorrer;
- **Avaliação** — base vs adaptador (perplexidade e exatidão), fidelidade
  numérica e histórico;
- **Perguntar ao modelo** — o adaptador a responder a um contrato real.

A animação é CSS (`chat-ui/src/modeloContratos.css`) e respeita
`prefers-reduced-motion`: um `setInterval` a 60 fps roubaria tempo ao treino, que
está a correr na mesma máquina.

## 8. Limitações honestas

- **CPU**: o dataset inteiro (807 pares) é ~3 h por época; a corrida de
  demonstração treinou 120 pares. Com GPU, `--max-pairs 0` e mais épocas.
- **0,5 B parâmetros**: aprende o formato e o vocabulário dos contratos, não
  raciocina como um 7 B. Não substitui o RAG (`rag/`) nem os modelos de
  fornecedor — complementa-os nos casos em que o formato é fixo.
- **Fidelidade**: a métrica de números existe precisamente porque um modelo
  pequeno pode trocar valores. Qualquer resposta do adaptador deve ser lida como
  rascunho, não como fonte de verdade — a fonte é o índice.
