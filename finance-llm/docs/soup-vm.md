# Fine-tuning numa VM com GPU

O [docs/soup.md](soup.md) descreve o fluxo completo — exportar do Elasticsearch,
treinar, usar o modelo. Este ficheiro responde à pergunta seguinte: **o que fazer
quando a máquina onde isto corre não tem GPU**, e como levantar uma VM que tenha.

## 1. O que esta máquina dá (e o que não dá)

Medido neste portátil:

| | Valor | Consequência |
|---|---|---|
| CPU | Intel Core Ultra 7 255U, 12 núcleos / 14 threads | Treina bem modelos pequenos; é o que treinou os 22 M |
| RAM | 31,4 GB no sistema, **16,4 GB visíveis ao Docker** (limite do Docker Desktop) | É este o teto real dos contentores |
| GPU | Intel Graphics (iGPU, 2 GB partilhados) — sem CUDA | `torch.cuda.is_available()` é `False`; `nvidia-smi` não existe |
| Disco | 141 GB livres em `C:` (das imagens, ~60 GB são recuperáveis) | Chega para o modelo de 22 M; uma imagem de GPU + os 15 GB do 7B pedem limpeza |
| Docker | Desktop 29.6.2, Compose v5.3.1, WSL2 | Os mesmos ficheiros do projecto correm numa VM Linux sem alterações |

O veredicto está no próprio Soup:

```bash
$ soup profile --config training/soup/soup-mistral-instruct.yaml
? No GPU detected: would fit in an assumed 24 GB (need ~14 GB)
```

`quantization: 4bit` é QLoRA, QLoRA é `bitsandbytes`, e `bitsandbytes` precisa de
CUDA. **Não há caminho para um 7B nesta máquina** — nem CPU (dezenas de segundos
por passo, centenas de horas por época), nem iGPU (o Soup não tem backend para
Intel XPU).

O que **continua** a fazer-se aqui, e já está feito: exportar datasets do
Elasticsearch, validar configs (`--dry-run`, `soup data validate`), treinar o
modelo de 22 M do sistema, subir o painel, e conversar com o Gemma local via
Ollama (`soup-ollama-bridge`). O que **não** se faz aqui é o treino que melhora a
qualidade das respostas — porque essa é uma questão de tamanho de modelo, não de
ferramenta.

## 2. Dimensionar a VM

| Receita | Precisa | GPU mínima |
|---|---|---|
| `soup-mistral.yaml` (modelo do sistema, 22 M) | nada disto — corre em CPU | — |
| `soup-mistral-instruct.yaml` (7B, QLoRA 4-bit) | **~14 GB de VRAM**, 16–32 GB de RAM, 100 GB de disco | RTX 4060 Ti 16 GB, RTX 4080 16 GB, L4 24 GB, A10G 24 GB, A100 40/80 GB |

Disco, em concreto: imagem do Soup 13,8 GB + pesos do 7B ~15 GB (ficam no volume
`soup-cache`) + checkpoints do adaptador (~50 MB, mas com histórico) → **60 GB é o
mínimo sensato, 100 GB é confortável**.

## 3. Onde

Todas as opções abaixo dão o mesmo: uma Ubuntu 22.04/24.04 com driver NVIDIA e
SSH. Valores indicativos — confirme no fornecedor, mudam com frequência.

| Fornecedor | Máquina | Ordem de grandeza |
|---|---|---|
| Vast.ai / RunPod | RTX 4090 24 GB | 0,35–0,60 $/h — o mais barato para um treino pontual |
| AWS | `g6.xlarge` (L4 24 GB) | ~0,80 $/h on-demand, spot bem abaixo |
| GCP | `g2-standard-4` (L4 24 GB) | ~0,70–0,85 $/h |
| Azure | `NC4as T4 v3` (T4 16 GB) | ~0,50 $/h |
| Scaleway (EU/FR) | GPU L4 / A100 | ~0,50–0,90 €/h |

Dois avisos que poupam uma hora de trabalho:

* **escolha a imagem com o driver já instalado** («NVIDIA driver», «Deep Learning
  VM», «GPU image»). Sem isso, o `nvidia-smi` não existe e o `vm_setup.sh` pára
  com o aviso.
* **desligue/termine a VM no fim**. Checkpoints do que interessa trazem-se para o
  portátil (adaptador: ~50 MB; GGUF q4 de um 7B: ~4,5 GB).

Se tiver um Mac com Apple Silicon, há um terceiro caminho: o Soup tem backend
**MLX** (o `soup train --help` refere-o). Não foi testado aqui, e o `bitsandbytes`
não entra nessa equação.

## 4. Levantar a VM

```bash
# daqui, com a IP da VM
scp training/soup/vm_setup.sh ubuntu@<ip>:
ssh ubuntu@<ip> 'bash vm_setup.sh'
```

