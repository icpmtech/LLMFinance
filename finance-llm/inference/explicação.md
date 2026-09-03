Este código é a **camada de inferência** do  LLM financeiro: carrega o modelo GPT-2 que treinaste, carrega o tokenizer e disponibiliza uma função `generate()` para fazer perguntas ao modelo e obter texto como resposta.

Abaixo está a explicação em **Markdown**, organizada por partes.

# Inferência do modelo financeiro

Este código é responsável por **carregar o modelo treinado e gerar texto a partir de um prompt**.

A arquitetura é:

```text
Prompt do utilizador
        ↓
Tokenizer
        ↓
Tokens / IDs
        ↓
GPT-2 Finance
        ↓
Novos tokens
        ↓
Tokenizer / Decode
        ↓
Texto gerado
```

---

## 1. Imports

```python
from pathlib import Path
from transformers import GPT2LMHeadModel, GPT2TokenizerFast
import torch
```

### `Path`

```python
from pathlib import Path
```

É utilizado para trabalhar com caminhos de ficheiros e diretórios de forma independente do sistema operativo.

Por exemplo:

```python
Path("model/gpt2-finance/final")
```

Em vez de construir caminhos manualmente:

```python
"model/gpt2-finance/final"
```

---

### `GPT2LMHeadModel`

```python
from transformers import GPT2LMHeadModel
```

É a implementação do GPT-2 utilizada para **geração de texto**.

O modelo contém os pesos que foram aprendidos durante o treino.

Neste projeto, esses pesos correspondem ao teu:

```text
GPT-2 Finance
```

---

### `GPT2TokenizerFast`

```python
from transformers import GPT2TokenizerFast
```

O tokenizer transforma texto em tokens que o modelo consegue processar.

Por exemplo:

```text
"What is the closing price of AAPL?"
```

pode ser transformado em algo semelhante a:

```text
[What, is, the, closing, price, of, AAPL, ?]
```

Internamente, esses tokens são convertidos em IDs numéricos.

```text
Texto
 ↓
Tokenizer
 ↓
[2061, 318, 262, 3280, ...]
```

---

### PyTorch

```python
import torch
```

O PyTorch é utilizado para executar o modelo.

Também permite verificar se existe uma GPU NVIDIA/CUDA disponível.

---

# 2. Localização do modelo

```python
ROOT = Path(__file__).resolve().parents[1]
MODEL_DIR = ROOT / "model" / "gpt2-finance" / "final"
```

Aqui o código determina onde está localizado o modelo treinado.

## `__file__`

```python
__file__
```

representa o caminho do ficheiro Python atual.

Por exemplo:

```text
C:\LLMFinance\finance-llm\src\inference.py
```

---

## `resolve()`

```python
Path(__file__).resolve()
```

transforma o caminho num caminho absoluto.

---

## `parents[1]`

```python
.parents[1]
```

sobe dois níveis na estrutura de diretórios.

Por exemplo:

```text
finance-llm/
│
├── model/
│   └── gpt2-finance/
│       └── final/
│
└── src/
    └── inference.py
```

Se o código está em:

```text
src/inference.py
```

então:

```python
ROOT
```

será:

```text
finance-llm/
```

---

## Diretório final do modelo

```python
MODEL_DIR = ROOT / "model" / "gpt2-finance" / "final"
```

Resulta em algo como:

```text
finance-llm/
└── model/
    └── gpt2-finance/
        └── final/
```

É aqui que estão os ficheiros do modelo treinado.

Normalmente encontrarás ficheiros como:

```text
config.json
model.safetensors
tokenizer.json
tokenizer_config.json
special_tokens_map.json
```

---

# 3. Classe `InferenceModel`

```python
class InferenceModel:
    """Envolve tokenizer e modelo para inferência."""
```

Esta classe encapsula toda a lógica necessária para utilizar o modelo.

Ou seja:

```text
InferenceModel
│
├── Tokenizer
├── Modelo
├── Device
└── Generate()
```

Assim, o restante código não precisa de saber como o modelo é carregado internamente.

---

# 4. Construtor

