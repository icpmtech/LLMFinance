# Otimização de Treino de LLMs Mistral em CPU

> Documento de referência do projeto **Finance-LLM** para treino eficiente em CPUs x86 sem GPU, mantendo a capacidade de pausa/continuação.

## 1. O problema

Modelos da família Mistral (mesmo versões reduzidas como a `mistral-finance` deste projeto) exigem dezenas a centenas de milhões de operações por batch. Treinar em CPU de consumo é viável, mas **lento**, se não forem aplicadas otimizações específicas:

- PyTorch CPU não usa todos os núcleos automaticamente de forma ideal.
- `bfloat16` não é acelerado em CPUs de consumo — pelo contrário, costuma ser mais lento.
- `torch.compile` exige um compilador C++ (MSVC `cl.exe` no Windows) que raramente está disponível em ambientes de produtividade normais.
- A transferência constante de dados entre RAM e cache penaliza batches muito grandes.

## 2. Hardware e ambiente detetado

A máquina atual foi caraterizada com:

| Componente | Valor |
|------------|-------|
| CPU | Intel(R) Core(TM) Ultra 7 255U |
| Núcleos físicos | 12 |
| Threads lógicas | 14 |
| RAM | 32 GB |
| PyTorch | 2.14.0+cpu |
| CUDA | Não |
| MPS (Apple Silicon) | Não |
| Intel Extension for PyTorch (IPEX) | Não instalado |
| MSVC (`cl.exe`) | Não detetado — `torch.compile` indisponível |

> **Nota:** sem IPEX/MSVC, as otimizações mais agressivas (QLoRA em CPU via IPEX, `torch.compile`) não estão acessíveis. A estratégia passa por extrair o máximo do backend MKL-DNN do PyTorch com configuração de threads e acumulação de gradientes.

## 3. Estratégia adotada no projeto

O script `training/train_mistral.py` implementa as seguintes otimizações:

### 3.1 Configuração de threads

```python
CPU_THREADS = int(os.environ.get("LLMFINANCE_CPU_THREADS", "8"))
torch.set_num_threads(CPU_THREADS)
torch.set_num_interop_threads(min(2, CPU_THREADS // 2))
torch.backends.mkldnn.enabled = True
```

- `set_num_threads(8)` foi o valor com melhor *throughput* no benchmark interno (~2,87 s/batch vs 4,86 s/batch com 10 threads).
- `set_num_interop_threads(2)` ajuda operações de *data loading* e I/O a não competir com o compute.
- MKL-DNN fica ativado para conv/linear em CPU.

### 3.2 Acumulação de gradientes

Em vez de aumentar `batch_size` (que aumenta a memória e a latência por passo), usamos gradient accumulation:

```bash
python training/train_mistral.py \
  --batch_size 8 \
  --gradient_accumulation_steps 4 \
  ...
```

Isso produz um **batch virtual de 32 exemplos**, mas cada passo do modelo continua a processar apenas 8 exemplos. A memória do otimizador não aumenta, e o número de actualizações de pesos reduz 4×, tornando o treino mais estável em CPU.

### 3.3 Truncação prévia dos textos

Antes de tokenizar, cortamos o texto a `max_length * 8` caracteres:

```python
char_limit = max_length * 8
if len(txt) > char_limit:
    txt = txt[:char_limit]
```

O tokenizer iria truncar para `max_length=96` tokens de qualquer forma; textos de milhares de caracteres apenas atrasam a tokenização sem acrescentar informação.

### 3.4 Formato de corpus otimizado

O `processing/build_corpus.py` gera pares **Instruction/Response** (e alternativas **Question/Answer**) com dados do Yahoo Finance, limitando cada exemplo a poucas centenas de caracteres. Isso reduz o tempo de tokenização e aumenta a densidade de aprendizagem por batch.

### 3.5 Pausa/continuação nativa

O treino pode ser interrompido e retomado, o que é essencial em treinos de várias horas:

```bash
# Criar flag de pausa
python training/train_mistral.py --pause

# Remover flag para continuar
python training/train_mistral.py --continue

# Retomar de estado guardado
python training/train_mistral.py --resume --epochs 5 ...
```

O estado é guardado periodicamente em `training/mistral_state.pt` e inclui:
- pesos do modelo,
- estado do otimizador,
- `step`, `epoch`, `last_loss`,
- estado do gerador aleatório do PyTorch.

## 4. Benchmark de configurações

Medido localmente no modelo `mistral-finance` (8 camadas, hidden 512, 8 heads, max_length 96, batch 8):

