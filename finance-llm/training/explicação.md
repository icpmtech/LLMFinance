Este é o **script de treino** do  Finance LLM. Ao contrário do código anterior, que apenas carregava o modelo e gerava respostas, este código **altera os pesos do GPT-2 usando os teus dados financeiros processados**.

# Treino do GPT-2 Finance

O fluxo geral é:

```text
data/final/train.jsonl
          ↓
     Carregar textos
          ↓
       Tokenizer
          ↓
    Token IDs + Mask
          ↓
      Dataset PyTorch
          ↓
       DataLoader
          ↓
       GPT-2 Finance
          ↓
         Loss
          ↓
    Backpropagation
          ↓
      AdamW Update
          ↓
    Novos pesos do modelo
          ↓
     Checkpoints
          ↓
   model/gpt2-finance/final
```

---

## 1. Imports

```python
from pathlib import Path
from transformers import GPT2LMHeadModel, GPT2TokenizerFast
import json
import torch
import torch.nn.functional as F
from torch.utils.data import DataLoader, TensorDataset
```

### `Path`

```python
from pathlib import Path
```

Serve para trabalhar com os diretórios:

```text
data/
model/
```

---

### Transformers

```python
from transformers import GPT2LMHeadModel, GPT2TokenizerFast
```

São utilizados:

* `GPT2LMHeadModel` → o modelo GPT-2
* `GPT2TokenizerFast` → transforma texto em tokens

---

### JSON

```python
import json
```

É utilizado para ler o ficheiro:

```text
train.jsonl
```

---

### PyTorch

```python
import torch
```

É a framework responsável pelo treino.

---

### `DataLoader` e `TensorDataset`

```python
from torch.utils.data import DataLoader, TensorDataset
```

São utilizados para organizar os dados em batches.

---

# 2. Diretórios

```python
ROOT = Path(__file__).resolve().parents[1]

FINAL_DIR = ROOT / "data" / "final"

MODEL_DIR = ROOT / "model" / "gpt2-finance"
```

A estrutura esperada do projeto é:

```text
finance-llm/
│
├── data/
│   └── final/
│       └── train.jsonl
│
├── model/
│   └── gpt2-finance/
│       ├── config.json
│       ├── model.safetensors
│       └── ...
│
└── src/
    └── train.py
```

---

# 3. Carregar o dataset JSONL

```python
def load_jsonl(path: Path) -> list[str]:
    """Carrega linhas de um ficheiro JSONL."""
    with path.open("r", encoding="utf-8") as f:
        return [json.loads(line)["text"] for line in f]
```

Esta função abre:

```text
data/final/train.jsonl
```

e extrai o campo:

```json
{
  "text": "A Apple reported revenue growth..."
}
```

O resultado será uma lista:

```python
[
    "A Apple reported revenue growth...",
    "The Federal Reserve maintained interest rates...",
    "Microsoft revenue increased...",
    ...
]
```

Ou seja:

```text
JSONL
 ↓
lista de textos
```

---

# 4. Função principal de treino

```python
def train_model(
    epochs: int = 1,
    batch_size: int = 8,
    max_length: int = 128,
    learning_rate: float = 5e-5,
    max_samples: int | None = None,
    save_checkpoints: bool = True,
):
```

Aqui defines os principais parâmetros do treino.

---

## `epochs`

```python
epochs=1
```

Uma epoch significa que o modelo percorre todo o dataset uma vez.

Por exemplo:

```text
100.000 documentos
       ↓
Epoch 1 → 100.000 documentos
Epoch 2 → 100.000 documentos
Epoch 3 → 100.000 documentos
```

Quanto maior o número de epochs, mais vezes os dados são utilizados.

---

## `batch_size`

```python
batch_size=8
```

Define quantos exemplos são processados simultaneamente.

```text
Batch 1 → 8 textos
Batch 2 → 8 textos
Batch 3 → 8 textos
...
```

Como estás limitado a **32 GB de RAM**, este parâmetro é particularmente importante.