```python
def __init__(self, device: str | None = None):
```

Este método é executado quando criamos:

```python
InferenceModel()
```

O parâmetro:

```python
device
```

permite escolher onde executar o modelo.

Por exemplo:

```python
InferenceModel("cpu")
```

ou:

```python
InferenceModel("cuda")
```

---

# 5. Carregar o tokenizer

```python
self.tokenizer = GPT2TokenizerFast.from_pretrained(MODEL_DIR)
```

Aqui o tokenizer treinado é carregado a partir de:

```text
model/gpt2-finance/final
```

É importante que seja utilizado o **mesmo tokenizer usado durante o treino**.

O fluxo é:

```text
Texto
  ↓
Tokenizer treinado
  ↓
Tokens
```

---

# 6. Carregar o modelo

```python
self.model = GPT2LMHeadModel.from_pretrained(MODEL_DIR)
```

Esta linha carrega os pesos do teu modelo.

Ou seja, é aqui que o GPT-2 Finance entra em memória.

```text
model/gpt2-finance/final
              ↓
      GPT2LMHeadModel
              ↓
          RAM / VRAM
```

---

# 7. Configuração do `pad_token`

```python
if self.tokenizer.pad_token is None:
    self.tokenizer.pad_token = self.tokenizer.eos_token
```

O GPT-2 originalmente não utiliza um `pad_token` da mesma forma que alguns outros modelos.

O código verifica:

```python
if self.tokenizer.pad_token is None:
```

Se não existir, utiliza o `eos_token`.

### `EOS`

EOS significa:

> End Of Sequence

É o token que indica ao modelo que uma sequência terminou.

Neste caso:

```python
PAD = EOS
```

Isto permite utilizar o modelo corretamente em determinadas operações de geração.

---

# 8. Configurar `pad_token_id`

```python
self.model.config.pad_token_id = self.tokenizer.pad_token_id
```

Aqui o modelo recebe o ID do token utilizado para padding.

É uma configuração importante para evitar problemas durante:

```python
model.generate()
```

---

# 9. Escolher CPU ou GPU

```python
self.device = torch.device(
    device or ("cuda" if torch.cuda.is_available() else "cpu")
)
```

Esta é uma parte muito importante.

O código verifica se existe CUDA disponível.

### Se existir GPU:

```text
CUDA disponível
       ↓
     GPU
```

### Se não existir:

```text
CUDA indisponível
       ↓
      CPU
```

Portanto:

```python
torch.cuda.is_available()
```

determina se o PyTorch consegue utilizar CUDA.

---

## Exemplo

Se tiveres uma NVIDIA compatível:

```python
self.device = torch.device("cuda")
```

Caso contrário:

```python
self.device = torch.device("cpu")
```

Isto é particularmente útil no teu projeto porque estás a trabalhar com uma máquina com **32 GB de RAM** e podes executar o modelo em CPU se não tiveres uma GPU adequada.

---

# 10. Enviar o modelo para CPU/GPU

```python
self.model.to(self.device)
```

Esta linha move o modelo para o dispositivo escolhido.

Por exemplo:

```text
Modelo
  ↓
CUDA
  ↓
GPU
```

ou:

```text
Modelo
  ↓
CPU
```

---

# 11. Colocar o modelo em modo avaliação

```python
self.model.eval()
```

Indica ao PyTorch que o modelo está em modo de **inferência**, e não de treino.

Durante o treino existem comportamentos específicos, como `Dropout`.

Durante a geração queremos que o modelo funcione de forma determinística relativamente à sua arquitetura de avaliação.

Portanto:

```python
model.train()
```

é usado para treino.

Enquanto:

```python
model.eval()
```

é usado para inferência.

---

# 12. Função `generate`

Agora temos:

```python
def generate(
    self,
    prompt: str,
    max_new_tokens: int = 60,
    temperature: float = 1.0
) -> str:
```

Esta é a função responsável por gerar texto.

Recebe:

### `prompt`

```python
prompt: str
```

É a pergunta ou texto inicial.

Exemplo:

```text
What is the closing price of AAPL?
```