| Threads | Tempo/batch | Tempo estimado 1 epoch (77k exemplos) |
|---------|-------------|--------------------------------------|
| 4 | 3,63 s | ~9,8 h |
| 6 | 3,55 s | ~9,6 h |
| **8** | **2,87 s** | **~7,7 h** |
| 10 | 4,24 s | ~11,4 h |
| 12 | 3,74 s | ~10,1 h |
| 14 | 5,76 s | ~15,5 h |

**Conclusão:** 8 threads é o ponto ótimo para esta CPU. `bfloat16` e `torch.compile` não são viáveis neste ambiente.

## 5. Comando recomendado

### Treino completo de 1 epoch (base)

```powershell
Set-Location C:\LLMFinance\finance-llm
Remove-Item -Path training\mistral_state.pt -ErrorAction SilentlyContinue
.venv\Scripts\python -u training\train_mistral.py `
  --epochs 1 `
  --batch_size 8 `
  --max_length 96 `
  --learning_rate 2e-5 `
  --save_checkpoints
```

### Treino com batch virtual maior (mais estável)

```powershell
.venv\Scripts\python -u training\train_mistral.py `
  --epochs 1 `
  --batch_size 8 `
  --gradient_accumulation_steps 4 `
  --max_length 96 `
  --learning_rate 2e-5 `
  --save_checkpoints
```

### Retomar treino interrompido

```powershell
.venv\Scripts\python -u training\train_mistral.py `
  --epochs 5 `
  --batch_size 8 `
  --max_length 96 `
  --learning_rate 2e-5 `
  --save_checkpoints `
  --resume
```

### Pausar/continuar treino em execução

```powershell
# Pausar (o treino em background verifica a flag a cada batch)
.venv\Scripts\python training\train_mistral.py --pause

# Continuar
.venv\Scripts\python training\train_mistral.py --continue
```

## 6. Monitorização

Durante o treino, o log imprime progresso a cada 20 steps efetivos:

```text
step 20/9701 | epoch 1/1 | loss 5.9319
step 40/9701 | epoch 1/1 | loss 5.4857
...
[SAVE] estado guardado em ...\training\mistral_state.pt (step 200)
```

Para correr em background no Windows com log:

```powershell
$proc = Start-Process `
  -FilePath .venv\Scripts\python.exe `
  -ArgumentList '-u','training\train_mistral.py','--epochs','1','--batch_size','8','--max_length','96','--learning_rate','2e-5','--save_checkpoints' `
  -WorkingDirectory C:\LLMFinance\finance-llm `
  -RedirectStandardOutput training\mistral_epoch1.log `
  -RedirectStandardError training\mistral_epoch1.err `
  -WindowStyle Hidden -PassThru
```

Verificar progresso:

```powershell
Get-Content training\mistral_epoch1.log -Tail 20
```

## 7. O que **não** funciona neste ambiente

| Técnica | Motivo |
|---------|--------|
| `torch.compile` | Requer compilador C++ (`cl.exe`) não presente. |
| `bfloat16` misto | Em CPU de consumo, matmul bf16 é ~50× mais lento que fp32. |
| IPEX | Extensão não instalada; exige build específico para Intel. |
| QLoRA via `bitsandbytes` | `bitsandbytes` é otimizado para GPU; versão CPU é experimental e não testada. |

Se no futuro a máquina tiver uma GPU NVIDIA ou Intel Arc com drivers adequados, a primeira otimização a aplicar é mover o modelo para CUDA/XPU e usar `fp16`/`bf16` nativo.

## 8. Próximas melhorias possíveis

1. **Dataset lazy/parquet**: guardar tokens pré-computados em ficheiro binário para evitar re-tokenizar a cada execução.
2. **DataLoader num worker**: carregar batches num processo separado com `num_workers=1` e `pin_memory=False` (em CPU raramente ajuda, mas pode ser testado).
3. **Adafactor**: substituir `AdamW` por `Adafactor` reduz memória do otimizador em ~50%; no entanto, para modelos pequenos o ganho é marginal.
4. **Compilar com MSVC**: se `cl.exe` for instalado (Build Tools for Visual Studio), `torch.compile` pode reduzir tempo de forward/backward em 20-40%.

## 9. Resumo

No sistema atual, a configuração mais rápida e estável para treinar o `mistral-finance` em CPU é:

- **8 threads PyTorch**
- **batch_size 8**
- **gradient_accumulation_steps 4** (batch virtual 32)
- **max_length 96**
- **learning_rate 2e-5**
- **fp32** (bf16 é mais lento)
- **checkpoints a cada 200 steps**
- **pausa/continuação via flag de ficheiro**

Com esta configuração, estima-se **~7,7 horas por epoch** sobre o corpus completo de 77.605 exemplos.