Se aparecer:

```text
Out of Memory
```

podes reduzir:

```python
batch_size=4
```

ou:

```python
batch_size=2
```

---

## `max_length`

```python
max_length=128
```

Cada exemplo será limitado a 128 tokens.

Por exemplo:

```text
Texto original
↓
500 tokens
↓
truncation
↓
128 tokens
```

Isto reduz bastante o consumo de memória.

---

## `learning_rate`

```python
learning_rate=5e-5
```

Controla o tamanho das alterações feitas aos pesos do modelo.

Simplificando:

```text
Learning rate baixo
→ aprendizagem mais lenta

Learning rate alto
→ aprendizagem mais agressiva
```

Para fine-tuning de GPT-2, `5e-5` é um ponto de partida razoável.

---

## `max_samples`

```python
max_samples: int | None = None
```

Permite limitar o número de exemplos.

Por exemplo:

```python
train_model(max_samples=1000)
```

irá utilizar apenas os primeiros 1000 exemplos.

É muito útil para testar o pipeline antes de fazer um treino grande.

---

# 5. Carregar tokenizer e modelo

```python
tokenizer = GPT2TokenizerFast.from_pretrained(MODEL_DIR)

model = GPT2LMHeadModel.from_pretrained(MODEL_DIR)
```

Aqui estás a carregar o modelo que já existe.

Portanto, **este código não cria um GPT-2 do zero**.

Ele faz:

```text
GPT-2 previamente criado
          ↓
      Fine-tuning
          ↓
     GPT-2 Finance
```

Isto é importante distinguir.

---

# 6. Configuração do PAD token

```python
if tokenizer.pad_token is None:
    tokenizer.pad_token = tokenizer.eos_token
```

Se o tokenizer não tiver `pad_token`, utiliza o `EOS`.

Depois:

```python
model.config.pad_token_id = tokenizer.pad_token_id
```

sincroniza essa configuração com o modelo.

---

# 7. `loss_type`

```python
model.config.loss_type = "ForCausalLMLoss"
```

Esta configuração evita o aviso que mencionaste anteriormente:

```text
loss_type=None
```

nas versões recentes do `transformers`.

O objetivo é indicar explicitamente que estamos a utilizar uma loss apropriada para:

```text
Causal Language Modeling
```

que é precisamente o tipo de treino utilizado pelo GPT-2.

---

# 8. Escolher CPU ou GPU

```python
device = torch.device(
    "cuda" if torch.cuda.is_available() else "cpu"
)
```

Se tiveres CUDA:

```text
GPU
```

Caso contrário:

```text
CPU
```

Depois:

```python
model.to(device)
```

envia o modelo para esse dispositivo.

---

# 9. Carregar os dados

```python
texts = load_jsonl(FINAL_DIR / "train.jsonl")
```

Carrega:

```text
data/final/train.jsonl
```

Se tiveres:

```json
{"text":"Apple reported revenue of $94.0 billion."}
{"text":"Microsoft increased cloud revenue."}
{"text":"The SEC filed a report regarding..."}
```

terás:

```python
texts = [
    "Apple reported revenue of $94.0 billion.",
    "Microsoft increased cloud revenue.",
    "The SEC filed a report regarding..."
]
```

---

# 10. Limitar o dataset

```python
if max_samples:
    texts = texts[:max_samples]
```

Por exemplo:

```python
train_model(max_samples=5000)
```

faz:

```text
Dataset original
      ↓
5000 exemplos
      ↓
Treino
```

---

# 11. Tokenização

Esta é uma das partes mais importantes:

```python
encodings = tokenizer(
    texts,
    truncation=True,
    padding="max_length",
    max_length=max_length,
    return_tensors="pt",
)
```

Transforma:

```text
Texto
```

em:

```text
Tokens
```

e depois:

```text
Tensor PyTorch
```

---

## `truncation=True`

Se um texto tiver mais de 128 tokens:

```text
500 tokens
   ↓
128 tokens
```

O restante é cortado.

---

## `padding="max_length"`