---

### `max_new_tokens`

```python
max_new_tokens: int = 60
```

Define o número máximo de novos tokens que o modelo pode gerar.

Por exemplo:

```python
max_new_tokens=60
```

permite gerar até aproximadamente 60 tokens adicionais.

---

### `temperature`

```python
temperature: float = 1.0
```

Controla a aleatoriedade da geração.

Uma ideia simplificada:

| Temperature | Comportamento       |
| ----------: | ------------------- |
|         `0` | Mais determinístico |
|       `0.2` | Muito conservador   |
|       `0.7` | Equilibrado         |
|       `1.0` | Mais criativo       |
|       `1.5` | Muito aleatório     |

Para um modelo financeiro, normalmente queres valores relativamente baixos.

Por exemplo:

```python
temperature=0.3
```

pode ser mais adequado para respostas financeiras factuais.

---

# 13. Tokenizar o prompt

```python
inputs = self.tokenizer(
    prompt,
    return_tensors="pt"
).to(self.device)
```

Aqui acontece:

```text
"What is the closing price of AAPL?"
                 ↓
             Tokenizer
                 ↓
           Token IDs
                 ↓
             PyTorch
                 ↓
           CPU / GPU
```

O parâmetro:

```python
return_tensors="pt"
```

significa que o resultado será convertido para tensores PyTorch.

---

# 14. `torch.no_grad()`

```python
with torch.no_grad():
```

Durante a inferência não precisamos de calcular gradientes.

No treino precisamos:

```text
Forward
 ↓
Loss
 ↓
Backward
 ↓
Gradients
 ↓
Update weights
```

Na inferência:

```text
Prompt
 ↓
Model
 ↓
Prediction
```

Não existe atualização dos pesos.

Por isso:

```python
torch.no_grad()
```

reduz o consumo de memória e evita cálculos desnecessários.

---

# 15. Geração do texto

A parte principal é:

```python
outputs = self.model.generate(
    **inputs,
    max_new_tokens=max_new_tokens,
    do_sample=temperature > 0,
    temperature=temperature if temperature > 0 else 1.0,
    pad_token_id=self.tokenizer.pad_token_id,
    eos_token_id=self.tokenizer.eos_token_id,
)
```

É aqui que o GPT-2 realmente gera a resposta.

---

# 16. `max_new_tokens`

```python
max_new_tokens=max_new_tokens
```

Controla o tamanho máximo da resposta.

Por exemplo:

```python
max_new_tokens=100
```

permite ao modelo gerar até 100 tokens novos.

---

# 17. `do_sample`

```python
do_sample=temperature > 0
```

Determina se o modelo deve utilizar sampling.

Se:

```python
temperature=0
```

então:

```python
do_sample=False
```

Se:

```python
temperature=0.7
```

então:

```python
do_sample=True
```

---

# 18. Temperature

```python
temperature=temperature if temperature > 0 else 1.0
```

Se a temperatura for maior que zero:

```python
temperature=0.7
```

usa:

```python
0.7
```

Se for zero:

```python
temperature=1.0
```

Isto evita passar `temperature=0` para a função quando `do_sample=False`.

---

# 19. EOS token

```python
eos_token_id=self.tokenizer.eos_token_id
```

O modelo recebe o ID do token:

```text
EOS = End Of Sequence
```

Quando o modelo produzir esse token, a geração pode terminar.

---

# 20. Converter tokens novamente para texto

Depois da geração:

```python
return self.tokenizer.decode(
    outputs[0],
    skip_special_tokens=True
)
```

O modelo produz IDs:

```text
[15496, 318, 262,  ...]
```

O tokenizer transforma-os novamente em texto:

```text
Hello, the financial market...
```

O fluxo completo é:

```text
Prompt
   ↓
Tokenizer
   ↓
Token IDs
   ↓
GPT-2
   ↓
Token IDs gerados
   ↓
Decode
   ↓
Texto
```

---

# 21. Variável `_generate`

Depois da classe temos:

```python
_generate = None
```

Esta variável será utilizada para guardar uma única instância do modelo.