O [training/soup/vm_setup.sh](../../training/soup/vm_setup.sh) instala o Docker e o
NVIDIA Container Toolkit e termina com um teste de fogo — um contentor CUDA a
correr `nvidia-smi` — que é exactamente o que o `docker-compose.gpu.yml` precisa.

## 5. Levar os dados

O dataset são ficheiros JSONL, não bases de dados: viajam bem.

```bash
# no portátil: exportar (o mesmo comando de docs/soup.md)
python training/export_es_dataset.py --dataset contratos --dataset empresas \
    --max-records 400 --seed 42 --tokenizer model/mistral-finance/final \
    --max-tokens 950 --out data/final/iqos_contratos_empresas.jsonl

# e enviar (794 registos = 0,66 MB; ~8 KB por registo: 10 mil ≈ 80 MB, 100 mil ≈ 800 MB)
rsync -avz --relative data/final/iqos_contratos_empresas.jsonl ubuntu@<ip>:~/LLMFinance/
```

O `--tokenizer` mede os pares com o tokenizer do modelo **de destino**: na VM, se
for treinar um 7B, exporte com o tokenizer do 7B (`--tokenizer
mistralai/Mistral-7B-Instruct-v0.3`) — e aí o orçamento de tokens é a janela dele
(24 000), não os 1 024 do modelo de 22 M.

Não vale a pena expor o Elasticsearch desta rede para a VM: exportar aqui (é onde
o índice está) e enviar o ficheiro é mais simples e mais seguro.

## 6. Treinar

```bash
git clone https://github.com/icpmtech/LLMFinance.git && cd LLMFinance/finance-llm

# o override é o que dá a GPU ao contentor; sem ele, o Docker recusa arrancar
docker compose -f docker-compose.yml -f docker-compose.gpu.yml --profile train build soup
docker compose -f docker-compose.yml -f docker-compose.gpu.yml --profile train run --rm soup \
  train -y --config training/soup/soup-mistral-instruct.yaml
```

Aponte `data.train` para o dataset do passo 5 e confirme com `--dry-run` antes de
gastar GPU. Para métricas ao vivo, o painel (`soup-ui`) sobe na VM e chega-se-lhe
por túnel SSH:

```bash
ssh -L 7860:127.0.0.1:7860 ubuntu@<ip>    # e abrir http://127.0.0.1:7860
```

## 7. Trazer o modelo de volta

```bash
# na VM: juntar o adaptador ao modelo de base
docker compose -f docker-compose.yml -f docker-compose.gpu.yml --profile train run --rm soup \
  merge --adapter ./model/soup-mistral-7b-lora --output ./model/soup-mistral-7b-merged

# e quantizar para GGUF (é o formato que o Ollama do portátil come)
docker compose -f docker-compose.yml -f docker-compose.gpu.yml --profile train run --rm soup \
  export --model ./model/soup-mistral-7b-merged --format gguf --quant q4_k_m
```

Duas formas de o usar:

* **trazido para cá** — `scp` do GGUF e um `Modelfile` no Ollama local (o
  `OLLAMA_URL` do compose já aponta para o Ollama do *host*);
* **deixado na VM** — corrija o `OLLAMA_URL` do `docker-compose.yml` para a IP da
  VM (e mantenha o Ollama lá a correr). Fica-se com um modelo que responde sem
  carregar o portátil.

## 8. Pilotar a VM sem sair do portátil

O Docker fala com uma VM por SSH, e os comandos do projecto não mudam:

```bash
docker context create gpu-vm --docker "host=ssh://ubuntu@<ip>"
docker --context gpu-vm compose -f docker-compose.yml -f docker-compose.gpu.yml \
  --profile train run --rm soup train -y --config training/soup/soup-mistral-instruct.yaml
```

Nota honesta: com um contexto remoto, o `run` é remoto mas o **build context é o
repositório local** — a primeira construção da imagem envia o projecto pela rede.
Se preferir, faça `git clone` na VM e corra lá dentro; o contexto SSH é mais
prático para o dia-a-dia (mostrar o painel, listar corridas, ver logs) do que para
a primeira construção.

## 9. Expectativas

* 794 registos, 1 época, LoRA r=16 num 7B: **dezenas de minutos** numa L4 —
  a factura de um treino destes são cêntimos.
* O mesmo trabalho no modelo de 22 M em CPU levou ~35 minutos (aqui, com o Docker
  limitado a 16 GB) — ver «Quanto tempo leva» em [soup.md](soup.md).
* Não treine nos 2,27 M contratos: uma época são semanas de GPU e o modelo não
  fica melhor do que com uma amostra curada de dezenas de milhares. O
  `--max-records` existe para isso.