Todos os exemplos passam a ter o mesmo tamanho:

```text
Texto A → 128 tokens
Texto B → 128 tokens
Texto C → 128 tokens
```

Isto facilita o processamento em batches.

---

## `return_tensors="pt"`

Indica:

```text
pt = PyTorch
```

Portanto, o tokenizer devolve tensores PyTorch.

---

# 12. `input_ids`

```python
input_ids = encodings["input_ids"]
```

São os IDs dos tokens.

Por exemplo:

```text
"Apple revenue increased"
```

pode ser representado internamente por:

```text
[14445, 12345, 6789]
```

Esses números são o que entra no GPT-2.

---

# 13. `attention_mask`

```python
attention_mask = encodings["attention_mask"]
```

Indica quais tokens são reais e quais são padding.

Por exemplo:

```text
Tokens:

[Apple] [revenue] [increased] [PAD] [PAD]
```

A máscara pode ser:

```text
[1] [1] [1] [0] [0]
```

Onde:

```text
1 = token válido
0 = padding
```

---

# 14. Criar os labels

```python
labels = input_ids.clone()
```

Aqui fazemos uma cópia dos tokens.

Isto é fundamental para o treino de um modelo causal como GPT-2.

O objetivo é ensinar:

```text
Token atual → próximo token
```

Por exemplo:

```text
Apple revenue increased today
```

O modelo aprende aproximadamente:

```text
Apple
 ↓
revenue

revenue
 ↓
increased

increased
 ↓
today
```

---

# 15. Ignorar o padding na loss

```python
labels[attention_mask == 0] = -100
```

O valor:

```text
-100
```

é utilizado pelo PyTorch/Transformers para indicar:

> não calcular loss neste token.

Portanto:

```text
[Apple] [revenue] [increased] [PAD] [PAD]
    ↓       ↓          ↓        ↓      ↓
  loss    loss       loss     IGNORE IGNORE
```

Isto é muito importante.

---

# 16. Criar o Dataset

```python
dataset = TensorDataset(
    input_ids,
    attention_mask,
    labels
)
```

Agora os três elementos ficam associados:

```text
Dataset
│
├── input_ids
├── attention_mask
└── labels
```

---

# 17. Criar o DataLoader

```python
loader = DataLoader(
    dataset,
    batch_size=batch_size,
    shuffle=True
)
```

O `DataLoader` divide os dados em batches.

Com:

```python
batch_size=8
```

terás:

```text
Dataset
   ↓
Batch 1 → 8 exemplos
Batch 2 → 8 exemplos
Batch 3 → 8 exemplos
...
```

`shuffle=True` mistura os dados a cada epoch.

---

# 18. Criar o Optimizer

```python
optimizer = torch.optim.AdamW(
    model.parameters(),
    lr=learning_rate
)
```

O `AdamW` é responsável por atualizar os pesos do GPT-2.

Durante o treino:

```text
Dados
 ↓
GPT-2
 ↓
Previsão
 ↓
Loss
 ↓
Gradientes
 ↓
AdamW
 ↓
Atualizar pesos
```

---

# 19. Modo treino

```python
model.train()
```

Aqui o modelo passa para modo de treino.

Agora estamos prontos para modificar os pesos.

---

# 20. Calcular número total de steps

```python
total_steps = len(loader) * epochs
```

Se tens:

```text
800 batches
```

e:

```text
3 epochs
```

então:

```text
800 × 3 = 2400 steps
```

---

# 21. Loop de treino

```python
step = 0

for epoch in range(epochs):
    for batch in loader:
```

Aqui começa efetivamente o treino.

Estrutura:

```text
Epoch 1
 ├── Batch 1
 ├── Batch 2
 ├── Batch 3
 └── ...

Epoch 2
 ├── Batch 1
 ├── Batch 2
 └── ...
```

---

# 22. Incrementar o step

```python
step += 1
```

Cada batch processado aumenta o contador.

Por exemplo:

```text
step 1
step 2
step 3
...
step 200
```