---

# 22. Função global `generate`

```python
def generate(
    prompt: str,
    max_new_tokens: int = 60,
    temperature: float = 1.0
) -> str:
```

Esta função torna a utilização do modelo muito mais simples.

Em vez de fazer:

```python
model = InferenceModel()
model.generate(...)
```

podemos simplesmente fazer:

```python
generate("What is the closing price of AAPL?")
```

---

# 23. Lazy loading

A parte mais interessante é:

```python
global _generate

if _generate is None:
    _generate = InferenceModel()
```

Isto significa que o modelo **não é carregado imediatamente** quando o ficheiro Python é importado.

Só é carregado quando a função `generate()` é chamada pela primeira vez.

### Primeira chamada

```text
generate()
   ↓
_generate == None
   ↓
Criar InferenceModel
   ↓
Carregar modelo
   ↓
Guardar em _generate
   ↓
Gerar resposta
```

### Segunda chamada

```text
generate()
   ↓
_generate já existe
   ↓
Não carregar novamente
   ↓
Gerar resposta
```

Isto é importante porque carregar um LLM pode consumir bastante RAM e tempo.

---

# 24. Chamada final

No final tens:

```python
if __name__ == "__main__":
    print(generate("What is the closing price of AAPL?"))
```

Isto permite executar diretamente o ficheiro.

Por exemplo:

```bash
python inference.py
```

O programa executará:

```python
generate("What is the closing price of AAPL?")
```

e imprimirá a resposta.

---

# Fluxo completo do teu código

Podemos resumir tudo desta forma:

```text
                    INFERENCE
                        │
                        ▼
          ┌─────────────────────────┐
          │ generate(prompt)        │
          └────────────┬────────────┘
                       │
                       ▼
              _generate existe?
                 │           │
                NÃO         SIM
                 │           │
                 ▼           │
        ┌────────────────┐   │
        │ InferenceModel │   │
        └───────┬────────┘   │
                │            │
                ▼            │
        Carregar Tokenizer   │
                │            │
                ▼            │
          Carregar GPT-2     │
                │            │
                ▼            │
          CPU ou GPU         │
                │            │
                └──────┬─────┘
                       ▼
                    Prompt
                       │
                       ▼
                   Tokenizer
                       │
                       ▼
                   Token IDs
                       │
                       ▼
                  GPT-2 Finance
                       │
                       ▼
                Novos Token IDs
                       │
                       ▼
                     Decode
                       │
                       ▼
                 Texto gerado
```

## Exemplo

Quando executas:

```python
generate(
    "What is the closing price of AAPL?",
    max_new_tokens=60,
    temperature=0.3
)
```

o processo é:

```text
"What is the closing price of AAPL?"
                 ↓
             Tokenizer
                 ↓
        Tokens numéricos
                 ↓
          GPT-2 Finance
                 ↓
      Previsão do próximo token
                 ↓
      Previsão do próximo token
                 ↓
                 ...
                 ↓
          Até 60 tokens
                 ↓
              Decode
                 ↓
       Resposta financeira
```

### Um ponto importante para o teu projeto

Este código **não consulta o preço atual da AAPL**. O GPT-2 apenas gera texto com base no que aprendeu durante o treino.

Portanto, se quiseres que o teu **Finance LLM** responda:

> "Qual é o preço atual da AAPL?"

com dados atuais do Yahoo Finance, SEC, etc., a arquitetura ideal é:

```text
              Utilizador
                  │
                  ▼
              Chat UI
                  │
                  ▼
             /chat API
                  │
                  ▼
          ┌───────────────┐
          │ Finance Agent │
          └───────┬───────┘
                  │
          ┌───────┴────────┐
          ▼                ▼
      yfinance            SEC
          │                │
          └───────┬────────┘
                  ▼
          Dados financeiros
                  │
                  ▼
          GPT-2 Finance LLM
                  │
                  ▼
             Resposta
```

Assim, o **modelo não precisa de memorizar preços atuais**: as APIs fornecem os dados em tempo real e o teu LLM interpreta-os e responde em linguagem natural.