---

# 23. Enviar os dados para CPU/GPU

```python
b_input, b_mask, b_labels = (
    x.to(device) for x in batch
)
```

Os três tensores vão para o dispositivo:

```text
input_ids
attention_mask
labels
       ↓
    CPU/GPU
```

---

# 24. Limpar os gradientes

```python
optimizer.zero_grad()
```

Antes de cada atualização, os gradientes anteriores são limpos.

---

# 25. Forward pass

```python
outputs = model(
    input_ids=b_input,
    attention_mask=b_mask,
    labels=b_labels
)
```

Aqui o GPT-2 recebe os dados.

```text
Input
 ↓
Transformer
 ↓
Predições
 ↓
Comparar com labels
 ↓
Loss
```

---

# 26. Obter a Loss

```python
loss = outputs.loss
```

A `loss` mede quão bem o modelo está a prever os próximos tokens.

Por exemplo:

```text
loss = 5.2
```

pode ser relativamente alta.

Depois:

```text
loss = 3.8
```

melhor.

Depois:

```text
loss = 2.1
```

melhor ainda.

Mas **loss menor não significa automaticamente que o modelo financeiro está bom**. É necessário avaliar o modelo com dados que não foram usados no treino.

---

# 27. Backpropagation

```python
loss.backward()
```

Esta é a fase de backpropagation.

O PyTorch calcula os gradientes:

```text
Loss
 ↓
Gradientes
 ↓
Pesos
```

O objetivo é descobrir como cada peso contribuiu para o erro.

---

# 28. Atualizar os pesos

```python
optimizer.step()
```

Agora o AdamW utiliza os gradientes para alterar os pesos.

```text
Pesos antigos
      ↓
    AdamW
      ↓
Pesos novos
```

Este é o processo que efetivamente **ensina o modelo**.

---

# 29. Mostrar a loss

```python
if step % 20 == 0:
    print(
        f"step {step}/{total_steps} | "
        f"epoch {epoch+1}/{epochs} | "
        f"loss {loss.item():.4f}"
    )
```

A cada 20 steps aparece algo como:

```text
step 20/500 | epoch 1/1 | loss 3.8421
step 40/500 | epoch 1/1 | loss 3.5217
step 60/500 | epoch 1/1 | loss 3.2145
```

Isto permite acompanhar a evolução do treino.

---

# 30. Checkpoints

```python
if save_checkpoints and step % 200 == 0:
```

A cada 200 steps o modelo pode ser guardado.

Por exemplo:

```text
model/
└── gpt2-finance/
    └── checkpoints/
        ├── step-200/
        ├── step-400/
        ├── step-600/
        └── ...
```

---

## Porque são importantes?

Imagine que o treino demora 10 horas.

Ao fim de 8 horas o computador falha.

Sem checkpoints:

```text
8 horas → trabalho perdido
```

Com checkpoints:

```text
step-200
step-400
step-600
step-800
...
```

podes recuperar uma versão anterior.

---

# 31. Criar diretório do checkpoint

```python
ckpt_dir = MODEL_DIR / "checkpoints" / f"step-{step}"

ckpt_dir.mkdir(
    parents=True,
    exist_ok=True
)
```

Por exemplo:

```text
step = 200
```

resulta em:

```text
model/gpt2-finance/checkpoints/step-200/
```

---

# 32. Guardar o modelo

```python
model.save_pretrained(ckpt_dir)
```

Guarda os pesos do modelo nesse checkpoint.

---

# 33. Guardar o modelo final

Quando o treino termina:

```python
final_dir = MODEL_DIR / "final"
```

fica:

```text
model/
└── gpt2-finance/
    └── final/
```

Depois:

```python
final_dir.mkdir(
    parents=True,
    exist_ok=True
)
```

cria o diretório se ainda não existir.

---

# 34. Guardar os pesos

```python
model.save_pretrained(final_dir)
```

Guarda o GPT-2 treinado.

---

# 35. Guardar o tokenizer

```python
tokenizer.save_pretrained(final_dir)
```

Isto é **muito importante**.

Não basta guardar o modelo.

Precisamos também de guardar o tokenizer correspondente.

```text
final/
│
├── modelo
│
└── tokenizer
```

Assim, o código de inferência que mostraste anteriormente pode fazer:

```python
GPT2TokenizerFast.from_pretrained(MODEL_DIR)
```

e:

```python
GPT2LMHeadModel.from_pretrained(MODEL_DIR)
```

---

# 36. Mensagem final

```python
print("Modelo guardado em", final_dir)
```

No final podes obter:

```text
Modelo guardado em
C:\LLMFinance\finance-llm\model\gpt2-finance\final
```

---

# 37. Execução direta

```python
if __name__ == "__main__":
    train_model()
```

Quando executares:

```bash
python train.py
```

será equivalente a:

```python
train_model(
    epochs=1,
    batch_size=8,
    max_length=128,
    learning_rate=5e-5,
    max_samples=None,
    save_checkpoints=True
)
```

---

# O que acontece durante um treino?

Imagina que tens:

```text
train.jsonl
```

com 10.000 documentos financeiros.

Com:

```python
batch_size=8
```

terás aproximadamente:

```text
10.000 / 8
≈ 1.250 steps
```

para uma epoch.

O processo será:

```text
10.000 textos
       ↓
Tokenizer
       ↓
10.000 exemplos
       ↓
1.250 batches
       ↓
┌──────────────────────┐
│ Batch                │
│                      │
│ GPT-2                │
│    ↓                 │
│ Prediction           │
│    ↓                 │
│ Loss                 │
│    ↓                 │
│ Backpropagation      │
│    ↓                 │
│ AdamW                │
│    ↓                 │
│ Atualizar pesos      │
└──────────────────────┘
       ↓
Próximo batch
       ↓
...
       ↓
Final
```

# Como os dois códigos se ligam

O código que mostraste anteriormente é a **inferência**:

```text
                 TREINO
                   │
                   ▼
        train.py
                   │
                   ▼
          GPT-2 + dados
                   │
                   ▼
        Pesos atualizados
                   │
                   ▼
model/gpt2-finance/final
                   │
                   ▼
              inference.py
                   │
                   ▼
               generate()
                   │
                   ▼
            Resposta do LLM
```

Ou seja:

```text
train.py
   ↓
TREINA

inference.py
   ↓
USA O MODELO
```

## ⚠️ Uma questão importante no teu projeto

Há uma diferença entre **treinar com dados financeiros** e criar um LLM financeiro realmente útil.

O teu código atual faz:

```text
Documentos financeiros
        ↓
Fine-tuning GPT-2
```

Isto ensina o modelo a **imitar os padrões linguísticos dos documentos**.

Mas, para o teu objetivo de criar um **Finance LLM**, eu recomendaria evoluir a arquitetura para:

```text
                 FINANCE LLM
                     │
       ┌─────────────┼─────────────┐
       │             │             │
       ▼             ▼             ▼
   SEC filings    yfinance      Notícias
       │             │             │
       └─────────────┼─────────────┘
                     ▼
               Data Pipeline
                     │
                     ▼
               Finance Dataset
                     │
                     ▼
              GPT-2 Fine-tuning
                     │
                     ▼
              Finance LLM
                     │
                     ▼
                RAG / Tools
                     │
          ┌──────────┴──────────┐
          ▼                     ▼
    Dados históricos       Dados atuais
          │                     │
          └──────────┬──────────┘
                     ▼
                  /chat
                     │
                     ▼
                  Chat UI
```

E há ainda uma melhoria importante no teu código atual: **`max_length=128` é bastante pequeno para documentos SEC e relatórios financeiros**. Para o teu projeto de 32 GB de RAM, podemos desenhar um treino mais eficiente com **chunking de documentos, gradient accumulation, mixed precision quando houver GPU, validação (`eval_loss`), early stopping e checkpoints**, sem exigir uma máquina muito mais potente.
